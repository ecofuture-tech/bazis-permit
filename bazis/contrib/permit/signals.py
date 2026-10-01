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
Invalidation of the cached permissions of the roles (see `PermitService.perms`).

The cache keys of all roles contain a common version, which any change of roles,
permission groups, permissions or their relations replaces: a change can affect any number
of roles in ways that are hard to follow (a reverse many-to-many change, a deleted group,
a renamed role), and permissions change rarely.
"""

from django.apps import apps
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save

from .schemas import perms_cache_invalidate


def perm_cache_clean(sender, **kwargs):
    # now, and once more after the commit: a request running in between could cache the
    # permissions committed before the change under the new version
    perms_cache_invalidate()
    transaction.on_commit(perms_cache_invalidate)


def connect():
    Role = apps.get_model('permit.Role')  # noqa: N806
    GroupPermission = apps.get_model('permit.GroupPermission')  # noqa: N806
    Permission = apps.get_model('permit.Permission')  # noqa: N806

    for through in (Role.groups_permission.through, GroupPermission.permissions.through):
        m2m_changed.connect(perm_cache_clean, sender=through, dispatch_uid=f'permit_{through}')
    for model in (Role, GroupPermission, Permission):
        for signal in (post_save, post_delete):
            signal.connect(perm_cache_clean, sender=model, dispatch_uid=f'permit_{signal}_{model}')
