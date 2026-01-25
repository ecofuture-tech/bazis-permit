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

import re
from typing import TYPE_CHECKING

from django.db.models import QuerySet

from bazis.contrib.permit.models_abstract import PermitSelectorMixin
from bazis.contrib.users import get_user_model
from bazis.core.schemas import CrudAccessAction
from bazis.core.utils.query_complex import QueryComplex, QueryComplexItem

from .schemas import PERM_ALL, PERM_SELF


if TYPE_CHECKING:
    from bazis.contrib.permit.schemas import PermitStructMixin
    from bazis.core.models_abstract import JsonApiMixin
    User = get_user_model()


def field_restrict_queryset(qs: QuerySet, context: dict) -> QuerySet:
    """
    Restrict the given queryset based on the context's route and action. If the
    context contains a route with a 'restrict_queryset' method, this method will be
    called with the queryset and action (defaulting to CrudAccessAction.VIEW).
    Otherwise, the original queryset is returned.
    """
    if 'route' in context and hasattr(context['route'], 'restrict_queryset'):
        action = context.get('restrict_action', CrudAccessAction.VIEW)
        return context['route'].restrict_queryset(qs, action)
    return qs


def is_model_permit(model: 'JsonApiMixin'):
    """
    Check if the given model's default route is a subclass of PermitRouteBase. This
    determines if the model is permitted by the application's routing rules.
    """
    from .routes_abstract import PermitRouteBase

    if issubclass(model.get_default_route(), PermitRouteBase):
        return True

    return False


def _selectors_perform(query: QueryComplex, user: 'User', struct: 'PermitStructMixin'):
    for node in (query.left, query.right):
        if isinstance(node, QueryComplexItem):
            if node.value == '__selector__':
                if node.key == PERM_ALL:
                    node.delete()

                elif not user.is_anonymous:
                    # get the selector field model
                    selector_model = struct.get_selector_model(node.key)

                    if selector_model and issubclass(selector_model, PermitSelectorMixin):
                        selector_value = selector_model.get_selector_for_user(user)

                        if selector_value:
                            # extract according to model rules
                            if node.key == PERM_SELF:
                                node.replace(key='pk', value=getattr(selector_value, 'pk', None))
                            else:
                                node.value = selector_value
                                node = struct.selector_extending(node)
                        else:
                            node.key = 'pk__isnull'
                            node.value = True

        if isinstance(node, QueryComplex):
            _selectors_perform(node, user, struct)


def selector_to_complex(query_str: str, user: 'User', struct: 'PermitStructMixin') -> QueryComplex:
    # check for simplified format
    if re.match(r'^[a-zA-Z_]+$', query_str):
        query_str = f'{query_str}=__selector__'

    query_complex = QueryComplex.from_data(query_str)
    _selectors_perform(query_complex, user, struct)

    return query_complex
