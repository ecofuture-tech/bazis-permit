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
entity.document.item.view.author=__selector__&is_active=true
entity.document.field.view.all.description.enable
entity.document.field.add.all.name.filter:^[A-Z]+$        # value must match
entity.parent.field.change.all.children.filter:is_active=true  # relation may reference
```

- level `item` (objects) or `field` (fields of objects);
- operations `add`, `view`, `change`, `delete`, `check` (verified on the saved item, after
  triggers filled its selectors) and custom ones;
- selector `all`, `author` (bazis-author) or a field linking the object to the user
  (`org_owner`, through a `PermitSelectorMixin` model with `get_selector_for_user`).

Roles for anonymous users: `Role(for_anonymous=True)`. Anonymous users never match a
selector other than `all`.

## Setup

```python
from bazis.contrib.permit.models_abstract import PermitModelMixin, UserPermitMixin
from bazis.contrib.permit.routes_abstract import PermitRouteBase

class User(UserPermitMixin, UserAbstract, DtMixin, UuidMixin, JsonApiMixin): ...

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
- In custom actions check explicitly: `self.check_access(CrudAccessAction.VIEW, item)`.

## Rules

- Every route of a protected model inherits `PermitRouteBase` (`permit.W002` lists the
  JSON:API routes that do not). A route of public data declares `permit_public = True`.
- Enable `BS_BAZIS_PERMIT_RELATIONS_VIEW_CHECK=true` (`permit.W001`): otherwise an item can
  reference objects the user cannot see, and a reverse relation can unlink objects the user
  cannot change.
- Permissions are cached per user for `BAZIS_PERMISSION_CACHE_EXPIRE` seconds and
  invalidated when roles, groups or permissions change through the ORM (`save`, `delete`,
  m2m); `QuerySet.update()` and `bulk_create()` do not invalidate the cache.
