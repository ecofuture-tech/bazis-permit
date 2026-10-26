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

from django.apps import apps

from bazis.contrib.author.routes_abstract import AuthorRouteBase
from bazis.contrib.permit.routes_abstract import PermitRouteBase
from bazis.core.routes_abstract.initial import http_get, http_post, route_declare
from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase
from bazis.core.schemas import (
    AccessAction,
    CrudAccessAction,
    CrudApiAction,
    SchemaField,
    SchemaFields,
)
from bazis.core.throttle import throttle


class ChildEntityRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    Defines routing and schema fields for the ChildEntity model, including its
    relationship with parent entities.
    """

    model = apps.get_model('entity.ChildEntity')

    fields = {
        None: SchemaFields(
            include={
                'parent_entities': None,
            },
        ),
    }


class DependentEntityRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    Defines routing for the DependentEntity model.
    """

    model = apps.get_model('entity.DependentEntity')


class ExtendedEntityRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    Defines routing for the ExtendedEntity model.
    """

    model = apps.get_model('entity.ExtendedEntity')


class ParentEntityRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    Defines routing and schema fields for the ParentEntity model, including its
    relationships with extended and dependent entities.
    """

    model = apps.get_model('entity.ParentEntity')

    # add fields (extended_entity, dependent_entities) to schema
    fields = {
        None: SchemaFields(
            include={
                'extended_entity': None, 'dependent_entities': None,
                'childs_detail': SchemaField(source='childs_detail', required=False),
                'some_count_property': SchemaField(source='some_count_property'),
            },
        ),
    }


class TeamAccessAction(AccessAction):
    """
    An operation of the permissions of its own: `entity.team.item.report.<selector>`.
    """

    REPORT = 'report'


class TeamRouteSet(PermitRouteBase):
    """
    Defines routing for the Team model, with its meetings (a filter through a relation).
    """

    model = apps.get_model('entity.Team')
    # the restrictions of the teams for the other routes (TeamGuestRouteSet below)
    default_route = True

    fields = {
        None: SchemaFields(include={'meetings': None}),
    }

    # custom actions: public=True for anyone; access_action: the roles decide, on the model
    # or on the item (taken before the action runs); public=False: authenticated users

    @http_get('/count/', access_action=CrudAccessAction.VIEW)
    def action_count(self, **kwargs) -> int:
        return self.restrict_queryset(self.model.objects.all(), CrudAccessAction.VIEW).count()

    @http_get('/motto/', public=True)
    def action_motto(self, **kwargs) -> str:
        return 'Together'

    @http_get(
        '/digest/', access_action=CrudAccessAction.VIEW, dependencies=[throttle('1/minute')]
    )
    def action_digest(self, **kwargs) -> int:
        return self.restrict_queryset(self.model.objects.all(), CrudAccessAction.VIEW).count()

    @http_post('/{item_id}/rename/', access_action=CrudAccessAction.CHANGE)
    def action_rename(self, item_id: str, name: str, **kwargs) -> str:
        # checked and locked already (a POST action): no other query
        item = self.set_item(item_id, with_lock=True)
        item.name = name
        item.save()
        return item.name

    @http_get('/{item_id}/card/', public=False)
    def action_card(self, item_id: str, **kwargs) -> str:
        return self.set_item(item_id).name

    @http_get('/{item_id}/report/', access_action=TeamAccessAction.REPORT)
    def action_report(self, item_id: str, **kwargs) -> str:
        return f'Report of {self.item.name}'


class MeetingRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    Defines routing for the Meeting model.
    """

    model = apps.get_model('entity.Meeting')
    default_route = True
    search_fields = ['title', 'description']


class MeetingCardRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    The list of the meetings without their description, which their cards show: the search
    reaches the description where the field permissions show it in every object, the filter
    and the sorting do not (the LIST schema has no description).
    """

    model = apps.get_model('entity.Meeting')
    actions = ['action_list', 'action_retrieve', 'action_schema_list', 'action_schema_retrieve']
    search_fields = ['title', 'description']

    fields = {
        CrudApiAction.LIST: SchemaFields(exclude={'description': None}),
    }

    @classmethod
    def get_url_prefix(cls) -> str:
        return '/entity/meeting_card'


class MeetingColumnsRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    The same list of the meetings without the cards (the responses of an update show the
    description of the meetings the user changes, not of every meeting of the list): the
    search does not reach the description.
    """

    model = apps.get_model('entity.Meeting')
    actions = ['action_list', 'action_update', 'action_schema_list']

    fields = {
        CrudApiAction.LIST: SchemaFields(exclude={'description': None}),
    }

    @classmethod
    def get_url_prefix(cls) -> str:
        return '/entity/meeting_columns'


class BookmarkRouteSet(JsonapiRouteBase):
    """
    A route without a user (not a UserRouteBase) of a public model: the parent entities it
    links and includes are restricted for the user of the request (or as for an anonymous
    user) by the default route of the parent entities.
    """

    model = apps.get_model('entity.Bookmark')
    permit_public = True


class TeamGuestRouteSet(TeamRouteSet):
    """
    The actions of the teams declared again for guests: an override keeps `public` unless it
    declares it, `route_declare` changes it without repeating the decorator.
    """

    actions = ['action_motto', 'action_count']

    @classmethod
    def get_url_prefix(cls) -> str:
        return '/entity/team_guest'

    @http_get('/motto/')
    def action_motto(self, **kwargs) -> str:
        return 'Together, as a guest'

    action_count = route_declare(TeamRouteSet.action_count, public=True)
