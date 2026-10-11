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
from bazis.core.schemas import CrudAccessAction, CrudApiAction

from tests import factories

from .test_permit_selectors import URL_MEETING, user_with


VIEW = ('entity.meeting.item.view.all', 'entity.team.item.view.all')
URL_PARENT = '/api/v1/entity/parent_entity/'
URL_CHILD = '/api/v1/entity/child_entity/'


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


def shown(resource: dict) -> set[str]:
    """The attributes and the relationships of a resource object."""
    return set(resource.get('attributes') or ()) | set(resource.get('relationships') or ())


def list_and_cards(client) -> dict[str, tuple[set, set]]:
    response = client.get(URL_MEETING)
    assert response.status_code == 200, response.content
    data = response.json()['data']
    assert len({it['id'] for it in data}) == len(data)
    result = {}
    for it in data:
        card = client.get(f'{URL_MEETING}{it["id"]}/')
        assert card.status_code == 200, card.content
        result[it['id']] = (shown(it), shown(card.json()['data']))
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


#: conditional field groups of the meetings, each hiding another field: the first four are
#: `FIELD_GROUPS_COMBINED_MAX`
CONDITIONAL = [
    'entity.meeting.field.view.author.title.disable',
    'entity.meeting.field.view.participants.description.disable',
    'entity.meeting.field.view.title=Sync.team.disable',
    'entity.meeting.field.view.title=Retro.dt_created.disable',
    'entity.meeting.field.view.title=Review.dt_updated.disable',
]


def schema_list_members(client) -> list[set[str]]:
    """The fields (attributes and relationships) of each member of `schema_list`, in order."""
    schema = client.get(f'{URL_MEETING}schema_list/').json()
    defs = schema['$defs']

    def resolve(it):
        return defs[it['$ref'].split('/')[-1]] if '$ref' in it else it

    items = schema['properties']['data']['items']
    members = []
    for member in items.get('anyOf', [items]):
        properties = resolve(member)['properties']
        members.append(
            set(resolve(properties['attributes']).get('properties', {}))
            | set(resolve(properties['relationships']).get('properties', {}))
        )
    return members


def conditional_meetings(user, *meetings):
    """secret: a participant; own: the author; both: both; plain: neither."""
    secret, plain, own, both = meetings
    secret.participants.add(user)
    both.participants.add(user)
    Meeting.objects.filter(pk__in=[own.pk, both.pk]).update(author=user)


@pytest.mark.django_db(transaction=True)
def test_schema_list_first_member_is_the_union(sample_app, meetings):
    """
    The first member of `schema_list` has every field some object of the list shows (a
    client takes its columns from it), no object has it; the member of each object is in it
    and is its card.
    """
    role = role_ordered('union', [*VIEW, *CONDITIONAL[:2]], False)
    user = user_with('union', role)
    conditional_meetings(user, *meetings)
    client = get_api_client(sample_app, user.jwt_build())

    first, *others = schema_list_members(client)
    assert first == set().union(*others)
    assert {'title', 'description'} <= first
    result = list_and_cards(client)
    for listed, card in result.values():
        assert listed == card and listed <= first and listed in others
    assert set().union(*(listed for listed, __ in result.values())) == first

    schemas = routes_abstract.SchemasPermit(MeetingRouteSet, user, Meeting, None, True)
    keys = [it.schema_key for it in schemas[CrudApiAction.LIST].model_fields['data'].annotation.__args__[0].__args__]
    assert keys[0] == routes_abstract.SCHEMA_KEY_UNION
    rows = MeetingRouteSet.restrict_queryset(Meeting.objects.all(), CrudAccessAction.VIEW, user=user)
    assert routes_abstract.SCHEMA_KEY_UNION not in set(rows.values_list('_schema_key', flat=True))


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('reverse', [False, True])
def test_conditional_groups_at_the_limit(sample_app, meetings, reverse):
    """
    `FIELD_GROUPS_COMBINED_MAX` conditional groups: every object of the list has the fields
    of its card.
    """
    assert len(CONDITIONAL[:-1]) == routes_abstract.FIELD_GROUPS_COMBINED_MAX
    name = f'limit_{int(reverse)}'
    role = role_ordered(name, [*VIEW, *CONDITIONAL[:-1]], reverse)
    user = user_with(name, role)
    conditional_meetings(user, *meetings)
    secret, plain, own, both = meetings
    client = get_api_client(sample_app, user.jwt_build())

    result = list_and_cards(client)
    for listed, card in result.values():
        assert listed == card
    assert 'description' not in result[str(secret.id)][0]
    assert not {'title', 'description', 'team'} & result[str(both.id)][0]
    assert not {'title', 'dt_created'} & result[str(own.id)][0]
    assert 'dt_updated' in result[str(plain.id)][0]
    first, *__ = schema_list_members(client)
    assert {'title', 'description', 'team', 'dt_created'} <= first


@pytest.mark.django_db(transaction=True)
def test_conditional_groups_over_the_limit(sample_app, meetings):
    """
    Over `FIELD_GROUPS_COMBINED_MAX` conditional groups every object of the list has the
    fields shown in all of them (`query_fields`): never a field its card hides; the first
    member of `schema_list` is that set.
    """
    role = role_ordered('over_limit', [*VIEW, *CONDITIONAL], False)
    user = user_with('over_limit', role)
    conditional_meetings(user, *meetings)
    client = get_api_client(sample_app, user.jwt_build())

    hidden = {'title', 'description', 'team', 'dt_created', 'dt_updated'}
    result = list_and_cards(client)
    for listed, card in result.values():
        assert listed <= card
        assert not hidden & listed
    assert {'title', 'description'} <= result[str(meetings[1].id)][1]
    first, *others = schema_list_members(client)
    assert not hidden & first and all(it <= first for it in others)
    assert not hidden & {f.name for f in MeetingRouteSet.query_fields(user=user)}


@pytest.mark.django_db(transaction=True)
def test_included_objects_with_conditional_groups(sample_app):
    """
    `include` with conditional field groups: a list of a permit route has no `included` (its
    schema has no inclusions), the item of another route includes each object with the
    fields of its card, whatever the groups it matches.
    """
    role = role_ordered(
        'included',
        [
            'entity.child_entity.item.view.all',
            'entity.parent_entity.item.view.all',
            'entity.parent_entity.field.view.author.description.disable',
            'entity.parent_entity.field.view.is_active=true.price.disable',
        ],
        False,
    )
    user = user_with('included', role)
    child = factories.ChildEntityFactory.create()
    parents = [
        factories.ParentEntityFactory.create(
            author=user if own else None, is_active=active, child_entities=child
        )
        for own in (False, True)
        for active in (False, True)
    ]
    client = get_api_client(sample_app, user.jwt_build())

    response = client.get(URL_CHILD, params={'include': 'parent_entities'})
    assert response.status_code == 200, response.content
    assert not response.json().get('included')

    response = client.get(f'{URL_CHILD}{child.id}/', params={'include': 'parent_entities'})
    assert response.status_code == 200, response.content
    included = {it['id']: shown(it) for it in response.json()['included']}
    assert set(included) == {str(it.id) for it in parents}
    for parent in parents:
        card = shown(client.get(f'{URL_PARENT}{parent.id}/').json()['data'])
        assert included[str(parent.id)] == card
        assert ('description' in card) is (parent.author_id != user.pk)
        assert ('price' in card) is not parent.is_active


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


#: a public subset of the fields: the role views the objects of a condition and shows only
#: the title in them, under the same condition (as `item.view.all.open` with
#: `field.view.all.open.__all__.disable` of a role for anonymous users)
PUBLIC_SUBSET = [
    'entity.meeting.field.view.title=Sync.__all__.disable',
    'entity.meeting.field.view.title=Sync.title.enable',
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('anonymous', [False, True])
def test_schema_list_has_the_combinations_of_the_objects_viewed(sample_app, meetings, anonymous):
    """
    The members of `schema_list` are the combinations of the conditional field groups an
    object the user views may match: with the view under the condition of the field group,
    no object he views is outside the group, so the combination without it (every field)
    is left out and the union names only the fields shown (it named the hidden ones).
    """
    name = f'public_subset_{int(anonymous)}'
    role = role_ordered(name, ['entity.meeting.item.view.title=Sync', *PUBLIC_SUBSET], False)
    if anonymous:
        role.for_anonymous = True
        role.save()
        client = get_api_client(sample_app)
    else:
        client = get_api_client(sample_app, user_with(name, role).jwt_build())

    members = schema_list_members(client)
    assert members and all(it == {'title'} for it in members)
    result = list_and_cards(client)
    assert [card for __, card in result.values()] == [{'title'}]
    assert all(listed == card for listed, card in result.values())


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    'views',
    [
        ['entity.meeting.item.view.all'],
        ['entity.meeting.item.view.title=Retro'],
        ['entity.meeting.item.view.title=Sync', 'entity.meeting.item.view.title=Retro'],
    ],
)
def test_schema_list_keeps_the_combinations_maybe_viewed(sample_app, meetings, views):
    """
    A view permission whose condition is no field group's (none: every object; another
    condition, also besides that of the group) leaves the combination without the group:
    the objects outside it show every field, and the union names them.
    """
    role = role_ordered('maybe_viewed', [*views, *PUBLIC_SUBSET], False)
    client = get_api_client(sample_app, user_with('maybe_viewed', role).jwt_build())

    first, *__ = schema_list_members(client)
    assert {'title', 'description', 'team'} <= first
    result = list_and_cards(client)
    assert all(listed == card for listed, card in result.values())
    assert set().union(*(listed for listed, __ in result.values())) <= first


@pytest.mark.django_db(transaction=True)
def test_schema_list_combinations_of_a_selector(sample_app, meetings):
    """
    The view and the field group under the same selector (`participants`): the combination
    without the group (every field) is left out, as for a condition of values.
    """
    role = role_ordered(
        'participant_subset',
        [
            'entity.meeting.item.view.participants',
            'entity.meeting.field.view.participants.__all__.disable',
            'entity.meeting.field.view.participants.title.enable',
        ],
        False,
    )
    user = user_with('participant_subset', role)
    secret, *__ = meetings
    secret.participants.add(user)
    client = get_api_client(sample_app, user.jwt_build())

    members = schema_list_members(client)
    assert members and all(it == {'title'} for it in members)
    result = list_and_cards(client)
    assert list(result.values()) == [({'title'}, {'title'})]


@pytest.mark.django_db(transaction=True)
def test_schema_list_combinations_with_a_group_not_required(sample_app, meetings):
    """
    Two conditional groups, the view under the condition of one of them: the combinations
    without it are left out (2 of 4), those with it, also with the other group, are kept.
    """
    role = role_ordered(
        'one_required',
        [
            'entity.meeting.item.view.title=Sync',
            *PUBLIC_SUBSET,
            'entity.meeting.field.view.participants.title.disable',
        ],
        False,
    )
    user = user_with('one_required', role)
    secret, plain, own, both = meetings
    both.participants.add(user)
    client = get_api_client(sample_app, user.jwt_build())

    schemas = routes_abstract.SchemasPermit(MeetingRouteSet, user, Meeting, None, True)
    members = schemas[CrudApiAction.LIST].model_fields['data'].annotation.__args__[0].__args__
    __, conditional = routes_abstract.field_groups_split(schemas.get_helper(CrudApiAction.LIST).permit_handler)
    assert len(conditional) == 2
    # the union, the fields shown everywhere, the two combinations with the group of the view
    assert len(members) == 4
    result = list_and_cards(client)
    # `Sync` with the user among its participants: the title of the group of the view wins
    assert list(result.values()) == [({'title'}, {'title'})]
    first, *others = schema_list_members(client)
    # the fields shown everywhere: none, as the other group hides the title alone
    assert first == {'title'} and all(it <= first for it in others)


@pytest.mark.django_db(transaction=True)
def test_list_object_of_an_unknown_combination(sample_app, meetings, monkeypatch, caplog):
    """
    An object whose combination has no member in the schema of the list is shown with the
    fields shown in every object and logged, not a 500 (bazis 2.16).
    """
    role = role_ordered('unknown_key', ['entity.meeting.item.view.title=Sync', *PUBLIC_SUBSET], False)
    user = user_with('unknown_key', role)
    monkeypatch.setattr(routes_abstract, 'field_groups_reachable', lambda handler, conditional: [])
    client = get_api_client(sample_app, user.jwt_build())

    response = client.get(URL_MEETING)
    assert response.status_code == 200, response.content
    assert [shown(it) for it in response.json()['data']] == [{'title'}]
    assert [it for it in caplog.records if 'has no member for the _schema_key' in it.getMessage()]
