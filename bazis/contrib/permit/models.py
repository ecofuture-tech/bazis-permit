from bazis.contrib.permit.models_abstract import (
    GroupPermissionBase,
    PermissionBase,
    RoleBase,
)


class Role(RoleBase):
    pass


class GroupPermission(GroupPermissionBase):
    pass


class Permission(PermissionBase):
    pass
