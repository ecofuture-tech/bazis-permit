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
An item can reference only the objects the user can view: otherwise a user could attach
records to objects of other users (e.g. a dependent entity to a foreign parent entity).
"""

import pytest
from bazis_test_utils.utils import get_api_client
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.users import get_user_model

from tests import factories


User = get_user_model()

PERMISSIONS = [
    'entity.parent_entity.item.add.all',
    # parent entities are visible to their authors only
    'entity.parent_entity.item.view.author',
    'entity.parent_entity.item.change.author',
    'entity.dependent_entity.item.add.all',
    'entity.dependent_entity.item.view.all',
    'entity.dependent_entity.item.change.author',
]


@pytest.fixture(autouse=True)
def relations_check(settings):
    settings.BAZIS_PERMIT_RELATIONS_VIEW_CHECK = True


@pytest.fixture
def users():
    group = GroupPermission.objects.create(slug='relations', **{to_attribute('name'): 'relations'})
    for slug in PERMISSIONS:
        group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
    role = Role.objects.create(slug='role_relations', **{to_attribute('name'): 'relations'})
    role.groups_permission.add(group)

    owner = User.objects.create_user('owner', password='weak_password_1')
    stranger = User.objects.create_user('stranger', password='weak_password_2')
    owner.roles.add(role)
    stranger.roles.add(role)
    owner.refresh_from_db()
    stranger.refresh_from_db()
    return owner, stranger


def _dependent_payload(parent_entity, item_id=None) -> dict:
    data = {
        'type': 'entity.dependent_entity',
        'bs:action': 'change' if item_id else 'add',
        'attributes': {'dependent_name': 'Dependent'},
        'relationships': {
            'parent_entity': {
                'data': {'id': str(parent_entity.id), 'type': 'entity.parent_entity'}
            },
        },
    }
    if item_id:
        data['id'] = str(item_id)
    return {'data': data}


@pytest.mark.django_db(transaction=True)
def test_create_with_foreign_relation_denied(sample_app, users):
    owner, stranger = users
    foreign_parent = factories.ParentEntityFactory.create(author=owner, child_entities=False)
    own_parent = factories.ParentEntityFactory.create(author=stranger, child_entities=False)
    client = get_api_client(sample_app, stranger.jwt_build())

    response = client.post(
        '/api/v1/entity/dependent_entity/', json_data=_dependent_payload(foreign_parent)
    )
    assert response.status_code == 403
    assert response.json()['errors'][0]['code'] == 'ERR_RELATION_ACCESS'
    assert not foreign_parent.dependent_entities.filter(author=stranger).exists()

    response = client.post('/api/v1/entity/dependent_entity/', json_data=_dependent_payload(own_parent))
    assert response.status_code == 201


@pytest.mark.django_db(transaction=True)
def test_update_with_foreign_relation_denied(sample_app, users):
    owner, stranger = users
    foreign_parent = factories.ParentEntityFactory.create(author=owner, child_entities=False)
    own_parent = factories.ParentEntityFactory.create(author=stranger, child_entities=False)
    dependent = factories.DependentEntityFactory.create(author=stranger, parent_entity=own_parent)
    client = get_api_client(sample_app, stranger.jwt_build())

    response = client.patch(
        f'/api/v1/entity/dependent_entity/{dependent.id}/',
        json_data=_dependent_payload(foreign_parent, item_id=dependent.id),
    )
    assert response.status_code == 403
    dependent.refresh_from_db()
    assert dependent.parent_entity_id == own_parent.id

    # the relation that does not change is not checked, even if it is not visible any more
    own_parent.author = owner
    own_parent.save()
    response = client.patch(
        f'/api/v1/entity/dependent_entity/{dependent.id}/',
        json_data=_dependent_payload(own_parent, item_id=dependent.id),
    )
    assert response.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_relations_check_disabled_for_route(sample_app, users, monkeypatch):
    from entity.routes import DependentEntityRouteSet

    owner, stranger = users
    foreign_parent = factories.ParentEntityFactory.create(author=owner, child_entities=False)
    monkeypatch.setattr(DependentEntityRouteSet, 'relations_view_check', False)

    response = get_api_client(sample_app, stranger.jwt_build()).post(
        '/api/v1/entity/dependent_entity/', json_data=_dependent_payload(foreign_parent)
    )
    assert response.status_code == 201


@pytest.mark.django_db(transaction=True)
def test_relations_check_disabled_by_default(sample_app, users, settings):
    owner, stranger = users
    foreign_parent = factories.ParentEntityFactory.create(author=owner, child_entities=False)
    settings.BAZIS_PERMIT_RELATIONS_VIEW_CHECK = False

    response = get_api_client(sample_app, stranger.jwt_build()).post(
        '/api/v1/entity/dependent_entity/', json_data=_dependent_payload(foreign_parent)
    )
    assert response.status_code == 201


@pytest.mark.django_db(transaction=True)
def test_relations_check_to_many(sample_app, users):
    """
    A reverse to-many relation changes the referenced objects: they must be visible too.
    """
    owner, stranger = users
    own_parent = factories.ParentEntityFactory.create(author=stranger, child_entities=False)
    foreign_parent = factories.ParentEntityFactory.create(author=owner, child_entities=False)
    dependent = factories.DependentEntityFactory.create(author=stranger, parent_entity=own_parent)
    client = get_api_client(sample_app, stranger.jwt_build())

    def patch(parent):
        return client.patch(
            f'/api/v1/entity/parent_entity/{parent.id}/',
            json_data={
                'data': {
                    'id': str(parent.id),
                    'type': 'entity.parent_entity',
                    'bs:action': 'change',
                    'relationships': {
                        'dependent_entities': {
                            'data': [{'id': str(dependent.id), 'type': 'entity.dependent_entity'}]
                        },
                    },
                },
            },
        )

    # dependent entities are visible to everybody, the own parent can be changed
    assert patch(own_parent).status_code == 200
    # the foreign parent is not visible, so it cannot be changed at all
    assert patch(foreign_parent).status_code in (403, 404)


@pytest.mark.django_db(transaction=True)
def test_anonymous_with_selector_permission(sample_app):
    """
    A selector permission (here `author`) of the anonymous role matches nothing.
    """
    group = GroupPermission.objects.create(slug='anonymous', **{to_attribute('name'): 'anonymous'})
    group.permissions.add(
        Permission.objects.get_or_create(slug='entity.parent_entity.item.view.author')[0]
    )
    role = Role.objects.create(
        slug='role_anonymous', for_anonymous=True, **{to_attribute('name'): 'anonymous'}
    )
    role.groups_permission.add(group)
    parent = factories.ParentEntityFactory.create(child_entities=False)

    response = get_api_client(sample_app).get('/api/v1/entity/parent_entity/')
    assert response.status_code == 200
    assert response.json()['data'] == []

    response = get_api_client(sample_app).get(f'/api/v1/entity/parent_entity/{parent.id}/')
    assert response.status_code in (403, 404)


@pytest.mark.django_db(transaction=True)
def test_permissions_cache_invalidation():
    from bazis.contrib.permit.services import PermitService

    user = User.objects.create_user('cached', password='weak_password_1')
    group = GroupPermission.objects.create(slug='cached', **{to_attribute('name'): 'cached'})
    role = Role.objects.create(slug='role_cached', **{to_attribute('name'): 'cached'})
    user.roles.add(role)

    def perms():
        return PermitService(User.objects.get(pk=user.pk)).perms

    # a role without permissions is cached as well
    assert perms() == {}

    # reverse many-to-many: the group is added to the role from the side of the group
    group.roles.add(role)
    permission = Permission.objects.create(slug='entity.parent_entity.item.view.all')
    # reverse many-to-many: the group is added from the side of the permission
    permission.groups.add(group)
    assert 'parent_entity' in perms()['entity']

    # a renamed permission
    permission.slug = 'entity.child_entity.item.view.all'
    permission.save()
    assert set(perms()['entity']) == {'child_entity'}

    # a deleted group
    group.delete()
    assert perms() == {}
