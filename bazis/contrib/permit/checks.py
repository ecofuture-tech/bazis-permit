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
Django system checks of bazis-permit (see `manage.py bazis_doctor`).
"""

from django.conf import settings
from django.core.checks import Warning, register


@register()
def check_relations_view(app_configs, **kwargs):
    """
    BAZIS_PERMIT_RELATIONS_VIEW_CHECK is deprecated and has no effect: the core checks the
    objects the relationships reference (bazis 2.7).
    """
    # the settings of the package are missing if BS_BAZIS_APPS does not list it
    if getattr(settings, 'BAZIS_PERMIT_RELATIONS_VIEW_CHECK', None) is not None:
        return [
            Warning(
                'BAZIS_PERMIT_RELATIONS_VIEW_CHECK is deprecated and has no effect: the core '
                'checks the objects referenced by relationships.',
                hint=(
                    'Remove BS_BAZIS_PERMIT_RELATIONS_VIEW_CHECK; '
                    '`relation_targets_check = False` turns the check off for a route.'
                ),
                id='permit.W001',
            )
        ]
    return []


@register()
def check_routes_permit(app_configs, **kwargs):
    """
    A JSON:API route that is not a permission route serves its model without checking
    the permissions. A route of public data declares `permit_public = True`. Runs when the
    application is loaded (`manage.py bazis_doctor`).
    """
    from bazis.core.introspect import loaded_app, route_sets

    if (app := loaded_app()) is None:
        return []

    from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

    from .routes_abstract import PermitRouteBase

    return [
        Warning(
            f'The route {route_cls.__module__}.{route_cls.__qualname__} does not check '
            'the permissions of the user.',
            hint=(
                'Inherit it from bazis.contrib.permit.routes_abstract.PermitRouteBase, or set '
                '`permit_public = True` on the route if its data is public.'
            ),
            obj=route_cls,
            id='permit.W002',
        )
        for route_cls in route_sets(app)
        if issubclass(route_cls, JsonapiRouteBase)
        and not issubclass(route_cls, PermitRouteBase)
        and not getattr(route_cls, 'permit_public', False)
    ]
