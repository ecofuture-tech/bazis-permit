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
from bazis.core.schemas import SchemaFields, SchemaField


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