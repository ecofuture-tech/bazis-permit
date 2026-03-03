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

from uuid import uuid4

import pytest
from bazis_test_utils.utils import get_api_client
from translated_fields import to_attribute

from bazis.contrib.permit.models import Role
from bazis.contrib.users import get_user_model


User = get_user_model()


def create_user() -> User:
    suffix = uuid4().hex[:8]
    return User.objects.create_user(
        f'user_{suffix}',
        email=f'user_{suffix}@site.com',
        password='weak_password',
    )


def create_role(name: str) -> Role:
    return Role.objects.create(slug=name, **{to_attribute('name'): name})


def patch_user_roles(sample_app, auth_user: User, target_user: User, role_ids: list[str]):
    return get_api_client(sample_app, auth_user.jwt_build()).patch(
        f'/api/v1/users/user/{target_user.id}/',
        json_data={
            'data': {
                'id': str(target_user.id),
                'type': 'users.user',
                'bs:action': 'change',
                'attributes': {},
                'relationships': {
                    'roles': {
                        'data': [
                            {
                                'id': str(role_id),
                                'type': 'permit.role',
                            }
                            for role_id in role_ids
                        ]
                    }
                },
            },
        },
    )


@pytest.mark.django_db(transaction=True)
def test_default_role_is_set_on_first_role_add() -> None:
    user = create_user()
    role = create_role('role_first_add')

    user.roles.add(role)
    user.refresh_from_db()

    assert user.role_current_id == role.id


@pytest.mark.django_db(transaction=True)
def test_role_current_is_not_overwritten_when_already_set() -> None:
    user = create_user()
    role_1 = create_role('role_keep_current_1')
    role_2 = create_role('role_keep_current_2')

    user.roles.add(role_1)
    user.refresh_from_db()
    assert user.role_current_id == role_1.id

    user.roles.add(role_2)
    user.refresh_from_db()

    assert user.role_current_id == role_1.id


@pytest.mark.django_db(transaction=True)
def test_delete_current_role_switches_to_remaining_role() -> None:
    user = create_user()
    role_1 = create_role('role_switch_on_delete_1')
    role_2 = create_role('role_switch_on_delete_2')

    user.roles.add(role_1, role_2)
    user.role_current = role_1
    user.save(update_fields=['role_current'])

    user.roles.remove(role_1)
    user.refresh_from_db()

    assert user.role_current_id == role_2.id


@pytest.mark.django_db(transaction=True)
def test_delete_non_current_role_keeps_role_current() -> None:
    user = create_user()
    role_1 = create_role('role_keep_on_other_delete_1')
    role_2 = create_role('role_keep_on_other_delete_2')

    user.roles.add(role_1, role_2)
    user.role_current = role_2
    user.save(update_fields=['role_current'])

    user.roles.remove(role_1)
    user.refresh_from_db()

    assert user.role_current_id == role_2.id


@pytest.mark.django_db(transaction=True)
def test_delete_last_role_sets_role_current_to_null() -> None:
    user = create_user()
    role = create_role('role_last_delete')

    user.roles.add(role)
    user.refresh_from_db()
    assert user.role_current_id == role.id

    user.roles.remove(role)
    user.refresh_from_db()

    assert user.role_current_id is None


@pytest.mark.django_db(transaction=True)
def test_save_after_roles_set_normalizes_stale_role_current() -> None:
    user = create_user()
    role_1 = create_role('role_stale_save_1')
    role_2 = create_role('role_stale_save_2')

    user.roles.add(role_1, role_2)
    user.role_current = role_1
    user.save(update_fields=['role_current'])

    user.roles.set([role_2])

    # Emulate route/schemas flow: python object still has stale role_current,
    # then force_update save is executed.
    user.save(force_update=True)
    user.refresh_from_db()

    assert user.role_current_id == role_2.id


@pytest.mark.django_db(transaction=True)
def test_save_with_role_current_outside_roles_normalizes_to_first_role() -> None:
    user = create_user()
    role_valid = create_role('role_valid_for_normalization')
    role_invalid = create_role('role_invalid_for_normalization')

    user.roles.add(role_valid)
    user.role_current = role_invalid
    user.save(force_update=True)
    user.refresh_from_db()

    assert user.role_current_id == role_valid.id


@pytest.mark.django_db(transaction=True)
def test_api_patch_roles_replaces_current_with_first_from_new_roles(sample_app) -> None:
    user = create_user()
    role_1 = create_role('api_patch_switch_1')
    role_2 = create_role('api_patch_switch_2')

    user.roles.add(role_1, role_2)
    user.role_current = role_1
    user.save(update_fields=['role_current'])

    response = patch_user_roles(sample_app, user, user, [str(role_2.id)])

    assert response.status_code == 200
    user.refresh_from_db()
    assert list(user.roles.values_list('id', flat=True)) == [role_2.id]
    assert user.role_current_id == role_2.id


@pytest.mark.django_db(transaction=True)
def test_api_patch_roles_empty_sets_role_current_null(sample_app) -> None:
    user = create_user()
    role = create_role('api_patch_empty')
    user.roles.add(role)
    user.refresh_from_db()
    assert user.role_current_id == role.id

    response = patch_user_roles(sample_app, user, user, [])

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.roles.count() == 0
    assert user.role_current_id is None
