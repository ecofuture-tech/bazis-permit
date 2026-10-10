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
The custom actions of a permission route are secure by default: closed to anonymous users
unless declared `public=True` (limited by `BAZIS_THROTTLE_PUBLIC`), with the permission
they declare (`access_action`) checked on the model for an action of the collection and on
the item for an action of an item (sample: `TeamRouteSet`).
"""

from django.core.cache import cache
from django.test import override_settings

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import Team

from bazis.contrib.permit.routes_abstract import PermitRouteBase
from bazis.core.routes_abstract.initial import OPENAPI_EXTENSION, http_get, http_post
from bazis.core.schemas import CrudAccessAction

from tests.test_permit_selectors import URL_TEAM, role_with, user_with


@pytest.fixture(autouse=True)
def throttle_counts():
    cache.delete_pattern('bazis:throttle:*')
    yield
    cache.delete_pattern('bazis:throttle:*')


@pytest.fixture
def team(db):
    return Team.objects.create(name='Core')


def rename(client, team, name='Platform'):
    return client.post(f'{URL_TEAM}{team.id}/rename/', params={'name': name})


@pytest.mark.django_db(transaction=True)
def test_anonymous_user(sample_app, team):
    """
    An anonymous user gets 403 on every action not declared public, also on an action of
    an item without `access_action`; the public action answers him.
    """
    client = get_api_client(sample_app)
    for response in (
        client.get(f'{URL_TEAM}count/'),
        rename(client, team),
        client.get(f'{URL_TEAM}{team.id}/card/'),
        client.get(f'{URL_TEAM}_id/'),
    ):
        assert response.status_code == 403, response.content
        assert response.json()['errors'][0]['code'] == 'ERR_FORBIDDEN'
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
        # the same address, authenticated: counted by address too
        user = user_with('viewer', role_with('nothing'))
        assert get_api_client(sample_app, user.jwt_build()).get(
            f'{URL_TEAM}motto/'
        ).status_code == 429
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
    assert meta['count/']['access_action'] == 'view'
    assert meta['{item_id}/rename/']['access_action'] == 'change'
    assert 'public' not in meta['{item_id}/card/']


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


def test_w007(monkeypatch, sample_app):
    """
    permit.W007: an action of the collection that declares neither `access_action` nor
    `public`; the actions of an item, the declared ones and the CRUD routes are fine. The
    sample has none.
    """
    from bazis.contrib.permit import checks
    from bazis.core import introspect

    assert [it for it in checks.check_actions_access(None) if it.id == 'permit.W007'] == []

    monkeypatch.setattr(
        introspect,
        'route_sets',
        lambda app: {
            ActionsRouteSet: [
                {'action': name} for name in ActionsRouteSet.routes_ctx if name != 'action_internal'
            ]
        },
    )
    (warning,) = checks.check_actions_access(None)
    assert warning.id == 'permit.W007'
    assert 'action_report' in warning.msg
