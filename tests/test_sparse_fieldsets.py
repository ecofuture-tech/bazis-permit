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

import pytest
from urllib.parse import quote
from bazis_test_utils.utils import get_api_client
from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.users import get_user_model

from tests import factories

User = get_user_model()

GROUPS = {
    'parent_entity': [
        'entity.parent_entity.item.add.all',  # everyone has the ability to add records
        'entity.parent_entity.item.view.author',  # only author has the ability to view his own records
        'entity.parent_entity.item.change.author',  # only the author can edit his own record
    ],
    'child_entity': [
        'entity.child_entity.item.view.all',  # everyone has the ability to view any records
        'entity.child_entity.item.change.author',  # only the author can edit the record
    ],
    'complex_parent_entity': [
        'entity.parent_entity.item.add.all',
        'entity.parent_entity.item.view.author=__selector__',
        f'entity.parent_entity.item.check.author=__selector__&name={quote("Test name 2")}',
        'entity.parent_entity.item.change.author=__selector__&is_active=false',
        'entity.parent_entity.field.view.author=__selector__&is_active=true.description.enable',
        'entity.parent_entity.field.view.author=__selector__&is_active=true.__all__.disable',
        'entity.parent_entity.field.view.author=__selector__&is_active=false.description.disable',
    ],
}


@pytest.fixture(scope='function')
def groups():
    # create roles and groups
    groups = {}
    for group_name, permissions in GROUPS.items():
        group = GroupPermission.objects.create(name_en=group_name, slug=group_name)
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
    role = Role.objects.create(name_en=name, slug=name)
    for group_name in groups_names:
        role.groups_permission.add(groups[group_name])
    return role


@pytest.mark.django_db(transaction=True)
def test_sparse_fieldsets(sample_app, groups):
    user_1 = User.objects.create_user('user1', email='user1@site.com', password='weak_password_2')
    parent_entity = factories.ParentEntityFactory.create(author=user_1,
                                                         description="Really hour finish thought old. Final might responsibility job result practice price possible.")
    child_entity = factories.ChildEntityFactory.create(child_name="David Bennett")
    parent_entity.child_entities.add(child_entity)
    child_entity.save()
    child_entity.refresh_from_db()

    role_1 = role_create(
        groups,
        'role_user1',
        [
            'parent_entity',
            'child_entity',
        ],
    )
    user_1.roles.add(role_1)

    # Проверка для списка.
    # Передаем поля основной модели (description), релейшенов (author), расчетных полей (childs_detail) и полей проперти (some_count_property).
    # При этом не передаем обязательный для request модели name, чтобы проверить его необязательность в response
    # Проверяем, что все остальные поля исключены.
    url = '/api/v1/entity/parent_entity/?fields[entity.parent_entity]=description,author,childs_detail,some_count_property'

    response = get_api_client(sample_app, user_1.jwt_build()).get(url)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "data": [
            {
                "attributes": {
                    "childs_detail": [
                        {
                            "child_name": "David Bennett",
                            "id": str(child_entity.id),
                        }
                    ],
                    "description": "Really hour finish thought old. Final might responsibility job result practice price possible.",
                    "some_count_property": 1000
                },
                "bs:action": "view",
                "id": str(parent_entity.id),
                "relationships": {
                    "author": {
                        "data": {
                            "id": str(user_1.id),
                            "type": "users.user"
                        }
                    }
                },
                "type": "entity.parent_entity"
            }
        ],
        "links": {
            "first": "http://testserver/api/v1/entity/parent_entity/?fields%5Bentity.parent_entity%5D=description%2Cauthor%2Cchilds_detail%2Csome_count_property",
            "last": "http://testserver/api/v1/entity/parent_entity/?fields%5Bentity.parent_entity%5D=description%2Cauthor%2Cchilds_detail%2Csome_count_property&page%5Blimit%5D=20&page%5Boffset%5D=0",
            "next": None,
            "prev": None
        },
        "meta": {}
    }

    # Проверка для объекта.
    # Передаем поля основной модели (description), релейшенов (author), расчетных полей (childs_detail) и полей проперти (some_count_property).
    # Передаем ограничение полей двух связанных моделей подключенных через include, fk и m2m связи.
    # При этом не передаем обязательный для request модели name, чтобы проверить его необязательность в response
    # Проверяем, что все остальные поля исключены.
    url = f'/api/v1/entity/parent_entity/{parent_entity.id}/?fields[entity.parent_entity]=description,author,childs_detail,some_count_property'
    url += '&include=author,child_entities&fields[users.user]=username&fields[entity.child_entity]=child_name'

    response = get_api_client(sample_app, user_1.jwt_build()).get(url)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "data": {
            "attributes": {
                "childs_detail": [
                    {
                        "child_name": "David Bennett",
                        "id": str(child_entity.id)
                    }
                ],
                "description": "Really hour finish thought old. Final might responsibility job result practice price possible.",
                "some_count_property": 1000
            },
            "bs:action": "view",
            "id": str(parent_entity.id),
            "relationships": {
                "author": {
                    "data": {
                        "id": str(user_1.id),
                        "type": "users.user"
                    }
                }
            },
            "type": "entity.parent_entity"
        },
        "included": [
            {
                "attributes": {
                    "username": "user1"
                },
                "bs:action": "view",
                "id": str(user_1.id),
                "relationships": {},
                "type": "users.user"
            },
            {
                "attributes": {
                    "child_name": "David Bennett"
                },
                "bs:action": "view",
                "id": str(child_entity.id),
                "relationships": {},
                "type": "entity.child_entity"
            }
        ],
        "meta": {}
    }

    # Проверим что удаление прав на таблицу child_entity сразу удалит связи с этой таблицей из ответа из included.
    role_1.groups_permission.remove(groups['child_entity'])

    response = get_api_client(sample_app, user_1.jwt_build()).get(url)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "data": {
            "attributes": {
                "childs_detail": [
                    {
                        "child_name": "David Bennett",
                        "id": str(child_entity.id)
                    }
                ],
                "description": "Really hour finish thought old. Final might responsibility job result practice price possible.",
                "some_count_property": 1000
            },
            "bs:action": "view",
            "id": str(parent_entity.id),
            "relationships": {
                "author": {
                    "data": {
                        "id": str(user_1.id),
                        "type": "users.user"
                    }
                }
            },
            "type": "entity.parent_entity"
        },
        "included": [
            {
                "attributes": {
                    "username": "user1"
                },
                "bs:action": "view",
                "id": str(user_1.id),
                "relationships": {},
                "type": "users.user"
            }
        ],
        "meta": {}
    }

    user_2 = User.objects.create_user('user2', email='user1@site.com', password='weak_password_2')

    # user_2 is assigned the role role_user2, which has access to the parent_entity and child_entity groups
    role_2 = role_create(
        groups,
        'role_user2',
        [
            'complex_parent_entity',
        ],
    )
    user_2.roles.add(role_2)

    # Проверка при создании по наименованию.
    # f'entity.parent_entity.item.check.author=__selector__&name={quote("Test name 2")}',
    response = get_api_client(sample_app, user_2.jwt_build()).post(
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
    items_id = []
    for _ in range(2):
        response = get_api_client(sample_app, user_2.jwt_build()).post(
            '/api/v1/entity/parent_entity/',
            json_data={
                'data': {
                    'type': 'entity.parent_entity',
                    'bs:action': 'add',
                    'attributes': {
                        'name': 'Test name 2',
                        'description': 'Test description',
                        'is_active': False,
                        'price': '100.49',
                        'dt_approved': '2024-01-12T16:54:12Z',
                    },
                },
            },
        )
        assert response.status_code == 201
        items_id.append(response.json()['data']['id'])

    # Проверка при обновлении по полю is_active подлежащего изменению объекта
    # 'entity.parent_entity.item.change.author=__selector__&is_active=false',
    response = get_api_client(sample_app, user_2.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{items_id[1]}/',
        json_data={
            'data': {
                'id': items_id[1],
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
    response = get_api_client(sample_app, user_2.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{items_id[1]}/',
        json_data={
            'data': {
                'id': items_id[1],
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'is_active': True,
                },
            },
        },
    )
    assert response.status_code == 403

    # Проверяем что автор видит только свои записи 'entity.parent_entity.item.view.author=__selector__',
    # Проверяем что поле description включается только для is_active=true, при этом другие поля сразу отключаются.
    # И наоборот, если is_active=false, то поле description не включается, зато другие не отключаются.
    # 'entity.parent_entity.field.view.author=__selector__&is_active=true.description.enable',
    # 'entity.parent_entity.field.view.author=__selector__&is_active=true.__all__.disable',
    # 'entity.parent_entity.field.view.author=__selector__&is_active=false.description.disable',
    url = '/api/v1/entity/parent_entity/?fields[entity.parent_entity]=description,author,childs_detail,some_count_property'
    response = get_api_client(sample_app, user_2.jwt_build()).get(url)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "data": [
            {
                "attributes": {
                    "childs_detail": [],
                    "some_count_property": 1000
                },
                "bs:action": "view",
                "id": str(items_id[0]),
                "relationships": {
                    "author": {
                        "data": {
                            "id": str(user_2.id),
                            "type": "users.user"
                        }
                    }
                },
                "type": "entity.parent_entity"
            },
            {
                "attributes": {
                    "description": "Test description"
                },
                "bs:action": "view",
                "id": str(items_id[1]),
                "relationships": {},
                "type": "entity.parent_entity"
            }
        ],
        "links": {
            "first": "http://testserver/api/v1/entity/parent_entity/?fields%5Bentity.parent_entity%5D=description%2Cauthor%2Cchilds_detail%2Csome_count_property",
            "last": "http://testserver/api/v1/entity/parent_entity/?fields%5Bentity.parent_entity%5D=description%2Cauthor%2Cchilds_detail%2Csome_count_property&page%5Blimit%5D=20&page%5Boffset%5D=0",
            "next": None,
            "prev": None
        },
        "meta": {}
    }
