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
- selector `all`, `self` (the object is the one its model gives the user as a selector
  source: the user himself on a user model, `users.user.item.change.self`), `author`
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
the languages of the project: a data migration sets both
(`Role.objects.create(slug='manager', name_en='Manager', name_ru='Менеджер')`); `name`
reads the column of the active language, else the first of them in `LANGUAGES`.

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
  `for_change`, `for_delete`, `for_create`, `crud_actions`.
- Anonymous users can only read (create, update and delete are 403), within the roles
  marked `for_anonymous`.
- Selector array fields (`autogen_<field>_selectors`, GIN) are generated only for the
  forward relations to `PermitSelectorMixin` models listed in `autogen_selectors_fields`;
  many-to-many and reverse selectors do not need them.
- In custom actions check explicitly: `self.check_access(CrudAccessAction.VIEW, item)`.
- Settings: `BS_BAZIS_PERMISSION_CACHE_EXPIRE` (seconds, 7; dynamic, in the admin) and
  the deprecated `BS_BAZIS_PERMIT_RELATIONS_VIEW_CHECK` (`permit.W001`).
- Field permissions in the API: `field.view.<selector>.<field>.disable` removes the field
  from the data of the objects the selector matches; `field.change.<selector>.<field>.readonly`
  marks it `readOnly: true` in `schema_update` of the item (the attributes schema in
  `$defs`), an update ignores it (200, the value unchanged) and its relationships
  endpoints answer 403 `ERR_RELATIONSHIP_READONLY`.
- An item that exists but that the user cannot see is 403, a missing one 404.
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
- To see more objects, add a permission (another selector), not code. An override of
  `restrict_queryset` keeps the permissions and narrows them:

  ```python
  @class_or_instance_method      # bazis.core.utils.functools
  def restrict_queryset(self, qs, access_action, user=None, permit=None, **kwargs):
      qs = super().restrict_queryset(qs, access_action, user=user, permit=permit, **kwargs)
      return qs.exclude(is_archived=True)
  ```

  (the queryset of bazis-permit also carries the field groups of its objects).

## Rules

- Every route of a protected model inherits `PermitRouteBase` (`permit.W002` lists the
  JSON:API routes that do not). A route of public data declares `permit_public = True`.
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
