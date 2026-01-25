from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from bazis.contrib.permit.admin_abstract import UserPermitAdminMixin
from bazis.contrib.users.admin_abstract import UserAdminAbstract


@admin.register(get_user_model())
class UserAdmin(UserPermitAdminMixin, UserAdminAbstract, UserAdmin):
    pass
