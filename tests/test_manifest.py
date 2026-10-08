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

from django.core import checks

import pytest
from entity.models import Bookmark
from entity.routes import ParentEntityRouteSet

from bazis.contrib.permit.checks import (
    check_relations_view,
    check_routes_permit,
    check_routes_permit_model,
)
from bazis.contrib.permit.routes_abstract import PermitRouteBase
from bazis.core.introspect import validate_manifest


def test_manifest_is_valid():
    assert validate_manifest('bazis.contrib.permit') == []


def test_relations_view_check(settings):
    """
    The deprecated BAZIS_PERMIT_RELATIONS_VIEW_CHECK is reported when it is set.
    """
    for value in (False, True):
        settings.BAZIS_PERMIT_RELATIONS_VIEW_CHECK = value
        assert [it.id for it in check_relations_view(None)] == ['permit.W001']
    settings.BAZIS_PERMIT_RELATIONS_VIEW_CHECK = None
    assert check_relations_view(None) == []


@pytest.mark.django_db
def test_routes_without_permissions(sample_app):
    warnings = {it.obj.__qualname__ for it in check_routes_permit(None)}
    # the user routes of bazis-users do not check permissions
    assert 'UserRouteSet' in warnings
    assert 'ParentEntityRouteSet' not in warnings
    # declared public
    assert 'RoleRoute' not in warnings


@pytest.mark.django_db
def test_routes_permit_model(sample_app, monkeypatch):
    """
    A permission route of a model that does not support permissions is reported (a
    Warning: it must not stop `migrate` or the server); the routes of the sample are not.
    """
    assert check_routes_permit_model(None) == []

    # abstract: not initialized, so it does not become the default route of the model
    bookmark_route = type(
        'BookmarkPermitRouteSet', (PermitRouteBase,), {'abstract': True, 'model': Bookmark}
    )
    monkeypatch.setattr(
        'bazis.core.introspect.route_sets',
        lambda app: {bookmark_route: [], ParentEntityRouteSet: []},
    )
    messages = check_routes_permit_model(None)
    assert [(it.id, it.obj) for it in messages] == [('permit.W003', bookmark_route)]
    assert messages[0].level == checks.WARNING
