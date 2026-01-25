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
from django.utils.html import mark_safe
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
        return mark_safe('<br/>'.join([role.name for role in user.roles.all()]))


class RoleAdminBase(M2mThroughMixin, DtAdminMixin, TranslatedFieldAdmin, admin.ModelAdmin):
    """
    Admin configuration for the Role model, including list display, editable fields,
    and horizontal filters.
    """

    list_display = (
        '__str__',
        'slug',
        'is_system',
    )
    list_editable = ('is_system',)
    filter_horizontal = ('groups_permission',)


class GroupPermissionAdminBase(DtAdminMixin, TranslatedFieldAdmin, admin.ModelAdmin):
    """
    Admin configuration for the GroupPermission model, including list display,
    editable fields, and horizontal filters.
    """

    filter_horizontal = ('permissions',)
    list_display = (
        'pk',
        'name',
        'slug',
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
