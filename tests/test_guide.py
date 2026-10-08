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
Statements of the guide (bazis/contrib/permit/AGENTS.md) not covered elsewhere: the
selector `self`, the field permissions in the API, the names of the roles in a data
migration, an override of `restrict_queryset`.
"""

from importlib.metadata import version

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import Team

from bazis.contrib.permit.models import Role

from tests.test_permit_selectors import (  # noqa: F401  the fixture
    URL_TEAM,
    ids,
    no_selector_warnings,
    role_with,
    user_with,
)


BAZIS_VERSION = tuple(int(it) for it in version('bazis').split('.')[:3] if it.isdigit())


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('no_selector_warnings')
def test_selector_self(sample_app, monkeypatch):
    """
    `self`: the object the model gives the user as a selector source
    (`get_selector_for_user`; the user himself for a user model), here one team he watches.
    """
    monkeypatch.setattr(
        Team, 'get_selector_for_user', classmethod(lambda cls, user: cls.objects.get(watchers=user))
    )
    role = role_with('team_self', 'entity.team.item.view.self')
    team, other_team = Team.objects.create(name='Core'), Team.objects.create(name='Docs')
    other = user_with('other', role)
    other.teams_watched.add(other_team)
    watcher = user_with('watcher', role)
    watcher.teams_watched.add(team)

    client = get_api_client(sample_app, watcher.jwt_build())
    assert ids(client.get(URL_TEAM)) == [str(team.id)]
    assert client.get(f'{URL_TEAM}{team.id}/').status_code == 200
    assert client.get(f'{URL_TEAM}{other_team.id}/').status_code in (403, 404)


@pytest.mark.django_db
def test_names_of_a_role_by_column():
    """
    The names of the roles and groups are columns `name_en` and `name_ru`, whatever the
    languages of the project: a data migration sets them by column.
    """
    role = Role.objects.create(slug='manager', name_en='Manager', name_ru='Менеджер')

    from django.utils import translation

    with translation.override('ru'):
        assert Role.objects.get(pk=role.pk).name == 'Менеджер'
    with translation.override('en'):
        assert Role.objects.get(pk=role.pk).name == 'Manager'


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('no_selector_warnings')
def test_restrict_queryset_narrowed_in_code(sample_app):
    """
    An override of `restrict_queryset` keeps the permissions with `super()` and narrows
    them (the queryset of bazis-permit also carries the field groups of the objects).
    """
    from entity.routes import TeamRouteSet

    from bazis.core.schemas import CrudAccessAction
    from bazis.core.utils.functools import class_or_instance_method

    class ActiveTeams(TeamRouteSet):
        # abstract: not initialized, it does not become the default route of the model
        abstract = True

        @class_or_instance_method
        def restrict_queryset(self, qs, access_action, user=None, permit=None, **kwargs):
            qs = super().restrict_queryset(qs, access_action, user=user, permit=permit, **kwargs)
            return qs.exclude(name__startswith='Old')

    role = role_with('team_watcher', 'entity.team.item.view.watchers')
    core, old, docs = (Team.objects.create(name=it) for it in ('Core', 'Old core', 'Docs'))
    watcher = user_with('watcher', role)
    watcher.teams_watched.add(core, old)

    def visible(route):
        qs = route.restrict_queryset(Team.objects.all(), CrudAccessAction.VIEW, user=watcher)
        return {it.name for it in qs}

    assert visible(TeamRouteSet) == {'Core', 'Old core'}
    assert visible(ActiveTeams) == {'Core'}


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('no_selector_warnings')
def test_read_only_fields_in_the_api(sample_app):
    """
    `field.change.<selector>.<field>.readonly`: an update ignores the field (200, the value
    unchanged), the relationships endpoints of a read-only relation answer 403.
    """
    from entity.models import Meeting

    from tests.test_permit_selectors import URL_MEETING, meeting_patch

    role = role_with(
        'meeting_readonly',
        'entity.meeting.item.view.author',
        'entity.meeting.item.change.author',
        'entity.meeting.field.change.author.title.readonly',
        'entity.meeting.field.change.author.team.readonly',
    )
    author = user_with('author', role)
    team = Team.objects.create(name='Core')
    meeting = Meeting.objects.create(title='Planning', author=author)
    client = get_api_client(sample_app, author.jwt_build())

    response = client.patch(
        f'{URL_MEETING}{meeting.id}/',
        json_data=meeting_patch(meeting, title='Renamed', description='Notes'),
    )
    assert response.status_code == 200, response.content
    meeting.refresh_from_db()
    assert (meeting.title, meeting.description) == ('Planning', 'Notes')

    if BAZIS_VERSION < (2, 8, 1):
        pytest.skip('bazis < 2.8.1 answers 500 (KeyError) on a read-only relationship')
    response = client.patch(
        f'{URL_MEETING}{meeting.id}/relationships/team',
        json_data={'data': {'type': 'entity.team', 'id': str(team.id)}},
    )
    assert response.status_code == 403
    assert response.json()['errors'][0]['code'] == 'ERR_RELATIONSHIP_READONLY'
    meeting.refresh_from_db()
    assert meeting.team_id is None
