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
permissions show the user (`PermitRouteBase.query_fields`, the query scope of Bazis 2.9).
"""

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import Meeting, Team
from entity.routes import MeetingRouteSet

from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

from .test_permit_selectors import URL_MEETING, URL_TEAM, ids, role_with, user_with


pytestmark = pytest.mark.skipif(
    not hasattr(JsonapiRouteBase, 'query_scope'),
    reason='the filter, the sorting and the search are restricted since Bazis 2.9',
)

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
    A field the permissions show in only some objects (or an object no field permission
    matches, which has every field) stays reachable for all the objects of the list: the
    known limitation of the per-user scope.
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
    assert ids(query(client, URL_MEETING, filter='description=Secret')) == [str(secret.id)]


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
