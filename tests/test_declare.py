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
The roles and permission groups declared in the code (`roles.py`, bazis.contrib.permit.declare)
and their application to the database after `migrate`.
"""

import logging
import threading

from django.contrib.admin.sites import site
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection, transaction
from django.test.client import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils.translation import gettext_lazy as _

import pytest
from bazis_test_utils.utils import get_api_client

from bazis.contrib.permit import declare
from bazis.contrib.permit.checks import check_declarations, check_declarations_applied
from bazis.contrib.permit.declare import Group, Role, apply_declarations, declaration_messages
from bazis.contrib.permit.models import GroupPermission, Permission
from bazis.contrib.permit.models import Role as RoleModel
from bazis.contrib.users import get_user_model

from tests import factories


User = get_user_model()

VIEW = 'entity.parent_entity.item.view.all'
CHANGE = 'entity.parent_entity.item.change.author'
ADD = 'entity.parent_entity.item.add.all'
#: the permission of the group declared by the sample (entity/roles.py)
GUEST = 'entity.meeting.item.view.guest_teams__members'


def writes(queries) -> list[str]:
    return [
        it['sql'] for it in queries
        if it['sql'].lstrip().split(' ', 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE')
    ]


def permissions(slug: str) -> set[str]:
    return set(GroupPermission.objects.get(slug=slug).permissions.values_list('slug', flat=True))


def groups_of(slug: str) -> set[str]:
    return set(RoleModel.objects.get(slug=slug).groups_permission.values_list('slug', flat=True))


@pytest.mark.django_db
def test_the_sample_declarations_are_applied_by_migrate():
    """
    The test database is migrated: the roles.py module of the sample is applied, with the
    names translated by the catalog of the sample into each column.
    """
    group_slugs = {it.slug for _module, it in declare.declarations()[0]}
    assert 'declared_guest_meetings' in group_slugs

    role = RoleModel.objects.get(slug='declared_guest')
    assert role.managed
    assert (role.name_en, role.name_ru) == ('Guest', 'Гость')
    assert groups_of('declared_guest') == {'declared_guest_meetings'}
    assert permissions('declared_guest_meetings') == {
        GUEST, 'entity.meeting.field.view.all.description.disable',
    }
    assert apply_declarations() == []


@pytest.mark.django_db
def test_apply_is_idempotent_and_writes_nothing_again():
    groups = [Group('decl_editors', _('Editors'), [VIEW, CHANGE])]
    roles = [Role('decl_editor', 'Editor', groups)]

    changes = apply_declarations(groups=groups, roles=roles)
    assert 'grouppermission decl_editors: created' in changes
    assert f'permission {CHANGE}: created' in changes
    assert RoleModel.objects.get(slug='decl_editor').managed
    assert permissions('decl_editors') == {VIEW, CHANGE}
    assert groups_of('decl_editor') == {'decl_editors'}

    with CaptureQueriesContext(connection) as queries:
        assert apply_declarations(groups=groups, roles=roles) == []
    assert writes(queries.captured_queries) == []


@pytest.mark.django_db
def test_a_permission_removed_from_the_code_is_revoked():
    roles = [Role('decl_editor', 'Editor', ['decl_editors', 'decl_viewers'])]
    apply_declarations(
        groups=[Group('decl_editors', 'Editors', [VIEW, CHANGE]), Group('decl_viewers', 'Viewers', [VIEW])],
        roles=roles,
    )

    changes = apply_declarations(
        groups=[Group('decl_editors', 'Editors', [VIEW]), Group('decl_viewers', 'Viewers', [VIEW])],
        roles=[Role('decl_editor', 'Editor', ['decl_editors'])],
    )
    assert sorted(changes) == [
        f'grouppermission decl_editors: permissions - {CHANGE}',
        'role decl_editor: groups_permission - decl_viewers',
    ]
    assert permissions('decl_editors') == {VIEW}
    assert groups_of('decl_editor') == {'decl_editors'}
    # the permission itself stays: other groups may have it
    assert Permission.objects.filter(slug=CHANGE).exists()


@pytest.mark.django_db
def test_admin_groups_and_unmarked_objects_are_left():
    groups = [Group('decl_viewers', 'Viewers', [VIEW])]
    roles = [Role('decl_viewer', 'Viewer', ['decl_viewers'])]
    apply_declarations(groups=groups, roles=roles)

    # the admin attaches its own group to the managed role, and has its own role
    admin_group = GroupPermission.objects.create(slug='admin_extra', name_en='Extra')
    admin_group.permissions.add(Permission.objects.get_or_create(slug=CHANGE)[0])
    RoleModel.objects.get(slug='decl_viewer').groups_permission.add(admin_group)
    admin_role = RoleModel.objects.create(slug='admin_role', name_en='Admin role')
    admin_role.groups_permission.add(admin_group)

    assert apply_declarations(groups=groups, roles=roles) == []
    assert groups_of('decl_viewer') == {'decl_viewers', 'admin_extra'}
    # a declared (managed) group the admin attaches to a declared role is not one of its
    # declared groups: it is removed
    other = Group('decl_others', 'Others', [CHANGE])
    apply_declarations(groups=[*groups, other], roles=roles)
    RoleModel.objects.get(slug='decl_viewer').groups_permission.add(GroupPermission.objects.get(slug='decl_others'))
    assert apply_declarations(groups=[*groups, other], roles=roles) == [
        'role decl_viewer: groups_permission - decl_others'
    ]
    assert groups_of('decl_viewer') == {'decl_viewers', 'admin_extra'}
    assert permissions('admin_extra') == {CHANGE}
    assert not RoleModel.objects.get(slug='admin_role').managed
    assert groups_of('admin_role') == {'admin_extra'}


@pytest.mark.django_db
def test_an_unmarked_object_of_the_slug_is_taken_over(caplog):
    group = GroupPermission.objects.create(slug='decl_viewers', name_en='Old')
    group.permissions.add(Permission.objects.get_or_create(slug=CHANGE)[0])

    with caplog.at_level(logging.WARNING, logger='bazis.contrib.permit.declare'):
        changes = apply_declarations(groups=[Group('decl_viewers', 'Viewers', [VIEW])], roles=[])

    assert 'grouppermission decl_viewers: name_en, name_ru, managed changed' in changes
    assert 'grouppermission decl_viewers exists and is not managed' in caplog.text
    group.refresh_from_db()
    assert group.managed and group.name_en == 'Viewers'
    # managed from now on: its permissions are the declared ones
    assert permissions('decl_viewers') == {VIEW}


@pytest.mark.django_db
def test_the_application_is_one_transaction(monkeypatch):
    relation = declare._Sync.relation

    def failing(self, obj, field, *args):
        if field == 'groups_permission':
            raise RuntimeError('failed')
        return relation(self, obj, field, *args)

    monkeypatch.setattr(declare._Sync, 'relation', failing)
    with pytest.raises(RuntimeError):
        apply_declarations(
            groups=[Group('decl_viewers', 'Viewers', [ADD])], roles=[Role('decl_viewer', 'Viewer', ['decl_viewers'])]
        )
    assert not GroupPermission.objects.filter(slug='decl_viewers').exists()
    assert not Permission.objects.filter(slug=ADD).exists()


@pytest.mark.django_db
def test_invalid_declarations_are_refused():
    with pytest.raises(ImproperlyConfigured, match='permit.E004'):
        apply_declarations(groups=[], roles=[Role('decl_viewer', 'Viewer', ['missing'])])
    assert not RoleModel.objects.filter(slug='decl_viewer').exists()


@pytest.mark.django_db
def test_the_cache_is_invalidated_only_by_a_change(monkeypatch):
    calls = []
    monkeypatch.setattr('bazis.contrib.permit.signals.perms_cache_invalidate', lambda: calls.append(1))
    groups = [Group('decl_viewers', 'Viewers', [VIEW])]
    roles = [Role('decl_viewer', 'Viewer', ['decl_viewers'])]

    apply_declarations(groups=groups, roles=roles)
    assert calls
    calls.clear()
    apply_declarations(groups=groups, roles=roles)
    assert calls == []


@pytest.mark.django_db
def test_post_migrate_skips_an_incomplete_migration_plan(monkeypatch):
    applied = []
    monkeypatch.setattr(declare, 'apply_declarations', lambda using: applied.append(using) or [])

    assert declare.migrations_complete()
    monkeypatch.setattr(
        'django.db.migrations.executor.MigrationExecutor.migration_plan', lambda self, targets: [object()]
    )
    assert not declare.migrations_complete()
    declare.post_migrate_apply(sender=None, using='default')
    assert applied == []


def test_post_migrate_skips_a_database_without_the_roles(monkeypatch):
    applied = []
    monkeypatch.setattr(declare, 'apply_declarations', lambda using: applied.append(using) or [])
    monkeypatch.setattr(declare.router, 'allow_migrate_model', lambda using, model: False)
    declare.post_migrate_apply(sender=None, using='other')
    assert applied == []


@pytest.mark.django_db(transaction=True)
def test_concurrent_applications_wait_for_each_other():
    """
    A second `migrate` applying the declarations waits for the transaction of the first
    (an advisory lock), then finds nothing to change.
    """
    groups = [Group('decl_viewers', 'Viewers', [VIEW])]
    held, release, results = threading.Event(), threading.Event(), []

    def first():
        try:
            with transaction.atomic():
                results.append(('first', apply_declarations(groups=groups, roles=[])))
                held.set()
                release.wait(10)
        finally:
            connection.close()

    def second():
        try:
            results.append(('second', apply_declarations(groups=groups, roles=[])))
        finally:
            connection.close()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    threads[0].start()
    assert held.wait(10)
    threads[1].start()
    threads[1].join(1)
    assert threads[1].is_alive(), 'the second application did not wait'
    release.set()
    for it in threads:
        it.join(10)
    assert [name for name, _changes in results] == ['first', 'second']
    assert results[0][1] and results[1][1] == []


@pytest.mark.django_db(transaction=True)
def test_flush_applies_the_declarations_again():
    """
    `flush` (the end of every test with transaction=True) sends `post_migrate`: the declared
    roles are there again after it, also for the next test.
    """
    call_command('flush', interactive=False, verbosity=0)
    assert RoleModel.objects.get(slug='declared_guest').managed
    RoleModel.objects.filter(slug='declared_guest').delete()


@pytest.mark.django_db(transaction=True)
def test_the_declarations_are_there_after_the_flush_of_the_previous_test():
    assert groups_of('declared_guest') == {'declared_guest_meetings'}


@pytest.mark.django_db(transaction=True)
def test_a_revoked_permission_denies_at_once(sample_app):
    """
    The user of a declared role views the parent entities; once the permission is removed
    from the code and applied, he does not (the cached permissions are invalidated).
    """
    groups = [Group('decl_viewers', 'Viewers', [VIEW])]
    roles = [Role('decl_viewer', 'Viewer', ['decl_viewers'])]
    apply_declarations(groups=groups, roles=roles)
    role = RoleModel.objects.get(slug='decl_viewer')
    user = User.objects.create_user('decl_user', email='decl@site.com', password='weak_password_2')
    user.roles.add(role)
    user.role_current = role
    user.save()
    factories.ParentEntityFactory.create()

    response = get_api_client(sample_app, user.jwt_build()).get('/api/v1/entity/parent_entity/')
    assert response.status_code == 200
    assert len(response.json()['data']) == 1

    apply_declarations(groups=[Group('decl_viewers', 'Viewers', [ADD])], roles=roles)
    response = get_api_client(sample_app, user.jwt_build()).get('/api/v1/entity/parent_entity/')
    assert response.status_code == 403


def codes(messages) -> list[str]:
    return [it.id for it in messages]


def errors(messages) -> list:
    return [it for it in messages if it.is_serious()]


def test_the_checks_of_the_sample_pass():
    assert check_declarations(None) == []


@pytest.mark.parametrize(
    ('slug', 'problem'),
    [
        ('entity.parent_entity.item', 'expected <app>.<model>'),
        ('entity.no_model.item.view.all', 'there is no model entity.no_model'),
        ('entity.bookmark.item.view.all', 'entity.Bookmark is not a PermitModelMixin'),
        ('entity.parent_entity.items.view.all', "the level 'items'"),
        ('entity.parent_entity.item.view.nobody', 'has no selector nobody'),
        ('entity.parent_entity.item.view.child_entities__nobody', 'has no selector nobody'),
        ('entity.parent_entity.item.view.missing__author', 'has no relation missing'),
        ('entity.parent_entity.item.view.self', 'is not a PermitSelectorMixin'),
        # auth.Group is a model of Django: no Bazis relations to follow
        ('entity.parent_entity.item.view.author__groups__user', 'auth.Group is not a Bazis model'),
        ('entity.parent_entity.item.view.author__groups__permissions__user', 'auth.Group is not a Bazis model'),
        ('entity.parent_entity.field.view.all.nothing.disable', 'has no field nothing'),
        ('entity.parent_entity.field.view.all.description', 'ends with'),
        ('entity.parent_entity.field.view.all.description.hide', "restriction 'hide'"),
    ],
)
def test_invalid_permissions(slug, problem):
    messages = errors(declaration_messages([('app.roles', Group('decl', 'Decl', [slug]))], []))
    assert codes(messages) == ['permit.E005']
    assert problem in messages[0].msg


@pytest.mark.parametrize(
    'slug',
    [
        VIEW,
        'entity.parent_entity.item.view.author',
        'entity.child_entity.item.change.author_parent',
        'entity.parent_entity.item.view.author=__selector__&is_active=true',
        'entity.parent_entity.field.view.all.__all__.disable',
        'entity.parent_entity.field.change.all.child_entities.filter:child_is_active=true',
        'entity.child_entity.field.add.all.child_name.filter:^[A-Z]+$',
        'entity.team.item.view.self',
    ],
)
def test_valid_permissions(slug):
    assert errors(declaration_messages([('app.roles', Group('decl', 'Decl', [slug]))], [])) == []


def test_invalid_groups_and_roles():
    messages = declaration_messages(
        [('a.roles', Group('decl', 'Decl')), ('b.roles', Group('decl', 'Decl')), ('a.roles', Group('Bad Slug', 'X'))],
        [('a.roles', Role('decl_role', '', ['decl', 'missing']))],
    )
    texts = [it.msg for it in messages if it.id == 'permit.E004']
    assert 'The group decl is declared more than once.' in texts
    assert "The slug 'Bad Slug' of a group is invalid." in texts
    assert any('decl_role: its name is not a text' in it for it in texts)
    assert 'The role decl_role has the group missing, which is not declared.' in texts


def test_untranslated_names_are_reported():
    messages = declaration_messages([('a.roles', Group('decl', _('Not translated anywhere')))], [])
    assert codes(messages) == ['permit.W004']
    assert 'into ru: Not translated anywhere' in messages[0].msg


@pytest.mark.django_db
def test_the_database_checks():
    assert check_declarations_applied(None) == []
    assert check_declarations_applied(None, databases=['default']) == []

    GroupPermission.objects.get(slug='declared_guest_meetings').permissions.remove(
        Permission.objects.get(slug=GUEST)
    )
    GroupPermission.objects.create(slug='decl_orphan', managed=True)
    messages = check_declarations_applied(None, databases=['default'])
    assert codes(messages) == ['permit.W005', 'permit.W006']
    assert f'grouppermission declared_guest_meetings: permissions + {GUEST}' in messages[0].msg
    assert 'grouppermission decl_orphan' in messages[1].msg
    # only listed: nothing was written
    assert GUEST not in permissions('declared_guest_meetings')


@pytest.mark.django_db
def test_the_admin_keeps_managed_objects_read_only():
    request = RequestFactory().get('/')
    request.user = User(is_superuser=True, is_active=True, is_staff=True)
    group_admin = site._registry[GroupPermission]
    role_admin = site._registry[RoleModel]
    group = GroupPermission.objects.get(slug='declared_guest_meetings')
    role = RoleModel.objects.get(slug='declared_guest')
    admin_group = GroupPermission.objects.create(slug='admin_extra', name_en='Extra')

    assert not group_admin.has_change_permission(request, group)
    assert group_admin.has_change_permission(request, admin_group)
    assert not group_admin.has_delete_permission(request, group)
    assert group_admin.has_delete_permission(request, admin_group)

    # the admin attaches its own groups to a managed role, nothing else
    assert role_admin.has_change_permission(request, role)
    readonly = role_admin.get_readonly_fields(request, role)
    assert {'slug', 'name_en', 'name_ru', 'for_anonymous', 'managed'} <= set(readonly)
    assert 'groups_permission' not in readonly
    assert 'slug' not in role_admin.get_readonly_fields(request, RoleModel(slug='new'))
    assert not role_admin.has_delete_permission(request, role)

    # a managed object no longer declared is an ordinary one; a bulk delete skips the declared
    orphan = GroupPermission.objects.create(slug='decl_orphan', managed=True)
    assert group_admin.has_change_permission(request, orphan)
    assert 'slug' not in group_admin.get_readonly_fields(request, orphan)
    assert group_admin.has_delete_permission(request, orphan)
    orphan_role = RoleModel.objects.create(slug='decl_orphan_role', managed=True)
    assert 'slug' not in role_admin.get_readonly_fields(request, orphan_role)
    assert role_admin.has_delete_permission(request, orphan_role)
    group_admin.delete_queryset(request, GroupPermission.objects.filter(slug__in=[group.slug, orphan.slug]))
    assert set(GroupPermission.objects.filter(slug__in=[group.slug, orphan.slug]).values_list('slug', flat=True)) == {
        group.slug
    }
