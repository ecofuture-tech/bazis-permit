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
The selector of an `item.add` permission is checked on the created item
(`PermitRouteBase.hook_after_create`): the item as created, saved with its to-many relations
and the values the server filled (the author, the fields of a trigger), before the
after-create effects of the route. A create whose item matches no `item.add` permission of
the user is 403 `ERR_FORBIDDEN` and rolled back; the presence of a permission still makes
the create schema and `for_create`.
"""

import uuid
from urllib.parse import urlencode

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import DependentEntity, Meeting, ParentEntity, Team
from entity.routes import MeetingRouteSet

from bazis.contrib.permit.routes_abstract import PermitRouteBase
from bazis.contrib.permit.services import PermitHandler
from bazis.core.schemas import CrudAccessAction

from .test_permit_selectors import URL_MEETING, meeting_patch, role_with, user_with


URL_PARENT = '/api/v1/entity/parent_entity/'
URL_DEPENDENT = '/api/v1/entity/dependent_entity/'


def meeting_create(**relationships) -> dict:
    data = {'type': 'entity.meeting', 'bs:action': 'add', 'attributes': {'title': 'Planning'}}
    if relationships:
        data['relationships'] = relationships
    return {'data': data}


def users_rel(*users) -> dict:
    return {'data': [{'id': str(it.id), 'type': 'users.user'} for it in users]}


def assert_forbidden(response):
    assert response.status_code == 403, response.content
    assert response.json()['errors'][0]['code'] == 'ERR_FORBIDDEN'


def client_of(sample_app, user):
    return get_api_client(sample_app, user.jwt_build())


@pytest.mark.django_db(transaction=True)
def test_add_author(sample_app):
    """`item.add.author`: the author is set by the server, so every create matches."""
    user = user_with('author', role_with('author', 'entity.meeting.item.add.author'))
    response = client_of(sample_app, user).post(URL_MEETING, json_data=meeting_create())
    # the response needs the view permission, the create itself is checked by add
    assert_forbidden(response)

    viewer = user_with(
        'viewer',
        role_with('viewer', 'entity.meeting.item.add.author', 'entity.meeting.item.view.all'),
    )
    response = client_of(sample_app, viewer).post(URL_MEETING, json_data=meeting_create())
    assert response.status_code == 201, response.content
    assert Meeting.objects.get().author == viewer


@pytest.mark.django_db(transaction=True)
def test_add_many_to_many_selector(sample_app):
    """
    `item.add.participants`: the item must have the user among its participants once
    created (the to-many relations of the document are saved before the check); one
    without him is refused, nothing written. The presence of the permission still gives
    the create schema and `for_create`.
    """
    role = role_with(
        'participant', 'entity.meeting.item.add.participants', 'entity.meeting.item.view.all'
    )
    user = user_with('participant', role)
    other = user_with('other', role)
    client = client_of(sample_app, user)

    response = client.get(f'{URL_MEETING}?meta=for_create')
    assert response.json()['meta']['for_create'] is True
    assert client.get(f'{URL_MEETING}schema_create/').status_code == 200

    assert_forbidden(client.post(URL_MEETING, json_data=meeting_create()))
    assert_forbidden(
        client.post(URL_MEETING, json_data=meeting_create(participants=users_rel(other)))
    )
    assert not Meeting.objects.exists()

    response = client.post(
        URL_MEETING, json_data=meeting_create(participants=users_rel(other, user))
    )
    assert response.status_code == 201, response.content
    assert set(Meeting.objects.get().participants.all()) == {user, other}


@pytest.mark.django_db(transaction=True)
def test_add_path_selector(sample_app):
    """
    `item.add.team__members` (a department): the meeting must belong to the team of the
    user; another team, or none, is refused.
    """
    team, other_team = Team.objects.create(name='Team'), Team.objects.create(name='Other')
    role = role_with(
        'member',
        'entity.meeting.item.add.team__members',
        'entity.meeting.item.view.all',
        'entity.team.item.view.all',
    )
    user = user_with('member', role, team=team)
    client = client_of(sample_app, user)

    def team_rel(it):
        return {'data': {'id': str(it.id), 'type': 'entity.team'}}

    assert_forbidden(client.post(URL_MEETING, json_data=meeting_create()))
    assert_forbidden(client.post(URL_MEETING, json_data=meeting_create(team=team_rel(other_team))))
    assert not Meeting.objects.exists()

    response = client.post(URL_MEETING, json_data=meeting_create(team=team_rel(team)))
    assert response.status_code == 201, response.content
    assert Meeting.objects.get().team == team


def dependent_create(parent: ParentEntity) -> dict:
    return {
        'data': {
            'type': 'entity.dependent_entity',
            'bs:action': 'add',
            'attributes': {
                'dependent_name': 'Dependent',
                'dependent_description': 'Dependent',
                'dependent_is_active': True,
                'dependent_price': '1.00',
                'dependent_dt_approved': '2024-06-28T16:54:12Z',
            },
            'relationships': {
                'parent_entity': {'data': {'id': str(parent.id), 'type': 'entity.parent_entity'}}
            },
        }
    }


@pytest.mark.django_db(transaction=True)
def test_add_selector_filled_by_a_trigger(sample_app):
    """
    `item.add.author_parent`: `author_parent` is copied from the author of the parent by a
    trigger at the insert; the item is checked with it, a dependent of the parent of another
    author is refused.
    """
    role = role_with(
        'dependent',
        'entity.dependent_entity.item.add.author_parent',
        'entity.dependent_entity.item.view.all',
        'entity.parent_entity.item.view.all',
    )
    user = user_with('dependent', role)
    other = user_with('other', role)
    own = ParentEntity.objects.create(name='Own', author=user)
    foreign = ParentEntity.objects.create(name='Foreign', author=other)
    client = client_of(sample_app, user)

    assert_forbidden(client.post(URL_DEPENDENT, json_data=dependent_create(foreign)))
    assert not DependentEntity.objects.exists()

    response = client.post(URL_DEPENDENT, json_data=dependent_create(own))
    assert response.status_code == 201, response.content
    assert DependentEntity.objects.get().author_parent == user


@pytest.mark.django_db(transaction=True)
def test_add_checks_the_included_items(sample_app):
    """
    An included item is checked against the `item.add` permissions of its own model: the
    whole create is refused and rolled back for a dependent the user may not add.
    """
    role = role_with(
        'included',
        'entity.parent_entity.item.add.all',
        'entity.parent_entity.item.view.all',
        'entity.dependent_entity.item.add.author_parent',
        'entity.dependent_entity.item.view.all',
    )
    user = user_with('included', role)
    other = user_with('other', role)
    foreign = ParentEntity.objects.create(name='Foreign', author=other)
    client = client_of(sample_app, user)
    query = urlencode({'include': 'dependent_entities'})

    def document(parent_id):
        dependent = dependent_create(ParentEntity(id=parent_id))['data']
        return {
            'data': {
                'id': str(uuid.uuid4()),
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {
                    'name': 'Parent',
                    'description': 'Parent',
                    'is_active': True,
                    'price': '1.00',
                    'dt_approved': '2024-06-28T16:54:12Z',
                },
            },
            'included': [dependent],
        }

    # the included dependent of the parent of another author
    payload = document(foreign.id)
    response = client.post(f'{URL_PARENT}?{query}', json_data=payload)
    assert_forbidden(response)
    assert list(ParentEntity.objects.all()) == [foreign]
    assert not DependentEntity.objects.exists()

    # the included dependent of the new parent, whose author is the user
    payload = document(None)
    payload['included'][0]['relationships']['parent_entity']['data']['id'] = payload['data']['id']
    response = client.post(f'{URL_PARENT}?{query}', json_data=payload)
    assert response.status_code == 201, response.content
    assert DependentEntity.objects.get().parent_entity_id == uuid.UUID(payload['data']['id'])


@pytest.mark.django_db(transaction=True)
def test_add_is_checked_before_the_effects_of_the_route(sample_app, monkeypatch):
    """
    The item is checked as created: an override of `hook_after_create` calls `super()`
    first, so what it changes afterwards (the server, not the user) does not refuse the
    create.
    """

    def hook_after_create(self, item):
        PermitRouteBase.hook_after_create(self, item)
        item.participants.clear()

    monkeypatch.setattr(MeetingRouteSet, 'hook_after_create', hook_after_create)
    role = role_with(
        'participant', 'entity.meeting.item.add.participants', 'entity.meeting.item.view.all'
    )
    user = user_with('participant', role)
    response = client_of(sample_app, user).post(
        URL_MEETING, json_data=meeting_create(participants=users_rel(user))
    )
    assert response.status_code == 201, response.content
    assert not Meeting.objects.get().participants.exists()


@pytest.mark.django_db(transaction=True)
def test_add_does_not_restrict_an_update(sample_app):
    """
    `add` is checked on a create only: an update the change permissions allow keeps working
    when the item no longer matches the selector of add (`check` restricts the result of a
    change).
    """
    role = role_with(
        'participant',
        'entity.meeting.item.add.participants',
        'entity.meeting.item.view.all',
        'entity.meeting.item.change.all',
    )
    user = user_with('participant', role)
    meeting = Meeting.objects.create(title='Planning')
    response = client_of(sample_app, user).patch(
        f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Changed')
    )
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert meeting.title == 'Changed'


@pytest.mark.django_db(transaction=True)
def test_add_with_several_permissions(sample_app):
    """
    The item must match one of the `item.add` permissions of the user, of any group:
    `participants` or the team of the user.
    """
    team = Team.objects.create(name='Team')
    role = role_with(
        'several',
        'entity.meeting.item.add.participants',
        'entity.meeting.item.add.team__members',
        'entity.meeting.item.view.all',
        'entity.team.item.view.all',
    )
    user = user_with('several', role, team=team)
    client = client_of(sample_app, user)
    response = client.post(
        URL_MEETING,
        json_data=meeting_create(team={'data': {'id': str(team.id), 'type': 'entity.team'}}),
    )
    assert response.status_code == 201, response.content
    response = client.post(URL_MEETING, json_data=meeting_create(participants=users_rel(user)))
    assert response.status_code == 201, response.content
    assert_forbidden(client.post(URL_MEETING, json_data=meeting_create()))
    assert Meeting.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_add_checks_each_item_after_its_own_insert(sample_app):
    """
    Each created item is checked right after its own insert, the main item before the
    included ones: a selector of the main item that only an included item would satisfy
    (`dependent_entities__author`, the dependents the request creates with it) refuses the
    create (too strict, never a bypass); the same document of a role that may add any
    parent is created.
    """
    role = role_with(
        'by_dependents',
        'entity.parent_entity.item.add.dependent_entities__author',
        'entity.parent_entity.item.view.all',
        'entity.dependent_entity.item.add.all',
        'entity.dependent_entity.item.view.all',
    )
    user = user_with('by_dependents', role)
    client = client_of(sample_app, user)
    parent_id = str(uuid.uuid4())
    dependent = dependent_create(ParentEntity(id=parent_id))['data']
    payload = {
        'data': {
            'id': parent_id,
            'type': 'entity.parent_entity',
            'bs:action': 'add',
            'attributes': {'name': 'Parent'},
        },
        'included': [dependent],
    }
    response = client.post(f'{URL_PARENT}?{urlencode({"include": "dependent_entities"})}', json_data=payload)
    assert_forbidden(response)
    assert not ParentEntity.objects.exists()
    assert not DependentEntity.objects.exists()

    anyone = user_with(
        'anyone',
        role_with(
            'anyone',
            'entity.parent_entity.item.add.all',
            'entity.parent_entity.item.view.all',
            'entity.dependent_entity.item.add.all',
            'entity.dependent_entity.item.view.all',
        ),
    )
    response = client_of(sample_app, anyone).post(
        f'{URL_PARENT}?{urlencode({"include": "dependent_entities"})}', json_data=payload
    )
    assert response.status_code == 201, response.content
    assert DependentEntity.objects.get().parent_entity_id == uuid.UUID(parent_id)


@pytest.mark.django_db(transaction=True)
def test_add_without_a_condition_is_not_evaluated(sample_app, monkeypatch):
    """
    A permission without a condition (`item.add.all`) allows every item: the created item
    is not evaluated (no query of its conditions); one with a selector is.
    """
    checked = []
    check_access = PermitHandler.check_access

    def recording(self, item_passive=False):
        if self.action == CrudAccessAction.ADD and self.item is not None:
            checked.append(self.item)
        return check_access(self, item_passive=item_passive)

    monkeypatch.setattr(PermitHandler, 'check_access', recording)
    plain = user_with('plain', role_with('plain', 'entity.meeting.item.add.all', 'entity.meeting.item.view.all'))
    assert client_of(sample_app, plain).post(URL_MEETING, json_data=meeting_create()).status_code == 201
    assert checked == []

    author = user_with(
        'author', role_with('author', 'entity.meeting.item.add.author', 'entity.meeting.item.view.all')
    )
    assert client_of(sample_app, author).post(URL_MEETING, json_data=meeting_create()).status_code == 201
    assert len(checked) == 1


@pytest.mark.django_db(transaction=True)
def test_add_of_an_included_model_without_a_permission_route(sample_app, monkeypatch):
    """
    An included item of a model whose default route is no `PermitRouteBase` is checked by
    the permission service of the route of the request (which built its create schema).
    """
    from bazis.contrib.permit import routes_abstract

    is_model_permit = routes_abstract.is_model_permit
    monkeypatch.setattr(
        routes_abstract,
        'is_model_permit',
        lambda model: model is not DependentEntity and is_model_permit(model),
    )
    role = role_with(
        'included',
        'entity.parent_entity.item.add.all',
        'entity.parent_entity.item.view.all',
        'entity.dependent_entity.item.add.author_parent',
        'entity.dependent_entity.item.view.all',
    )
    user = user_with('included', role)
    other = user_with('other', role)
    foreign = ParentEntity.objects.create(name='Foreign', author=other)
    payload = {
        'data': {
            'id': str(uuid.uuid4()),
            'type': 'entity.parent_entity',
            'bs:action': 'add',
            'attributes': {'name': 'Parent'},
        },
        'included': [dependent_create(foreign)['data']],
    }
    response = client_of(sample_app, user).post(
        f'{URL_PARENT}?{urlencode({"include": "dependent_entities"})}', json_data=payload
    )
    assert_forbidden(response)
    assert list(ParentEntity.objects.all()) == [foreign]
