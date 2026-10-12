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

from django.db.models import Case, ExpressionWrapper, IntegerField, QuerySet, Value, When
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from fastapi import Depends

from pydantic import BaseModel

from bazis.contrib.users import get_anonymous_user_model, get_user_model
from bazis.contrib.users.models_abstract import UserMixin
from bazis.contrib.users.routes_abstract import UserRouteBase
from bazis.core.errors import JsonApi403Exception
from bazis.core.models_abstract import JsonApiMixin
from bazis.core.routes_abstract.context import RouteContext
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
from bazis.core.schemas.enums import HttpMethod, RouteKind
from bazis.core.services.includes import include_to_list
from bazis.core.utils.functools import class_or_instance_method
from bazis.core.utils.orm import apply_calc_queryset
from bazis.core.utils.query_complex import QueryToOrm

from .services import PermitService
from .utils import is_model_permit


User = get_user_model()
AnonymousUser = get_anonymous_user_model()

logger = logging.getLogger(__name__)


#: the HTTP methods of the actions that write: their item is checked locked
WRITE_METHODS = frozenset({HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE})


def route_is_action(route_ctx: RouteContext) -> bool:
    """
    A custom action: a route of kind `other` (the CRUD, relationships and schema routes
    check the permissions themselves), not the internal route (`http_internal`).
    """
    return (
        (route_ctx.kind or RouteKind.OTHER) is RouteKind.OTHER
        and route_ctx.http_method != HttpMethod.INTERNAL
    )


def route_is_item(route_ctx: RouteContext) -> bool:
    """
    A route of an item: `{item_id}` in its path.
    """
    return '{item_id}' in route_ctx.route_params.path


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


#: the most conditional field groups of the user for a model whose combinations a list tells
#: apart (2 ** N schemas of its objects); with more, every object of the list has the fields
#: shown in all of them (`fields_shown_everywhere`, as `query_fields`)
FIELD_GROUPS_COMBINED_MAX = 4

#: the `_schema_key` of the first member of the schema of a list, the union of the fields of
#: its other members (the columns a client shows): no object has it
SCHEMA_KEY_UNION = -1


def field_groups_split(handler) -> tuple[list[dict], list[tuple[list[dict], Any]]]:
    """
    The field groups of a permission handler (`perms_field_groups`): the values of those
    without a condition (every object matches them) and the conditional groups in a stable
    order (by the hash of the condition, not by the ids of the permissions), so that the
    bits of a combination (`field_groups_combination`) are the same in the query of a list
    (`restrict_queryset`) and in its schema (`build_schema_list`).
    """
    unconditional = []
    conditional = []
    for values, cond in handler.perms_field_groups:
        if cond:
            conditional.append((values, cond))
        else:
            unconditional.extend(values)
    conditional.sort(key=lambda it: hash(it[1]))
    return unconditional, conditional


def field_groups_combination(unconditional, conditional, mask: int) -> list[dict]:
    """
    The field permissions of an object that matches the conditional groups of the bits of
    `mask` (and no other): those without a condition and those of these groups.
    """
    values = list(unconditional)
    for bit, (group_values, __) in enumerate(conditional):
        if mask & (1 << bit):
            values.extend(group_values)
    return values


def field_groups_reachable(handler, conditional) -> list[int]:
    """
    The combinations (masks) of the conditional field groups that an object the user views
    may match. An object he views matches a condition of his view permissions
    (`perms_item`): when each of these conditions is the condition of a conditional field
    group (the same selector and status, `item.view.all.open` and
    `field.view.all.open.…`), a combination without any of these groups is matched by no
    object he views (a role for anonymous users does not see the fields of the other
    statuses). The conditions are compared as they are, not by what they imply: a view
    permission whose condition is no field group's (or none) leaves every combination.
    """
    bits = {hash(cond): bit for bit, (__, cond) in enumerate(conditional)}
    required = 0
    for __, cond in handler.perms_item:
        if not cond or (bit := bits.get(hash(cond))) is None:
            return list(range(1 << len(conditional)))
        required |= 1 << bit
    return [mask for mask in range(1 << len(conditional)) if mask & required]


def fields_shown_everywhere(factory, handler) -> list['SchemaField']:
    """
    The fields of the schema factory that the field permissions of the handler show in every
    object: shown by the groups without a condition alone and with each conditional one. A
    restriction that shows a field wins over one that hides it, so a combination of
    conditional groups hides a field only if one of them does.
    """
    unconditional, conditional = field_groups_split(handler)

    def shown(values: list[dict]) -> set[str]:
        return {f.name for f in factory.fields_patch(fields_restricts_collect(values))}

    names = shown(unconditional)
    for values, __ in conditional:
        names &= shown([*unconditional, *values])
    return [f for f in factory.fields_list if f.name in names]


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
        self.permit_service = route_cls.permit_service_for(user)
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
        The schema of a list: a resource schema for each combination of the conditional
        field groups an object the user views may match (`_schema_key`, the bits of the
        combination set by `restrict_queryset`; `field_groups_reachable`), with the field
        permissions of the groups without a condition and of the groups of the combination,
        as the card of the object. Over `FIELD_GROUPS_COMBINED_MAX` conditional groups, and
        for an object without `_schema_key`, the fields shown in every object
        (`fields_shown_everywhere`). The first member is the union of the fields of the
        others (`SCHEMA_KEY_UNION`, no object has it): a client takes its columns from it.
        """
        helper = self.get_helper(CrudApiAction.LIST)
        factory = helper.schema_factory
        unconditional, conditional = field_groups_split(helper.permit_handler)

        variants = {None: fields_shown_everywhere(factory, helper.permit_handler)}
        if len(conditional) <= FIELD_GROUPS_COMBINED_MAX:
            for mask in field_groups_reachable(helper.permit_handler, conditional):
                values = field_groups_combination(unconditional, conditional, mask)
                variants[mask] = factory.fields_patch(fields_restricts_collect(values))
        names = {f.name for fields in variants.values() for f in fields}
        variants = {SCHEMA_KEY_UNION: [f for f in factory.fields_list if f.name in names]} | variants

        schema_resources = [
            SchemaResourceBuilder(factory, fields=fields).build(
                _schema_key=key, is_response_schema=self.is_response_schema
            )
            for key, fields in variants.items()
        ]
        return helper.build_schema(
            inclusions=[], schema_resource=reduce(lambda it, res: it | res, schema_resources)
        )

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
    #: the class of `schemas` and `schemas_responses`
    schemas_class: type[SchemasPermit] = SchemasPermit
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
            # a list of its own, as the core makes it: the inherited one belongs to the parent
            cls.actions_exclude = list(
                dict.fromkeys(
                    [*(cls.actions_exclude or []), 'action_schema_create', 'action_schema_update']
                )
            )

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
        Creates the schemas of the route (`schemas_class`) for the user of the request.
        """

        def get_item():
            """
            Helper function to get the current item or model for schema creation.
            """
            return self.item or self.model

        self.schemas = self.schemas_class(
            type(self), self.inject.user, get_item, getattr(self.inject, 'include', [])
        )
        self.schemas_responses = self.schemas_class(
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

    def route_check(self, *args, **kwargs):
        """
        Who may call a custom action (`route_is_action`), before it runs: a `public=True`
        action anyone; with `access_action` the roles decide (also those for anonymous
        users), on the model for an action of the collection, on the item for an action of
        an item, taken here into `self.item` (404 for an item the user cannot view, 403
        without the permission), locked until the end of the request for a method that
        writes (POST, PUT, PATCH, DELETE: the permission checked holds while the action
        runs); with neither only an authenticated user (403, as a create or an update).
        """
        super().route_check(*args, **kwargs)
        route_ctx = self.route_ctx
        if not route_is_action(route_ctx) or route_ctx.public:
            return
        target = self.model
        if route_ctx.access_action is not None and route_is_item(route_ctx):
            target = self.set_item(
                kwargs['item_id'], with_lock=route_ctx.http_method in WRITE_METHODS
            )
        if not self.action_allowed(route_ctx, target):
            raise JsonApi403Exception

    def action_allowed(
        self, route_ctx: RouteContext, item_or_model: JsonApiMixin | type[JsonApiMixin]
    ) -> bool:
        """
        Whether the user may call the custom action `route_ctx` on `item_or_model` (the
        item of an action of an item, the model of an action of the collection) by what it
        declares: `public=True` anyone, `access_action` the roles, neither an authenticated
        user. The rule `route_check` enforces and the meta field `custom_actions` reports;
        a check the action makes in its own code is not part of it.
        """
        if route_ctx.public:
            return True
        if route_ctx.access_action is None:
            return not self.inject.user.is_anonymous
        return self.inject.permit.handler(route_ctx.access_action, item_or_model).check_access()

    def get_queryset_for_item(self, item_id: str, with_lock: bool = False):
        """
        The item of a route of an item (retrieve, update, delete, the relationships and the
        schema routes, the transits of bazis-statusy, custom actions using `set_item` or
        `get_item`) is looked up among the objects the user can view, in the same query: an
        item he cannot view is not found, the same 404 as a missing one (same detail, same
        queries); the routes answer 403 for an item he views but cannot change. A lookup of
        the item the route already holds (the read of the response after a create, an
        update or a transit) is not restricted again: the response of a create or an update
        refuses an item the write made invisible with 403 (rolled back), as the schema of the
        response requires the view permission; a statusy transit answers 204 instead.
        """
        qs = super().get_queryset_for_item(item_id, with_lock)
        # (the core has checked that the id can be a key)
        if self.item is not None and self.item.pk == self.model._meta.pk.to_python(item_id):
            return qs
        visible = self.restrict_queryset(self.model.objects.all(), CrudAccessAction.VIEW)
        # a subquery: the lock of the query (FOR NO KEY UPDATE) stays on the item alone
        return qs.filter(pk__in=visible.values('pk'))

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
        every object (the filter, the sorting and the search of a request start with them,
        also through a relation into the objects of the model; a field shown in only some
        objects would tell its values in the others by trial), none if the user cannot have
        the roles of bazis-permit. An object has the field permissions of every field group
        it matches (`perms_field_groups`): those without a condition and any of the others,
        so a field must be shown by those without a condition alone and with each of the
        others. A restriction that shows a field wins over one that hides it, so a
        combination of conditional groups hides a field only if one of them does. The
        conditions are not compared with those of `item.view`: a field hidden only in the
        objects the user cannot see is not reachable either. Which objects are reached is
        decided by `restrict_queryset`.
        """
        if (permit := cls._permit_service_on_class(user)) is None:
            return []
        handler = permit.handler(CrudApiAction.LIST.access_action, cls.model)
        factory = cls.schema_factories.get(CrudApiAction.LIST) or cls.build_schema_factory(
            CrudApiAction.LIST
        )
        return fields_shown_everywhere(factory, handler)

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

        # "add": the objects that exist are not restricted by it; the selector and the status
        # of the permissions are checked on the created item (`hook_after_create`)
        if access_action == CrudAccessAction.ADD:
            return qs

        # the schema of each object in a list: the combination of the conditional field
        # groups it matches, one bit per group (`build_schema_list`); None over the limit
        __, conditional = field_groups_split(permit_handler)
        schema_key = Value(None if len(conditional) > FIELD_GROUPS_COMBINED_MAX else 0)
        if len(conditional) <= FIELD_GROUPS_COMBINED_MAX:
            for bit, (__, cond) in enumerate(conditional):
                q_orm = QueryToOrm(cond, qs.model)
                if q_orm.fields_calc:
                    qs = apply_calc_queryset(qs, q_orm.fields_calc)
                schema_key = schema_key + Case(
                    When(q_orm.q or Value(True), then=Value(1 << bit)), default=Value(0)
                )
        qs = qs.annotate(
            _schema_key=ExpressionWrapper(schema_key, output_field=IntegerField(null=True))
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
        Whether the user may create an item: he has an `item.add` permission on the model,
        whatever its selector and status (the created item is checked against them,
        `hook_after_create`), so a create may still be refused.
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

    @meta_field([CrudApiAction.LIST, CrudApiAction.RETRIEVE], title=_('Available custom actions'))
    def custom_actions(self) -> list[str]:
        """
        The custom actions the user may call (`action_allowed`), by their names (`action` of
        `x-bazis` in OpenAPI): on an item those of an item (`{item_id}` in the path) on this
        item, on a list those of the collection. Only the actions the route registered.
        """
        item_scope = self.item is not None
        return [
            name
            for name, route_ctx in type(self).routes_ctx.items()
            if route_ctx.route is not None
            and route_is_action(route_ctx)
            and route_is_item(route_ctx) == item_scope
            and self.action_allowed(route_ctx, self.item if item_scope else self.model)
        ]

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

    def hook_after_create(self, item: JsonApiMixin):
        """
        The created item, also an included one, must match an `item.add` permission of the
        user on its model: its selector and, on a model with statuses, its status (the
        status segment is literal: `item.add.all.draft` creates only in `draft`), evaluated
        on the saved row with its to-many relations and the values the server filled
        (`author`), before the after-create effects of the route: an override calls
        `super()` first, so an automatic transit it makes comes after the check. A create
        whose item matches none is 403 `ERR_FORBIDDEN`, the request rolled back. Each item
        is checked right after its own insert (the main item, then the included ones in the
        order of the document): a selector that only an item created later in the request
        would satisfy refuses the create (too strict, never a bypass). An included item of
        another model is checked by the permission service of its default route, or by the
        one of this route when that route is no `PermitRouteBase` (this service built its
        create schema). A permission without a condition allows every item, without a query.
        """
        super().hook_after_create(item)
        model = type(item)
        if not issubclass(model, self.model) and is_model_permit(model):
            permit = model.get_default_route().permit_service_for(self.inject.user)
        else:
            permit = self.inject.permit
        handler = permit.handler(CrudAccessAction.ADD, item)
        if any(not cond for __, cond in handler.perms_item):
            return
        if not handler.check_access():
            raise JsonApi403Exception()

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