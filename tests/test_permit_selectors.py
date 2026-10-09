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
Selectors by a many-to-many relation (`Meeting.participants`) and by the reverse relations of
the user (`Team.members`: the foreign key `User.team`; `Team.watchers`: the many-to-many
relation `User.teams_watched`): the user sees, changes, gets the fields of and runs the
operations on the objects he is one of the related objects of.
"""

import logging
from itertools import chain

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import Meeting, Profile, Team
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.permit.services import PermitService
from bazis.contrib.users import get_user_model
from bazis.core.schemas import AccessAction, CrudAccessAction


User = get_user_model()

URL_MEETING = '/api/v1/entity/meeting/'
URL_TEAM = '/api/v1/entity/team/'


class MeetingAccessAction(AccessAction):
    """
    A custom operation of the meetings, as the `transit` of bazis-statusy: the permission
    `entity.meeting.item.transit.<selector>.<transit>` names the transit after the selector.
    """

    TRANSIT = 'transit'


def role_with(name: str, *slugs: str) -> Role:
    group = GroupPermission.objects.create(slug=name, **{to_attribute('name'): name})
    for slug in slugs:
        group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
    role = Role.objects.create(slug=name, **{to_attribute('name'): name})
    role.groups_permission.add(group)
    return role


def user_with(name: str, role: Role, **kwargs) -> User:
    user = User.objects.create_user(name, email=f'{name}@site.com', password='weak_password', **kwargs)
    user.roles.add(role)
    # a trigger sets the current role
    user.refresh_from_db()
    return user


def ids(response) -> list[str]:
    assert response.status_code == 200, response.content
    return sorted(it['id'] for it in response.json()['data'])


def meeting_patch(meeting: Meeting, **attributes) -> dict:
    return {
        'data': {
            'id': str(meeting.id),
            'type': 'entity.meeting',
            'bs:action': 'change',
            'attributes': attributes,
        },
    }


@pytest.fixture
def no_selector_warnings(caplog):
    """
    The selectors resolve: bazis-permit does not log a permission that matches nothing.
    """
    caplog.set_level(logging.WARNING, logger='bazis.contrib.permit.utils')
    yield
    assert not [it for it in caplog.records if 'has no selector' in it.getMessage()]


@pytest.mark.django_db(transaction=True)
def test_selector_many_to_many(sample_app, no_selector_warnings):
    """
    `participants` (many-to-many): a participant sees and changes the meeting, a user who
    is not one of its participants does not; the list has each meeting once, also when
    several permissions (`author`, `participants`) and several participants match it; the
    `check` permission is verified on the changed participants.
    """
    role = role_with(
        'meeting_participant',
        'entity.meeting.item.view.author',
        'entity.meeting.item.view.participants',
        'entity.meeting.item.change.participants',
        # a participant cannot leave the meeting by changing it
        'entity.meeting.item.check.participants',
    )
    author = user_with('author', role)
    participant = user_with('participant', role)
    other_participant = user_with('other_participant', role)
    outsider = user_with('outsider', role)

    meeting = Meeting.objects.create(title='Planning', author=author)
    meeting.participants.add(participant, other_participant, author)
    other = Meeting.objects.create(title='Other', author=outsider)

    for user in (author, participant):
        client = get_api_client(sample_app, user.jwt_build())
        assert ids(client.get(URL_MEETING)) == [str(meeting.id)]
        assert client.get(f'{URL_MEETING}{meeting.id}/').status_code == 200
        assert client.get(f'{URL_MEETING}{other.id}/').status_code in (403, 404)

    client = get_api_client(sample_app, outsider.jwt_build())
    assert ids(client.get(URL_MEETING)) == [str(other.id)]
    assert client.get(f'{URL_MEETING}{meeting.id}/').status_code in (403, 404)
    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Hijacked'))
    assert response.status_code in (403, 404)

    client = get_api_client(sample_app, participant.jwt_build())
    response = client.get(f'{URL_MEETING}?meta=for_change')
    assert response.json()['meta']['for_change'] == [str(meeting.id)]
    response = client.get(f'{URL_MEETING}{meeting.id}/?meta=crud_actions')
    assert 'change' in response.json()['meta']['crud_actions']
    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Retro'))
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert meeting.title == 'Retro'

    # the check runs on the changed item: without himself in the participants it fails
    def participants_patch(*users):
        data = meeting_patch(meeting)
        data['data']['relationships'] = {
            'participants': {'data': [{'id': str(it.id), 'type': 'users.user'} for it in users]},
        }
        return client.patch(f'{URL_MEETING}{meeting.id}/', json_data=data)

    response = participants_patch(participant, other_participant)
    assert response.status_code == 200, response.content
    response = participants_patch(other_participant)
    assert response.status_code == 403, response.content
    assert set(meeting.participants.all()) == {participant, other_participant}

    # removed from the participants, the user no longer sees the meeting
    meeting.participants.remove(participant)
    client = get_api_client(sample_app, participant.jwt_build())
    assert ids(client.get(URL_MEETING)) == []
    assert client.get(f'{URL_MEETING}{meeting.id}/').status_code in (403, 404)


@pytest.mark.django_db(transaction=True)
def test_selector_reverse_foreign_key(sample_app, no_selector_warnings):
    """
    `members` (the reverse relation of the foreign key `User.team`): a member sees his team,
    and through the team (`team__members`) its meetings; another user does not.
    """
    role = role_with(
        'team_member',
        'entity.team.item.view.members',
        'entity.meeting.item.view.team__members',
    )
    team = Team.objects.create(name='Core')
    other_team = Team.objects.create(name='Docs')
    member = user_with('member', role, team=team)
    outsider = user_with('outsider', role, team=other_team)
    loner = user_with('loner', role)
    meeting = Meeting.objects.create(title='Standup', team=team)

    client = get_api_client(sample_app, member.jwt_build())
    assert ids(client.get(URL_TEAM)) == [str(team.id)]
    assert client.get(f'{URL_TEAM}{team.id}/').status_code == 200
    assert client.get(f'{URL_TEAM}{other_team.id}/').status_code in (403, 404)
    assert ids(client.get(URL_MEETING)) == [str(meeting.id)]

    client = get_api_client(sample_app, outsider.jwt_build())
    assert ids(client.get(URL_TEAM)) == [str(other_team.id)]
    assert client.get(f'{URL_TEAM}{team.id}/').status_code in (403, 404)
    assert ids(client.get(URL_MEETING)) == []

    client = get_api_client(sample_app, loner.jwt_build())
    assert ids(client.get(URL_TEAM)) == []
    assert ids(client.get(URL_MEETING)) == []


@pytest.mark.django_db(transaction=True)
def test_selector_reverse_many_to_many(sample_app, no_selector_warnings):
    """
    `watchers` (the reverse relation of the many-to-many relation `User.teams_watched`): a
    watcher sees the teams he watches and nothing else.
    """
    role = role_with('team_watcher', 'entity.team.item.view.watchers')
    team = Team.objects.create(name='Core')
    other_team = Team.objects.create(name='Docs')
    watcher = user_with('watcher', role)
    watcher.teams_watched.add(team)
    other = user_with('other', role)
    other.teams_watched.add(team, other_team)
    outsider = user_with('outsider', role)

    client = get_api_client(sample_app, watcher.jwt_build())
    assert ids(client.get(URL_TEAM)) == [str(team.id)]
    assert client.get(f'{URL_TEAM}{team.id}/').status_code == 200
    assert client.get(f'{URL_TEAM}{other_team.id}/').status_code in (403, 404)

    client = get_api_client(sample_app, other.jwt_build())
    assert ids(client.get(URL_TEAM)) == sorted([str(team.id), str(other_team.id)])

    client = get_api_client(sample_app, outsider.jwt_build())
    assert ids(client.get(URL_TEAM)) == []
    assert client.get(f'{URL_TEAM}{team.id}/').status_code in (403, 404)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('watched', [0, 1, 2])
def test_selector_self_of_several_values(sample_app, no_selector_warnings, watched):
    """
    `self` of a selector model whose source has several values (`Team.get_selector_for_user`:
    the teams the user watches): the user sees those objects. It found nothing, as the
    source was taken for one object.
    """
    role = role_with('team_self', 'entity.team.item.view.self')
    teams = [Team.objects.create(name=name) for name in ('Core', 'Docs', 'Ops')]
    user = user_with('watcher', role)
    user.teams_watched.add(*teams[:watched])

    client = get_api_client(sample_app, user.jwt_build())
    assert ids(client.get(URL_TEAM)) == sorted(str(team.id) for team in teams[:watched])
    for team in teams[:watched]:
        assert client.get(f'{URL_TEAM}{team.id}/').status_code == 200
    assert client.get(f'{URL_TEAM}{teams[2].id}/').status_code == 404


@pytest.mark.django_db(transaction=True)
def test_selector_many_to_many_fields(sample_app, no_selector_warnings):
    """
    Field permissions by the selector `participants`: a participant who is not the author
    does not see the description and cannot change the title; the author can.
    """
    role = role_with(
        'meeting_fields',
        'entity.meeting.item.view.author',
        'entity.meeting.item.view.participants',
        'entity.meeting.item.change.author',
        'entity.meeting.item.change.participants',
        'entity.meeting.field.view.participants.description.disable',
        'entity.meeting.field.view.author.description.enable',
        'entity.meeting.field.change.participants.title.readonly',
        'entity.meeting.field.change.author.title.enable',
    )
    author = user_with('author', role)
    participant = user_with('participant', role)
    own = Meeting.objects.create(title='Own', description='Own notes', author=participant)
    meeting = Meeting.objects.create(title='Planning', description='Secret notes', author=author)
    meeting.participants.add(participant)

    client = get_api_client(sample_app, participant.jwt_build())
    response = client.get(URL_MEETING)
    assert response.status_code == 200
    attributes = {it['id']: it['attributes'] for it in response.json()['data']}
    assert set(attributes) == {str(own.id), str(meeting.id)}
    assert 'description' not in attributes[str(meeting.id)]
    assert attributes[str(own.id)]['description'] == 'Own notes'

    response = client.get(f'{URL_MEETING}{meeting.id}/')
    assert response.status_code == 200
    assert 'description' not in response.json()['data']['attributes']

    schema = client.get(f'{URL_MEETING}{meeting.id}/schema_update/').json()
    attributes = next(v for k, v in schema['$defs'].items() if k.endswith('__Attributes__Attributes'))
    assert attributes['properties']['title']['readOnly'] is True
    client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Renamed'))
    meeting.refresh_from_db()
    assert meeting.title == 'Planning'

    client = get_api_client(sample_app, author.jwt_build())
    response = client.get(f'{URL_MEETING}{meeting.id}/')
    assert response.json()['data']['attributes']['description'] == 'Secret notes'
    response = client.patch(f'{URL_MEETING}{meeting.id}/', json_data=meeting_patch(meeting, title='Renamed'))
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert meeting.title == 'Renamed'


@pytest.mark.django_db(transaction=True)
def test_selector_many_to_many_operation(no_selector_warnings):
    """
    A custom operation with a segment after the selector (as the transits of
    bazis-statusy): a participant may run the transit `confirm`, an outsider none.
    """
    role = role_with(
        'meeting_transit',
        'entity.meeting.item.view.participants',
        'entity.meeting.item.transit.participants.confirm',
        'entity.meeting.item.transit.author.cancel',
    )
    participant = user_with('participant', role)
    outsider = user_with('outsider', role)
    meeting = Meeting.objects.create(title='Planning', author=outsider)
    meeting.participants.add(participant)

    def transits(user):
        handler = PermitService(user).handler(MeetingAccessAction.TRANSIT, meeting)
        return set(chain(*[it.keys() for it in handler.perms_item_values]))

    assert transits(participant) == {'confirm'}
    assert transits(outsider) == {'cancel'}
    assert transits(user_with('nobody', role)) == set()


@pytest.mark.django_db(transaction=True)
def test_selector_many_to_many_check_on_create(sample_app, no_selector_warnings):
    """
    `check.participants` on a created meeting: its participants are saved before the check,
    so the user creates only the meetings he takes part in.
    """
    role = role_with(
        'meeting_create',
        'entity.meeting.item.add.all',
        'entity.meeting.item.view.participants',
        'entity.meeting.item.check.participants',
    )
    user = user_with('user', role)
    other = user_with('other', role)
    client = get_api_client(sample_app, user.jwt_build())

    def create(*participants):
        return client.post(URL_MEETING, json_data={'data': {
            'type': 'entity.meeting',
            'bs:action': 'add',
            'attributes': {'title': 'Planning'},
            'relationships': {'participants': {
                'data': [{'id': str(it.id), 'type': 'users.user'} for it in participants],
            }},
        }})

    response = create(user, other)
    assert response.status_code == 201, response.content
    assert set(Meeting.objects.get(pk=response.json()['data']['id']).participants.all()) == {user, other}

    assert create(other).status_code == 403
    assert Meeting.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_selector_many_to_many_several_values(sample_app, no_selector_warnings):
    """
    A selector source with several values (`Team.get_selector_for_user`: the teams the user
    watches) through a many-to-many field (`guest_teams`), and a many-to-many relation in the
    middle of a path (`guest_teams__members`).
    """
    role = role_with(
        'meeting_guest',
        'entity.meeting.item.view.guest_teams',
        'entity.meeting.item.view.guest_teams__members',
    )
    core, docs, ops = (Team.objects.create(name=it) for it in ('Core', 'Docs', 'Ops'))
    watcher = user_with('watcher', role)
    watcher.teams_watched.add(core, docs)
    member = user_with('member', role, team=ops)
    outsider = user_with('outsider', role)

    with_core = Meeting.objects.create(title='Core')
    with_core.guest_teams.add(core, ops)
    with_docs = Meeting.objects.create(title='Docs')
    with_docs.guest_teams.add(docs)
    with_ops = Meeting.objects.create(title='Ops')
    with_ops.guest_teams.add(ops)
    Meeting.objects.create(title='None')

    client = get_api_client(sample_app, watcher.jwt_build())
    assert ids(client.get(URL_MEETING)) == sorted([str(with_core.id), str(with_docs.id)])
    client = get_api_client(sample_app, member.jwt_build())
    assert ids(client.get(URL_MEETING)) == sorted([str(with_core.id), str(with_ops.id)])
    client = get_api_client(sample_app, outsider.jwt_build())
    assert ids(client.get(URL_MEETING)) == []


@pytest.mark.django_db(transaction=True)
def test_selector_primary_key_one_to_one(no_selector_warnings):
    """
    A one-to-one field to the user that is the primary key of the model (not serialized) is
    a selector, as every foreign key.
    """
    assert 'user' in Profile.get_selector_fields()
    role = role_with('profile_own', 'entity.profile.item.view.user')
    user = user_with('user', role)
    other = user_with('other', role)
    own = Profile.objects.create(user=user)
    Profile.objects.create(user=other)

    handler = PermitService(user).handler(CrudAccessAction.VIEW, Profile)
    assert list(Profile.perms_item_apply(Profile.objects.all(), handler.perms_item)) == [own]


@pytest.mark.django_db(transaction=True)
def test_selector_unknown_still_matches_nothing(sample_app, caplog):
    """
    A selector that is no relation of the model to a selector source still matches nothing
    and is logged.
    """
    caplog.set_level(logging.WARNING, logger='bazis.contrib.permit.utils')
    role = role_with('meeting_unknown', 'entity.meeting.item.view.title')
    user = user_with('user', role)
    meeting = Meeting.objects.create(title='title', author=user)
    meeting.participants.add(user)

    assert ids(get_api_client(sample_app, user.jwt_build()).get(URL_MEETING)) == []
    assert [it for it in caplog.records if 'has no selector' in it.getMessage()]


@pytest.mark.django_db(transaction=True)
def test_selector_many_to_many_anonymous(sample_app):
    """
    An anonymous user is nobody's selector: a role for anonymous users with the selector
    `participants` shows nothing.
    """
    role = role_with('meeting_anonymous', 'entity.meeting.item.view.participants')
    role.for_anonymous = True
    role.save()
    user = user_with('user', role)
    meeting = Meeting.objects.create(title='Planning', author=user)
    meeting.participants.add(user)

    assert ids(get_api_client(sample_app).get(URL_MEETING)) == []
