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

from django.apps import apps
from django.core.cache import cache
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .schemas import PERMS_CACHE_PREFIX


@receiver(m2m_changed)
def perm_cache_clean(sender, instance, action, reverse, pk_set, *args, **kwargs):
    Role = apps.get_model('permit.Role')  # noqa: N806
    GroupPermission = apps.get_model('permit.GroupPermission') # noqa: N806
    if sender == Role.groups_permission.through:
        cache.delete(f'{PERMS_CACHE_PREFIX}{instance.slug}')
    elif sender == GroupPermission.permissions.through:
        for role in Role.objects.filter(groups_permission=instance):
            cache.delete(f'{PERMS_CACHE_PREFIX}{role.slug}')
