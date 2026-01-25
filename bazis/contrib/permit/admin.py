from django.contrib import admin

from . import models
from .admin_abstract import GroupPermissionAdminBase, PermissionAdminBase, RoleAdminBase


@admin.register(models.Role)
class RoleAdmin(RoleAdminBase):
    pass


@admin.register(models.GroupPermission)
class GroupPermissionAdmin(GroupPermissionAdminBase):
    pass


@admin.register(models.Permission)
class PermissionAdmin(PermissionAdminBase):
    pass
