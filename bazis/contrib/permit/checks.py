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
from django.core.checks import Tags, Warning, register


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


@register()
def check_routes_permit_model(app_configs, **kwargs):
    """
    A permission route (`PermitRouteBase`) resolves the permissions of its model through
    `PermitStructMixin` (`PermitModelMixin` for a Django model): with another model its list,
    items, `included` and the filters through a relation into it fail as soon as the user
    has a permission on the model. A Warning (not an Error), so that `migrate` and the
    server still start. Runs when the application is loaded (`manage.py bazis_doctor`).
    """
    from bazis.core.introspect import loaded_app, route_sets

    if (app := loaded_app()) is None:
        return []

    from .routes_abstract import PermitRouteBase
    from .schemas import PermitStructMixin

    return [
        Warning(
            f'The model {route_cls.model._meta.label} of the permission route '
            f'{route_cls.__module__}.{route_cls.__qualname__} does not support permissions.',
            hint=(
                'Inherit the model from bazis.contrib.permit.models_abstract.PermitModelMixin '
                '(a StatusyChildMixin model of bazis-statusy: update bazis-statusy to 2.5), or '
                'serve it with a route that is not a PermitRouteBase.'
            ),
            obj=route_cls,
            id='permit.W003',
        )
        for route_cls in route_sets(app)
        if issubclass(route_cls, PermitRouteBase)
        and not issubclass(route_cls.model, PermitStructMixin)
    ]


@register()
def check_declarations(app_configs, **kwargs):
    """
    The roles and permission groups declared in the `roles.py` modules: their slugs, the
    groups of the roles, the models, selectors and fields of the permissions
    (permit.E004, permit.E005) and the translations of their names (permit.W004).
    """
    from .declare import declaration_messages, declarations

    return declaration_messages(*declarations())


@register(Tags.database)
def check_declarations_applied(app_configs, databases=None, **kwargs):
    """
    The database has the declared roles and groups (permit.W005) and no managed one that
    is no longer declared (permit.W006). Warnings: `migrate` runs the database checks before
    it applies the declarations. Skipped while migrations are not applied.
    """
    from .declare import (
        apply_declarations,
        declaration_messages,
        declarations,
        migrations_complete,
        orphans,
    )

    messages = []
    groups, roles = declarations()
    if any(it.is_serious() for it in declaration_messages(groups, roles)):
        # permit.E004, permit.E005
        return []
    for using in databases or ():
        if not migrations_complete(using):
            continue
        if changes := apply_declarations(using, groups, roles, dry_run=True):
            messages.append(
                Warning(
                    f'The database {using} differs from the declared roles: {"; ".join(changes)}.',
                    hint='Run `manage.py migrate`: it applies the declarations.',
                    id='permit.W005',
                )
            )
        if found := orphans(using, groups, roles):
            messages.append(
                Warning(
                    f'The database {using} has managed roles or groups that are not declared: '
                    f'{", ".join(found)}.',
                    hint='Declare them again in a roles.py module, or delete them in the admin.',
                    id='permit.W006',
                )
            )
    return messages
