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

from django.contrib import admin

from bazis.contrib.permit.admin_abstract import PermitAutocompleteMixin
from bazis.core.admin_abstract import DtAdminMixin

from .models import ChildEntity, DependentEntity, ExtendedEntity, ParentEntity


@admin.register(ChildEntity)
class ChildEntityAdmin(DtAdminMixin, admin.ModelAdmin):
    """
    Admin configuration for the ChildEntity model, including display, filter, and
    search options.
    """

    list_display = ('id', 'child_name', 'child_is_active')
    list_filter = ('child_is_active',)
    search_fields = ('child_name', 'child_description')


@admin.register(DependentEntity)
class DependentEntityAdmin(DtAdminMixin, admin.ModelAdmin):
    """
    Admin configuration for the DependentEntity model, including display, filter,
    and search options.
    """

    list_display = ('id', 'dependent_name', 'dependent_is_active')
    list_filter = ('dependent_is_active',)
    search_fields = ('dependent_name', 'dependent_description')


@admin.register(ExtendedEntity)
class ExtendedEntityAdmin(DtAdminMixin, admin.ModelAdmin):
    """
    Admin configuration for the ExtendedEntity model, including display, filter, and
    search options.
    """

    list_display = ('id', 'extended_name', 'extended_is_active')
    list_filter = ('extended_is_active',)
    search_fields = ('extended_name', 'extended_description')


class ChildEntityInline(admin.TabularInline):
    """
    Inline admin interface for managing ChildEntity instances related to
    ParentEntity.
    """

    model = ParentEntity.child_entities.through
    extra = 0


class DependentEntityInline(admin.TabularInline):
    """
    Inline admin interface for managing DependentEntity instances.
    """

    model = DependentEntity
    extra = 0


class ExtendedEntityInline(admin.TabularInline):
    """
    Inline admin interface for managing ExtendedEntity instances.
    """

    model = ExtendedEntity
    extra = 0


@admin.register(ParentEntity)
class ParentEntityAdmin(PermitAutocompleteMixin, DtAdminMixin, admin.ModelAdmin):
    """
    Admin configuration for the ParentEntity model, including display, filter,
    search options, and related inlines.
    """
    list_display = ('id', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    inlines = (ChildEntityInline, DependentEntityInline, ExtendedEntityInline)

