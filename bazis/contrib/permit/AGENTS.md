# bazis-permit — guide for AI agents

Permissions for Bazis routes: which objects a user sees and changes, which fields he sees
and writes, which objects a relation may reference. Needs bazis-users. Use it for any API
where users must not see or change everything.

## Model of permissions

User → `roles` (one active: `role_current`) → `Role.groups_permission` →
`GroupPermission.permissions` → `Permission` (a slug):

```
<app>.<model>.<level>.<operation>.<selector>[.<additional>]
entity.document.item.view.org_owner            # documents of the user's organization
entity.document.item.change.author             # documents the user is the author of
entity.meeting.item.view.participants          # meetings the user participates in (m2m)
entity.team.item.view.members                  # the team of the user (reverse of User.team)
entity.meeting.item.view.team__members         # the meetings of the user's team
entity.document.item.view.author=__selector__&is_active=true
entity.document.field.view.all.description.enable
entity.document.field.add.all.name.filter:^[A-Z]+$        # value must match
entity.parent.field.change.all.children.filter:is_active=true  # relation may reference
```

- level `item` (objects) or `field` (fields of objects);
- operations `add`, `view`, `change`, `delete`, `check` (verified on the saved item, after
  triggers filled its selectors) and custom ones;
- selector `all`, `self` (on a model that is itself a `PermitSelectorMixin`: the object
  is the one its `get_selector_for_user(user)` gives, the user himself on a user model,
  `users.user.item.change.self`; a source of several objects, a list or a queryset,
  matches each of them), `author`
  (bazis-author) or a relation linking the object to the user or his selector source
  (`org_owner`: a model that inherits `PermitSelectorMixin` and implements the classmethod
  `get_selector_for_user(user)`, returning an object or a list): a foreign key,
  a many-to-many field (`participants`) or a reverse relation by its `related_name`
  (`members` for `User.team = ForeignKey(Team, related_name='members')`, `watchers` for
  `User.teams_watched = ManyToManyField(Team, related_name='watchers')`), or a path of
  relations (`team__members`). A many-to-many or reverse selector matches the objects the
  user is one of the related objects of (an EXISTS subquery: no duplicates); it works for
  the field permissions (`field.view.participants.description.disable`), `check` and
  custom operations such as the transits of bazis-statusy
  (`item.transit.participants.<status>.<transit>`). A custom `through` model needs a unique
  constraint or index on its two foreign keys. A selector that is no such relation matches
  nothing and is logged (`Permit: ... has no selector`).

Roles for anonymous users: `Role(for_anonymous=True)`. Anonymous users never match a
selector other than `all`.

The names of `Role` and `GroupPermission` (and of the statuses and transits of
bazis-statusy) are translated fields with the columns `name_en` and `name_ru`, whatever
the languages of the project; `name` reads the column of the active language, else the
first of them in `LANGUAGES`.

## Roles in the code (`roles.py`)

The roles and permission groups of a product are declared in the `roles.py` module of an
application, not in data migrations:

```python
# support/roles.py
from django.utils.translation import gettext_lazy as _
from bazis.contrib.permit.declare import Group, Role

CLIENT = Group('tickets_client', _('Tickets of the client'), [
    'support.ticket.item.view.author.all',          # a model with statuses: .<status>
    'support.ticket.field.view.all.all.assignee.disable',
])
GROUPS = [CLIENT]
ROLES = [Role('client', _('Client'), [CLIENT])]    # groups: Group objects or slugs
```

- `migrate` applies them (`post_migrate`, also sent by `flush`) once all the migrations
  of the project are applied, in one transaction; applied again it writes nothing. The
  declared groups and roles are marked `managed`: the permissions of a managed group and
  the managed groups of a declared role are exactly the declared ones (removed from the
  code = revoked). The groups that are not declared that the admin attached to a declared
  role, and the roles and groups that are not declared, are left; a declared group the
  admin attaches to a declared role that does not list it is removed. A declared slug that
  exists unmarked is taken over with a warning in the log, and from then on synced: its
  permissions (or managed groups) that are not declared are revoked. A managed object no
  longer declared is kept (`permit.W006`) and is an ordinary object in the admin again.
  Concurrent `migrate` runs apply them one after the other (a PostgreSQL advisory lock).
- A data migration of the product runs before the declarations are applied (they are
  applied after the last migration): on a fresh database it cannot rely on the declared
  roles or groups.
- Names: English msgids (`gettext_lazy`); `name_en`/`name_ru` get the translations of the
  catalogs of the project (`manage.py bazis_messages status` lists the untranslated ones;
  `permit.W004` is removed in bazis-permit 2.11).
- The admin shows declared objects read-only (a declared role still takes groups of the
  admin) and does not delete them.
- Tests: the test database is migrated (also with `--reuse-db`: Django still runs
  `migrate` on the kept database), so the declarations are there; a test with
  `transaction=True` gets them back after the flush. `bazis_test_utils` gives
  `apply_declarations()` and the fixture `bazis_declared`, for a test that changes the
  declared rows itself.
- `bazis.contrib.permit.declare.apply_declarations(using, groups=None, roles=None,
  dry_run=False)` returns the changes; `dry_run` only lists them.
- Checks: `permit.E004` (a slug, a duplicate, a group of a role that is not declared),
  `permit.E005` (a permission: grammar, the model is a `PermitModelMixin`, the selector is
  a relation to a `PermitSelectorMixin` model, the field exists, the restriction is
  `enable`/`disable`/`readonly`/`filter:`); with a database (`bazis_doctor`
  from bazis 2.13, against the database it reaches; with an older core only
  `manage.py check --database default`) `permit.W005` (the database differs: migrate) and
  `permit.W006` (orphans). These are warnings: `migrate` runs the
  database checks before it applies the declarations.

## Setup

```python
from bazis.contrib.permit.models_abstract import (
    AnonymousUserPermitMixin, PermitModelMixin, PermitSelectorMixin, UserPermitMixin,
)
from bazis.contrib.permit.routes_abstract import PermitRouteBase

# users/models.py: the user is the source of the `author` selector (PermitSelectorMixin),
# the anonymous user gets the roles for anonymous users
class User(UserPermitMixin, PermitSelectorMixin, UuidMixin, UserAbstract, JsonApiMixin):
    pass

class AnonymousUser(AnonymousUserPermitMixin, AnonymousUserAbstract):
    pass

class Document(PermitModelMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin):
    autogen_selectors_fields = ['author']    # selector fields with GIN indexes
    ...

class DocumentRouteSet(PermitRouteBase):
    model = apps.get_model('docs.Document')
```

- `BS_INSTALLED_APPS` includes `bazis.contrib.permit`; register `bazis.contrib.permit.router`
  for the roles, groups and permissions API.
- `PermitRouteBase` filters the querysets, hides fields, builds the schemas per user, checks
  every CRUD action and the relationships endpoints, and adds the meta fields
  `for_change`, `for_delete`, `for_create`, `crud_actions`, `custom_actions` (requested
  with `?meta=`, see Custom actions).
- Anonymous users can only read (create, update and delete are 403; update and delete
  of an item they cannot view 404), within the roles marked `for_anonymous`.
- An item the user cannot view does not exist for him: the routes of an item (retrieve,
  update, delete, the relationships endpoints, `schema_retrieve`, `schema_update`, the
  transits of bazis-statusy) look the item up among the objects he views
  (`PermitRouteBase.get_queryset_for_item`, `restrict_queryset` for `view` in the same
  query) and answer the 404 of the core for a missing item, the same detail and queries;
  an item he views but cannot change or delete is 403. The read of the response after a
  write is not restricted: a create or an update that makes the item invisible is 403 and
  rolled back; a statusy transit that hides it is kept and answers 204.
- Selector array fields (`autogen_<field>_selectors`, GIN) are generated only for the
  forward relations to `PermitSelectorMixin` models listed in `autogen_selectors_fields`;
  many-to-many and reverse selectors do not need them. An array holds ids of selector
  objects that the permissions of the selector also match (a delegate of the author: the
  project fills it, or the admin); it is not in the schemas of the routes
  (`get_fields_hidden`, bazis-permit 2.11 with bazis 2.16), so the `fields` of a route do
  not exclude it and a client cannot write it.
- Custom actions (routes of kind `other` of the `http_*` decorators, see below) check the
  permission they declare (`access_action`), else are closed to anonymous users unless
  `public=True`.
- Settings: `BS_BAZIS_PERMISSION_CACHE_EXPIRE` (seconds, 7; dynamic, in the admin) and
  the deprecated `BS_BAZIS_PERMIT_RELATIONS_VIEW_CHECK` (`permit.W001`).
- Field permissions in the API: `field.view.<selector>.<field>.disable` removes the field
  from the data of the objects the selector matches; `field.change.<selector>.<field>.readonly`
  marks it `readOnly: true` in `schema_update` of the item (the attributes schema in
  `$defs`), an update ignores it (200, the value unchanged) and its relationships
  endpoints answer 403 `ERR_RELATIONSHIP_READONLY` (bazis 2.8.1; a 500 before).
  `__all__` in place of the field is every field of the schema; a restriction of the
  field itself replaces the one of `__all__` of the same kind (availability: `enable`,
  `readonly`, `disable`), and of the permissions of the user that match an object,
  `enable` wins over `readonly` and `disable`, and `readonly` over `disable`. One field writable, the others read-only (a model with statuses has the
  status segment, `client.all.__all__.readonly`):

  ```python
  'service.act.field.change.client.__all__.readonly',
  'service.act.field.change.client.confirmed.enable',
  ```
- A selector source (`client` above, `Act.client = ForeignKey(Client)`): the model
  inherits `PermitSelectorMixin` and implements the classmethod
  `get_selector_for_user(user)`; a false value (no client) makes the permission match
  nothing:

  ```python
  class Client(PermitSelectorMixin, ...):
      @classmethod
      def get_selector_for_user(cls, user):
          return user.client          # an object, a list or a queryset; None: nothing
  ```
- The users: the routes of bazis-users do not check permissions (`permit.W002` lists
  them). To restrict them, the user model also inherits `PermitModelMixin` (else
  `permit.W003`) and the project registers its own route set of it, a `PermitRouteBase`
  (`default_route = True`), instead of the router of bazis-users.
- Another route of a protected model (a projection every user sees, a calendar) may be a
  route without permissions (`UserRequiredRouteBase` of bazis-users): its list and items
  are its `get_queryset`, and the relationships, `included` and filters of the other
  routes still use `restrict_queryset` of the default route (the `PermitRouteBase`; declare
  `default_route = True` on it). `permit.W002` reports it; `permit_public = True` on the
  route only says that its data is public and silences the warning, it changes nothing
  else.
- A route that restricts its objects by a rule of its own overrides `restrict_queryset`
  (of `RestrictedQsRouteMixin`) and applies it in its `get_queryset` (the core does not
  apply it to the list and items of the route): `permit.W002` skips it (bazis-permit
  2.10), with no `permit_public`. So are the routes of bazis-uploadable (the files of the
  user) and bazis-bg (the tasks of the user) and their subclasses. The check sees only
  the override, not that `get_queryset` uses it.
- To see more objects, add a permission (another selector), not code. An override of
  `restrict_queryset` keeps the permissions and narrows them:

  ```python
  @class_or_instance_method      # bazis.core.utils.functools
  def restrict_queryset(self, qs, access_action, user=None, permit=None, **kwargs):
      qs = super().restrict_queryset(qs, access_action, user=user, permit=permit, **kwargs)
      return qs.exclude(is_archived=True)
  ```

  (the queryset of bazis-permit also carries the field groups of its objects).

## Custom actions

A custom action of a `PermitRouteBase` (a route of kind `other`: the `http_*` decorators
without `kind=`, not `http_internal`; the CRUD, relationships and schema routes check
themselves) declares who may call it (bazis-permit 2.11 with bazis 2.16). bazis-permit
checks it in `route_check`, before the action runs, in its transaction:

```python
from bazis.core.routes_abstract.initial import http_get, http_post
from bazis.core.schemas.enums import CrudAccessAction
from bazis.core.throttle import throttle

class CertificateRouteSet(PermitRouteBase):
    model = apps.get_model('training.Certificate')

    @http_get('/export/', access_action=CrudAccessAction.VIEW)     # the collection
    def action_export(self, **kwargs):
        qs = self.restrict_queryset(self.model.objects.all(), CrudAccessAction.VIEW)
        ...

    @http_post('/{item_id}/revoke/', access_action=CrudAccessAction.CHANGE)  # an item
    def action_revoke(self, item_id: str, **kwargs):
        item = self.set_item(item_id, with_lock=True)   # checked and locked already
        ...

    @http_get('/{item_id}/card/', public=False)          # any authenticated user
    def action_card(self, item_id: str, **kwargs):
        return self.set_item(item_id).title              # among the items he views

    @http_get('/verify/', public=True, dependencies=[throttle('10/minute', key='ip')])
    def action_verify(self, code: str, **kwargs):        # anyone
        ...
```

- `public=True`: anyone, also anonymous users, without a check; limited by
  `BAZIS_THROTTLE_PUBLIC` (`'30/minute'` per user or IP address, dynamic; empty:
  unlimited) unless it declares its own `throttle` (core guide). Restrict what it returns
  yourself. A public action of an item that takes its item with `set_item` still looks it
  up among the objects the (anonymous) user views.
- `access_action=CrudAccessAction.<X>` (or `StatusyAccessAction.TRANSIT`, ...): the roles
  decide, also the roles for anonymous users (`Role(for_anonymous=True)`). An action of the
  collection (no `{item_id}` in the path) needs the permission on the model (403). An action
  of an item: bazis-permit takes the item of `item_id` into `self.item` before the action
  runs (404 for an item the user cannot view) and checks the permission on it (403). For a
  method that writes (POST, PUT, PATCH, DELETE) it takes it locked (`FOR NO KEY UPDATE`,
  until the end of the request), so the permission checked (by a selector or a status of
  the item) holds while the action runs; `self.set_item(item_id, with_lock=True)` then
  returns it without another query. A GET action that needs the lock calls
  `set_item(item_id, with_lock=True)` (the item is read again, locked; the permission was
  checked before the action on the unlocked item, so a GET action must not rely on a
  permission that depends on fields another request may change meanwhile). The core `/_id/` route declares `access_action=view`: open as `GET /`.
- Neither (or `public=False`): authenticated users only, anonymous ones get 403
  `ERR_FORBIDDEN` (as on a create or an update), whatever their roles. Without a
  declaration `permit.W007` warns, for an action of the collection and of an item: declare
  `access_action`, or `public=False` when any authenticated user may call it (an action of
  an item that takes its item with `set_item` only among the items he views). Check any
  other operation explicitly: `self.check_access(CrudAccessAction.CHANGE, item)` (403).
- An override that does not repeat `public`/`access_action` keeps those of the route it
  overrides (as `kind`); `route_declare(route, public=True)` (core) changes them on an
  inherited route without repeating its decorator. `x-bazis` in OpenAPI shows `public`
  (always) and `access_action` (when declared).
- **Which actions the user may call** (to show the buttons of a client): the meta field
  `custom_actions` (bazis-permit 2.11), requested with `?meta=custom_actions` (with
  others: `?meta=crud_actions,custom_actions`), lists the names of the actions (`action`
  of `x-bazis` in OpenAPI, e.g. `action_revoke`) the user may call by the rule above
  (`PermitRouteBase.action_allowed`, the one `route_check` enforces): on an item (retrieve,
  and the response of a create, an update or a transit) the actions of an item on this
  item, on a list the actions of the collection; only the routes the route set registers
  (`actions`/`actions_exclude`). A check the action makes in its own code (the transits
  of bazis-statusy: `state_actions`) is not part of it. Do not write a meta field of your
  own for it.

  ```
  GET /api/v1/training/certificate/<id>/?meta=crud_actions,custom_actions
  "meta": {"crud_actions": ["view", "change"], "custom_actions": ["action_card", "action_revoke"]}
  GET /api/v1/training/certificate/?meta=custom_actions
  "meta": {"custom_actions": ["action_export", "action_list_id", "action_verify"]}
  ```
- **An operation of its own** (a permission no CRUD operation expresses: export the
  participants, revoke): a subclass of `AccessAction` (core) whose value is the operation
  of the permission slug. Any operation name is valid in a slug; a model with statuses has
  the status segment after the selector, as for the CRUD operations:

  ```python
  # training/access.py
  from bazis.core.schemas.enums import AccessAction

  class CertificateAccessAction(AccessAction):
      REPORT = 'report'        # training.certificate.item.report.<selector>[.<status>]

  # training/routes.py
  @http_post('/{item_id}/report/', access_action=CertificateAccessAction.REPORT)
  def action_report(self, item_id: str, **kwargs): ...

  # training/roles.py: the roles that may call it
  'training.certificate.item.report.author',
  ```

  Check it in code with `self.check_access(CertificateAccessAction.REPORT, item)` (403).

## Rules

- Every route of a protected model inherits `PermitRouteBase` or restricts its objects
  with its own `restrict_queryset` (`permit.W002` lists the JSON:API routes that do
  neither). Only a route of public data declares `permit_public = True`.
- Every custom action declares `access_action` or `public` (`permit.W007`); an action open
  to anonymous users is `public=True`, and an action closed to them needs no check of
  `is_anonymous` in its code.
- The model of a `PermitRouteBase` route is a `PermitModelMixin` (a `PermitStructMixin`):
  with another model the route and the relations into it fail with `AttributeError` as
  soon as the user has a permission on the model (`permit.W003`, a warning).
- The core (Bazis 2.7) lets an item reference only the objects the user can view (a
  reverse relation: link and unlink only the objects he can change), and `included` shows
  only the objects he can view, by `restrict_queryset` of the default route of the related
  model (`PermitRouteBase` for a protected model). Do not check the related objects
  yourself; `relation_targets_check = False` turns it off for a route. A route without a
  user (not a `UserRouteBase`) is checked as for an anonymous user unless the request user
  is in `UserMixin.CTX_USER_REQUEST`.
- `BS_BAZIS_PERMIT_RELATIONS_VIEW_CHECK` and `relations_view_check` are deprecated (no
  effect; `relations_view_check = False` works as `relation_targets_check = False`) and
  will be removed in 3.0; `permit.W001` reports the setting.
- Override `restrict_queryset(qs, access_action, user=None, permit=None, **kwargs)` with
  `**kwargs`: the core calls it on the class.
- With Bazis 2.9 the `filter`, `sort` and `search` of a request reach only the fields the
  field permissions show the user: `PermitRouteBase.query_fields(user=None, **kwargs)` is
  the union of the fields of the field groups the objects match (all the fields if an
  object can match none: it has no field permissions). A field hidden in every object is
  400 `ERR_FILTER`; a field shown in only some objects stays filterable, sortable and
  searchable in all of them, so hide it in the route `fields` if its values must not be
  found by trial. The internal conditions of the
  permissions (`QueryToOrm` of selectors, `filter:` restrictions) are not restricted.
- Permissions are cached per user for `BAZIS_PERMISSION_CACHE_EXPIRE` seconds and
  invalidated when roles, groups or permissions change through the ORM (`save`, `delete`,
  m2m); `QuerySet.update()` and `bulk_create()` do not invalidate the cache.
