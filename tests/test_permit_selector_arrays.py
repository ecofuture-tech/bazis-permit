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
The generated selector arrays (`autogen_<field>_selectors` of `autogen_selectors_fields`)
are not in the schemas of the routes (`PermitModelMixin.get_fields_hidden`): a client
neither reads the ids of the users in them nor writes them to grant the visibility of an
object. They still select the objects for the permissions.
"""

import json

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity

from tests import factories
from tests.test_permit_selectors import role_with, user_with


ARRAY = 'autogen_author_selectors'
URL = '/api/v1/entity/parent_entity/'


@pytest.fixture
def users(db):
    role = role_with(
        'parent_author',
        'entity.parent_entity.item.add.all',
        'entity.parent_entity.item.view.author',
        'entity.parent_entity.item.change.author',
        'entity.dependent_entity.item.view.all',
    )
    return user_with('author', role), user_with('delegate', role), user_with('outsider', role)


@pytest.mark.django_db(transaction=True)
def test_selector_arrays_not_in_the_schemas(sample_app, users):
    author, _delegate, _outsider = users
    assert ARRAY in ParentEntity.get_fields_info().attributes
    assert ARRAY in ParentEntity.get_fields_hidden()

    item = factories.ParentEntityFactory(author=author)
    dependent = factories.DependentEntityFactory(parent_entity=item, author=author)
    client = get_api_client(sample_app, author.jwt_build())

    assert ARRAY not in json.dumps(sample_app.openapi())
    for url in (
        f'{URL}schema_list/',
        f'{URL}schema_create/',
        f'{URL}{item.pk}/schema_retrieve/',
        f'{URL}{item.pk}/schema_update/',
    ):
        response = client.get(url)
        assert response.status_code == 200, (url, response.text)
        assert ARRAY not in response.text, url

    response = client.get(f'{URL}{item.pk}/')
    assert response.status_code == 200, response.text
    assert ARRAY not in response.json()['data']['attributes']
    assert ARRAY not in client.get(URL).text

    # included by the route of another model: the default route of the parent entities
    response = client.get(f'/api/v1/entity/dependent_entity/{dependent.pk}/?include=parent_entity')
    assert response.status_code == 200, response.text
    included = response.json()['included']
    assert included and ARRAY not in included[0]['attributes']

    # not a key of a filter nor of a sort
    assert client.get(f'{URL}?filter={ARRAY}={author.pk}').status_code == 400
    assert client.get(f'{URL}?sort={ARRAY}').status_code == 400


@pytest.mark.django_db(transaction=True)
def test_selector_arrays_not_written_by_a_client(sample_app, users):
    """
    A writer of the object cannot put the id of another user into its array: the array
    would give him the permissions of the author on it.
    """
    author, delegate, _outsider = users
    item = factories.ParentEntityFactory(author=author)
    client = get_api_client(sample_app, author.jwt_build())

    response = client.patch(
        f'{URL}{item.pk}/',
        json_data={
            'data': {
                'id': str(item.pk),
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {ARRAY: [str(delegate.pk)]},
            },
        },
    )
    assert response.status_code == 422, response.text
    item.refresh_from_db()
    assert getattr(item, ARRAY) is None

    response = client.post(
        URL,
        json_data={
            'data': {
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {'name': 'New', ARRAY: [str(delegate.pk)]},
            },
        },
    )
    assert response.status_code == 422, response.text
    assert not ParentEntity.objects.filter(name='New').exists()


@pytest.mark.django_db(transaction=True)
def test_selector_arrays_select_the_objects(sample_app, users):
    """
    The array the project fills selects the object for the permissions of its selector:
    the delegate it names sees and changes it as the author, another user does not.
    """
    author, delegate, outsider = users
    item = factories.ParentEntityFactory(author=author)
    ParentEntity.objects.filter(pk=item.pk).update(**{ARRAY: [str(delegate.pk)]})

    client = get_api_client(sample_app, delegate.jwt_build())
    assert [it['id'] for it in client.get(URL).json()['data']] == [str(item.pk)]
    response = client.patch(
        f'{URL}{item.pk}/',
        json_data={
            'data': {
                'id': str(item.pk),
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {'name': 'Renamed'},
            },
        },
    )
    assert response.status_code == 200, response.text
    assert ARRAY not in response.json()['data']['attributes']

    client = get_api_client(sample_app, outsider.jwt_build())
    assert client.get(URL).json()['data'] == []
    assert client.get(f'{URL}{item.pk}/').status_code == 404
