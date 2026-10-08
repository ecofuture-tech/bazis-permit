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
from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase
from bazis.core.schemas import SchemaField, SchemaFields


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

class TeamRouteSet(PermitRouteBase):
    """
    Defines routing for the Team model, with its meetings (a filter through a relation).
    """

    model = apps.get_model('entity.Team')

    fields = {
        None: SchemaFields(include={'meetings': None}),
    }


class MeetingRouteSet(PermitRouteBase, AuthorRouteBase):
    """
    Defines routing for the Meeting model.
    """

    model = apps.get_model('entity.Meeting')
    search_fields = ['title', 'description']


class BookmarkRouteSet(JsonapiRouteBase):
    """
    A route without a user (not a UserRouteBase) of a public model: the parent entities it
    links and includes are restricted for the user of the request (or as for an anonymous
    user) by the default route of the parent entities.
    """

    model = apps.get_model('entity.Bookmark')
    permit_public = True
