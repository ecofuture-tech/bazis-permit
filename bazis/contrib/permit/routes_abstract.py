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

import dataclasses
import inspect
import logging
import warnings
from collections import UserDict, defaultdict
from collections.abc import Callable, Iterable
from functools import reduce
from typing import Any, Self

from django.db.models import Case, IntegerField, QuerySet, Value, When
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from fastapi import Depends, HTTPException

from pydantic import BaseModel

from bazis.contrib.users import get_anonymous_user_model, get_user_model
from bazis.contrib.users.models_abstract import UserMixin
from bazis.contrib.users.routes_abstract import UserRouteBase
from bazis.core.errors import JsonApi403Exception
from bazis.core.models_abstract import JsonApiMixin
from bazis.core.routes_abstract.initial import http_get, inject_make
from bazis.core.routes_abstract.jsonapi import RestrictedQsRouteMixin, with_cache_openapi_schema
from bazis.core.schemas import (
    AccessAction,
    ApiAction,
    CrudAccessAction,
    CrudApiAction,
    SchemaField,
    SchemaFields,
    SchemaResourceBuilder,
    meta_field,
)
from bazis.core.services.includes import include_to_list
from bazis.core.utils.functools import class_or_instance_method
from bazis.core.utils.orm import apply_calc_queryset
from bazis.core.utils.query_complex import QueryToOrm

from .services import PermitService
from .utils import is_model_permit


User = get_user_model()
AnonymousUser = get_anonymous_user_model()

logger = logging.getLogger(__name__)


def fields_restricts_collect(perms_field_values):
    """
    Collects and aggregates field restrictions from permission values.
    """
    fields_restricts = defaultdict(set)
    for perm_vals in perms_field_values:
        for f_name, restricts in perm_vals.items():
            for restrict in restricts.keys():
                fields_restricts[f_name] |= set(restrict.split('|'))
    return fields_restricts


class _SchemasPermitHelper:
    """
    Auxiliary class for encapsulating the schema building context.
        The schema will be assembled only if there is permission for the action.
    """

    def __init__(
        self,
        route_cls: type['PermitRouteBase'],
        permit_service: PermitService,
        api_action: ApiAction,
        item_or_model: JsonApiMixin | type[JsonApiMixin] | Callable,
        includes: list[str] = None,
        is_response_schema: bool = False,
    ):
        """
        Initializes the _SchemasPermitHelper with the necessary context for schema
        building, including route class, permit service, API action, and item or model.
        """
        item_or_model = item_or_model() if inspect.isfunction(item_or_model) else item_or_model

        self.api_action = api_action
        self.route_cls = route_cls
        self.schema_factory = route_cls.schema_factories[api_action]
        self.permit_service = permit_service
        self.permit_handler = permit_service.handler(api_action.access_action, item_or_model)
        self.item = item_or_model if isinstance(item_or_model, JsonApiMixin) else None
        self.includes = includes or []
        self.is_response_schema = is_response_schema

        if not self.permit_handler.check_access():
            raise JsonApi403Exception()

    @cached_property
    def fields(self) -> list['SchemaField']:
        """
        Based on the main instance, patches and returns a copy of the schema fields.
        """
        return self.schema_factory.fields_patch(
            fields_restricts_collect(self.permit_handler.perms_field_values)
        )

    @cached_property
    def inclusions(self) -> Iterable[type['BaseModel']]:
        """
        Performs schema assembly for existing and requested included objects.
                :return: An iterable of BaseModel types for the included objects.
        """
        fields_names = [f.name for f in self.fields]

        # we leave only those inclusions that are present in the final set of fields
        # and explicitly requested through the parameter
        inclusions_factory = {
            k: v
            for k, v in self.schema_factory.inclusions_factory_with_default.items()
            if k in fields_names and k in self.includes
        }

        for inclusion_name, inclusion_factory in inclusions_factory.items():
            # find the included object
            if not (items := self.item.fields_for_included.get(inclusion_name)):
                continue

            # process through the list, as there may be included m2m
            for item in items:
                if not item:
                    continue

                model = type(item)

                if inclusion_factory.model != model:
                    if issubclass(model, JsonApiMixin):
                        if route_cls := model.get_default_route():
                            fields_struct = route_cls.build_schema_attrs(
                                self.api_action, 'fields', SchemaFields
                            )

                            inclusion_factory = dataclasses.replace(
                                inclusion_factory,
                                route_cls=route_cls,
                                model=type(item),
                                fields_struct=fields_struct,
                            )

                fields = None

                # sub-service permissions
                if is_model_permit(type(item)):
                    permit_handler = self.permit_service.handler(
                        self.api_action.access_action, item
                    )
                    # the core leaves out the objects the user cannot view (bazis 2.7); the
                    # update schema includes only the objects the user can change
                    if not permit_handler.check_access():
                        continue

                    # perform field patching
                    fields = inclusion_factory.fields_patch(
                        fields_restricts_collect(permit_handler.perms_field_values)
                    )

                # assemble the included schema with a patched copy of the schema fields
                yield SchemaResourceBuilder(inclusion_factory, fields=fields).build(
                    is_response_schema=self.is_response_schema, id=item.id
                )

    @cached_property
    def inclusions_for_create(self) -> Iterable[type['BaseModel']]:
        """
        Performs schema assembly for created included objects.
                :return: An iterable of BaseModel types for the created included objects.
        """
        # add schemas for creating included if they are available
        schema = self.route_cls.schema_factories[CrudApiAction.CREATE]
        inclusions_factory = {
            k: v
            for k, v in schema.inclusions_factory_with_default.items()
            if k in self.fields and k in self.includes
        }

        for _inclusion_name, inclusion_factory in inclusions_factory.items():
            # sub-service permissions
            permit_handler = self.permit_service.handler(
                CrudAccessAction.ADD, inclusion_factory.model
            )
            # check access rights
            if not permit_handler.check_access():
                continue

            # perform field patching
            fields = inclusion_factory.fields_patch(
                fields_restricts_collect(permit_handler.perms_field_values)
            )

            # assemble the included schema with a patched copy of the schema fields
            yield SchemaResourceBuilder(inclusion_factory, fields=fields).build()

    def build_schema(self, schema_resource=None, inclusions=None):
        """
        Builds the schema with the given schema resource and inclusions. If no schema
        resource is explicitly passed, it assembles one with fields. A response schema
        is built from response resource schemas, in which no field is required: a sparse
        fieldset may leave out any of them.
        """
        if not schema_resource:
            schema_resource = SchemaResourceBuilder(self.schema_factory, fields=self.fields).build(
                is_response_schema=self.is_response_schema
            )
        return self.schema_factory.build_schema(
            schema_resource=schema_resource,
            inclusions=inclusions,
            is_response_schema=self.is_response_schema,
        )


class SchemasPermit(UserDict):
    """
    A dictionary-like class that manages schema permissions and building for a given
    route class, user, and item or model.
    """

    def __init__(
        self,
        route_cls: type['PermitRouteBase'],
        user: User | AnonymousUser,
        item_or_model: JsonApiMixin | type[JsonApiMixin] | Callable,
        includes: list[str] = None,
        is_response_schema: bool = False,
        dict=None,
        /,
        **kwargs,
    ):
        """
        Initializes the SchemasPermit with the route class, user, item or model, and
        optional includes.
        """
        self.route_cls = route_cls
        self.permit_service = route_cls.InjectPermit.__annotations__['permit'](user)
        self.item_or_model = item_or_model
        self.includes = includes
        self.is_response_schema = is_response_schema
        super().__init__(dict=dict, **kwargs)

    def get_helper(self, api_action: ApiAction):
        """
        Returns an instance of _SchemasPermitHelper for the given API action.
        """
        return _SchemasPermitHelper(
            self.route_cls, self.permit_service, api_action, self.item_or_model, self.includes, self.is_response_schema
        )

    def build_schema_list(self):
        """
        For the list, performs a separate assembly of the combined schema.
                Collects variations of field sets based on permissions.
                :return: The assembled schema for the list action.
        """
        helper = self.get_helper(CrudApiAction.LIST)
        schema_resources = [
            SchemaResourceBuilder(helper.schema_factory).build(is_response_schema=self.is_response_schema)]

        # get unique permission groups
        for values, cond in helper.permit_handler.perms_field_groups:
            restricts_collect = fields_restricts_collect(values)
            fields = helper.schema_factory.fields_patch(restricts_collect)

            # add a new resource schema to the set
            schema_resources.append(
                SchemaResourceBuilder(helper.schema_factory, fields=fields).build(
                    _schema_key=hash(cond), is_response_schema=self.is_response_schema
                )
            )

        if schema_resources:
            schema_resource_union = reduce(lambda it, res: it | res, schema_resources)
        else:
            schema_resource_union = None

        return helper.build_schema(inclusions=[], schema_resource=schema_resource_union)

    def build_schema_retrieve(self):
        """
        Builds the schema for the retrieve action, including any requested inclusions.
        """
        helper = self.get_helper(CrudApiAction.RETRIEVE)
        inclusions = list(helper.inclusions)
        return helper.build_schema(inclusions=inclusions)

    def build_schema_update(self):
        """
        Builds the schema for the update action, including any requested inclusions and
        those for creation.
        """
        helper = self.get_helper(CrudApiAction.UPDATE)
        return helper.build_schema(
            inclusions=list(helper.inclusions) + list(helper.inclusions_for_create)
        )

    def build_schema_create(self):
        """
        Builds the schema for the create action, including any requested inclusions for
        creation.
        """
        helper = self.get_helper(CrudApiAction.CREATE)
        return helper.build_schema(inclusions=list(helper.inclusions_for_create))

    @classmethod
    def get_builders(cls) -> dict[ApiAction, Callable]:
        """
        Returns a dictionary mapping API actions to their corresponding schema building
        methods.
        """
        return {
            CrudApiAction.LIST: cls.build_schema_list,
            CrudApiAction.RETRIEVE: cls.build_schema_retrieve,
            CrudApiAction.UPDATE: cls.build_schema_update,
            CrudApiAction.CREATE: cls.build_schema_create,
        }

    def __getitem__(self, key: ApiAction):
        """
        Retrieves the schema for the given API action, building it if it does not
        already exist in the data.
        """
        if key not in self.data:
            if get_schema := self.get_builders().get(key):
                self.data[key] = get_schema(self)
        return super().__getitem__(key)

    def get(self, key: ApiAction, default=None) -> type[BaseModel] | None:
        try:
            return self[key]
        except KeyError:
            return default


class PermitRouteBase(RestrictedQsRouteMixin, UserRouteBase):
    """
    Base class for routes that require permission checks, providing methods for
    schema management and access control.
    """

    abstract: bool = True
    schemas: SchemasPermit
    schemas_responses: SchemasPermit

    #: deprecated, removed in bazis-permit 3.0: the core checks the objects the relationships
    #: of a created or changed item reference (`relation_targets_check`, bazis 2.7). False
    #: turns that check off (`relation_targets_check = False`), True does nothing.
    relations_view_check: bool | None = None

    fields: dict[ApiAction, SchemaFields] = {
        CrudApiAction.CREATE: SchemaFields(
            exclude={'dt_created': None, 'dt_updated': None},
        ),
        CrudApiAction.UPDATE: SchemaFields(
            exclude={'dt_created': None, 'dt_updated': None},
        ),
    }

    @inject_make()
    class InjectPermit:
        """
        Dependency injection class for PermitService, used to manage permissions.
        """
        permit: PermitService = Depends()

    @classmethod
    def cls_init(cls):
        """
        Class-level initialization method that configures actions based on model
        properties, such as excluding creation and update actions for proxy models.
        """
        super().cls_init()
        if cls.relations_view_check is not None:
            warnings.warn(
                f'{cls.__module__}.{cls.__qualname__}: relations_view_check is deprecated and '
                'will be removed in bazis-permit 3.0; the core checks the related objects, '
                'relation_targets_check = False turns the check off.',
                DeprecationWarning,
                stacklevel=2,
            )
            if cls.relations_view_check is False:
                cls.relation_targets_check = False
        # creation/update actions are not available for proxy models, as they can change the state
        # of visibility of proxy model objects
        if cls.model._meta.proxy:
            cls.actions_exclude = cls.actions_exclude or []
            cls.actions_exclude.extend(['action_schema_create', 'action_schema_update'])

    @http_get('/schema_list/', response_model=dict[str, Any])
    def action_schema_list(self, **kwargs):
        """
        HTTP GET endpoint to retrieve the schema for listing items, returning the
        OpenAPI schema.
        """
        return with_cache_openapi_schema(self.schemas_responses[CrudApiAction.LIST])

    @http_get('/schema_create/', response_model=dict[str, Any])
    def action_schema_create(
        self, include: str | None = Depends(include_to_list), **kwargs
    ):
        """
        HTTP GET endpoint to retrieve the schema for creating an item, returning the
        OpenAPI schema.
        """
        return with_cache_openapi_schema(self.schemas[CrudApiAction.CREATE])

    @http_get('/{item_id}/schema_retrieve/', response_model=dict[str, Any])
    def action_schema_retrieve(
        self, item_id: str, include: str | None = Depends(include_to_list), **kwargs
    ):
        """
        HTTP GET endpoint to retrieve the schema for a specific item, returning the
        OpenAPI schema.
        """
        self.set_api_action(CrudApiAction.RETRIEVE)
        self.set_item(item_id)
        return with_cache_openapi_schema(self.schemas_responses[CrudApiAction.RETRIEVE])

    @http_get('/{item_id}/schema_update/', response_model=dict[str, Any])
    def action_schema_update(
        self, item_id: str, include: str | None = Depends(include_to_list), **kwargs
    ):
        """
        HTTP GET endpoint to retrieve the schema for updating a specific item, returning
        the OpenAPI schema.
        """
        self.set_api_action(CrudApiAction.UPDATE)
        self.set_item(item_id)
        return with_cache_openapi_schema(self.schemas[CrudApiAction.UPDATE])

    def __init__(self, *args, **kwargs):
        """
        Initializes the PermitRouteBase, setting up schemas and other necessary
        properties.
        """
        super().__init__(*args, **kwargs)
        self.schemas_make()

    def schemas_make(self):
        """
        Creates and initializes the SchemasPermit instance for the route.
        """

        def get_item():
            """
            Helper function to get the current item or model for schema creation.
            """
            return self.item or self.model

        self.schemas = SchemasPermit(
            type(self), self.inject.user, get_item, getattr(self.inject, 'include', [])
        )
        self.schemas_responses = SchemasPermit(
            type(self), self.inject.user, get_item, getattr(self.inject, 'include', []), True
        )

    def check_access(
        self, access_action: AccessAction, item_or_model: JsonApiMixin | type[JsonApiMixin], item_passive=False
    ):
        """
        Checks access permissions for the given action and item or model.
                Raises a 403 exception if access is denied.
        """
        if not self.inject.permit.handler(access_action, item_or_model).check_access(
                item_passive=item_passive
        ):
            raise JsonApi403Exception()

    def set_item(self, item_id: str, with_lock: bool = False, is_force: bool = False) -> JsonApiMixin:
        """
        The item of a route of an item (retrieve, update, delete, the relationships and the
        schema routes, the transits of bazis-statusy): an item the user cannot view does not
        exist for him, 404 as a missing one, so that the answer does not tell that it
        exists; the routes answer 403 for an item he views but cannot change. The check is
        made on a handler of its own: the cached one would keep the values of the item
        before a write of the request (a transit that hides it).
        """
        previous = self.item
        item = super().set_item(item_id, with_lock=with_lock, is_force=is_force)
        if item is not previous:
            permit = self.inject.permit
            if not permit.handler_class(permit, CrudAccessAction.VIEW, item).check_access():
                self.item = None
                raise HTTPException(status_code=404, detail='Item not found')
        return item

    @classmethod
    def permit_service_for(cls, user: User | AnonymousUser | None) -> PermitService:
        """
        The permission service of the user for a call on the class: the core calls
        `restrict_queryset` once per relationship of an item, and a new service would load
        the role and the permissions every time. Within a request (`JsonApiMixin.CTX_ROUTE`)
        it is the service of the route of the request if that route has the same user,
        otherwise one kept on that route for the rest of the request.
        """
        service_cls = [f for f in dataclasses.fields(cls.InjectPermit) if f.name == 'permit'][0].type
        if (route := JsonApiMixin.CTX_ROUTE.get()) is None:
            return service_cls(user)

        def user_key(it):
            return None if it is None or it.is_anonymous else it.pk

        key = (service_cls, user_key(user))
        if isinstance(route, PermitRouteBase):
            permit = route.inject.permit
            if (type(permit), user_key(permit.user)) == key:
                return permit
        services = vars(route).setdefault('_permit_services', {})
        if key not in services:
            services[key] = service_cls(user)
        return services[key]

    @classmethod
    def _permit_service_on_class(cls, user: User | AnonymousUser | None) -> PermitService | None:
        """
        The permission service for a call of the core on the class (`restrict_queryset`,
        `query_fields`) with the user of the calling route: None there (a route without a
        user) is the authenticated user of the request (`UserMixin.CTX_USER_REQUEST`), and
        without one the roles for anonymous users. None if the user cannot have the roles of
        bazis-permit (e.g. an anonymous user model without AnonymousUserPermitMixin): he
        sees nothing.
        """
        if user is None:
            user = UserMixin.CTX_USER_REQUEST.get()
        permit = cls.permit_service_for(user)
        return permit if hasattr(permit.user, 'role_current') else None

    @classmethod
    def query_fields(cls, user=None, **kwargs) -> list[SchemaField]:
        """
        The fields of the LIST schema of the route the field permissions of the user show in
        some object (Bazis 2.9: the filter, the sorting and the search of a request start
        with them, also through a relation into the objects of the model): the union of the
        fields of the field groups that the objects match (`perms_field_groups`, in the
        order of `restrict_queryset`), all the fields if an object can match none of them
        (its schema has no field permissions), none if the user cannot have the roles of
        bazis-permit. A field visible in only some objects of the list stays reachable for
        all of them. Which objects are reached is decided by `restrict_queryset`.
        """
        if (permit := cls._permit_service_on_class(user)) is None:
            return []
        handler = permit.handler(CrudApiAction.LIST.access_action, cls.model)
        factory = cls.schema_factories.get(CrudApiAction.LIST) or cls.build_schema_factory(
            CrudApiAction.LIST
        )
        names = set()
        for values, cond in handler.perms_field_groups:
            names.update(f.name for f in factory.fields_patch(fields_restricts_collect(values)))
            if not cond:
                # every object matches this group or one before it
                return [f for f in factory.fields_list if f.name in names]
        return factory.fields_list

    @class_or_instance_method
    def restrict_queryset(
        self: type[Self] | Self,
        qs: QuerySet,
        access_action: AccessAction,
        user: User | AnonymousUser | None = None,
        permit: PermitService = None,
        **kwargs,
    ):
        """
        Restricts the queryset based on permissions for the given access action and user.
        The core calls it on the class for the relationships, `included` and the filters
        through a relation of the other routes, with the user of the calling route
        (`_permit_service_on_class`). It never fails for a missing user: a user without the
        roles of bazis-permit sees nothing. The calls of a request share the permission
        service of the user (`permit_service_for`).
                :return: The restricted queryset.
        """
        if not permit:
            if isinstance(self, PermitRouteBase):
                permit = self.inject.permit
            elif (permit := self._permit_service_on_class(user)) is None:
                return qs.none()

        permit_handler = permit.handler(access_action, qs.model)
        if not permit_handler.perms_item:
            return qs.none()

        # for the "add" action, the mere fact of having permissions is sufficient
        if access_action == CrudAccessAction.ADD:
            return qs

        # here we select by IDs of objects that are affected by field permissions
        # after obtaining such selections, we annotate the objects inside qs with hashes of specific schemas

        cases = []
        for __, cond in permit_handler.perms_field_groups:
            q_orm = QueryToOrm(cond, qs.model)
            if q_orm.fields_calc:
                qs = apply_calc_queryset(qs, q_orm.fields_calc)

            cases.append(When(q_orm.q or Value(True), then=Value(hash(cond))))

        qs = qs.annotate(
            _schema_key=Case(
                *cases,
                default=Value(None),
                output_field=IntegerField(null=True)
            )
        )

        qs = permit_handler.struct.perms_item_apply(qs, permit_handler.perms_item)
        return qs

    def get_queryset_for_list(self):
        """
        Retrieves the queryset for listing items, applying access checks and
        restrictions.
        """
        self.check_access(CrudAccessAction.VIEW, self.model)
        return self.restrict_queryset(
            super().get_queryset_for_list(),
            CrudAccessAction.VIEW,
        )

    @meta_field([CrudApiAction.LIST], title=_('Available for editing'))
    def for_change(self) -> list[str]:
        """
        Returns a list of primary keys (PKs) that will be available for editing from the
        current page.
        """
        return [
            str(pk)
            for pk in self.restrict_queryset(
                super().get_queryset_for_list().filter(pk__in=self.list()),
                CrudAccessAction.CHANGE,
            ).values_list('pk', flat=True)
        ]

    @meta_field([CrudApiAction.LIST], title=_('Available for deletion'))
    def for_delete(self) -> list[str]:
        """
        Returns a list of primary keys (PKs) that will be available for deletion from
        the current page.
        """
        return [
            str(pk)
            for pk in self.restrict_queryset(
                super().get_queryset_for_list().filter(pk__in=self.list()),
                CrudAccessAction.DELETE,
            ).values_list('pk', flat=True)
        ]

    @meta_field([CrudApiAction.LIST], title=_('Available for creation'))
    def for_create(self) -> bool:
        """
        Returns a boolean value indicating the availability of the "Create" action.
        """
        try:
            self.check_access(CrudAccessAction.ADD, self.model)
        except JsonApi403Exception:
            return False
        else:
            return True

    @meta_field([CrudApiAction.RETRIEVE], title=_('Available actions'))
    def crud_actions(self) -> list[str]:
        """
        Returns a list of available CRUD actions for the current object.
        """
        actions = []
        for action in CrudAccessAction:
            try:
                self.check_access(action, self.item)
            except JsonApi403Exception:
                pass
            else:
                actions.append(action.value)
        return actions

    def update(self, item_id: str, *args, **kwargs) -> JsonApiMixin:
        """
        In protected routes, anonymous users cannot create or update items. Raises
        JsonApi403Exception if the user is anonymous (404 for an item he cannot view).
        """
        if self.inject.user.is_anonymous:
            self.set_item(item_id)
            raise JsonApi403Exception
        return super().update(item_id, *args, **kwargs)

    def create(self, *args, **kwargs) -> JsonApiMixin:
        """
        In protected routes, anonymous users cannot create or update items. Raises
        JsonApi403Exception if the user is anonymous.
        """
        # in protected routes, anonymous users cannot create or update items
        if self.inject.user.is_anonymous:
            raise JsonApi403Exception
        return super().create(*args, **kwargs)

    def destroy(self, item_id: str) -> JsonApiMixin:
        # in protected routes, anonymous users cannot create or update items
        """
        In protected routes, anonymous users cannot create or update items. Raises
        JsonApi403Exception if the user is anonymous. Explicitly checks permissions for
        deletion.
        """
        item = self.set_item(item_id)
        if self.inject.user.is_anonymous:
            raise JsonApi403Exception
        # explicitly check permissions, as the schema is not built for deletion
        self.check_access(CrudAccessAction.DELETE, item)
        return super().destroy(item_id=item_id)

    def hook_before_relationships_change(self, item, data, related_field_name, action):
        """
        The relationships endpoints: the update schema already checked the change
        permission, the core the referenced objects (`relations_access_check`).
        """
        if self.inject.user.is_anonymous:
            raise JsonApi403Exception
        super().hook_before_relationships_change(item, data, related_field_name, action)

    def hook_after_relationships_change(self, item, data, related_field_name, action):
        super().hook_after_relationships_change(item, data, related_field_name, action)
        self.check_access(CrudAccessAction.CHECK, item, item_passive=True)

    def item_update(self, item: JsonApiMixin, data: Any):
        """
        Updates the item with the given data, checking permissions for the update action.
        """
        item = super().item_update(item, data)
        self.check_access(CrudAccessAction.CHECK, item, item_passive=True)
        return item

    def item_create(self, data: Any):
        """
        Creates an item with the given data, checking permissions for the create action.
        """
        item = super().item_create(data)
        self.check_access(CrudAccessAction.CHECK, item, item_passive=True)
        return item