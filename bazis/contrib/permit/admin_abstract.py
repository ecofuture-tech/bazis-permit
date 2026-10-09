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

import re

from django import forms
from django.contrib import admin
from django.contrib.admin.views.autocomplete import AutocompleteJsonView
from django.contrib.admin.widgets import AutocompleteMixin as AutocompleteMixinDjango
from django.urls import re_path, reverse
from django.utils.html import format_html_join, mark_safe
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from translated_fields import TranslatedFieldAdmin

from bazis.contrib.permit.schemas import PATTERN_SELECTORS
from bazis.contrib.users import get_user_model
from bazis.core.admin_abstract import AutocompleteMixin, DtAdminMixin, M2mThroughMixin
from bazis.core.utils.sets_order import OrderedSet


User = get_user_model()


class UserPermitAdminMixin:
    """
    A mixin class for customizing the Django admin interface for user permits,
    adding additional fields and display options related to user roles.
    """

    def get_fields_permissions(self, request, obj=None):
        """
        Extends the parent method to include 'roles' and 'role_current' in the fields
        permissions for the admin interface.
        """
        return super().get_fields_permissions(request, obj) + ('roles', 'role_current')

    def get_list_display(self, request):
        """
        Extends the parent method to include 'get_roles_name' and 'role_current' in the
        list display for the admin interface, ensuring unique display fields using
        OrderedSet.
        """
        return tuple(
            OrderedSet(
                ('id',) + super().get_list_display(request) + ('get_roles_name', 'role_current')
            )
        )

    @admin.display(description=_('Roles'))
    def get_roles_name(self, user):
        """
        Returns a safe HTML string that displays the names of all roles associated with
        a user, separated by line breaks. This method is used in the admin interface to
        show user roles.
        """
        return format_html_join(mark_safe('<br/>'), '{}', ((role.name,) for role in user.roles.all()))


class ManagedAdminMixin:
    """
    The objects declared in the code (`managed` and declared in a roles.py module,
    bazis.contrib.permit.declare) are read-only in the admin, besides the fields of
    `managed_editable`, and are not deleted: `migrate` would bring them back. A managed
    object no longer declared is an ordinary object again.
    """

    #: the fields of a declared object the admin still changes
    managed_editable: tuple[str, ...] = ()

    def declared_slugs(self) -> set[str]:
        from .declare import declared_slugs

        return declared_slugs(self.model._meta.model_name)

    def is_declared(self, obj) -> bool:
        return obj.managed and obj.slug in self.declared_slugs()

    def get_readonly_fields(self, request, obj=None):
        fields = (*super().get_readonly_fields(request, obj), 'managed')
        if obj is not None and self.is_declared(obj):
            opts = self.model._meta
            fields += tuple(
                f.name for f in (*opts.concrete_fields, *opts.many_to_many)
                if f.editable and f.name not in self.managed_editable and f.name not in fields
            )
        return fields

    def has_change_permission(self, request, obj=None):
        if obj is not None and not self.managed_editable and self.is_declared(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and self.is_declared(obj):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset.exclude(managed=True, slug__in=self.declared_slugs()))

    def get_changelist_formset(self, request, **kwargs):
        formset = super().get_changelist_formset(request, **kwargs)
        editable = self.managed_editable
        declared = self.declared_slugs()

        class ManagedFormSet(formset):
            def _construct_form(self, i, **kwargs):
                form = super()._construct_form(i, **kwargs)
                if form.instance.managed and form.instance.slug in declared:
                    for name, field in form.fields.items():
                        if name not in editable:
                            field.disabled = True
                return form

        return ManagedFormSet


class RoleAdminBase(
    ManagedAdminMixin, M2mThroughMixin, DtAdminMixin, TranslatedFieldAdmin, admin.ModelAdmin
):
    """
    Admin configuration for the Role model, including list display, editable fields,
    and horizontal filters. The admin attaches its own groups to a managed role.
    """

    list_display = (
        '__str__',
        'slug',
        'is_system',
        'managed',
    )
    list_editable = ('is_system',)
    filter_horizontal = ('groups_permission',)
    managed_editable = ('groups_permission', 'is_system')


class GroupPermissionAdminBase(
    ManagedAdminMixin, DtAdminMixin, TranslatedFieldAdmin, admin.ModelAdmin
):
    """
    Admin configuration for the GroupPermission model, including list display,
    editable fields, and horizontal filters.
    """

    filter_horizontal = ('permissions',)
    list_display = (
        'pk',
        'name',
        'slug',
        'managed',
    )
    list_editable = (
        'slug',
    )


class PermissionAdminBase(DtAdminMixin, TranslatedFieldAdmin, admin.ModelAdmin):
    """
    Admin configuration for the Permission model, including list display, editable
    fields, and search fields.
    """

    list_display = (
        '__str__',
        'slug',
    )
    search_fields = ('slug',)
    list_editable = ('slug',)


class PermitAutocompleteJsonView(AutocompleteJsonView):
    def process_request(self, request):
        if match := re.match(PATTERN_SELECTORS, request.GET['field_name']):
            target_field = match.group(1)
            request_GET = request.GET.copy() # noqa: N806
            request_GET['field_name'] = target_field
            request.GET = request_GET
        return super().process_request(request)


class PermitAutocompleteSelectMultiple(AutocompleteMixinDjango, forms.SelectMultiple):
    def __init__(self, origin_field, ref_field, admin_site, using, url_autocomplete, **kwargs):
        self.url_autocomplete = url_autocomplete
        self.origin_field = origin_field
        super().__init__(ref_field, admin_site, using=using, **kwargs)

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs=extra_attrs)
        attrs['data-field-name'] = self.origin_field.name
        return attrs

    def get_url(self):
        return reverse(f'{self.admin_site.name}:{self.url_autocomplete}')


class PermitAutocompleteMultipleChoiceField(forms.ModelMultipleChoiceField):
    def prepare_value(self, value):
        if isinstance(value, list):
            return value
        return super().prepare_value(value)

    def clean(self, value):
        if value:
            return [str(user.pk) for user in super().clean(value)]
        return []


class PermitAutocompleteMixin(AutocompleteMixin):
    """
    Admin configuration for the ParentEntity model, including display, filter,
    search options, and related inlines.
    """

    class Media:
        js = ('admin/js/autocomplete.js',)

    def formfield_for_dbfield(self, db_field, **kwargs):
        if match := re.match(PATTERN_SELECTORS, db_field.name):
            target_field_name = match.group(1)
            origin_field = db_field
            db_field = self.model.get_fields_info().relations.get(target_field_name).model_field

            kwargs['widget'] = PermitAutocompleteSelectMultiple(
                origin_field,
                db_field,
                self.admin_site,
                using=kwargs.get("using"),
                url_autocomplete=self.get_url_autocomplete()
            )
            kwargs['label'] = capfirst(origin_field.verbose_name.strip())
            kwargs['form_class'] = PermitAutocompleteMultipleChoiceField

        formfield = super().formfield_for_dbfield(db_field, **kwargs)

        return formfield

    def get_url_autocomplete(self):
        return f'{self.opts.app_label}_{self.opts.model_name}_changelist-autocomplete'

    def get_urls(self):
        urls = super().get_urls()

        urls = [
                   re_path(
                       r'^autocomplete/$', self.autocomplete_view, name=self.get_url_autocomplete()
                       ),
               ] + urls
        return urls

    def autocomplete_view(self, request):
        return PermitAutocompleteJsonView.as_view(admin_site=self.admin_site)(request)
