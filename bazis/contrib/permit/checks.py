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
    A JSON:API route that does not restrict its objects serves its whole model: a route
    restricts them with its `restrict_queryset`, the permissions for a permission route
    (`PermitRouteBase`), its own rule for a route that overrides it (the files of
    bazis-uploadable, the tasks of bazis-bg). A route of public data declares
    `permit_public = True`. Runs when the application is loaded (`manage.py bazis_doctor`).
    """
    from bazis.core.introspect import loaded_app, route_sets

    if (app := loaded_app()) is None:
        return []

    from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase
    from bazis.core.routes_abstract.jsonapi.mixins import restrict_queryset_override

    return [
        Warning(
            f'The route {route_cls.__module__}.{route_cls.__qualname__} does not restrict '
            'its objects: it checks neither the permissions of the user nor a rule of its own.',
            hint=(
                'Inherit it from bazis.contrib.permit.routes_abstract.PermitRouteBase, or '
                'override restrict_queryset with your own rule (and apply it in get_queryset); '
                'set `permit_public = True` only if the data of the route is public.'
            ),
            obj=route_cls,
            id='permit.W002',
        )
        for route_cls in route_sets(app)
        if issubclass(route_cls, JsonapiRouteBase)
        and restrict_queryset_override(route_cls) is None
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
def check_actions_access(app_configs, **kwargs):
    """
    A custom action of a permission route that declares neither `access_action` nor
    `public` (True or False) is open to every authenticated user whatever his permissions
    (an action of an item that takes its item with `set_item` only among those the user
    views). Runs
    when the application is loaded (`manage.py bazis_doctor`).
    """
    from bazis.core.introspect import loaded_app, route_sets

    if (app := loaded_app()) is None:
        return []

    from .routes_abstract import PermitRouteBase, route_is_action

    return [
        Warning(
            f'The action {route_ctx.name} of the permission route '
            f'{route_cls.__module__}.{route_cls.__qualname__} declares neither the permission '
            'it requires nor that it is public: every authenticated user can call it.',
            hint=(
                'Declare access_action= of its http_* decorator (the permission it requires on '
                'the model, or on the item for an action of an item, e.g. '
                'CrudAccessAction.CHANGE), public=True if anonymous users may call it (limited '
                'by BAZIS_THROTTLE_PUBLIC per user or IP address), or public=False if every '
                'authenticated user may (an action of an item that takes its item with '
                'set_item: among the items he views).'
            ),
            obj=route_cls,
            id='permit.W007',
        )
        for route_cls, routes in route_sets(app).items()
        if issubclass(route_cls, PermitRouteBase)
        for action in dict.fromkeys(it['action'] for it in routes)
        if route_is_action(route_ctx := route_cls.routes_ctx[action])
        and route_ctx.public is None
        and route_ctx.access_action is None
    ]


def _anonymous_match(selector: str, of_item: bool) -> bool:
    """
    Whether a permission with the selector may let an anonymous user call an action: any
    selector for an action of the collection (it needs a permission on the model), for an
    action of an item one an anonymous user may match: `all`, or a condition other than a
    plain selector (a relation), unless its only branch is `__selector__` (he is nobody's
    selector: `author=__selector__&is_active=true` matches nothing). A condition with an
    alternative or a negation (`author=__selector__|is_public=true`,
    `~author=__selector__`) may match him: it is reported (the check does not evaluate it).
    """
    from .declare import SELECTOR_NAME
    from .schemas import PERM_ALL

    if not of_item:
        return True
    if selector == PERM_ALL:
        return True
    if SELECTOR_NAME.match(selector):
        return False
    return '__selector__' not in selector or '|' in selector or '~' in selector


def anonymous_actions(roles: dict[str, set[str]], source: str) -> list[Warning]:
    """
    permit.W008: the custom actions of the permission routes (not public) whose
    `access_action` the roles for anonymous users have, `roles` (their slug → their
    permission slugs, from `source`): anonymous users call them. The ids of the list
    (`/_id/` of the core) are the list in another form and are left out.
    """
    from bazis.core.introspect import loaded_app, route_sets
    from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

    from .routes_abstract import PermitRouteBase, route_is_action, route_is_item
    from .schemas import PermitStructMixin

    if not roles or (app := loaded_app()) is None:
        return []
    list_ids = JsonapiRouteBase.routes_ctx['action_list_id'].func

    messages = []
    for route_cls, routes in route_sets(app).items():
        if not (
            issubclass(route_cls, PermitRouteBase)
            and issubclass(route_cls.model, PermitStructMixin)
        ):
            continue
        for action in dict.fromkeys(it['action'] for it in routes):
            route_ctx = route_cls.routes_ctx[action]
            if (
                not route_is_action(route_ctx)
                or route_ctx.public
                or route_ctx.access_action is None
                or route_ctx.func is list_ids
            ):
                continue
            prefix = (
                f'{route_cls.model.get_resource_label()}.item.{route_ctx.access_action.value}.'
            )
            granted = sorted(
                f'{role} ({slug})'
                for role, slugs in roles.items()
                for slug in slugs
                if slug.startswith(prefix)
                and _anonymous_match(slug[len(prefix):].split('.')[0], route_is_item(route_ctx))
            )
            if granted:
                messages.append(
                    Warning(
                        f'The action {action} of the permission route '
                        f'{route_cls.__module__}.{route_cls.__qualname__} requires '
                        f'{prefix}…, which roles for anonymous users ({source}) have: '
                        f'{", ".join(granted)}. Anonymous users can call it.',
                        hint=(
                            'If anonymous users may call it, declare public=True (and restrict '
                            'what it returns yourself). Otherwise declare an operation of its '
                            "own as its access_action (a subclass of AccessAction, e.g. "
                            "REPORT = 'report': the permission <app>.<model>.item.report."
                            '<selector>) and grant it only to the roles that may call it: '
                            'access_action=CrudAccessAction.VIEW opens an aggregate or a '
                            'report to everyone who can view the model.'
                        ),
                        obj=route_cls,
                        id='permit.W008',
                    )
                )
    return messages


def _declared_anonymous() -> dict[str, set[str]]:
    """
    The roles for anonymous users declared in the `roles.py` modules, with the permissions
    of their groups.
    """
    from .declare import declarations

    groups, roles = declarations()
    permissions = {it.slug: set(it.permissions) for _module, it in groups}
    return {
        role.slug: set().union(*(permissions.get(it, set()) for it in role.groups))
        for _module, role in roles
        if role.for_anonymous
    }


@register()
def check_actions_anonymous(app_configs, **kwargs):
    """
    permit.W008 for the roles for anonymous users declared in the `roles.py` modules
    (`Role(for_anonymous=True)`). Runs when the application is loaded (`manage.py
    bazis_doctor`).
    """
    return anonymous_actions(_declared_anonymous(), 'roles.py')


@register(Tags.database)
def check_actions_anonymous_applied(app_configs, databases=None, **kwargs):
    """
    permit.W008 for the roles for anonymous users of the database (made in the admin or the
    API, or the groups the admin attached to a declared role): their permissions that the
    declarations do not give, which `check_actions_anonymous` reports. Skipped while
    migrations are not applied.
    """
    from django.apps import apps

    from bazis.core.declare import migrations_complete

    declared = _declared_anonymous()
    roles = {}
    for using in databases or ():
        if not migrations_complete(using):
            continue
        for role, slug in (
            apps.get_model('permit.Role')
            .objects.using(using)
            .filter(for_anonymous=True, groups_permission__permissions__isnull=False)
            .values_list('slug', 'groups_permission__permissions__slug')
        ):
            if slug not in declared.get(role, ()):
                roles.setdefault(role, set()).add(slug)
    return anonymous_actions(roles, 'the database')


#: the restrictions of a field that show it, replacing a `disable`
SHOWN = frozenset({'enable', 'readonly', 'writeonly'})


def _disabled_by(field: str, restricts: dict[str, set[str]]) -> str | None:
    """
    The key of the restrictions of a group that hide the field (the field, or `__all__`),
    or None: its own restrictions of availability replace those of `__all__`, as in
    `fields_patch` of the core.
    """
    key = field if restricts.get(field, set()) & (SHOWN | {'disable'}) else '__all__'
    own = restricts.get(key, set())
    return key if 'disable' in own and not own & SHOWN else None


def required_disabled(groups) -> list[Warning]:
    """
    permit.W009: the field permissions `field.add|change.….<field>.disable` of the declared
    `groups` that do not hide their field, because the core hides only an optional field
    from the schemas of writing (`fields_patch`): a field required to create an item stays
    in the create schema (and a request without it is 422), and in the update schema, which
    still accepts it. Their restrictions are combined per model, operation and condition,
    as one user with the group gets them, and checked against the schemas of the
    permission routes of the model.
    """
    from bazis.core.introspect import loaded_app, route_sets
    from bazis.core.schemas import CrudApiAction

    from .declare import Group, _model, permission_problem
    from .routes_abstract import PermitRouteBase

    if (app := loaded_app()) is None:
        return []
    actions = {'add': CrudApiAction.CREATE, 'change': CrudApiAction.UPDATE}
    routes = [it for it in route_sets(app) if issubclass(it, PermitRouteBase)]

    messages = []
    for module, group in groups:
        if not isinstance(group, Group):
            continue
        # (model, operation, condition) → the restrictions and the permissions of each field
        found: dict[tuple, tuple[dict[str, set[str]], dict[str, list[str]]]] = {}
        for slug in dict.fromkeys(group.permissions):
            parts = slug.split('.')
            if parts[2:3] != ['field'] or parts[3] not in actions or permission_problem(slug):
                continue
            model = _model(parts[0], parts[1])
            status = 1 if hasattr(model, 'get_status_field') else 0
            field = parts[5 + status]
            key = (model, parts[3], tuple(parts[4:5 + status]))
            restricts, slugs = found.setdefault(key, ({}, {}))
            restricts.setdefault(field, set()).update('.'.join(parts[6 + status:]).split('|'))
            slugs.setdefault(field, []).append(slug)

        reported = set()
        for (model, operation, _condition), (restricts, slugs) in found.items():
            for route_cls in routes:
                factory = route_cls.schema_factories.get(actions[operation])
                if route_cls.model is not model or factory is None:
                    continue
                # fields_patch changes the sets it is given
                kept = factory.fields_patch({k: set(v) for k, v in restricts.items()})
                for field in kept:
                    if (key := _disabled_by(field.source, restricts)) is None:
                        continue
                    for slug in slugs[key]:
                        if (slug, field.source) in reported:
                            continue
                        reported.add((slug, field.source))
                        messages.append(_required_disabled(
                            slug, group.slug, field.source, operation, route_cls, module
                        ))
    return messages


def _required_disabled(slug, group, field, operation, route_cls, module) -> Warning:
    route = f'{route_cls.__module__}.{route_cls.__qualname__}'
    if operation == 'add':
        text = (
            f'The permission {slug} of the group {group} does not hide the field {field}: '
            f'{route_cls.model._meta.label}.{field} is required, so the create schema of '
            f'{route} keeps it and a request without it is refused (422).'
        )
        hint = (
            '`disable` hides only an optional field. To fill the field on the server, make it '
            'optional in the model (blank=True, null=True or a default) and set it in '
            'hook_before_create of the route (or by the default); otherwise let the role send '
            'it and remove the permission.'
        )
    else:
        text = (
            f'The permission {slug} of the group {group} does not hide the field {field}: '
            f'{route_cls.model._meta.label}.{field} is required, so the update schema of '
            f'{route} keeps it and an update still changes it.'
        )
        hint = (
            '`disable` hides only an optional field. Declare the field `readonly` for the '
            'role instead (an update ignores it), or make it optional in the model.'
        )
    return Warning(text, hint=hint, obj=module, id='permit.W009')


@register()
def check_declarations_fields(app_configs, **kwargs):
    """
    permit.W009 for the permission groups declared in the `roles.py` modules. Runs when the
    application is loaded (`manage.py bazis_doctor`).
    """
    from .declare import declarations

    return required_disabled(declarations()[0])


@register()
def check_declarations(app_configs, **kwargs):
    """
    The roles and permission groups declared in the `roles.py` modules: their slugs, the
    groups of the roles, the models, selectors and fields of the permissions
    (permit.E004, permit.E005). The translations of their names: `bazis_messages status`.
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
    from bazis.core.declare import migrations_complete

    from .declare import apply_declarations, declaration_messages, declarations, orphans

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
