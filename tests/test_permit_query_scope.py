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
The filter, the sorting and the search of a request reach only the fields the field
permissions show the user (`PermitRouteBase.query_fields`, the query scope of Bazis 2.9):
the filter and the sorting those of the LIST schema, the search those of the LIST and the
RETRIEVE schemas (Bazis 2.23).
"""

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import Meeting, Team
from entity.routes import MeetingCardRouteSet, MeetingColumnsRouteSet, MeetingRouteSet

from bazis.core.checks import check_search_fields
from bazis.core.schemas import CrudApiAction
from bazis.core.utils.query_complex import route_search_fields

from tests import factories

from .test_permit_selectors import URL_MEETING, URL_TEAM, ids, role_with, user_with


URL_MEETING_CARD = '/api/v1/entity/meeting_card/'
URL_MEETING_COLUMNS = '/api/v1/entity/meeting_columns/'
URL_PARENT = '/api/v1/entity/parent_entity/'
URL_CHILD = '/api/v1/entity/child_entity/'

VIEW = (
    'entity.meeting.item.view.all',
    'entity.team.item.view.all',
)


def query(client, url: str, **params):
    return client.get(url, params=params)


def assert_invalid(response, pointer: str):
    assert response.status_code == 400, response.content
    error = response.json()['errors'][0]
    assert error['code'] == 'ERR_FILTER'
    assert error['source']['pointer'] == pointer


@pytest.fixture
def meetings():
    team = Team.objects.create(name='Core')
    secret = Meeting.objects.create(title='Planning', description='Secret notes', team=team)
    plain = Meeting.objects.create(title='Review', description='Plain notes')
    return team, secret, plain


@pytest.mark.django_db(transaction=True)
def test_field_hidden_from_user(sample_app, meetings):
    """
    A field the permissions always hide from the user cannot be filtered, sorted or searched
    by, on the route and through a relation into its objects; the answer is the one for a
    field that does not exist.
    """
    team, secret, plain = meetings
    role = role_with('no_description', *VIEW, 'entity.meeting.field.view.all.description.disable')
    user = user_with('no_description', role)
    client = get_api_client(sample_app, user.jwt_build())

    response = client.get(f'{URL_MEETING}{secret.id}/')
    assert 'description' not in response.json()['data']['attributes']

    assert_invalid(query(client, URL_MEETING, filter='description=Secret'), '/query/filter')
    assert_invalid(query(client, URL_MEETING, filter='nothing=Secret'), '/query/filter')
    assert_invalid(query(client, URL_MEETING, sort='description'), '/query/sort')
    assert_invalid(query(client, URL_TEAM, filter='meetings__description=Secret'), '/query/filter')
    # the search leaves the hidden search field out
    assert ids(query(client, URL_MEETING, search='Secret')) == []
    assert ids(query(client, URL_MEETING, filter='$search=Secret')) == []
    assert ids(query(client, URL_MEETING, search='Planning')) == [str(secret.id)]

    # the fields it sees
    assert ids(query(client, URL_MEETING, filter='title=Planning')) == [str(secret.id)]
    assert ids(query(client, URL_TEAM, filter='meetings__title=Planning')) == [str(team.id)]

    names = {f.name for f in MeetingRouteSet.query_fields(user=user)}
    assert 'title' in names and 'description' not in names


@pytest.mark.django_db(transaction=True)
def test_field_visible_to_user(sample_app, meetings):
    """
    The user the permissions show the field to filters, sorts and searches by it.
    """
    team, secret, plain = meetings
    role = role_with('with_description', *VIEW, 'entity.meeting.field.view.all.description.enable')
    client = get_api_client(sample_app, user_with('with_description', role).jwt_build())

    assert ids(query(client, URL_MEETING, filter='description=Secret')) == [str(secret.id)]
    response = query(client, URL_MEETING, sort='-description')
    assert [it['id'] for it in response.json()['data']] == [str(secret.id), str(plain.id)]
    assert ids(query(client, URL_MEETING, search='Secret')) == [str(secret.id)]
    assert ids(query(client, URL_TEAM, filter='meetings__description=Secret')) == [str(team.id)]


@pytest.mark.django_db(transaction=True)
def test_field_visible_in_some_objects(sample_app, meetings):
    """
    A field the permissions show in only some objects is reachable in none of them: a
    filter, a sorting or a search by it in the objects that show it would also tell its
    values in the others (an oracle by trial).
    """
    team, secret, plain = meetings
    role = role_with(
        'own_description',
        *VIEW,
        'entity.meeting.field.view.author.description.enable',
        'entity.meeting.field.view.participants.description.disable',
    )
    user = user_with('own_description', role)
    secret.participants.add(user)
    client = get_api_client(sample_app, user.jwt_build())

    response = client.get(f'{URL_MEETING}{secret.id}/')
    assert 'description' not in response.json()['data']['attributes']
    response = client.get(f'{URL_MEETING}{plain.id}/')
    assert response.json()['data']['attributes']['description'] == 'Plain notes'

    assert_invalid(query(client, URL_MEETING, filter='description=Secret'), '/query/filter')
    assert_invalid(query(client, URL_MEETING, sort='description'), '/query/sort')
    assert_invalid(query(client, URL_TEAM, filter='meetings__description=Secret'), '/query/filter')
    assert ids(query(client, URL_MEETING, search='Secret')) == []
    # the fields every object shows
    assert ids(query(client, URL_MEETING, filter='title=Planning')) == [str(secret.id)]
    assert ids(query(client, URL_MEETING, search='Review')) == [str(plain.id)]


@pytest.mark.django_db(transaction=True)
def test_field_hidden_in_the_objects_the_user_sees(sample_app, meetings):
    """
    The field permissions of the objects the user sees hide a field and the other objects
    match no field permission (they would show every field) but are hidden from him: the
    field is reachable in no object, also through a relation into them. Before 2.11 such
    objects made every field reachable.
    """
    team, secret, plain = meetings
    role = role_with(
        'participant_title',
        'entity.meeting.item.view.participants',
        'entity.team.item.view.all',
        'entity.meeting.field.view.participants.__all__.disable',
        'entity.meeting.field.view.participants.title.enable',
        'entity.meeting.field.view.participants.team.enable',
    )
    user = user_with('participant_title', role)
    secret.participants.add(user)
    client = get_api_client(sample_app, user.jwt_build())

    assert ids(query(client, URL_MEETING)) == [str(secret.id)]
    response = client.get(f'{URL_MEETING}{secret.id}/')
    assert 'description' not in response.json()['data']['attributes']

    assert_invalid(query(client, URL_MEETING, filter='description=Secret'), '/query/filter')
    assert_invalid(query(client, URL_MEETING, filter='description__startswith=S'), '/query/filter')
    assert_invalid(query(client, URL_MEETING, sort='-description'), '/query/sort')
    assert_invalid(query(client, URL_TEAM, filter='meetings__description=Secret'), '/query/filter')
    assert ids(query(client, URL_MEETING, search='Secret')) == []
    assert ids(query(client, URL_MEETING, filter='$search=Secret')) == []
    # the fields the objects he sees show
    assert ids(query(client, URL_MEETING, filter='title=Planning')) == [str(secret.id)]
    assert ids(query(client, URL_MEETING, search='Planning')) == [str(secret.id)]
    assert ids(query(client, URL_TEAM, filter='meetings__title=Planning')) == [str(team.id)]
    names = {f.name for f in MeetingRouteSet.query_fields(user=user)}
    assert {'title', 'team'} <= names and 'description' not in names


@pytest.mark.django_db(transaction=True)
def test_field_shown_by_a_permission_of_every_object(sample_app, meetings):
    """
    A restriction that shows a field wins over one that hides it: a field an unconditional
    permission shows stays reachable whatever the conditional ones hide.
    """
    team, secret, plain = meetings
    role = role_with(
        'description_always',
        *VIEW,
        'entity.meeting.field.view.all.description.enable',
        'entity.meeting.field.view.participants.description.disable',
        'entity.meeting.field.view.participants.title.disable',
    )
    user = user_with('description_always', role)
    secret.participants.add(user)
    client = get_api_client(sample_app, user.jwt_build())

    response = client.get(f'{URL_MEETING}{secret.id}/')
    assert response.json()['data']['attributes']['description'] == 'Secret notes'
    assert 'title' not in response.json()['data']['attributes']
    assert ids(query(client, URL_MEETING, filter='description=Secret')) == [str(secret.id)]
    assert_invalid(query(client, URL_MEETING, filter='title=Planning'), '/query/filter')


@pytest.mark.django_db(transaction=True)
def test_anonymous_field_hidden_by_a_condition(sample_app):
    """
    The roles for anonymous users: the objects they see (`is_active=true`, as a status of
    bazis-statusy) hide the price, the others are hidden from them. The price cannot be
    filtered, sorted or searched by, on the route or through a relation, so its values
    cannot be found by trial.
    """
    role = role_with(
        'guest_price',
        'entity.parent_entity.item.view.is_active=true',
        'entity.parent_entity.field.view.is_active=true.__all__.disable',
        'entity.parent_entity.field.view.is_active=true.name.enable',
        'entity.child_entity.item.view.all',
    )
    role.for_anonymous = True
    role.save()
    child = factories.ChildEntityFactory.create()
    high = factories.ParentEntityFactory.create(name='High', is_active=True, price=900, child_entities=child)
    low = factories.ParentEntityFactory.create(name='Low', is_active=True, price=100, child_entities=child)
    factories.ParentEntityFactory.create(name='Draft', is_active=False, price=5, child_entities=child)
    client = get_api_client(sample_app)

    assert ids(query(client, URL_PARENT)) == sorted([str(high.id), str(low.id)])
    response = client.get(f'{URL_PARENT}{high.id}/')
    assert set(response.json()['data']['attributes']) == {'name'}

    for key in ('price__gte=500', 'price=900', 'description__isnull=false', 'is_active=true'):
        assert_invalid(query(client, URL_PARENT, filter=key), '/query/filter')
    assert_invalid(query(client, URL_PARENT, sort='price'), '/query/sort')
    assert_invalid(query(client, URL_CHILD, filter='parent_entities__price__gte=500'), '/query/filter')

    # neither `include` nor `fields[]` shows it
    response = client.get(
        f'{URL_CHILD}{child.id}/',
        params={'include': 'parent_entities', 'fields[entity.parent_entity]': 'name,price'},
    )
    assert response.status_code == 200, response.content
    included = response.json()['included']
    assert sorted(it['id'] for it in included) == sorted([str(high.id), str(low.id)])
    assert all(set(it['attributes']) == {'name'} for it in included)

    assert ids(query(client, URL_PARENT, filter='name=High')) == [str(high.id)]
    assert ids(query(client, URL_CHILD, filter='parent_entities__name=Low')) == [str(child.id)]
    response = client.get(f'{URL_PARENT}route_filter_fields/')
    assert response.status_code == 200, response.content
    names = {it['name'] for it in response.json()['fields']}
    assert 'name' in names and not names & {'price', 'description', 'is_active'}


@pytest.mark.django_db(transaction=True)
def test_relation_into_objects_hidden_from_user(sample_app, meetings):
    """
    A filter through a relation into the objects the user cannot see matches nothing.
    """
    team, secret, plain = meetings
    role = role_with('teams_only', 'entity.team.item.view.all')
    client = get_api_client(sample_app, user_with('teams_only', role).jwt_build())

    assert ids(query(client, URL_TEAM)) == [str(team.id)]
    assert ids(query(client, URL_TEAM, filter='meetings__title=Planning')) == []
    assert ids(query(client, URL_TEAM, filter='meetings__exists=true')) == []


def names_of(route_cls, user, **kwargs) -> set[str]:
    return {f.name for f in route_cls.query_fields(user=user, **kwargs)}


@pytest.mark.django_db(transaction=True)
def test_search_reaches_a_field_of_the_card(sample_app, meetings):
    """
    The list of `meeting_card` leaves the description out, its cards show it: the search
    finds by it, the filter and the sorting by it are 400 (the LIST schema has no such
    field).
    """
    team, secret, plain = meetings
    role = role_with('card_reader', *VIEW)
    user = user_with('card_reader', role)
    client = get_api_client(sample_app, user.jwt_build())

    response = query(client, URL_MEETING_CARD)
    assert all('description' not in it['attributes'] for it in response.json()['data'])
    response = client.get(f'{URL_MEETING_CARD}{secret.id}/')
    assert response.json()['data']['attributes']['description'] == 'Secret notes'

    assert ids(query(client, URL_MEETING_CARD, search='Secret')) == [str(secret.id)]
    assert ids(query(client, URL_MEETING_CARD, filter='$search=Secret')) == [str(secret.id)]
    assert ids(query(client, URL_MEETING_CARD, search='Review')) == [str(plain.id)]
    assert_invalid(query(client, URL_MEETING_CARD, filter='description=Secret'), '/query/filter')
    assert_invalid(query(client, URL_MEETING_CARD, sort='description'), '/query/sort')

    assert 'description' not in names_of(MeetingCardRouteSet, user)
    assert 'description' in names_of(MeetingCardRouteSet, user, api_action=CrudApiAction.RETRIEVE)
    assert route_search_fields(MeetingCardRouteSet) == ['title', 'description']


@pytest.mark.django_db(transaction=True)
def test_search_leaves_out_a_field_of_the_card_hidden_from_user(sample_app, meetings):
    """
    The field permissions apply to the fields of the card as to those of the list: a
    description they hide from the user is not searched on `meeting_card`.
    """
    team, secret, plain = meetings
    role = role_with('card_no_description', *VIEW, 'entity.meeting.field.view.all.description.disable')
    user = user_with('card_no_description', role)
    client = get_api_client(sample_app, user.jwt_build())

    response = client.get(f'{URL_MEETING_CARD}{secret.id}/')
    assert 'description' not in response.json()['data']['attributes']
    assert ids(query(client, URL_MEETING_CARD, search='Secret')) == []
    assert ids(query(client, URL_MEETING_CARD, filter='$search=Secret')) == []
    assert ids(query(client, URL_MEETING_CARD, search='Planning')) == [str(secret.id)]
    assert_invalid(query(client, URL_MEETING_CARD, filter='description=Secret'), '/query/filter')
    assert 'description' not in names_of(
        MeetingCardRouteSet, user, api_action=CrudApiAction.RETRIEVE
    )


@pytest.mark.django_db(transaction=True)
def test_search_leaves_out_a_field_of_the_card_hidden_in_some_objects(sample_app, meetings):
    """
    A description of the card the field permissions show in only some objects is not
    searched in any of them, as on the list: the search in the objects that show it would
    tell it in the others.
    """
    team, secret, plain = meetings
    role = role_with(
        'card_own_description', *VIEW, 'entity.meeting.field.view.participants.description.disable'
    )
    user = user_with('card_own_description', role)
    secret.participants.add(user)
    client = get_api_client(sample_app, user.jwt_build())

    response = client.get(f'{URL_MEETING_CARD}{secret.id}/')
    assert 'description' not in response.json()['data']['attributes']
    response = client.get(f'{URL_MEETING_CARD}{plain.id}/')
    assert response.json()['data']['attributes']['description'] == 'Plain notes'

    assert ids(query(client, URL_MEETING_CARD, search='Secret')) == []
    assert ids(query(client, URL_MEETING_CARD, search='Plain')) == []
    assert ids(query(client, URL_MEETING_CARD, search='Review')) == [str(plain.id)]
    assert 'description' not in names_of(
        MeetingCardRouteSet, user, api_action=CrudApiAction.RETRIEVE
    )


@pytest.mark.django_db(transaction=True)
def test_search_of_a_route_without_the_card(sample_app, meetings):
    """
    `meeting_columns` serves no card: the responses of its updates show the description
    (its RETRIEVE schema) only of the meetings the user changes, so the search does not
    reach it.
    """
    team, secret, plain = meetings
    role = role_with('columns_reader', *VIEW)
    user = user_with('columns_reader', role)
    client = get_api_client(sample_app, user.jwt_build())

    assert CrudApiAction.RETRIEVE in MeetingColumnsRouteSet.schema_factories
    listed = names_of(MeetingColumnsRouteSet, user)
    assert 'description' not in listed
    assert names_of(MeetingColumnsRouteSet, user, api_action=CrudApiAction.RETRIEVE) == listed
    assert route_search_fields(MeetingColumnsRouteSet) == ['title']
    assert ids(query(client, URL_MEETING_COLUMNS, search='Secret')) == []
    assert ids(query(client, URL_MEETING_COLUMNS, search='Planning')) == [str(secret.id)]


@pytest.mark.django_db(transaction=True)
def test_search_through_a_relation_reaches_the_card_of_the_related_objects(
    sample_app, meetings, monkeypatch
):
    """
    With `meeting_card` the default route of the meetings, `meetings__$search` of the teams
    reaches the description of their cards where the field permissions show it, and a filter
    by it through the relation is 400.
    """
    team, secret, plain = meetings
    monkeypatch.setattr(Meeting, '_default_route', MeetingCardRouteSet)

    role = role_with('teams_cards', *VIEW)
    client = get_api_client(sample_app, user_with('teams_cards', role).jwt_build())
    assert ids(query(client, URL_TEAM, filter='meetings__$search=Secret')) == [str(team.id)]
    assert_invalid(query(client, URL_TEAM, filter='meetings__description=Secret'), '/query/filter')

    role = role_with('teams_no_cards', *VIEW, 'entity.meeting.field.view.all.description.disable')
    client = get_api_client(sample_app, user_with('teams_no_cards', role).jwt_build())
    assert ids(query(client, URL_TEAM, filter='meetings__$search=Secret')) == []
    assert ids(query(client, URL_TEAM, filter='meetings__$search=Planning')) == [str(team.id)]


@pytest.mark.django_db(transaction=True)
def test_search_of_the_card_without_the_view_of_the_objects(sample_app, meetings):
    """
    A user who cannot view the meetings, and an anonymous user without roles, are refused a
    search by a field of the card as the list itself: 403 before the search runs.
    """
    role = role_with('teams_only_card', 'entity.team.item.view.all')
    clients = [
        get_api_client(sample_app, user_with('teams_only_card', role).jwt_build()),
        get_api_client(sample_app),
    ]
    for client in clients:
        for params in ({}, {'search': 'Secret'}, {'search': 'Planning'}):
            response = query(client, URL_MEETING_CARD, **params)
            assert response.status_code == 403, response.content
            assert response.json()['errors'][0]['code'] == 'ERR_FORBIDDEN'


def test_search_field_of_the_card_is_not_reported(sample_app, monkeypatch):
    """
    `bazis.W007` does not report a search field only the card of a route shows, it reports
    one of a route without the card.
    """
    def reported():
        return {it.obj for it in check_search_fields(None) if it.id == 'bazis.W007'}

    assert not {it for it in reported() if 'Meeting' in it}
    monkeypatch.setattr(MeetingColumnsRouteSet, 'search_fields', ['title', 'description'])
    assert {it for it in reported() if 'Meeting' in it} == {
        f'{MeetingColumnsRouteSet.__module__}.{MeetingColumnsRouteSet.__qualname__}'
    }
