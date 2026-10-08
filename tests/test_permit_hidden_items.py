# Copyright 2026 EcoFuture Technology Services LLC and contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
An item the user cannot view does not exist for him: every route of an item answers 404,
as for a missing item, instead of 403, which told that the item exists. An item he views
but cannot change or delete is still 403.
"""

import uuid

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.users import get_user_model

from tests import factories


User = get_user_model()

URL = '/api/v1/entity/parent_entity/'


def user_with(name: str, *slugs: str) -> User:
    group = GroupPermission.objects.create(slug=name, **{to_attribute('name'): name})
    for slug in slugs:
        group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
    role = Role.objects.create(slug=name, **{to_attribute('name'): name})
    role.groups_permission.add(group)
    user = User.objects.create_user(name, password='weak_password_5')
    user.roles.add(role)
    # a trigger sets the current role
    user.refresh_from_db()
    return user


def item_requests(item_id, child) -> list[tuple[str, str, dict | None]]:
    patch = {
        'data': {
            'id': str(item_id),
            'type': 'entity.parent_entity',
            'bs:action': 'change',
            'attributes': {'name': 'Changed'},
        }
    }
    relationship = f'{URL}{item_id}/relationships/child_entities'
    children = {'data': [{'id': str(child.id), 'type': 'entity.child_entity'}]}
    return [
        ('GET', f'{URL}{item_id}/', None),
        ('GET', f'{URL}{item_id}/schema_retrieve/', None),
        ('GET', f'{URL}{item_id}/schema_update/', None),
        ('PATCH', f'{URL}{item_id}/', patch),
        # (without objects POST and DELETE change nothing and do not look for the item)
        ('POST', relationship, children),
        ('PATCH', relationship, {'data': []}),
        ('DELETE', relationship, children),
        ('DELETE', f'{URL}{item_id}/', None),
    ]


def send(client, method, url, payload):
    return client.client.request(method, url, headers=client.headers, json=payload)


def error_of(response):
    (error,) = response.json()['errors']
    return error['status'], error.get('code'), error['detail']


@pytest.mark.django_db(transaction=True)
def test_item_the_user_cannot_view_is_not_found(sample_app):
    owner_perms = (
        'entity.parent_entity.item.add.all',
        'entity.parent_entity.item.view.author',
        'entity.parent_entity.item.change.author',
        'entity.parent_entity.item.delete.author',
        'entity.child_entity.item.view.all',
    )
    owner = user_with('owner', *owner_perms)
    stranger = user_with('stranger', *owner_perms)
    viewer = user_with(
        'viewer',
        'entity.parent_entity.item.view.all',
        'entity.parent_entity.item.change.author',
        'entity.parent_entity.item.delete.author',
    )
    item = factories.ParentEntityFactory.create(author=owner, child_entities=False)
    child = factories.ChildEntityFactory.create()

    missing = error_of(get_api_client(sample_app, stranger.jwt_build()).get(f'{URL}{uuid.uuid4()}/'))
    assert missing[0] == 404

    for client in (get_api_client(sample_app, stranger.jwt_build()), get_api_client(sample_app)):
        for method, url, payload in item_requests(item.id, child):
            response = send(client, method, url, payload)
            assert response.status_code == 404, (method, url, response.text)
            assert error_of(response) == missing, (method, url)

    # he views it, he does not change nor delete it: 403
    client = get_api_client(sample_app, viewer.jwt_build())
    for method, url, payload in item_requests(item.id, child):
        response = send(client, method, url, payload)
        expected = 200 if method == 'GET' and not url.endswith('/schema_update/') else 403
        assert response.status_code == expected, (method, url, response.text)

    item.refresh_from_db()
    assert item.name != 'Changed'
    assert ParentEntity.objects.filter(pk=item.pk).exists()

    # the owner does all of it
    client = get_api_client(sample_app, owner.jwt_build())
    for method, url, payload in item_requests(item.id, child):
        response = send(client, method, url, payload)
        assert response.status_code in (200, 204), (method, url, response.text)
    assert not ParentEntity.objects.filter(pk=item.pk).exists()
