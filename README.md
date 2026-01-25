# Bazis Permit

[![PyPI version](https://img.shields.io/pypi/v/bazis-permit.svg)](https://pypi.org/project/bazis-permit/)
[![Python Versions](https://img.shields.io/pypi/pyversions/bazis-permit.svg)](https://pypi.org/project/bazis-permit/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

An extension package for Bazis that provides a flexible and powerful permission management system with support for roles, permission groups, and granular access control at object and field levels.

## Quick Start

```bash
# Install the package
uv add bazis-permit

# Create a model with permissions
from bazis.contrib.permit.models_abstract import PermitModelMixin, PermitSelectorMixin
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin
from django.db import models

class Organization(PermitSelectorMixin, DtMixin, UuidMixin, JsonApiMixin):
    """Organization - selector source"""
    name = models.CharField(max_length=255)
    
    @classmethod
    def get_selector_for_user(cls, user):
        return user.organization

class Document(PermitModelMixin, DtMixin, UuidMixin, JsonApiMixin):
    """Document with access control"""
    title = models.CharField(max_length=255)
    org_owner = models.ForeignKey(Organization, on_delete=models.CASCADE)

# Create a route with permission checking
from bazis.contrib.permit.routes_abstract import PermitRouteBase
from django.apps import apps

class DocumentRouteSet(PermitRouteBase):
    model = apps.get_model('myapp.Document')
```

## Table of Contents

- [Description](#description)
- [Requirements](#requirements)
- [Installation](#installation)
- [Core Concepts](#core-concepts)
  - [Permission System Levels](#permission-system-levels)
  - [Permission Format](#permission-format)
  - [Selectors](#selectors)
- [Usage](#usage)
  - [Creating Models](#creating-models)
  - [Creating Permissions](#creating-permissions)
  - [Creating Roles](#creating-roles)
  - [Creating Routes](#creating-routes)
  - [Access Checking](#access-checking)
- [Examples](#examples)
- [License](#license)
- [Links](#links)

## Description

**Bazis Permit** is an extension package for the Bazis framework that provides a comprehensive permission management system. The package includes:

- **Role-based model** — users have roles, roles contain permission groups
- **Granular control** — permissions at object and field levels
- **Selectors** — flexible system for linking permissions with objects
- **Automatic checking** — built-in permission verification in routes
- **Dynamic schemas** — JSON:API schemas adapt to user permissions
- **Caching** — efficient permission caching for improved performance
- **Field filtering** — visibility restrictions for fields based on permissions

**This package requires installation of `bazis` and `bazis-users` packages.**

## Requirements

- **Python**: 3.12+
- **bazis**: latest version
- **bazis-users**: latest version
- **PostgreSQL**: 12+
- **Redis**: For caching

## Installation

### Using uv (recommended)

```bash
uv add bazis-permit
```

### Using pip

```bash
pip install bazis-permit
```

## Core Concepts

### Permission System Levels

The permission system has the following hierarchy:

```
User
  └─ role_current (Current role)
       └─ Role
            └─ groups_permission (Permission groups)
                 └─ GroupPermission
                      └─ permissions
                           └─ Permission
```

#### 1. Permission

The simplest structure, represented as a string in a special format.

**Model**: `bazis.contrib.permit.models.Permission`

**Examples**:
```
entity.document.item.view.org_owner
entity.document.item.change.author
entity.document.field.view.all.description.enable
```

#### 2. GroupPermission

A set of permissions grouped by some criterion.

**Model**: `bazis.contrib.permit.models.GroupPermission`

**Example**:
```python
from bazis.contrib.permit.models import GroupPermission, Permission

# Create a permission group for document management
group = GroupPermission.objects.create(
    slug='document_manager',
    name='Document Manager'
)

# Add permissions to the group
group.permissions.add(
    Permission.objects.get_or_create(slug='entity.document.item.add.all')[0],
    Permission.objects.get_or_create(slug='entity.document.item.view.all')[0],
    Permission.objects.get_or_create(slug='entity.document.item.change.author')[0],
)
```

#### 3. Role

A role includes multiple permission groups.

**Model**: `bazis.contrib.permit.models.Role`

**Example**:
```python
from bazis.contrib.permit.models import Role

# Create a role
role = Role.objects.create(
    slug='manager',
    name='Manager',
    for_anonymous=False  # Not available for anonymous users
)

# Add permission groups
role.groups_permission.add(
    document_group,
    report_group
)
```

#### 4. User

A user can have multiple roles, but only one role is active.

**Model**: Must inherit from `bazis.contrib.permit.models_abstract.UserPermitMixin`

**Example**:
```python
from bazis.contrib.permit.models_abstract import UserPermitMixin
from bazis.contrib.users.models_abstract import UserAbstract
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin

class User(UserPermitMixin, UserAbstract, DtMixin, UuidMixin, JsonApiMixin):
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

# Assign a role to the user
user.roles.add(manager_role)
user.role_current = manager_role
user.save()
```

### Permission Format

General permission format:

```
LABEL_APP.LABEL_MODEL.PERM_LEVEL.PERM_OPERATION.SELECTOR[.ADDITIONAL]+
```

**Components**:

#### LABEL_APP.LABEL_MODEL

Full model label including the app label.

**Examples**:
- `entity.document`
- `organization.organization`
- `facility.facility`

#### PERM_LEVEL

Permission level:

- **item** — object level
- **field** — object field level (bounded context)

#### PERM_OPERATION

Operation to which the permission applies.

**Basic operations** (`CrudAccessAction`):
- `add` — create
- `view` — read/view
- `change` — update
- `delete` — delete
- `check` — check (used for validation after create/update)

**Custom operation example**:
```python
from bazis.core.schemas import AccessAction

class CustomAccessAction(AccessAction):
    APPROVE = 'approve'  # Approve
    REJECT = 'reject'    # Reject
```

#### SELECTOR

Name of a field in the model whose value links the permission with an object.

**Special selectors**:
- `all` — permission applies to all objects
- `author` — permission applies to objects where the user is the author
- `org_owner` — permission applies to objects of the user's organization

#### ADDITIONAL

Additional parameters to refine the permission.

**Examples**:

1. **Field conditions**:
```
entity.document.item.view.author=__selector__&is_active=true
```
View documents where author = current user AND is_active = true

2. **Field-level restrictions**:
```
entity.document.field.view.all.description.enable
```
Enable visibility of the description field for all

```
entity.document.field.view.author=__selector__&is_active=true.__all__.disable
```
Disable all fields for author's documents with is_active=true

3. **Value filters**:
```
entity.document.field.add.all.name.filter:^[A-Z]+$
```
The name field must match the regex when creating

```
entity.parent.field.change.all.child_entities.filter:child_is_active=true
```
Only items with child_is_active=true can be added to child_entities

### Selectors

Selectors allow linking permissions with specific objects through field values.

#### Creating a Selector Source

```python
from bazis.contrib.permit.models_abstract import PermitSelectorMixin
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin
from django.db import models

class Organization(PermitSelectorMixin, DtMixin, UuidMixin, JsonApiMixin):
    """Organization - selector source"""
    name = models.CharField(max_length=255)
    
    @classmethod
    def get_selector_for_user(cls, user):
        """
        Links user with organization.
        Assumes User has an organization field.
        """
        return user.organization
    
    class Meta:
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'
```

#### Using Selector in a Model

```python
from bazis.contrib.permit.models_abstract import PermitModelMixin

class Document(PermitModelMixin, DtMixin, UuidMixin, JsonApiMixin):
    """Document with access control"""
    title = models.CharField(max_length=255)
    content = models.TextField()
    org_owner = models.ForeignKey(
        Organization,
        verbose_name='Owner Organization',
        on_delete=models.CASCADE
    )
    
    class Meta:
        verbose_name = 'Document'
        verbose_name_plural = 'Documents'
```

#### Creating a Permission with Selector

```
entity.document.item.view.org_owner
```

**Meaning**: User can view documents where `org_owner` equals `user.organization`

## Usage

### Creating Models

#### Selector Source Model

```python
from bazis.contrib.permit.models_abstract import PermitSelectorMixin
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin
from django.db import models

class Organization(PermitSelectorMixin, DtMixin, UuidMixin, JsonApiMixin):
    name = models.CharField('Name', max_length=255)
    
    @classmethod
    def get_selector_for_user(cls, user):
        return user.organization
    
    class Meta:
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'
```

#### Model with Access Control

```python
from bazis.contrib.permit.models_abstract import PermitModelMixin
from bazis.contrib.author.models_abstract import AuthorMixin
from bazis.core.models_abstract import DtMixin, UuidMixin, JsonApiMixin
from django.db import models

class ParentEntity(PermitModelMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin):
    """Parent entity with permissions"""
    # Specify fields for automatic selector generation
    autogen_selectors_fields = ['author']
    
    name = models.CharField('Name', max_length=255)
    description = models.TextField('Description', blank=True)
    is_active = models.BooleanField('Active', default=True)
    price = models.DecimalField('Price', max_digits=10, decimal_places=2)
    
    class Meta:
        verbose_name = 'Parent Entity'
        verbose_name_plural = 'Parent Entities'
```

**Selector Auto-generation**:

`autogen_selectors_fields` — list of fields for which selector fields with GIN indexes will be automatically created. If `None` — auto-generation is disabled.

### Creating Permissions

```python
from bazis.contrib.permit.models import Permission, GroupPermission

# Permissions for ParentEntity
parent_entity_perms = [
    'entity.parent_entity.item.add.all',           # Everyone can create
    'entity.parent_entity.item.view.author',       # Author can view
    'entity.parent_entity.item.change.author',     # Author can edit
]

# Create permission group
group = GroupPermission.objects.create(
    slug='parent_entity_group',
    name='Parent Entity Permissions'
)

for perm_slug in parent_entity_perms:
    perm, created = Permission.objects.get_or_create(slug=perm_slug)
    group.permissions.add(perm)
```

### Creating Roles

```python
from bazis.contrib.permit.models import Role

# Create manager role
manager_role = Role.objects.create(
    slug='manager',
    name='Manager',
    for_anonymous=False
)

# Add permission groups to role
manager_role.groups_permission.add(
    parent_entity_group,
    child_entity_group,
    document_group
)

# Assign role to user
user.roles.add(manager_role)
user.role_current = manager_role
user.save()
```

### Creating Routes

```python
from bazis.contrib.permit.routes_abstract import PermitRouteBase
from bazis.contrib.author.routes_abstract import AuthorRouteBase
from bazis.core.schemas import SchemaFields
from django.apps import apps

class ParentEntityRouteSet(PermitRouteBase, AuthorRouteBase):
    """Route with automatic permission checking"""
    model = apps.get_model('entity.ParentEntity')
    
    fields = {
        None: SchemaFields(
            include={
                'extended_entity': None,
                'dependent_entities': None,
            },
        ),
    }
```

**What PermitRouteBase provides**:

1. **Automatic permission checking** for every CRUD action
2. **Dynamic schemas** — fields are automatically hidden/shown based on permissions
3. **QuerySet filtering** — user sees only objects they have access to
4. **Meta-fields**:
   - `for_change` — list of IDs available for editing
   - `for_delete` — list of IDs available for deletion
   - `for_create` — create availability
   - `crud_actions` — list of available actions for the object

### Access Checking

#### Automatic Checking

In routes inheriting from `PermitRouteBase`, access checking happens automatically when accessing `self.schemas`.

#### Manual Checking in Custom Actions

```python
from bazis.core.schemas import CrudAccessAction
from django.apps import apps

class DocumentRouteSet(PermitRouteBase):
    model = apps.get_model('myapp.Document')
    
    @http_post('/{item_id}/sign/')
    def action_sign(self, item_id: str):
        """Sign document"""
        document = self.set_item(item_id)
        
        # Check: can user view the document
        self.check_access(CrudAccessAction.VIEW, document)
        
        # Check: can user create signature
        self.check_access(
            CrudAccessAction.ADD,
            apps.get_model('document.Signature')
        )
        
        # Signing logic
        signature = Signature.objects.create(
            document=document,
            user=self.inject.user
        )
        
        return {'status': 'signed', 'signature_id': str(signature.id)}
```

## Examples

### Example 1: Basic Permission Setup

```python
from bazis.contrib.permit.models import Permission, GroupPermission, Role

# Create permissions
permissions = {
    'document_add': 'myapp.document.item.add.all',
    'document_view_own': 'myapp.document.item.view.author',
    'document_view_org': 'myapp.document.item.view.org_owner',
    'document_change_own': 'myapp.document.item.change.author',
    'document_delete_own': 'myapp.document.item.delete.author',
}

# Create group for regular users
user_group = GroupPermission.objects.create(
    slug='document_user',
    name='Document User'
)

for perm_slug in ['document_add', 'document_view_own', 'document_change_own']:
    perm, _ = Permission.objects.get_or_create(slug=permissions[perm_slug])
    user_group.permissions.add(perm)

# Create group for administrators
admin_group = GroupPermission.objects.create(
    slug='document_admin',
    name='Document Administrator'
)

for perm_slug in permissions.values():
    perm, _ = Permission.objects.get_or_create(slug=perm_slug)
    admin_group.permissions.add(perm)

# Create roles
user_role = Role.objects.create(slug='user', name='User')
user_role.groups_permission.add(user_group)

admin_role = Role.objects.create(slug='admin', name='Administrator')
admin_role.groups_permission.add(admin_group)
```

### Example 2: Complex Permissions with Conditions

```python
# Permissions with field conditions
complex_perms = [
    # Can only create with name "Test name"
    'entity.parent_entity.item.check.author=__selector__&name=Test name',
    
    # Can view own objects
    'entity.parent_entity.item.view.author=__selector__',
    
    # Can edit only inactive own objects
    'entity.parent_entity.item.change.author=__selector__&is_active=false',
    
    # Description field visible only for active own objects
    'entity.parent_entity.field.view.author=__selector__&is_active=true.description.enable',
    
    # All other fields hidden for active own objects
    'entity.parent_entity.field.view.author=__selector__&is_active=true.__all__.disable',
    
    # Description field hidden for inactive own objects
    'entity.parent_entity.field.view.author=__selector__&is_active=false.description.disable',
]

group = GroupPermission.objects.create(
    slug='complex_permissions',
    name='Complex Permissions'
)

for perm_slug in complex_perms:
    perm, _ = Permission.objects.get_or_create(slug=perm_slug)
    group.permissions.add(perm)
```

### Example 3: Field Filters

```python
# Field value filters
field_filter_perms = [
    # child_name field must match regex when creating
    'entity.child_entity.field.add.all.child_name.filter:^[A-Z]+$',
    
    # Only active items can be added to child_entities
    'entity.parent_entity.field.add.all.child_entities.filter:child_is_active=true',
    
    # child_name must match regex when changing
    'entity.child_entity.field.change.all.child_name.filter:^[A-Z]+$',
    
    # Only active items can be added to child_entities when changing
    'entity.parent_entity.field.change.all.child_entities.filter:child_is_active=true',
    
    # Only active parents can be set in parent_entity
    'entity.dependent_entity.field.add.all.parent_entity.filter:is_active=true',
    'entity.dependent_entity.field.change.all.parent_entity.filter:is_active=true',
]

group = GroupPermission.objects.create(
    slug='field_filters',
    name='Field Filters'
)

for perm_slug in field_filter_perms:
    perm, _ = Permission.objects.get_or_create(slug=perm_slug)
    group.permissions.add(perm)
```

### Example 4: Access Checking in Tests

```python
import pytest
from bazis.contrib.permit.models import Permission, GroupPermission, Role
from bazis.contrib.users import get_user_model

User = get_user_model()

@pytest.mark.django_db
def test_permissions(sample_app):
    # Create users
    user_1 = User.objects.create_user('user1', email='user1@example.com', password='pass')
    user_2 = User.objects.create_user('user2', email='user2@example.com', password='pass')
    
    # Create permission group
    group = GroupPermission.objects.create(slug='test_group', name='Test Group')
    group.permissions.add(
        Permission.objects.get_or_create(slug='entity.document.item.add.all')[0],
        Permission.objects.get_or_create(slug='entity.document.item.view.author')[0],
        Permission.objects.get_or_create(slug='entity.document.item.change.author')[0],
    )
    
    # Create role and assign to user
    role = Role.objects.create(slug='user_role', name='User Role')
    role.groups_permission.add(group)
    user_1.roles.add(role)
    user_1.role_current = role
    user_1.save()
    
    # user_1 can create documents
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/documents/document/',
        json_data={
            'data': {
                'type': 'myapp.document',
                'bs:action': 'add',
                'attributes': {'title': 'New Document'}
            }
        }
    )
    assert response.status_code == 201
    doc_id = response.json()['data']['id']
    
    # user_1 can view their own document
    response = get_api_client(sample_app, user_1.jwt_build()).get(
        f'/api/v1/documents/document/{doc_id}/'
    )
    assert response.status_code == 200
    
    # user_2 cannot view another user's document
    response = get_api_client(sample_app, user_2.jwt_build()).get(
        f'/api/v1/documents/document/{doc_id}/'
    )
    assert response.status_code == 403
```

### Example 5: Client Usage

```javascript
class PermitClient {
  constructor(apiUrl, token) {
    this.apiUrl = apiUrl;
    this.token = token;
  }

  async getSchemaForAction(resource, action, itemId = null) {
    let url = `${this.apiUrl}/${resource}/`;
    
    if (itemId) {
      url += `${itemId}/schema_${action}/`;
    } else {
      url += `schema_${action}/`;
    }
    
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${this.token}`
      }
    });
    
    if (response.ok) {
      return await response.json();
    }
    
    throw new Error('Cannot get schema');
  }

  async canPerformAction(resource, action, itemId = null) {
    try {
      await this.getSchemaForAction(resource, action, itemId);
      return true;
    } catch {
      return false;
    }
  }

  async getAvailableActions(resource, itemId) {
    const response = await fetch(
      `${this.apiUrl}/${resource}/${itemId}/`,
      {
        headers: {
          'Authorization': `Bearer ${this.token}`
        }
      }
    );
    
    if (response.ok) {
      const data = await response.json();
      return data.meta.crud_actions || [];
    }
    
    return [];
  }
}

// Usage
const client = new PermitClient('http://api.example.com/api/v1', jwtToken);

// Check if action is possible
const canEdit = await client.canPerformAction('documents/document', 'update', docId);

if (canEdit) {
  console.log('User can edit this document');
}

// Get available actions
const actions = await client.getAvailableActions('documents/document', docId);
console.log('Available actions:', actions);
// ['view', 'change', 'delete']
```

## License

Apache License 2.0

See [LICENSE](LICENSE) file for details.

## Links

- [Bazis Documentation](https://github.com/ecofuture-tech/bazis) — main repository
- [Bazis Users](https://github.com/ecofuture-tech/bazis-users) — user management package
- [Bazis Author](https://github.com/ecofuture-tech/bazis-author) — authorship tracking package
- [Bazis Permit Repository](https://github.com/ecofuture-tech/bazis-permit) — package repository
- [Issue Tracker](https://github.com/ecofuture-tech/bazis-permit/issues) — report bugs or request features

## Support

If you have questions or issues:
- Check the [Bazis documentation](https://github.com/ecofuture-tech/bazis)
- Search [existing issues](https://github.com/ecofuture-tech/bazis-permit/issues)
- Create a [new issue](https://github.com/ecofuture-tech/bazis-permit/issues/new) with detailed information

---

Made with ❤️ by the Bazis team