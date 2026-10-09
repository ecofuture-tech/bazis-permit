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
Roles and permission groups declared in the code of the applications.

An application declares them in `<app>/roles.py`::

    from django.utils.translation import gettext_lazy as _
    from bazis.contrib.permit.declare import Group, Role

    GROUPS = [Group('tickets_client', _('Tickets of the client'), [
        'support.ticket.item.view.author.all',
    ])]
    ROLES = [Role('client', _('Client'), ['tickets_client'])]

After `migrate` (the `post_migrate` signal, once the migrations of the project are all
applied) the database has them: the groups and roles are created or updated and marked
`managed`, the permissions of a managed group are exactly the declared ones (a permission
removed from the code is revoked), the managed groups of a declared role are exactly the
declared ones. The roles and groups that are not declared (made in the admin) and the
groups the admin attached to a declared role are left as they are; a declared slug that
exists unmarked is taken over with a warning. A managed object no longer declared is kept
(the database check warns). The names are English msgids: each `name_<language>` column
gets their translation in the catalogs of the project.

The helpers `discover`, `translations` and `migrations_complete` are shared with the
declarations of bazis-statusy (`workflow.py`).
"""

import logging
import re
import sys
from dataclasses import dataclass
from importlib import import_module

from django.apps import apps
from django.conf import settings
from django.core.checks import CheckMessage, Error, Warning
from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Q
from django.utils import translation
from django.utils.functional import Promise
from django.utils.module_loading import module_has_submodule

from translated_fields import to_attribute

from bazis.core.utils.functools import camel_2_snake

from .models_abstract import LANGUAGES, PermitModelMixin, PermitSelectorMixin


logger = logging.getLogger(__name__)

#: the slug of a declared group or role
SLUG = re.compile(r'^[a-z0-9_-]+$')
#: a selector in the simplified format (a relation or a path of relations); any other one
#: is a query (`author=__selector__&is_active=true`), not checked
SELECTOR_NAME = re.compile(r'^[a-zA-Z_]+$')
#: the restrictions of a field permission, besides `filter:<condition>`
FIELD_RESTRICTS = {'enable', 'disable', 'readonly'}


@dataclass(frozen=True)
class Group:
    """
    A permission group: its slug, its English name (`gettext_lazy`) and its permissions.
    """

    slug: str
    name: str | Promise
    permissions: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'permissions', tuple(self.permissions))


@dataclass(frozen=True)
class Role:
    """
    A role: its slug, its English name (`gettext_lazy`), its groups (declared groups or
    their slugs) and whether it is a role of the anonymous users.
    """

    slug: str
    name: str | Promise
    groups: tuple[str, ...] = ()
    for_anonymous: bool = False

    def __post_init__(self):
        object.__setattr__(
            self, 'groups', tuple(it.slug if isinstance(it, Group) else it for it in self.groups)
        )


def discover(module: str, attribute: str) -> list[tuple[str, object]]:
    """
    The items of the list `attribute` of the modules `<app>.<module>` of the installed
    applications, with the name of their module. A module without the attribute is not a
    declaration and is skipped.
    """
    found = []
    for app_config in apps.get_app_configs():
        if module_has_submodule(app_config.module, module):
            declared = import_module(f'{app_config.name}.{module}')
            found.extend((declared.__name__, it) for it in getattr(declared, attribute, ()))
    return found


def translations(text: str | Promise, field: str = 'name') -> dict[str, str]:
    """
    The columns of a translated field (those of the migrations of the package) with the
    translation of the text in their language.
    """
    values = {}
    for language in LANGUAGES:
        with translation.override(language):
            values[to_attribute(field, language)] = str(text)
    return values


def untranslated(texts: list[str | Promise]) -> dict[str, list[str]]:
    """
    The texts that have no translation in a language of LANGUAGES other than English (the
    language of the msgids), by language.
    """
    with translation.override(None):
        sources = [str(it) for it in texts]
    missing = {}
    for language, _name in settings.LANGUAGES:
        if language.lower().split('-')[0] == 'en':
            continue
        with translation.override(language):
            if names := [src for src, text in zip(sources, texts, strict=True) if str(text) == src]:
                missing[language] = names
    return missing


def migrations_complete(using: str = DEFAULT_DB_ALIAS) -> bool:
    """
    Whether the database has all the migrations of the project: the declarations are
    applied only then (a `migrate` to an earlier migration skips them).
    """
    executor = MigrationExecutor(connections[using])
    return not executor.migration_plan(executor.loader.graph.leaf_nodes())


def declarations() -> tuple[list[tuple[str, Group]], list[tuple[str, Role]]]:
    """
    The groups (GROUPS) and the roles (ROLES) of the `roles.py` modules of the
    applications, with their module.
    """
    return discover('roles', 'GROUPS'), discover('roles', 'ROLES')


def declared_slugs(model_name: str) -> set[str]:
    """
    The declared slugs of the groups (`grouppermission`) or of the roles (`role`).
    """
    groups, roles = declarations()
    return {it.slug for _module, it in (groups if model_name == 'grouppermission' else roles)}


def _model(app_label: str, name: str):
    """
    The model of the permissions `<app_label>.<name>.…` (the resource name of the model).
    """
    try:
        models = apps.get_app_config(app_label).get_models()
    except LookupError:
        return None
    for model in models:
        resource_name = getattr(model, 'get_resource_name', None)
        if (resource_name() if resource_name else camel_2_snake(model.__name__)) == name:
            return model
    return None


def _selector_problem(model, selector: str) -> str | None:
    if selector == 'all' or not SELECTOR_NAME.match(selector):
        return None
    if selector == 'self':
        if issubclass(model, PermitSelectorMixin):
            return None
        return f'{model._meta.label} is not a PermitSelectorMixin: it has no selector self'
    *path, name = selector.split('__')
    kls = model
    for part in path:
        if not (rel := kls.get_fields_info().relations.get(part)):
            return f'{kls._meta.label} has no relation {part}'
        kls = rel.related_model
        if isinstance(kls, str):
            kls = apps.get_model(kls)
    selectors = PermitModelMixin.get_selector_fields.__func__(kls)
    if name not in selectors:
        return (
            f'{kls._meta.label} has no selector {name} (a relation to a PermitSelectorMixin '
            f'model; its selectors: {", ".join(sorted(selectors)) or "none"})'
        )
    return None


def _has_field(model, name: str) -> bool:
    if name == '__all__':
        return True
    info = model.get_fields_info()
    return name in info.fields or name in info.attributes_and_pk or hasattr(model, name)


def permission_problem(slug: str) -> str | None:  # noqa: C901
    """
    What is wrong with a permission slug
    `<app>.<model>.<item|field>.<operation>.<selector>[.<status>][.<field>.<restriction>]`,
    or None. The status is the segment of the models with statuses (bazis-statusy).
    """
    parts = slug.split('.')
    if len(parts) < 5 or not all(parts[:5]):
        return 'expected <app>.<model>.<item|field>.<operation>.<selector>…'
    app_label, model_name, level, operation, selector = parts[:5]
    if (model := _model(app_label, model_name)) is None:
        return f'there is no model {app_label}.{model_name}'
    if not issubclass(model, PermitModelMixin):
        return f'{model._meta.label} is not a PermitModelMixin'
    if level not in ('item', 'field'):
        return f'the level {level!r} is neither item nor field'
    if problem := _selector_problem(model, selector):
        return problem

    status = 1 if hasattr(model, 'get_status_field') else 0
    if level == 'item':
        if len(parts) < 5 + status or not all(parts[5:]):
            return 'expected <selector>.<status> for a model with statuses'
        if status and operation == 'transit' and len(parts) != 7:
            return 'expected item.transit.<selector>.<status>.<transit>'
        return None

    if len(parts) < 7 + status or not all(parts[5:6 + status]):
        return 'a field permission ends with [<status>.]<field>.<restriction>'
    field, restrict = parts[5 + status], '.'.join(parts[6 + status:])
    if not _has_field(model, field):
        return f'{model._meta.label} has no field {field}'
    for it in restrict.split('|'):
        if it not in FIELD_RESTRICTS and not it.startswith('filter:'):
            return f'the restriction {it!r} is not one of enable, disable, readonly, filter:…'
    return None


def _duplicates(declared: list[tuple[str, object]], key: str) -> dict[str, list[str]]:
    modules = {}
    for module, it in declared:
        modules.setdefault(getattr(it, key, None), []).append(module)
    return {value: found for value, found in modules.items() if len(found) > 1}


def _name_problem(it) -> str | None:
    if isinstance(it.name, (str, Promise)) and str(it.name):
        return None
    return 'its name is not a text (an English gettext_lazy msgid)'


def declaration_messages(groups, roles) -> list[CheckMessage]:  # noqa: C901
    """
    The problems of the declarations (the system checks permit.E004, permit.E005 and
    permit.W004); `apply_declarations` refuses declarations with errors.
    """
    messages = []

    def error(text, module, hint=None, *, id):  # the id of the check
        messages.append(Error(text, hint=hint, obj=module, id=id))

    for kind, declared in (('group', groups), ('role', roles)):
        for slug, modules in _duplicates(declared, 'slug').items():
            error(
                f'The {kind} {slug} is declared more than once.', ', '.join(modules), id='permit.E004'
            )
        for module, it in declared:
            expected = Group if kind == 'group' else Role
            if not isinstance(it, expected):
                error(f'{it!r} of {module} is not a {expected.__name__}.', module, id='permit.E004')
                continue
            if not isinstance(it.slug, str) or not SLUG.match(it.slug):
                error(
                    f'The slug {it.slug!r} of a {kind} is invalid.', module,
                    hint='Lowercase letters, digits, "_" and "-".', id='permit.E004',
                )
            if problem := _name_problem(it):
                error(f'The {kind} {it.slug}: {problem}.', module, id='permit.E004')

    group_slugs = {it.slug for _module, it in groups if isinstance(it, Group)}
    for module, role in roles:
        if not isinstance(role, Role):
            continue
        for slug in role.groups:
            if slug not in group_slugs:
                error(
                    f'The role {role.slug} has the group {slug}, which is not declared.', module,
                    hint='Declare the group in GROUPS of a roles.py module.', id='permit.E004',
                )

    for module, group in groups:
        if not isinstance(group, Group):
            continue
        for slug in dict.fromkeys(group.permissions):
            if problem := permission_problem(slug):
                error(
                    f'The permission {slug} of the group {group.slug}: {problem}.', module,
                    id='permit.E005',
                )

    names = [
        it.name for _module, it in [*groups, *roles]
        if isinstance(it, (Group, Role)) and not _name_problem(it)
    ]
    for language, missing in untranslated(names).items():
        messages.append(
            Warning(
                f'The names of declared roles or groups have no translation into {language}: '
                f'{", ".join(missing)}.',
                hint='Translate them in the locale of the project (makemessages, compilemessages).',
                id='permit.W004',
            )
        )
    return messages


class _Sync:
    """
    Brings the database to the declarations, or only lists the changes (`dry_run`).
    """

    def __init__(self, using: str, dry_run: bool):
        self.using = using
        self.dry_run = dry_run
        self.changes: list[str] = []

    def object(self, model, slug: str, values: dict):
        """
        The managed object of the slug with these values: created, updated or taken over.
        """
        label = f'{model._meta.model_name} {slug}'
        obj = model.objects.using(self.using).filter(slug=slug).first()
        if obj is None:
            self.changes.append(f'{label}: created')
            obj = model(slug=slug, managed=True, **values)
            if not self.dry_run:
                obj.save(using=self.using)
            return obj
        changed = [name for name, value in values.items() if getattr(obj, name) != value]
        if not obj.managed:
            if not self.dry_run:
                logger.warning(
                    'The %s exists and is not managed by the code: the declaration takes it over.', label
                )
            changed.append('managed')
            obj.managed = True
        if changed:
            self.changes.append(f'{label}: {", ".join(changed)} changed')
            for name in changed:
                if name in values:
                    setattr(obj, name, values[name])
            if not self.dry_run:
                obj.save(using=self.using, update_fields=changed)
        return obj

    def relation(self, obj, field: str, current, declared: set[str], related_model) -> None:
        """
        The objects (by slug) of a many-to-many field among `current` (a function of the
        object giving a queryset of them) are exactly the declared ones.
        """
        current = set() if obj._state.adding else set(current(obj).values_list('slug', flat=True))
        added, removed = sorted(declared - current), sorted(current - declared)
        if added or removed:
            label = f'{obj._meta.model_name} {obj.slug}'
            self.changes.extend(f'{label}: {field} + {it}' for it in added)
            self.changes.extend(f'{label}: {field} - {it}' for it in removed)
            if not self.dry_run:
                objects = related_model.objects.using(self.using)
                manager = getattr(obj, field)
                if added:
                    manager.add(*objects.filter(slug__in=added))
                if removed:
                    manager.remove(*objects.filter(slug__in=removed))


def apply_declarations(
    using: str = DEFAULT_DB_ALIAS, groups=None, roles=None, dry_run: bool = False
) -> list[str]:
    """
    Applies the declared groups and roles (by default those of the `roles.py` modules) to
    the database in one transaction and returns the changes; with `dry_run` only returns
    them. Applied again, it writes nothing. The writes invalidate the cached permissions
    (the signals of the package), so nothing is invalidated when nothing changes.
    """
    if groups is None and roles is None:
        groups, roles = declarations()
    groups = [it if isinstance(it, tuple) else ('', it) for it in groups or ()]
    roles = [it if isinstance(it, tuple) else ('', it) for it in roles or ()]
    if errors := [it for it in declaration_messages(groups, roles) if it.is_serious()]:
        raise ImproperlyConfigured(
            'Invalid declarations of roles:\n' + '\n'.join(f'{it.id}: {it.msg}' for it in errors)
        )

    role_model = apps.get_model('permit.Role')
    group_model = apps.get_model('permit.GroupPermission')
    permission_model = apps.get_model('permit.Permission')
    sync = _Sync(using, dry_run)

    with transaction.atomic(using=using):
        slugs = {slug for _module, group in groups for slug in group.permissions}
        existing = set(
            permission_model.objects.using(using).filter(slug__in=slugs).values_list('slug', flat=True)
        )
        if missing := sorted(slugs - existing):
            sync.changes.extend(f'permission {it}: created' for it in missing)
            if not dry_run:
                permission_model.objects.using(using).bulk_create(
                    [permission_model(slug=it) for it in missing]
                )

        for _module, group in groups:
            obj = sync.object(group_model, group.slug, translations(group.name))
            sync.relation(
                obj, 'permissions', lambda it: it.permissions.all(), set(group.permissions), permission_model
            )

        declared_groups = {group.slug for _module, group in groups}
        for _module, role in roles:
            obj = sync.object(
                role_model, role.slug, {**translations(role.name), 'for_anonymous': role.for_anonymous}
            )
            # the groups the admin attached (not managed) stay
            sync.relation(
                obj, 'groups_permission',
                lambda it: it.groups_permission.filter(Q(managed=True) | Q(slug__in=declared_groups)),
                set(role.groups), group_model,
            )
    return sync.changes


def orphans(using: str = DEFAULT_DB_ALIAS, groups=None, roles=None) -> list[str]:
    """
    The managed groups and roles of the database that are no longer declared.
    """
    if groups is None and roles is None:
        groups, roles = declarations()
    found = []
    for model_name, declared in (('GroupPermission', groups), ('Role', roles)):
        slugs = {(it[1] if isinstance(it, tuple) else it).slug for it in declared or ()}
        model = apps.get_model('permit', model_name)
        found.extend(
            f'{model._meta.model_name} {slug}'
            for slug in model.objects.using(using).filter(managed=True).exclude(slug__in=slugs)
            .order_by('slug').values_list('slug', flat=True)
        )
    return found


def post_migrate_apply(sender, using=DEFAULT_DB_ALIAS, verbosity=1, **kwargs):
    """
    The receiver of `post_migrate` (also sent by `flush`): applies the declarations once
    the migrations of the project are all applied.
    """
    if not migrations_complete(using):
        logger.info('Not all the migrations are applied: the declared roles are not applied.')
        return
    changes = apply_declarations(using)
    stdout = kwargs.get('stdout') or sys.stdout
    if changes and verbosity >= 1:
        stdout.write(f'  Applied the declared roles: {len(changes)} change(s)\n')
    if verbosity >= 2:
        for change in changes:
            stdout.write(f'    {change}\n')
