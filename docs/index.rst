
.. toctree::
   :hidden:

   Home page <self>
   structure


Bazis Permit Framework Documentation
====================================

The Bazis Permit framework is a robust and flexible permission management system designed to integrate seamlessly with Django applications. It provides a comprehensive set of tools to define, manage, and enforce permissions for various entities within an application. This documentation will help you understand the core concepts, advantages, and usage of the Bazis Permit framework.

The framework is a subproject of the Bazis framework family
-----------------------------------------------------------

Main Concept
------------

The Bazis Permit framework is built on the concept of roles, permissions, and groups. It allows you to define roles that can be assigned to users, and these roles can include multiple permissions grouped together. The framework ensures that users can perform actions only within their assigned roles and permissions.

Installation
============

.. code-block:: ini

To install the Bazis framework, run the following command:

.. code-block:: bash

    pip install bazis-permit

Usage
=====

Main Levels of the Permission System
------------------------------------

The permission system has the following main levels:

- **Permission**:
  - This is the simplest structure :py:class:`~bazis.contrib.permit.models.Permission`, represented as a string in a special format (description of the format below).
- **Group Permission**:
  - Includes a set of permissions grouped by some criteria
  - Working model: :py:class:`~bazis.contrib.permit.models.GroupPermission`
- **Role**:
  - A role can include several groups of permissions
  - Working model: :py:class:`~bazis.contrib.permit.models.Role`
- **User**:
  - The project must define a custom user class inherited from :py:class:`~bazis.contrib.permit.models_abstract.UserPermitMixin`
  - A user can have multiple roles :py:attr:`~bazis.contrib.permit.models_abstract.UserPermitMixin.roles`, but only one role can be active :py:attr:`~bazis.contrib.permit.models_abstract.UserPermitMixin.role_current`
    - The current role can be set via: admin panel, endpoint, or by signal :py:func:`~bazis.contrib.permit.models_abstract.set_default_user_role`

Key Components
~~~~~~~~~~~~~~

- **Roles**: Represent a set of permissions that can be assigned to users.
- **Permissions**: Define specific actions that can be performed on entities.
- **Groups**: Group multiple permissions together for easier management.
- **Entities**: The objects or models in your application that permissions are applied to.

Core Classes and Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Role**: Represents a role in the system.
- **Permission**: Represents a single permission.
- **GroupPermission**: Represents a group of permissions.
- **PermitService**: Manages permission data and provides handlers for checking permissions.
- **PermitRouteBase**: Base class for routes that require permission checks.

General Format of Permissions
-----------------------------

**LABEL_APP.LABEL_MODEL.PERM_LEVEL.PERM_OPERATION.SELECTOR[.ADDITIONAL]+**, where:

- **LABEL_APP.LABEL_MODEL** - the full label of the model, including the application label
- **PERM_LEVEL** - the level of permission. Default options:
  - **item** - object level
  - **field** - field level. In this case, the permission acts in a restrictive context, i.e., it imposes some restriction on the use of the field
- **PERM_OPERATION** - the label of the operation to which the permission will be applied.
  - Basic structure: :py:class:`~bazis.core.schemas.AccessAction`
  - To define your own operation, you need to:
    - Create a permission handling service inherited from :py:class:`~bazis.contrib.permit.services.PermitService`
      - Example can be found here: :py:class:`~bazis.contrib.statusy.services.PermitStatusyService`
    - Create your own route class inherited from :py:class:`~bazis.contrib.permit.routes_abstract.PermitRouteBase`
      - In it, in the Inject class, set the permit attribute to a Depends link to the created service
      - Example can be found here: :py:class:`~bazis.contrib.statusy.routes_abstract.StatusyPermitRouteSetBase`
- **SELECTOR** - the name of the field in the model (LABEL_MODEL). The value of this field from a specific object will be the link between the permission and the object. Description of working with selectors - below.

Selectors
---------

To create permissions, you need to define models whose links can become selectors. To declare such a model, you need to inherit from the mixin: :py:class:`~bazis.contrib.permit.models_abstract.PermitSelectorMixin`. This source model must implement a class method :py:meth:`~bazis.contrib.permit.models_abstract.PermitSelectorMixin.get_selector_for_user`, which takes a user object and returns an instance of the current model. The get_selector_for_user method allows you to link the user and the current object, extracting information about the current object from the user object according to the rule specified in get_selector_for_user.

Example:

We want to make the Organization model a source of selectors. Also, in our project, the User model is inherited from :py:class:`~bazis.contrib.organization.models_abstract.UserOrganizationMixin`, which defines the organization field. Then we create a model::

    class Organization(PermitSelectorMixin, models_abstract.OrganizationAbstract):
        @classmethod
        def get_selector_for_user(cls, user):
            return user.organization

After such a declaration, any model referring to Organization can have a permission with a selector corresponding to the name of this field. For example::

    class Facility(InitialBase):
        org_owner = models.ForeignKey(
            'organization.Organization', verbose_name='Organization Owner',
            blank=True, null=True, db_index=True, on_delete=models.SET_NULL
        )

Now you can create a permission:
**facility.facility.item.change.org_owner**

This permission means: The user can edit the "facility.facility" object if the org_owner field of the current object is equal to the organization field in the current user's object.

Permission Checks in Custom Actions
-----------------------------------

If you need to perform a permission check within custom actions, you need to:

- Ensure that the route inherits from PermitRouteBase
- Use the check_access method
  - The first parameter specifies the AccessAction type of action. There are 2 standard sets:
    - contrib.permit.schemas.CrudAccessAction - for CRUD actions
    - contrib.statusy.schemas.StatusyAccessAction - adds a transition action
    - You can also create your own actions
  - The second parameter specifies what the permission is requested for:
    - Either an object
    - Or a model

Example:
Implementation of the document signing check (contrib.document.routes.DocumentRouteSet.action_sign):

- Signing is allowed for those who can read the document and create a signature
- self.check_access(PermitCrudAction.VIEW, document)
- self.check_access(PermitCrudAction.ADD, apps.get_model('document.Signature'))

Access checks in standard endpoints in routes inherited from PermitRouteBase occur implicitly:

- This route defines the schemas attribute
- This attribute is a dict-like object
- This object has strictly defined schema builders that are triggered when trying to access self.schemas with the key of one of the CrudApiAction values
- The builder initializer is PermitSchemaBuilder
  - It, in turn, calls check_access with the necessary parameters during initialization

Advantages Over Other Solutions
-------------------------------

- **Granular Control**: Provides fine-grained control over permissions at both the entity and field levels.
- **Integration with Django**: Seamlessly integrates with Django's ORM and admin interface.
- **Caching**: Utilizes caching to improve performance by storing permission data.
- **Flexibility**: Supports complex permission scenarios, including field-level restrictions and dynamic permission checks.
- **Extensibility**: Easily extendable to support custom permission logic and additional features.
