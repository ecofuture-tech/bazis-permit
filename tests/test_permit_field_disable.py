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
`field.change.<selector>.<field>.disable` hides the field from the update schema whatever
its requiredness in the model (bazis 2.16): an update, the relationships endpoints and the
`included` of an update cannot write it. `field.add.….disable` of a required field keeps
it in the create schema: an item cannot be created without it.
"""

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import DependentEntity, Meeting
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role

from tests import factories

from .test_permit_selectors import URL_MEETING, meeting_patch, role_with, user_with


URL_DEPENDENT = '/api/v1/entity/dependent_entity/'
MEETING = (
    'entity.meeting.item.view.all',
    'entity.meeting.item.add.all',
    'entity.meeting.item.change.all',
)


def client_with(sample_app, name: str, *slugs: str):
    user = user_with(name, role_with(name, *slugs))
    return get_api_client(sample_app, user.jwt_build())


def update_fields(client, url: str) -> set[str]:
    """The attributes and the relationships of the update schema of the object at `url`."""
    response = client.get(f'{url}schema_update/')
    assert response.status_code == 200, response.content
    defs = response.json()['$defs']
    names = set()
    for name, schema in defs.items():
        if name.endswith('__Attributes') or name.endswith('__Relationships'):
            names |= set(schema.get('properties') or ())
    return names


@pytest.mark.django_db(transaction=True)
def test_change_disable_of_required_field(sample_app):
    """
    The required `title` disabled on change is not in the update schema: an update with it
    is refused (422), the other fields stay writable.
    """
    meeting = Meeting.objects.create(title='Planning', description='Notes')
    client = client_with(sample_app, 'editor', *MEETING, 'entity.meeting.field.change.all.title.disable')

    assert 'title' not in update_fields(client, f'{URL_MEETING}{meeting.id}/')
    assert 'description' in update_fields(client, f'{URL_MEETING}{meeting.id}/')

    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Hijacked'))
    assert response.status_code == 422, response.content
    meeting.refresh_from_db()
    assert meeting.title == 'Planning'

    response = client.patch(
        f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, description='Changed')
    )
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert (meeting.title, meeting.description) == ('Planning', 'Changed')

    # the card still shows the field: only the change disables it
    response = client.get(f'{URL_MEETING}{meeting.id}/')
    assert response.json()['data']['attributes']['title'] == 'Planning'


@pytest.mark.django_db(transaction=True)
def test_change_disable_of_all_fields(sample_app):
    """`__all__.disable` on change hides the required fields too; an `enable` shows one."""
    meeting = Meeting.objects.create(title='Planning', description='Notes')
    client = client_with(
        sample_app,
        'editor',
        *MEETING,
        'entity.meeting.field.change.all.__all__.disable',
        'entity.meeting.field.change.all.description.enable',
    )

    fields = update_fields(client, f'{URL_MEETING}{meeting.id}/')
    assert 'title' not in fields
    assert 'description' in fields

    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Hijacked'))
    assert response.status_code == 422, response.content
    response = client.patch(
        f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, description='Changed')
    )
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert (meeting.title, meeting.description) == ('Planning', 'Changed')


@pytest.mark.django_db(transaction=True)
def test_change_enable_overrides_disable(sample_app):
    """An `enable` of the required field in another group of the role wins over its `disable`."""
    meeting = Meeting.objects.create(title='Planning')
    client = client_with(
        sample_app,
        'editor',
        *MEETING,
        'entity.meeting.field.change.all.title.disable',
        'entity.meeting.field.change.all.title.enable',
    )

    assert 'title' in update_fields(client, f'{URL_MEETING}{meeting.id}/')
    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Renamed'))
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert meeting.title == 'Renamed'


@pytest.mark.django_db(transaction=True)
def test_change_readonly_of_required_field(sample_app):
    """
    `readonly` of a required field on change, the workaround before bazis 2.16: the update
    ignores it.
    """
    meeting = Meeting.objects.create(title='Planning')
    client = client_with(sample_app, 'editor', *MEETING, 'entity.meeting.field.change.all.title.readonly')

    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Hijacked'))
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert meeting.title == 'Planning'


@pytest.mark.django_db(transaction=True)
def test_change_disable_of_optional_field(sample_app):
    """An optional field disabled on change was and is hidden from the update schema."""
    meeting = Meeting.objects.create(title='Planning', description='Notes')
    client = client_with(sample_app, 'editor', *MEETING, 'entity.meeting.field.change.all.description.disable')

    fields = update_fields(client, f'{URL_MEETING}{meeting.id}/')
    assert 'description' not in fields
    assert 'title' in fields
    response = client.patch(
        f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, description='Changed')
    )
    assert response.status_code == 422, response.content
    meeting.refresh_from_db()
    assert meeting.description == 'Notes'


@pytest.mark.django_db(transaction=True)
def test_add_disable_of_required_field_keeps_it(sample_app):
    """
    The required `title` disabled on add stays in the create schema (permit.W009): a create
    without it is refused, a create with it succeeds. The disable on change does not affect
    the create.
    """
    client = client_with(
        sample_app,
        'creator',
        *MEETING,
        'entity.meeting.field.add.all.title.disable',
        'entity.meeting.field.change.all.title.disable',
    )

    def create(**attributes):
        return client.post(
            URL_MEETING,
            json_data={'data': {'type': 'entity.meeting', 'bs:action': 'add', 'attributes': attributes}},
        )

    response = create(description='Notes')
    assert response.status_code == 422, response.content
    assert 'title' in str(response.json())

    response = create(title='Planning')
    assert response.status_code == 201, response.content
    assert Meeting.objects.get(id=response.json()['data']['id']).title == 'Planning'


@pytest.mark.django_db(transaction=True)
def test_change_disable_of_required_relation(sample_app):
    """
    The required relation `parent_entity` disabled on change: neither an update nor the
    relationships endpoint changes it.
    """
    parent = factories.ParentEntityFactory.create()
    other = factories.ParentEntityFactory.create()
    dependent = factories.DependentEntityFactory.create(parent_entity=parent)
    client = client_with(
        sample_app,
        'editor',
        'entity.dependent_entity.item.view.all',
        'entity.dependent_entity.item.change.all',
        'entity.parent_entity.item.view.all',
        'entity.dependent_entity.field.change.all.parent_entity.disable',
    )
    linkage = {'data': {'id': str(other.id), 'type': 'entity.parent_entity'}}

    assert 'parent_entity' not in update_fields(client, f'{URL_DEPENDENT}{dependent.id}/')

    response = client.patch(
        f'{URL_DEPENDENT}{dependent.id}/',
        json_data={
            'data': {
                'id': str(dependent.id),
                'type': 'entity.dependent_entity',
                'bs:action': 'change',
                'relationships': {'parent_entity': linkage},
            },
        },
    )
    assert response.status_code == 422, response.content

    response = client.patch(
        f'{URL_DEPENDENT}{dependent.id}/relationships/parent_entity', json_data=linkage
    )
    assert response.status_code == 403, response.content
    assert response.json()['errors'][0]['code'] == 'ERR_RELATIONSHIP_READONLY'

    dependent.refresh_from_db()
    assert dependent.parent_entity_id == parent.id

    # without the disable the role changes it
    client = client_with(
        sample_app,
        'owner',
        'entity.dependent_entity.item.view.all',
        'entity.dependent_entity.item.change.all',
        'entity.parent_entity.item.view.all',
    )
    response = client.patch(
        f'{URL_DEPENDENT}{dependent.id}/relationships/parent_entity', json_data=linkage
    )
    assert response.status_code in (200, 204), response.content
    assert DependentEntity.objects.get(id=dependent.id).parent_entity_id == other.id


def client_with_groups(sample_app, name: str, *groups: tuple[str, ...]):
    """A user whose role has a permission group for each tuple of `groups`."""
    role = Role.objects.create(slug=name, **{to_attribute('name'): name})
    for i, slugs in enumerate(groups):
        group = GroupPermission.objects.create(slug=f'{name}_{i}', **{to_attribute('name'): name})
        for slug in slugs:
            group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
        role.groups_permission.add(group)
    user = user_with(name, role)
    return get_api_client(sample_app, user.jwt_build())


@pytest.mark.django_db(transaction=True)
def test_change_own_required_against_disable_of_all(sample_app):
    """
    `<field>.required` keeps the field against `__all__.disable` on change (the permission
    names it): the update writes it, the other fields are hidden.
    """
    meeting = Meeting.objects.create(title='Planning', description='Notes')
    client = client_with(
        sample_app,
        'editor',
        *MEETING,
        'entity.meeting.field.change.all.__all__.disable',
        'entity.meeting.field.change.all.description.required',
    )

    fields = update_fields(client, f'{URL_MEETING}{meeting.id}/')
    assert 'description' in fields
    assert 'title' not in fields
    response = client.patch(
        f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, description='Changed')
    )
    assert response.status_code == 200, response.content
    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Hijacked'))
    assert response.status_code == 422, response.content
    meeting.refresh_from_db()
    assert (meeting.title, meeting.description) == ('Planning', 'Changed')


@pytest.mark.django_db(transaction=True)
def test_change_own_disable_wins_over_own_required_of_another_group(sample_app):
    """
    The restrictions of the groups of a user are merged: `<field>.required` of one group
    does not keep the field `<field>.disable` of another hides, also against
    `__all__.disable`.
    """
    meeting = Meeting.objects.create(title='Planning', description='Notes')
    for extra in ((), ('entity.meeting.field.change.all.__all__.disable',)):
        Role.objects.all().delete()
        GroupPermission.objects.all().delete()
        client = client_with_groups(
            sample_app,
            f'editor{len(extra)}',
            (*MEETING, 'entity.meeting.field.change.all.description.required', *extra),
            ('entity.meeting.field.change.all.description.disable',),
        )

        assert 'description' not in update_fields(client, f'{URL_MEETING}{meeting.id}/')
        response = client.patch(
            f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, description='Hijacked')
        )
        assert response.status_code == 422, response.content
        meeting.refresh_from_db()
        assert meeting.description == 'Notes'


def create_fields(client, url: str) -> set[str]:
    """The attributes and the relationships of the create schema of the route at `url`."""
    response = client.get(f'{url}schema_create/')
    assert response.status_code == 200, response.content
    names = set()
    for name, schema in response.json()['$defs'].items():
        if name.endswith('__Attributes') or name.endswith('__Relationships'):
            names |= set(schema.get('properties') or ())
    return names


@pytest.mark.django_db(transaction=True)
def test_add_field_permission_applies_only_without_a_condition(sample_app, caplog):
    """
    The create schema is built before the object exists: `field.add.all.<field>.disable`
    hides the field from a create, `field.add.<selector>.<field>.disable` (an author, also
    the user who creates) never applies (permit.E006 in `roles.py`, permit.W010 of
    `bazis_doctor` in the database; a create logs nothing). The condition of a change
    permission still applies to the item.
    """
    hidden = client_with(
        sample_app, 'hidden', *MEETING, 'entity.meeting.field.add.all.description.disable'
    )
    assert 'description' not in create_fields(hidden, URL_MEETING)
    response = hidden.post(
        URL_MEETING,
        json_data={
            'data': {
                'type': 'entity.meeting',
                'bs:action': 'add',
                'attributes': {'title': 'Planning', 'description': 'Notes'},
            }
        },
    )
    assert response.status_code == 422, response.content
    assert response.json()['errors'][0]['source']['pointer'] == '/data/attributes/description'

    conditional = client_with(
        sample_app,
        'conditional',
        *MEETING,
        'entity.meeting.field.add.author.description.disable',
        'entity.meeting.field.change.author.description.readonly',
    )
    with caplog.at_level('WARNING', logger='bazis.contrib.permit'):
        assert 'description' in create_fields(conditional, URL_MEETING)
    assert 'permit.E006' not in caplog.text
    response = conditional.post(
        URL_MEETING,
        json_data={
            'data': {
                'type': 'entity.meeting',
                'bs:action': 'add',
                'attributes': {'title': 'Planning', 'description': 'Notes'},
            }
        },
    )
    assert response.status_code == 201, response.content
    meeting = Meeting.objects.get(id=response.json()['data']['id'])
    assert meeting.description == 'Notes'
    # the author's update: the readonly of change applies to his item
    response = conditional.patch(
        f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, description='Changed')
    )
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert meeting.description == 'Notes'
