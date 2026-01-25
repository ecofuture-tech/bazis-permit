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

from collections import defaultdict
from collections.abc import Iterable

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from fastapi import Depends

from starlette.status import HTTP_403_FORBIDDEN

from bazis.contrib.users import get_anonymous_user_model, get_user_model
from bazis.contrib.users.service import get_user_optional
from bazis.core.errors import JsonApiHttpException
from bazis.core.schemas import AccessAction
from bazis.core.utils.query_complex import QueryComplex

from .schemas import (
    PERMS_CACHE_PREFIX,
    PermitContext,
    PermitStructMixin,
)
from .utils import selector_to_complex


User = get_user_model()
AnonymousUser = get_anonymous_user_model()


class PermitHandler:
    """
    Handles permission checks for a given action and item or structure, utilizing
    the PermitService.
    """

    def __init__(
        self,
        permit_service: 'PermitService',
        action: AccessAction,
        item_or_struct: PermitStructMixin | type[PermitStructMixin],
    ):
        """
        Initializes the PermitHandler with the given permit service, action, and item or
        structure.
        """
        self.permit_service = permit_service
        self.action = action

        if isinstance(item_or_struct, PermitStructMixin):
            self.struct = type(item_or_struct)
            self.item = item_or_struct
        else:
            self.struct = item_or_struct
            self.item = None

    def _get_perms(self, context: PermitContext, action: AccessAction = None):
        """
        Retrieves the permissions for a given context and action from the permit
        service.
        """
        perms = (
            self.permit_service.perms.get(self.struct.get_resource_app(), {})
            .get(self.struct.get_resource_name(), {})
            .get(context.value, {})
            .get((action or self.action).value, {})
        )
        return perms

    def _parse_perms(self, perms: dict) -> Iterable[tuple[dict, QueryComplex]]:
        """
        Parses a dictionary of permissions, searching for permissions related to the current model.
                :param perms: Dictionary of permissions.
                :return: An iterator yielding tuples of the form: permission, selector conditions.
        """
        for query_str, perm in perms.items():
            yield perm, selector_to_complex(query_str, self.permit_service.user, self.struct)

    @cached_property
    def perms_item(self) -> list[tuple[dict, QueryComplex]]:
        """
        Cached property that returns a list of parsed permissions for a specific item
        context.
        """
        perms = list(self._parse_perms(self._get_perms(PermitContext.ITEM)))
        return perms

    @cached_property
    def perms_field(self) -> list[tuple[dict, QueryComplex]]:
        """
        Cached property that returns a list of parsed permissions for a specific field
        context.
        """
        perms = list(self._parse_perms(self._get_perms(PermitContext.FIELD)))
        return perms

    def _get_perms_values(self, perms: list) -> Iterable[dict]:
        """
        Retrieves values from permissions for a specific item or in general.
                :param perms: List of permissions.
                :return: An iterable of permission values.
        """
        if self.item:
            self.item.prepare_conditions(perms)

        for perm, cond in perms:
            if not cond:
                yield perm
            elif self.item and self.item.check_condition(cond):
                yield perm

    def _get_perms_groups(self, perms: list) -> list[tuple[list[dict], QueryComplex]]:
        """
        Collects all possible groups of permission values based on selector conditions.
                :param perms: List of permissions.
                :return: A list of tuples containing grouped permission values and their conditions.
        """
        groups = defaultdict(list)
        for perm, cond in perms:
            groups[cond].append(perm)
        return [(_perms, cond) for cond, _perms in groups.items()]

    @cached_property
    def perms_item_values(self) -> list[dict]:
        """
        Cached property that returns a list of permission values for a specific item
        context.
        """
        perms = list(self._get_perms_values(self.perms_item))
        return perms

    @cached_property
    def perms_field_values(self) -> list[dict]:
        """
        Cached property that returns a list of permission values for a specific field
        context.
        """
        perms = list(self._get_perms_values(self.perms_field))
        return perms

    @cached_property
    def perms_item_groups(self) -> list[tuple[list[dict], QueryComplex]]:
        """
        Cached property that returns a list of grouped permission values for a specific
        item context.
        """
        perms = self._get_perms_groups(self.perms_item)
        return perms

    @cached_property
    def perms_field_groups(self) -> list[tuple[list[dict], QueryComplex]]:
        """
        Cached property that returns a list of grouped permission values for a specific
        field context.
        """
        perms = self._get_perms_groups(self.perms_field)
        return perms

    def check_access(self, item_passive=False) -> bool:
        """
        Checks if the action is permitted for the model based on the permissions.
                If checking for a specific entity, it verifies the presence of permission values for this item.
                If no specific entity is provided, it checks for the presence of the permissions themselves.
                item_passive: if True, then in the complete absence of permissions it is considered that everything is allowed
                :return: Boolean indicating whether access is granted.
        """
        if self.item:
            if item_passive:
                if any(self.perms_item):
                    return any(self.perms_item_values)
                else:
                    return True
            else:
                return any(self.perms_item_values)
        else:
            return any(self.perms_item)


class PermitService:
    """
    Manages permission data and provides handlers for checking permissions based on
    user roles.
    """

    handler_class = PermitHandler

    def __init__(self, user: User | AnonymousUser = Depends(get_user_optional)):
        """
        Initializes the PermitService with the given user, setting up the user and
        handlers.
        """
        self.user = user or AnonymousUser()
        self.handlers = {}

    @cached_property
    def perms(self) -> dict:
        """
        Parses string permissions into a dictionary, utilizing cache for efficiency.
                :return: A dictionary representing the permission tree.
        """
        if not hasattr(self.user, 'role_current'):
            raise JsonApiHttpException(
                HTTP_403_FORBIDDEN, detail=_('User instance anonymous or missing the role_current property')
            )

        if not self.user.role_current:
            return {}

        cache_key = f'{PERMS_CACHE_PREFIX}{self.user.role_current.slug}'

        # try to get permissions from cache
        if perms := cache.get(cache_key):
            return perms

        permissions = list(
            apps.get_model('permit.Permission')
            .objects.filter(
                groups__roles=self.user.role_current,
            )
            .distinct('id')
            .values_list('slug', flat=True)
        )

        perms = tmp = {}
        # Fill all permissions ['authing.user.item.view.all.all', ...] into a dictionary
        for it in permissions:
            for p in it.split('.'):
                tmp = tmp.setdefault(p, {})
            # indicate that the permission is complete
            tmp[None] = None
            tmp = perms

        cache.set(cache_key, perms, timeout=settings.BAZIS_PERMISSION_CACHE_EXPIRE)
        return perms

    def handler(
        self,
        access_action: AccessAction,
        item_or_struct: PermitStructMixin | type[PermitStructMixin],
    ) -> PermitHandler:
        """
        Returns a PermitHandler for the given action and item or structure, creating one
        if it doesn't exist.
        """
        handler_key = (access_action, item_or_struct)
        if handler_key not in self.handlers:
            self.handlers[handler_key] = self.handler_class(
                permit_service=self, action=access_action, item_or_struct=item_or_struct
            )
        return self.handlers[handler_key]
