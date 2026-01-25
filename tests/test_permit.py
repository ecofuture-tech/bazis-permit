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

from urllib.parse import quote, urlencode

import pytest
from bazis_test_utils.utils import get_api_client
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.users import get_user_model

from tests import factories


User = get_user_model()


GROUPS = {
    'parent_entity': [
        'entity.parent_entity.item.add.all',  # everyone has the ability to add records
        'entity.parent_entity.item.view.author',  # everyone has the ability to view any records
        'entity.parent_entity.item.change.author',  # only the author can edit the record
    ],
    'parent_entity_view_all': [
        'entity.parent_entity.item.add.all',  # everyone has the ability to add records
        'entity.parent_entity.item.view.all',  # everyone has the ability to view any records
        'entity.parent_entity.item.change.author',  # only the author can edit the record
    ],
    'child_entity': [
        'entity.child_entity.item.add.all',  # everyone has the ability to add records
        'entity.child_entity.item.view.all',  # everyone has the ability to view any records
        'entity.child_entity.item.change.author',  # only the author can edit the record
        'entity.child_entity.item.change.author_parent',  # the parent author can edit the record
        'entity.child_entity.item.delete.author',  # only the author can delete the record
    ],
    'dependent_entity': [
        'entity.dependent_entity.item.add.all',  # everyone has the ability to add records
        'entity.dependent_entity.item.view.all',  # everyone has the ability to view any records
        'entity.dependent_entity.item.change.author',  # only the author can edit the record
        'entity.dependent_entity.item.delete.author',  # only the author can delete the record
    ],
    'extended_entity': [
        'entity.extended_entity.item.add.all',  # everyone has the ability to add records
        'entity.extended_entity.item.view.author',  # only the author can view the record
        'entity.extended_entity.item.view.author_parent',  # the parent author can edit the record
        'entity.extended_entity.item.change.author',  # only the author can edit the record
        'entity.extended_entity.item.delete.author',  # only the author can delete the record
    ],
    'complex_parent_entity': [
        'entity.parent_entity.item.add.all',
        f'entity.parent_entity.item.check.author=__selector__&name={quote("Test name")}',
        'entity.parent_entity.item.view.author=__selector__',
        'entity.parent_entity.item.change.author=__selector__&is_active=false',
        'entity.parent_entity.field.view.author=__selector__&is_active=true.description.enable',
        'entity.parent_entity.field.view.author=__selector__&is_active=true.__all__.disable',
        'entity.parent_entity.field.view.author=__selector__&is_active=false.description.disable',
    ],
    'child_entity_fields': [
        'entity.child_entity.item.add.all',
        'entity.child_entity.field.add.all.child_name.filter:^[A-Z]+$',
        'entity.parent_entity.field.add.all.child_entities.filter:child_is_active=true',
        'entity.child_entity.field.change.all.child_name.filter:^[A-Z]+$',
        'entity.parent_entity.field.change.all.child_entities.filter:child_is_active=true',
        'entity.dependent_entity.field.add.all.parent_entity.filter:is_active=true',
        'entity.dependent_entity.field.change.all.parent_entity.filter:is_active=true',
    ],
}


@pytest.fixture(scope='function')
def groups():
    # create roles and groups
    groups = {}
    for group_name, permissions in GROUPS.items():
        group = GroupPermission.objects.create(
            slug=group_name,
            **{to_attribute('name'): group_name}
        )
        for it in permissions:
            group.permissions.add(Permission.objects.get_or_create(slug=it)[0])
        groups[group_name] = group
    return groups


def role_create(groups, name: str, groups_names: list[str]):
    """
    Helper function to create a role and assign it to specified groups of
    permissions.
    """
    # create roles and groups
    role = Role.objects.create(slug=name, **{to_attribute('name'): name})
    for group_name in groups_names:
        role.groups_permission.add(groups[group_name])
    return role


@pytest.mark.django_db(transaction=True)
def test_transfer_trigger():
    """
    Test the transfer trigger functionality by creating a parent entity and a child
    entity, linking them, and verifying the parent author relationship.
    """
    user_1 = User.objects.create_user('user1', email='user1@site.com', password='weak_password_2')
    parent_entity = factories.ParentEntityFactory.create(author=user_1)
    child_entity = factories.ChildEntityFactory.create()
    parent_entity.child_entities.add(child_entity)
    child_entity.save()
    child_entity.refresh_from_db()
    assert child_entity.author_parent == parent_entity.author


@pytest.mark.django_db(transaction=True)
def test_permit(sample_app, groups):
    """
    Test the permission system by verifying the ability to create, view, edit, and
    delete records based on user roles and permissions.
    """
    # without authorization, you cannot view/patch/create/delete records on protected routes
    parent_entity = factories.ParentEntityFactory.create(child_entities=True)

    response = get_api_client(sample_app).get(f'/api/v1/entity/parent_entity/{parent_entity.id}/schema_retrieve/')
    assert response.status_code == 403

    response = get_api_client(sample_app).get(f'/api/v1/entity/parent_entity/{parent_entity.id}/')
    assert response.status_code == 403

    response = get_api_client(sample_app).patch(
        f'/api/v1/entity/parent_entity/{parent_entity.id}/',
        json_data={
            'data': {
                'id': str(parent_entity.id),
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'name': 'New test name',
                },
            },
        },
    )
    assert response.status_code == 403

    response = get_api_client(sample_app).post(
        '/api/v1/entity/parent_entity/',
        json_data={
            'data': {
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {
                    'name': 'Test name',
                    'description': 'Test description',
                    'is_active': True,
                    'price': '100.49',
                    'dt_approved': '2024-01-12T16:54:12Z',
                },
            },
        },
    )
    assert response.status_code == 403

    response = get_api_client(sample_app).delete(
        f'/api/v1/entity/parent_entity/{str(parent_entity.id)}/'
    )
    assert response.status_code == 403

    user_1 = User.objects.create_user('user1', email='user1@site.com', password='weak_password_1')
    user_2 = User.objects.create_user('user2', email='user2@site.com', password='weak_password_2')
    user_3 = User.objects.create_user('user3', email='user3@site.com', password='weak_password_3')

    # user_1 is assigned the role role_user1, which has access to the parent_entity
    # and child_entity groups
    user_1.roles.add(
        role_create(
            groups,
            'role_user1',
            [
                'parent_entity',
                'child_entity',
                'dependent_entity',
                'extended_entity',
            ],
        )
    )
    user_2.roles.add(
        role_create(
            groups,
            'role_user2',
            [
                'parent_entity_view_all',
                'child_entity',
                'dependent_entity',
                'extended_entity',
            ],
        )
    )
    user_3.roles.add(role_create(groups,'role_user3', ['child_entity']))

    # now user_1 can create records in parent_entity
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/entity/parent_entity/',
        json_data={
            'data': {
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {
                    'name': 'Test name',
                    'description': 'Test description',
                    'is_active': True,
                    'price': '100.49',
                    'dt_approved': '2024-01-12T16:54:12Z',
                },
            },
        },
    )
    assert response.status_code == 201

    data = response.json()

    it = data['data']
    assert it['type'] == 'entity.parent_entity'
    assert it['bs:action'] == 'view'

    parent_entity_id = str(it['id'])

    response = get_api_client(sample_app).get(
        '/api/v1/entity/parent_entity/',
    )
    assert response.status_code == 403


    response = get_api_client(sample_app, user_1.jwt_build()).get(
        '/api/v1/entity/parent_entity/',
    )
    assert response.status_code == 200
    assert len(response.json()['data']) == 1


    # user user_2 can view records in parent_entity
    response = get_api_client(sample_app, user_2.jwt_build()).get(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/'
    )
    assert response.status_code == 200

    # user user_1 can edit the record in parent_entity
    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/',
        json_data={
            'data': {
                'id': parent_entity_id,
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'name': 'Test name',
                    'description': 'Test description',
                    'is_active': True,
                    'price': '100.49',
                    'dt_approved': '2024-01-12T16:54:12Z',
                },
            },
        },
    )
    assert response.status_code == 200

    # user user_2 does not have access to edit parent_entity
    response = get_api_client(sample_app, user_2.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/',
        json_data={
            'data': {
                'id': parent_entity_id,
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'name': 'Test name',
                    'description': 'Test description',
                    'is_active': True,
                    'price': '100.49',
                    'dt_approved': '2024-01-12T16:54:12Z',
                },
            },
        },
    )
    assert response.status_code == 403

    # user user_1 cannot delete the record in parent_entity
    response = get_api_client(sample_app, user_1.jwt_build()).delete(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/'
    )
    assert response.status_code == 403

    # user user_3 creates a child record, referencing parent_entity_id
    response = get_api_client(sample_app, user_3.jwt_build()).post(
        '/api/v1/entity/child_entity/',
        json_data={
            'data': {
                'type': 'entity.child_entity',
                'bs:action': 'add',
                'attributes': {
                    'child_name': 'Child test name 2',
                    'child_description': 'Child test description 2',
                    'child_is_active': False,
                    'child_price': '25.19',
                    'child_dt_approved': '2024-01-13T16:54:12Z',
                },
                'relationships': {
                    'parent_entities': {
                        'data': [
                            {
                                'id': parent_entity_id,
                                'type': 'entity.parent_entity',
                            }
                        ],
                    },
                },
            },
        },
    )
    assert response.status_code == 201
    child_entity_id = str(response.json()['data']['id'])

    # since the relationship between child_entity and parent_entity is m2m,
    # child_entity needs to be updated to refresh author_parent
    response = get_api_client(sample_app, user_3.jwt_build()).patch(
        f'/api/v1/entity/child_entity/{child_entity_id}/',
        json_data={
            'data': {
                'id': child_entity_id,
                'type': 'entity.child_entity',
                'bs:action': 'change',
                'attributes': {},
            },
        },
    )
    assert response.status_code == 200

    data = response.json()
    relationships = data['data']['relationships']

    # check that the parent author matches the parent author of the child record
    assert relationships['author_parent'] == {
        'data': {
            'id': str(user_1.pk),
            'type': 'users.user',
        },
    }

    # user user_2 cannot edit child_entity
    response = get_api_client(sample_app, user_2.jwt_build()).patch(
        f'/api/v1/entity/child_entity/{child_entity_id}/',
        json_data={
            'data': {
                'id': child_entity_id,
                'type': 'entity.child_entity',
                'bs:action': 'change',
                'attributes': {},
            },
        },
    )
    assert response.status_code == 403

    # user user_1 can edit child_entity thanks to 'entity.child_entity.item.change.author_parent'
    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/child_entity/{child_entity_id}/',
        json_data={
            'data': {
                'id': child_entity_id,
                'type': 'entity.child_entity',
                'bs:action': 'change',
                'attributes': {},
            },
        },
    )
    assert response.status_code == 200

    # user_1 can add dependent_entity and extended_entity
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/entity/dependent_entity/',
        json_data={
            'data': {
                'type': 'entity.dependent_entity',
                'bs:action': 'add',
                'attributes': {
                    'dependent_name': 'Dependent test name',
                    'dependent_description': 'Dependent test description',
                    'dependent_is_active': True,
                    'dependent_price': '100.00',
                    'dependent_dt_approved': '2024-06-28T16:54:12Z',
                },
                'relationships': {
                    'parent_entity': {
                        'data': {
                            'id': parent_entity_id,
                            'type': 'entity.parent_entity',
                        },
                    },
                },
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    it = data['data']
    assert it['type'] == 'entity.dependent_entity'
    assert it['bs:action'] == 'view'

    assert data['data']['relationships']['author_parent']['data']['id'] == str(user_1.id)
    depended_entity_id = str(it['id'])

    # user_1 can add extended_entity
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/entity/extended_entity/',
        json_data={
            'data': {
                'type': 'entity.extended_entity',
                'bs:action': 'add',
                'attributes': {
                    'extended_name': 'Extended test name',
                    'extended_description': 'Extended test description',
                    'extended_is_active': True,
                    'extended_price': '100.00',
                    'extended_dt_approved': '2024-06-28T16:54:12Z',
                },
                'relationships': {
                    'parent_entity': {
                        'data': {
                            'id': parent_entity_id,
                            'type': 'entity.parent_entity',
                        },
                    },
                },
            }
        },
    )

    assert response.status_code == 201

    data = response.json()

    it = data['data']
    assert it['type'] == 'entity.extended_entity'
    assert it['bs:action'] == 'view'

    assert data['data']['relationships']['author_parent']['data']['id'] == str(user_1.id)
    extended_entity_id = str(it['id'])

    # user user_2 can view parent_entity and child_entity, dependent_entity,
    # but not extended_entity
    query = urlencode(
        {
            'include': 'extended_entity,dependent_entities,child_entities',
        }
    )

    response = get_api_client(sample_app, user_2.jwt_build()).get(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/?{query}'
    )
    assert response.status_code == 200

    data = response.json()

    it = data['data']
    assert it['type'] == 'entity.parent_entity'
    assert it['bs:action'] == 'view'

    assert parent_entity_id == str(it['id'])

    assert len(data['included']) == 2

    for include in data['included']:
        assert include['type'] in ['entity.child_entity', 'entity.dependent_entity']
        assert include['type'] != 'entity.extended_entity'

    # user user_1 can view parent_entity and child_entity, dependent_entity and extended_entity
    response = get_api_client(sample_app, user_1.jwt_build()).get(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/?{query}'
    )
    assert response.status_code == 200

    data = response.json()

    it = data['data']
    assert it['type'] == 'entity.parent_entity'
    assert it['bs:action'] == 'view'

    assert parent_entity_id == str(it['id'])

    assert len(data['included']) == 3
    for include in data['included']:
        assert include['type'] in [
            'entity.child_entity',
            'entity.dependent_entity',
            'entity.extended_entity',
        ]

    # user user_2 cannot delete the record with extended_entity and dependent_entity
    response = get_api_client(sample_app, user_2.jwt_build()).delete(
        f'/api/v1/entity/extended_entity/{extended_entity_id}/'
    )
    assert response.status_code == 403

    response = get_api_client(sample_app, user_2.jwt_build()).delete(
        f'/api/v1/entity/dependent_entity/{depended_entity_id}/'
    )
    assert response.status_code == 403

    # user user_1 can delete the record with extended_entity and dependent_entity
    response = get_api_client(sample_app, user_1.jwt_build()).delete(
        f'/api/v1/entity/extended_entity/{extended_entity_id}/'
    )
    assert response.status_code == 204

    response = get_api_client(sample_app, user_1.jwt_build()).delete(
        f'/api/v1/entity/dependent_entity/{depended_entity_id}/'
    )
    assert response.status_code == 204


@pytest.mark.django_db(transaction=True)
def test_permit_complex(sample_app, groups):
    """
    Test the permission system by verifying the ability to create, view, edit, and
    delete records based on user roles and permissions.
    """
    user_1 = User.objects.create_user('user1', email='user1@site.com', password='weak_password_1')

    # user_1 is assigned the role role_user1, which has access to the parent_entity
    # and child_entity groups
    user_1.roles.add(
        role_create(
            groups,
            'role_user1',
            [
                'complex_parent_entity',
            ],
        )
    )

    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/entity/parent_entity/',
        json_data={
            'data': {
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {
                    'name': 'Test name 1',
                    'description': 'Test description',
                    'is_active': True,
                    'price': '100.49',
                    'dt_approved': '2024-01-12T16:54:12Z',
                },
            },
        },
    )
    assert response.status_code == 403

    # now user_1 can create records in parent_entity
    for _ in range(2):
        response = get_api_client(sample_app, user_1.jwt_build()).post(
            '/api/v1/entity/parent_entity/',
            json_data={
                'data': {
                    'type': 'entity.parent_entity',
                    'bs:action': 'add',
                    'attributes': {
                        'name': 'Test name',
                        'description': 'Test description',
                        'is_active': False,
                        'price': '100.49',
                        'dt_approved': '2024-01-12T16:54:12Z',
                    },
                },
            },
        )

        assert response.status_code == 201

        data = response.json()

        it = data['data']
        assert it['type'] == 'entity.parent_entity'
        assert it['bs:action'] == 'view'

    item_id = response.json()['data']['id']

    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{item_id}/',
        json_data={
            'data': {
                'id': item_id,
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'is_active': True,
                },
            },
        },
    )
    assert response.status_code == 200

    # the second attempt to change the record will be unsuccessful because only is_active=false is allowed for editing
    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{item_id}/',
        json_data={
            'data': {
                'id': item_id,
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'is_active': True,
                },
            },
        },
    )
    assert response.status_code == 403


    response = get_api_client(sample_app, user_1.jwt_build()).get(
        '/api/v1/entity/parent_entity/',
    )
    assert response.status_code == 200

    data_list = response.json()['data']

    assert len(data_list) == 2

    for it in data_list:
        if it['id'] == item_id:
            assert it['attributes'] == {'description': 'Test description'}
        else:
            assert 'description' not in it['attributes']


@pytest.mark.django_db(transaction=True)
def test_filters_fields(sample_app, groups):
    user_1 = User.objects.create_user('user1', email='user1@site.com', password='weak_password_1')

    user_1.roles.add(
        role_create(
            groups,
            'role_user1',
            [
                'child_entity',
                'child_entity_fields',
                'parent_entity',
                'dependent_entity',
            ],
        )
    )

    children_is_active = [True, False, True]

    # create child items with different child_is_active values
    # also pass child_name, which does not match the field filter
    children = []
    for is_active in children_is_active:
        response = get_api_client(sample_app, user_1.jwt_build()).post(
            '/api/v1/entity/child_entity/',
            json_data={
                'data': {
                    'type': 'entity.child_entity',
                    'bs:action': 'add',
                    'attributes': {
                        'child_name': 'Test name 1',
                        'child_description': 'Test description',
                        'child_is_active': is_active,
                        'child_price': '100.49',
                        'child_dt_approved': '2024-01-12T16:54:12Z',
                    },
                },
            },
        )

        data = response.json()

        assert response.status_code == 201

        # make sure that child_name is not set
        assert data['data']['attributes']['child_name'] == ''

        children.append(data['data']['id'])

    # create a parent item, trying to set ALL child items
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/entity/parent_entity/',
        json_data={
            'data': {
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {
                    'name': 'Test name 1',
                    'description': 'Test description',
                    'is_active': True,
                    'price': '100.49',
                    'dt_approved': '2024-01-12T16:54:12Z',
                },
                'relationships': {
                    'child_entities': {
                        'data': [
                            {
                                'type': 'entity.child_entity',
                                'id': child_id,
                            } for child_id in children
                        ],
                    },
                },
            },
        },
    )

    data = response.json()

    parent_id = data['data']['id']

    child_data_ids = [child['id'] for child in data['data']['relationships']['child_entities']['data']]

    # ONLY child items with child_is_active=True should be set after creating the parent
    for i, child in enumerate(children):
        if children_is_active[i]:
            assert child in child_data_ids
        else:
            assert child not in child_data_ids

    # now set a valid child_name, but deactivate child_is_active
    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/child_entity/{children[0]}/',
        json_data={
            'data': {
                'id': children[0],
                'type': 'entity.child_entity',
                'bs:action': 'change',
                'attributes': {
                    'child_name': 'TEST',
                    'child_is_active': False,
                },
            },
        },
    )
    assert response.status_code == 200

    data = response.json()

    # make sure that child_name is set
    assert data['data']['attributes']['child_name'] == 'TEST'

    # explicitly set only 1 child item (the third one)
    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{parent_id}/',
        json_data={
            'data': {
                'id': parent_id,
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'relationships': {
                    'child_entities': {
                        'data': [
                            {
                                'type': 'entity.child_entity',
                                'id': child_id,
                            } for child_id in children[2:3]
                        ],
                    },
                },
            },
        },
    )

    data = response.json()

    # although only the third one was set, the first one is also available, because at the time of changing
    # the parent, the first item's child_is_active = False, and resetting it
    # is not available to the user, therefore it remains in the set
    assert len(data['data']['relationships']['child_entities']['data']) == 2
    #
    for child in data['data']['relationships']['child_entities']['data']:
        # this item is available because the user cannot change it according to the filter (child_is_active: False)
        if child['id'] == children[0]:
            assert child['id'] in children
        # this item is available because the user can change it according to the filter and it was just set (child_is_active: False)
        if child['id'] == children[2]:
            assert child['id'] in children

    # in this case we can set the parent, because the parent has is_active: True
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/entity/dependent_entity/',
        json_data={
            'data': {
                'type': 'entity.dependent_entity',
                'bs:action': 'add',
                'attributes': {
                    'dependent_name': 'Dependent test name',
                },
                'relationships': {
                    'parent_entity': {
                        'data':
                            {
                                'type': 'entity.parent_entity',
                                'id': parent_id,
                            }
                        ,
                    },
                },
            },
        },
    )

    data = response.json()

    dependent_entity_id = data['data']['id']

    assert data['data']['relationships']['parent_entity']['data']['id'] == parent_id

    # set the parent to is_active: False
    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{parent_id}/',
        json_data={
            'data': {
                'id': parent_id,
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'is_active': False,
                },
            },
        },
    )

    parent_wrong = factories.ParentEntityFactory.create(
        name='Parent test name',
    )

    # in this case we cannot change the parent, because the original parent has is_active: False
    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/dependent_entity/{dependent_entity_id}/',
        json_data={
            'data': {
                'id': dependent_entity_id,
                'type': 'entity.dependent_entity',
                'bs:action': 'change',
                'relationships': {
                    'parent_entity': {
                        'data':
                            {
                                'type': 'entity.parent_entity',
                                'id': str(parent_wrong.id),
                            }
                        ,
                    },
                },
            },
        },
    )

    data = response.json()

    assert data['data']['relationships']['parent_entity']['data']['id'] == parent_id
