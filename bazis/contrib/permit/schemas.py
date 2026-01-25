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

import enum
from typing import TYPE_CHECKING

from pydantic import BaseModel

from bazis.core.utils.query_complex import QueryComplexItem


if TYPE_CHECKING:
    from .models_abstract import PermitSelectorMixin


PATTERN_SELECTORS = r'^autogen_(.+)_selectors$'
def ATTR_SELECTORS(x):  # noqa: N802
    return f'autogen_{x}_selectors'

ANONYMOUS_ID = 'anon'
PERMS_CACHE_PREFIX = 'users_perms::'
PERM_ALL = 'all'
PERM_SELF = 'self'


@enum.unique
class PermitContext(enum.Enum):
    """
    Enumeration representing different contexts in which permissions can be applied,
    such as 'item' or 'field'.
    """

    ITEM = 'item'
    FIELD = 'field'


class SelectorField(BaseModel):
    """
    Data model for a selector field, which includes the name, label, and associated
    model type.
    """

    name: str
    label: str
    model: type['PermitSelectorMixin']


class PermitStructMixin:
    """
    Mixin that provides permission handling for structures that do not inherit from
    InitialBase.
    """

    @classmethod
    def get_resource_verbose_name(cls) -> str:
        """
        Mandatory method.
        Returns a human-readable name of the structure's application, used in the permissions settings panel.
        """
        raise NotImplementedError

    @classmethod
    def get_resource_app(cls) -> str:
        """
        Mandatory method.
        Returns the programmatic name of the structure's application, used when searching for permissions.
        """
        raise NotImplementedError

    @classmethod
    def get_resource_name(cls) -> str:
        """
        Mandatory method.
        Returns the programmatic name of the structure, used when searching for permissions.
        """
        raise NotImplementedError

    @classmethod
    def get_selector_fields(cls) -> dict[str, SelectorField]:
        """
        Mandatory method.
        Defines a set of selectors applicable to the current structure. If the structure does not imply
        the presence of selectors, an empty dictionary can be returned, making only the 'all' selector applicable.
        Returns a dictionary of selector fields, where the key is the field name and the value is the selector
        model (e.g., User, Organization).
        In standard Django models, this dictionary is generated based on fields that refer to selector models.
        """
        raise NotImplementedError

    @classmethod
    def parse_selector(cls, selector: str) -> tuple[type['PermitStructMixin'], str]:
        """
        Preferable.
        Parses the selector and returns a tuple consisting of the final model and the selector name.
        Without overriding this method, selectors cannot be multi-level.
        :param kls:
        :param relation:
        :return:
        """
        return cls, selector

    @classmethod
    def selector_extending(cls, node: QueryComplexItem) -> QueryComplexItem:
        """
        Optional.
        Extends the query node for the selector.
        Can be overridden to add additional conditions for the selector.
        """
        return node

    @classmethod
    def get_default_fields(cls) -> list[str]:
        """
        Optional method.
        Returns a list of default fields of the structure that can be restricted by permissions.
        This is relevant if the structure implements field-level permissions.
        """
        return []

    def check_condition(self, conditions: dict) -> bool:
        """
        Optional method for cases where working with a specific object is not expected.
        Compares the conditions obtained from permissions with the values of the object's fields.
        Returns True if all conditions are met, otherwise False.
        Conditions: a dictionary where the key is the selector name (field name in the structure),
        and the value is the selector value, which can be a single value or a list of values.
        """
        raise NotImplementedError

    @classmethod
    def get_selector_model(cls, selector) -> type['PermitSelectorMixin']:
        """
        Does not require overriding.
        Returns the selector model (a descendant of PermitSelectorMixin) referenced by the selector.
        """
        from .models_abstract import PermitSelectorMixin

        # will return itself if the selector is 'self'
        if selector == PERM_SELF and issubclass(cls, PermitSelectorMixin):
            return cls

        kls, selector = cls.parse_selector(selector)

        if selector_field := kls.get_selector_fields().get(selector):
            return selector_field.model

    @classmethod
    def get_resource_path(cls) -> str:
        """
        Does not require overriding.
        Returns the relative path of the structure.
        """
        return f'{cls.get_resource_app()}/{cls.get_resource_name()}'

    @classmethod
    def get_resource_label(cls) -> str:
        """
        Does not require overriding.
        Returns the full label of the structure.
        """
        return f'{cls.get_resource_app()}.{cls.get_resource_name()}'
