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
An object of a list has the fields of its card: the field permissions of every field group
it matches (those without a condition and each conditional one), whatever the order of
the permissions (their ids).
"""

import uuid

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import Meeting, Team
from entity.routes import MeetingRouteSet
from translated_fields import to_attribute

from bazis.contrib.permit import routes_abstract
from bazis.contrib.permit.models import GroupPermission, Permission, Role

from .test_permit_selectors import URL_MEETING, user_with


VIEW = ('entity.meeting.item.view.all', 'entity.team.item.view.all')


def role_ordered(name: str, slugs: list[str], reverse: bool) -> Role:
    """A role whose permissions have ids in the order of `slugs` (reversed with `reverse`)."""
    group = GroupPermission.objects.create(slug=name, **{to_attribute('name'): name})
    ordered = list(reversed(slugs)) if reverse else slugs
    for i, slug in enumerate(ordered):
        permission = Permission.objects.filter(slug=slug).first() or Permission.objects.create(
            id=uuid.UUID(int=(1 << 120) + i), slug=slug
        )
        group.permissions.add(permission)
    role = Role.objects.create(slug=name, **{to_attribute('name'): name})
    role.groups_permission.add(group)
    return role


def list_and_cards(client) -> dict[str, tuple[set, set]]:
    response = client.get(URL_MEETING)
    assert response.status_code == 200, response.content
    data = response.json()['data']
    assert len({it['id'] for it in data}) == len(data)
    result = {}
    for it in data:
        card = client.get(f'{URL_MEETING}{it["id"]}/')
        assert card.status_code == 200, card.content
        result[it['id']] = (set(it['attributes']), set(card.json()['data']['attributes']))
    return result


@pytest.fixture
def meetings():
    team = Team.objects.create(name='Core')
    return (
        Meeting.objects.create(title='Planning', description='Secret notes', team=team),
        Meeting.objects.create(title='Review', description='Plain notes'),
        Meeting.objects.create(title='Retro', description='Own notes'),
        Meeting.objects.create(title='Sync', description='Both notes'),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('reverse', [False, True])
def test_unconditional_enable_with_a_conditional_disable(sample_app, meetings, reverse):
    """
    `description.enable` for every object wins over `description.disable` of the meetings
    of a participant, `title.disable` of those hides the title: in the list as in the card.
    """
    secret, plain, *__ = meetings
    name = f'enable_{int(reverse)}'
    role = role_ordered(
        name,
        [
            *VIEW,
            'entity.meeting.field.view.all.description.enable',
            'entity.meeting.field.view.participants.description.disable',
            'entity.meeting.field.view.participants.title.disable',
        ],
        reverse,
    )
    user = user_with(name, role)
    secret.participants.add(user)
    result = list_and_cards(get_api_client(sample_app, user.jwt_build()))

    for listed, card in result.values():
        assert listed == card
    listed, __ = result[str(secret.id)]
    assert 'description' in listed and 'title' not in listed
    assert {'description', 'title'} <= result[str(plain.id)][0]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('reverse', [False, True])
def test_an_object_in_two_conditional_groups(sample_app, meetings, reverse):
    """
    An object of two conditional groups has the restrictions of both: the author does not
    see the title of his meetings, a participant their description, both neither.
    """
    secret, plain, own, both = meetings
    name = f'two_{int(reverse)}'
    role = role_ordered(
        name,
        [
            *VIEW,
            'entity.meeting.field.view.author.title.disable',
            'entity.meeting.field.view.participants.description.disable',
        ],
        reverse,
    )
    user = user_with(name, role)
    other = user_with(f'{name}_other', role)
    # (several participants: a join would repeat the meeting in the list)
    secret.participants.add(user, other)
    both.participants.add(other, user)
    Meeting.objects.filter(pk__in=[own.pk, both.pk]).update(author=user)
    result = list_and_cards(get_api_client(sample_app, user.jwt_build()))

    for listed, card in result.values():
        assert listed == card
    assert not {'title', 'description'} & result[str(both.id)][0]
    assert 'description' not in result[str(secret.id)][0] and 'title' in result[str(secret.id)][0]
    assert 'title' not in result[str(own.id)][0] and 'description' in result[str(own.id)][0]
    assert {'title', 'description'} <= result[str(plain.id)][0]
    names = {f.name for f in MeetingRouteSet.query_fields(user=user)}
    assert not {'title', 'description'} & names


@pytest.mark.django_db(transaction=True)
def test_more_conditional_groups_than_the_list_combines(sample_app, meetings, monkeypatch):
    """
    Over `FIELD_GROUPS_COMBINED_MAX` conditional groups the list shows every object with the
    fields shown in all of them (`query_fields`): never a field its card hides.
    """
    monkeypatch.setattr(routes_abstract, 'FIELD_GROUPS_COMBINED_MAX', 1)
    secret, plain, own, both = meetings
    role = role_ordered(
        'over_max',
        [
            *VIEW,
            'entity.meeting.field.view.author.title.disable',
            'entity.meeting.field.view.participants.description.disable',
        ],
        False,
    )
    user = user_with('over_max', role)
    secret.participants.add(user)
    result = list_and_cards(get_api_client(sample_app, user.jwt_build()))

    for listed, card in result.values():
        assert listed <= card
        assert not {'title', 'description'} & listed
    assert {'title', 'description'} <= result[str(plain.id)][1]


@pytest.mark.django_db(transaction=True)
def test_every_field_hidden(sample_app, meetings):
    """
    `__all__.disable` with nothing enabled hides every field: the card, the list and the
    objects in `included` have no attributes and no relationships (bazis 2.16: an empty list
    of fields was the default schema, every field).
    """
    secret, *__ = meetings
    role = role_ordered(
        'nothing',
        [*VIEW, 'entity.meeting.field.view.all.__all__.disable'],
        False,
    )
    client = get_api_client(sample_app, user_with('nothing', role).jwt_build())

    result = list_and_cards(client)
    assert result and all(listed == card == set() for listed, card in result.values())
    card = client.get(f'{URL_MEETING}{secret.id}/').json()['data']
    assert not card.get('relationships')
    response = client.get(f'/api/v1/entity/team/{secret.team_id}/', params={'include': 'meetings'})
    assert response.status_code == 200, response.content
    for it in response.json().get('included', []):
        assert not it.get('attributes') and not it.get('relationships')
