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
The custom actions of a permission route are secure by default: `public=True` opens one to
anyone (limited by `BAZIS_THROTTLE_PUBLIC`); with `access_action` the roles decide (also
those for anonymous users), on the model for an action of the collection and on the item,
taken before the action runs, for an action of an item; with neither only authenticated
users (sample: `TeamRouteSet`, `TeamGuestRouteSet`). The meta field `custom_actions` lists
the actions the user may call by that rule. The counters of the throttles are reset before
each test by the plugin of bazis-test-utils.
"""

from django.test import override_settings

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import Team
from entity.routes import TeamRouteSet

from bazis.contrib.permit.models import Permission, Role
from bazis.contrib.permit.routes_abstract import PermitRouteBase, route_is_action
from bazis.core.routes_abstract.initial import (
    OPENAPI_EXTENSION,
    http_get,
    http_internal,
    http_post,
)
from bazis.core.schemas import CrudAccessAction

from tests.test_permit_selectors import URL_TEAM, role_with, user_with


URL_TEAM_GUEST = '/api/v1/entity/team_guest/'


@pytest.fixture
def team(db):
    return Team.objects.create(name='Core')


def rename(client, team, name='Platform'):
    return client.post(f'{URL_TEAM}{team.id}/rename/', params={'name': name})


@pytest.mark.django_db(transaction=True)
def test_anonymous_user(sample_app, team):
    """
    An anonymous user without a role: 403 on an action without `access_action` (`card`,
    `public=False`) and on those whose permission he lacks on the model (`count`, `/_id/`),
    404 on an action of an item he cannot view (`rename`, checked before it runs); the
    public action answers him.
    """
    client = get_api_client(sample_app)
    for response in (
        client.get(f'{URL_TEAM}count/'),
        client.get(f'{URL_TEAM}{team.id}/card/'),
        client.get(f'{URL_TEAM}_id/'),
    ):
        assert response.status_code == 403, response.content
        assert response.json()['errors'][0]['code'] == 'ERR_FORBIDDEN'
    assert rename(client, team).status_code == 404
    assert Team.objects.get(pk=team.pk).name == 'Core'

    response = client.get(f'{URL_TEAM}motto/')
    assert response.status_code == 200
    assert response.json() == 'Together'


@pytest.mark.django_db(transaction=True)
def test_user_without_permission(sample_app, team):
    """
    An authenticated user without permissions on the model: 403 on the action of the
    collection with `access_action`, 404 on the actions of an item he cannot view.
    """
    user = user_with('stranger', role_with('nothing'))
    client = get_api_client(sample_app, user.jwt_build())
    assert client.get(f'{URL_TEAM}count/').status_code == 403
    assert rename(client, team).status_code == 404
    assert client.get(f'{URL_TEAM}{team.id}/card/').status_code == 404
    assert client.get(f'{URL_TEAM}motto/').status_code == 200


@pytest.mark.django_db(transaction=True)
def test_access_action(sample_app, team):
    """
    A viewer passes the actions that require `view` and gets 403 on the action of the item
    that requires `change`; a user who can change the team renames it.
    """
    viewer = user_with('viewer', role_with('team_view', 'entity.team.item.view.all'))
    client = get_api_client(sample_app, viewer.jwt_build())
    assert client.get(f'{URL_TEAM}count/').json() == 1
    assert client.get(f'{URL_TEAM}{team.id}/card/').json() == 'Core'
    assert client.get(f'{URL_TEAM}_id/').json() == [str(team.id)]
    response = rename(client, team)
    assert response.status_code == 403
    assert Team.objects.get(pk=team.pk).name == 'Core'

    editor = user_with(
        'editor',
        role_with('team_edit', 'entity.team.item.view.all', 'entity.team.item.change.all'),
    )
    response = rename(get_api_client(sample_app, editor.jwt_build()), team)
    assert response.status_code == 200, response.content
    assert Team.objects.get(pk=team.pk).name == 'Platform'


@pytest.mark.django_db(transaction=True)
def test_public_action_is_throttled(sample_app):
    """
    A public action without a throttle of its own is limited by `BAZIS_THROTTLE_PUBLIC`
    per IP address: 429 `ERR_THROTTLED` with `Retry-After` over the limit; an empty rate or
    `BAZIS_THROTTLE_ENABLED` off do not limit it.
    """
    client = get_api_client(sample_app)
    with override_settings(BAZIS_THROTTLE_PUBLIC='2/minute'):
        assert [client.get(f'{URL_TEAM}motto/').status_code for _ in range(2)] == [200, 200]
        response = client.get(f'{URL_TEAM}motto/')
        assert response.status_code == 429
        assert response.json()['errors'][0]['code'] == 'ERR_THROTTLED'
        assert 1 <= int(response.headers['Retry-After']) <= 60
        # the same address, authenticated: counted apart, by the user (user_or_ip)
        user = user_with('viewer', role_with('nothing'))
        assert get_api_client(sample_app, user.jwt_build()).get(
            f'{URL_TEAM}motto/'
        ).status_code == 200
        # other actions are not limited
        assert client.get(f'{URL_TEAM}count/').status_code == 403

    with override_settings(BAZIS_THROTTLE_PUBLIC='2/minute', BAZIS_THROTTLE_ENABLED=False):
        assert client.get(f'{URL_TEAM}motto/').status_code == 200
    with override_settings(BAZIS_THROTTLE_PUBLIC=''):
        assert client.get(f'{URL_TEAM}motto/').status_code == 200


@pytest.mark.django_db(transaction=True)
def test_throttle_by_user(sample_app):
    """
    A throttle with the default key counts each authenticated user apart (the same IP
    address): the second call of a user is 429, the first of another user passes.
    """
    role = role_with('team_view', 'entity.team.item.view.all')
    first, second = user_with('first', role), user_with('second', role)
    first_client = get_api_client(sample_app, first.jwt_build())
    assert first_client.get(f'{URL_TEAM}digest/').status_code == 200
    assert first_client.get(f'{URL_TEAM}digest/').status_code == 429
    assert get_api_client(sample_app, second.jwt_build()).get(f'{URL_TEAM}digest/').status_code == 200
    # an anonymous user is counted by his address (first call) and refused
    assert get_api_client(sample_app).get(f'{URL_TEAM}digest/').status_code == 403


def test_openapi(sample_app):
    """
    `x-bazis` tells API clients the public actions and the permissions of the actions.
    """
    operations = sample_app.openapi()['paths']
    meta = {
        path.removeprefix(URL_TEAM): next(iter(item.values()))[OPENAPI_EXTENSION]
        for path, item in operations.items()
        if path.startswith(URL_TEAM)
    }
    assert meta['motto/']['public'] is True
    assert 'access_action' not in meta['motto/']
    assert (meta['count/']['public'], meta['count/']['access_action']) == (False, 'view')
    assert meta['{item_id}/rename/']['access_action'] == 'change'
    assert meta['{item_id}/card/']['public'] is False
    assert meta['_id/']['access_action'] == 'view'
    guest = {
        path.removeprefix(URL_TEAM_GUEST): next(iter(item.values()))[OPENAPI_EXTENSION]
        for path, item in operations.items()
        if path.startswith(URL_TEAM_GUEST)
    }
    assert guest['motto/']['public'] is True
    assert (guest['count/']['public'], guest['count/']['access_action']) == (True, 'view')


class ActionsRouteSet(PermitRouteBase):
    # abstract: not a route of the model (the default route of Team stays the sample's)
    abstract = True
    model = Team

    @http_get('/report/')
    def action_report(self, **kwargs):
        pass

    @http_post('/sync/', public=False)
    def action_sync(self, **kwargs):
        pass

    @http_get('/stats/', access_action=CrudAccessAction.VIEW)
    def action_stats(self, **kwargs):
        pass

    @http_get('/{item_id}/card/')
    def action_card(self, item_id: str, **kwargs):
        pass

    @http_get('/{item_id}/badge/', public=False)
    def action_badge(self, item_id: str, **kwargs):
        pass

    @http_internal('/')
    def action_internal(self, **kwargs):
        pass


def test_w007(monkeypatch, sample_app):
    """
    permit.W007: an action, of the collection or of an item, that declares neither
    `access_action` nor `public`; the declared ones (also `public=False`), the CRUD routes
    and the internal route are fine. The sample has none.
    """
    from bazis.contrib.permit import checks
    from bazis.core import introspect

    assert [it for it in checks.check_actions_access(None) if it.id == 'permit.W007'] == []

    monkeypatch.setattr(
        introspect,
        'route_sets',
        lambda app: {ActionsRouteSet: [{'action': name} for name in ActionsRouteSet.routes_ctx]},
    )
    warnings = checks.check_actions_access(None)
    assert [it.id for it in warnings] == ['permit.W007'] * 2
    assert ['action_report' in it.msg or 'action_card' in it.msg for it in warnings] == [True] * 2


def test_internal_route_is_no_action():
    assert route_is_action(ActionsRouteSet.action_report)
    assert not route_is_action(ActionsRouteSet.action_internal)


@pytest.mark.django_db(transaction=True)
def test_roles_for_anonymous_users(sample_app, team):
    """
    `/_id/` declares `access_action=view`: open as `GET /`, also to an anonymous user with a
    role for anonymous users that views the teams; without the role both are 403.
    """
    client = get_api_client(sample_app)
    role = role_with('team_guest', 'entity.team.item.view.all')
    role.for_anonymous = True
    role.save()
    assert client.get(URL_TEAM).status_code == 200
    assert client.get(f'{URL_TEAM}_id/').json() == [str(team.id)]
    # an action with access_action: the role decides; one without: authenticated only
    assert client.get(f'{URL_TEAM}count/').json() == 1
    assert client.get(f'{URL_TEAM}{team.id}/card/').status_code == 403

    Role.objects.filter(for_anonymous=True).delete()
    assert client.get(URL_TEAM).status_code == 403
    assert client.get(f'{URL_TEAM}_id/').status_code == 403


@pytest.mark.django_db(transaction=True)
def test_inherited_and_declared_public(sample_app, team):
    """
    An override that does not declare `public` keeps it (`motto` of `TeamGuestRouteSet`);
    `route_declare(..., public=True)` opens an action that requires a permission
    (`count`) to anonymous users there, not on the route it comes from.
    """
    client = get_api_client(sample_app)
    assert client.get(f'{URL_TEAM_GUEST}motto/').json() == 'Together, as a guest'
    response = client.get(f'{URL_TEAM_GUEST}count/')
    assert (response.status_code, response.json()) == (200, 0)
    assert client.get(f'{URL_TEAM}count/').status_code == 403


@pytest.mark.django_db(transaction=True)
def test_item_of_a_writing_action_is_checked_locked(sample_app, team, monkeypatch):
    """
    The item of an action of an item that writes (POST `rename`, access_action=change) is
    taken locked before the action runs, so the permission checked holds while it runs;
    its `set_item(item_id, with_lock=True)` gets it without another query. A GET action
    takes no lock.
    """
    from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

    lookups = []
    lookup = JsonapiRouteBase.get_queryset_for_item

    def recorded(self, item_id, with_lock=False):
        lookups.append((type(self).__name__, with_lock))
        return lookup(self, item_id, with_lock)

    monkeypatch.setattr(JsonapiRouteBase, 'get_queryset_for_item', recorded)
    editor = user_with(
        'editor',
        role_with('team_edit', 'entity.team.item.view.all', 'entity.team.item.change.all'),
    )
    client = get_api_client(sample_app, editor.jwt_build())
    assert rename(client, team).status_code == 200
    # one lookup, locked, in route_check; the set_item of the action returns that item
    assert lookups == [('TeamRouteSet', True)]
    assert Team.objects.get(pk=team.pk).name == 'Platform'

    lookups.clear()
    assert client.get(f'{URL_TEAM}{team.id}/card/').status_code == 200
    assert lookups == [('TeamRouteSet', False)]


def custom_actions(client, url) -> list[str]:
    response = client.get(url, params={'meta': 'custom_actions'})
    assert response.status_code == 200, response.content
    return sorted(response.json()['meta']['custom_actions'])


#: the actions of the collection of the teams that need the permission view
COLLECTION_VIEW = ['action_count', 'action_digest', 'action_list_id']


@pytest.mark.django_db(transaction=True)
def test_custom_actions_meta(sample_app, team, monkeypatch):
    """
    `custom_actions` of a list: the actions of the collection the user may call (the public
    one, those whose permission he has on the model); of an item: the actions of an item
    he may call on it (`card` for any authenticated user, `rename` with `change`, `report`
    with the operation of its own `report`), by the rule of `route_check`.
    """
    viewer = user_with('viewer', role_with('team_view', 'entity.team.item.view.all'))
    client = get_api_client(sample_app, viewer.jwt_build())
    assert custom_actions(client, URL_TEAM) == sorted(['action_motto', *COLLECTION_VIEW])
    assert custom_actions(client, f'{URL_TEAM}{team.id}/') == ['action_card']
    # the meta field agrees with the check of the actions
    assert client.get(f'{URL_TEAM}{team.id}/report/').status_code == 403
    # an action the route did not register is not listed
    monkeypatch.setattr(TeamRouteSet.routes_ctx['action_motto'], 'route', None)
    assert custom_actions(client, URL_TEAM) == COLLECTION_VIEW
    monkeypatch.undo()

    editor = user_with(
        'editor',
        role_with('team_edit', 'entity.team.item.view.all', 'entity.team.item.change.all'),
    )
    client = get_api_client(sample_app, editor.jwt_build())
    assert custom_actions(client, f'{URL_TEAM}{team.id}/') == ['action_card', 'action_rename']

    reporter = user_with(
        'reporter',
        role_with('team_report', 'entity.team.item.view.all', 'entity.team.item.report.all'),
    )
    client = get_api_client(sample_app, reporter.jwt_build())
    assert custom_actions(client, f'{URL_TEAM}{team.id}/') == ['action_card', 'action_report']
    response = client.get(f'{URL_TEAM}{team.id}/report/')
    assert (response.status_code, response.json()) == (200, 'Report of Core')
    meta = client.get(
        f'{URL_TEAM}{team.id}/', params={'meta': 'crud_actions,custom_actions'}
    ).json()['meta']
    assert (meta['crud_actions'], meta['custom_actions']) == (
        ['view'], ['action_card', 'action_report']
    )

    # without the meta requested: none
    assert 'custom_actions' not in client.get(URL_TEAM).json().get('meta', {})


@pytest.mark.django_db(transaction=True)
def test_custom_actions_meta_by_selector(sample_app, team):
    """
    A permission of a custom operation with a selector: `report` is listed on the team of
    the user (`members`), not on another team he views.
    """
    other = Team.objects.create(name='Other')
    role = role_with('member', 'entity.team.item.view.all', 'entity.team.item.report.members')
    member = user_with('member', role, team=team)
    client = get_api_client(sample_app, member.jwt_build())
    assert custom_actions(client, f'{URL_TEAM}{team.id}/') == ['action_card', 'action_report']
    assert custom_actions(client, f'{URL_TEAM}{other.id}/') == ['action_card']
    assert client.get(f'{URL_TEAM}{other.id}/report/').status_code == 403
    assert client.get(f'{URL_TEAM}{team.id}/report/').status_code == 200


@pytest.mark.django_db(transaction=True)
def test_custom_actions_meta_anonymous(sample_app, team):
    """
    An anonymous user with a role for anonymous users that views the teams: the public
    action and those his role allows; no action closed to anonymous users (`card`), none
    whose permission he lacks (`rename`, `report`).
    """
    role = role_with('team_guest', 'entity.team.item.view.all')
    role.for_anonymous = True
    role.save()
    client = get_api_client(sample_app)
    assert custom_actions(client, URL_TEAM) == sorted(['action_motto', *COLLECTION_VIEW])
    assert custom_actions(client, f'{URL_TEAM}{team.id}/') == []

    Role.objects.filter(for_anonymous=True).delete()
    # without the role he cannot list the teams
    assert client.get(URL_TEAM, params={'meta': 'custom_actions'}).status_code == 403



def w008(messages) -> dict[str, str]:
    """The actions permit.W008 reports, with their messages."""
    assert {it.id for it in messages} <= {'permit.W008'}
    return {it.msg.split(' ', 3)[2]: it.msg for it in messages}


@pytest.fixture
def declared_anonymous(monkeypatch):
    """
    Declares in the roles.py modules a role for anonymous users (`anon`) and a role of the
    users (`staff`), both with the permissions given.
    """
    from bazis.contrib.permit import declare

    def declared(*slugs):
        groups = [declare.Group('anon_group', 'Anonymous', slugs),
                  declare.Group('staff_group', 'Staff', slugs)]
        roles = [declare.Role('anon', 'Anonymous', [groups[0]], for_anonymous=True),
                 declare.Role('staff', 'Staff', [groups[1]])]
        monkeypatch.setattr(
            declare,
            'declarations',
            lambda: ([('roles', it) for it in groups], [('roles', it) for it in roles]),
        )

    return declared


def test_w008_declared_roles(sample_app, declared_anonymous):
    """
    permit.W008: a custom action (not public) whose `access_action` a role for anonymous
    users declared in roles.py has: anonymous users call it (an aggregate with
    `CrudAccessAction.VIEW` is open to whoever views the model). An action of the
    collection needs a permission with any selector, one of an item a selector an anonymous
    user matches (`all`). Not reported: the public actions (`motto`, `count` declared public
    on `TeamGuestRouteSet`), those without `access_action` (`card`), the ids of the list
    (`/_id/`), the roles of the users.
    """
    from bazis.contrib.permit import checks

    assert checks.check_actions_anonymous(None) == []

    declared_anonymous('entity.team.item.view.all')
    found = w008(checks.check_actions_anonymous(None))
    assert sorted(found) == ['action_count', 'action_digest']
    assert 'entity.routes.TeamRouteSet' in found['action_count']
    assert 'anon (entity.team.item.view.all)' in found['action_count']
    assert 'staff' not in found['action_count']
    assert 'roles.py' in found['action_count']

    # an action of the collection: a permission with any selector
    declared_anonymous('entity.team.item.view.members')
    assert sorted(w008(checks.check_actions_anonymous(None))) == ['action_count', 'action_digest']

    # an action of an item: only a selector an anonymous user matches
    declared_anonymous('entity.team.item.report.members', 'entity.team.item.change.members')
    assert w008(checks.check_actions_anonymous(None)) == {}
    declared_anonymous('entity.team.item.report.all', 'entity.team.item.change.all')
    found = w008(checks.check_actions_anonymous(None))
    assert sorted(found) == ['action_rename', 'action_report']
    assert 'entity.team.item.report.' in found['action_report']

    # a condition: with `__selector__` only, it matches no anonymous user; with an
    # alternative or a negation it may (not evaluated: reported)
    declared_anonymous('entity.team.item.report.members=__selector__&name=Core')
    assert w008(checks.check_actions_anonymous(None)) == {}
    declared_anonymous('entity.team.item.report.name=Core')
    assert sorted(w008(checks.check_actions_anonymous(None))) == ['action_report']
    declared_anonymous('entity.team.item.report.members=__selector__|name=Core')
    assert sorted(w008(checks.check_actions_anonymous(None))) == ['action_report']
    declared_anonymous('entity.team.item.report.~members=__selector__')
    assert sorted(w008(checks.check_actions_anonymous(None))) == ['action_report']


@pytest.mark.django_db(transaction=True)
def test_w008_follows_route_check(sample_app, team):
    """
    What permit.W008 reports is what route_check allows: an anonymous user with a role for
    anonymous users having `entity.team.item.view.members` (a selector he never matches)
    calls the actions of the collection with `access_action=view`; with
    `entity.team.item.report.members` not the action of an item `report`, with
    `entity.team.item.report.all` or a condition with an alternative without
    `__selector__` he does.
    """
    client = get_api_client(sample_app)
    role = role_with('team_guest', 'entity.team.item.view.members')
    role.for_anonymous = True
    role.save()
    response = client.get(f'{URL_TEAM}count/')
    assert (response.status_code, response.json()) == (200, 0)

    Role.objects.filter(for_anonymous=True).delete()
    role = role_with('team_report', 'entity.team.item.view.all', 'entity.team.item.report.members')
    role.for_anonymous = True
    role.save()
    assert client.get(f'{URL_TEAM}{team.id}/report/').status_code == 403
    role.groups_permission.first().permissions.add(
        Permission.objects.get_or_create(slug='entity.team.item.report.all')[0]
    )
    assert client.get(f'{URL_TEAM}{team.id}/report/').status_code == 200

    # an alternative without `__selector__` matches him (permit.W008 reports it)
    Role.objects.filter(for_anonymous=True).delete()
    role = role_with(
        'team_alternative',
        'entity.team.item.view.all',
        'entity.team.item.report.members=__selector__|name=Core',
    )
    role.for_anonymous = True
    role.save()
    assert client.get(f'{URL_TEAM}{team.id}/report/').status_code == 200


@pytest.mark.django_db(transaction=True)
def test_w008_roles_of_the_database(sample_app, declared_anonymous):
    """
    permit.W008 for the roles for anonymous users of the database (the admin, the API):
    with the database checks, the permissions the declarations do not give (those are
    reported by the check of roles.py, not twice).
    """
    from bazis.contrib.permit import checks

    assert checks.check_actions_anonymous_applied(None, databases=['default']) == []
    role = role_with('team_guest', 'entity.team.item.view.all')
    role.for_anonymous = True
    role.save()
    role_with('team_staff', 'entity.team.item.report.all')

    assert checks.check_actions_anonymous_applied(None) == []
    found = w008(checks.check_actions_anonymous_applied(None, databases=['default']))
    assert sorted(found) == ['action_count', 'action_digest']
    assert 'team_guest (entity.team.item.view.all)' in found['action_count']
    assert 'the database' in found['action_count']

    # declared (and applied): reported by the check of roles.py only
    declared_anonymous('entity.team.item.view.all')
    Role.objects.filter(slug='team_guest').update(slug='anon')
    assert checks.check_actions_anonymous_applied(None, databases=['default']) == []
    assert sorted(w008(checks.check_actions_anonymous(None))) == ['action_count', 'action_digest']
