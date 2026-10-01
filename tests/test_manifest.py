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

import pytest

from bazis.contrib.permit.checks import check_relations_view, check_routes_permit
from bazis.core.introspect import validate_manifest


def test_manifest_is_valid():
    assert validate_manifest('bazis.contrib.permit') == []


def test_relations_view_check(settings):
    settings.BAZIS_PERMIT_RELATIONS_VIEW_CHECK = False
    assert [it.id for it in check_relations_view(None)] == ['permit.W001']
    settings.BAZIS_PERMIT_RELATIONS_VIEW_CHECK = True
    assert check_relations_view(None) == []


@pytest.mark.django_db
def test_routes_without_permissions(sample_app):
    warnings = {it.obj.__qualname__ for it in check_routes_permit(None)}
    # the user routes of bazis-users do not check permissions
    assert 'UserRouteSet' in warnings
    assert 'ParentEntityRouteSet' not in warnings
    # declared public
    assert 'RoleRoute' not in warnings
