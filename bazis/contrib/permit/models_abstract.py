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

from collections.abc import Iterable
from functools import reduce

from django.apps import apps
from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db.models import BooleanField, Case, QuerySet, Value, When
from django.db.models.constants import LOOKUP_SEP
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from translated_fields import TranslatedFieldWithFallback

from bazis.contrib.users.models_abstract import UserMixin
from bazis.core.models_abstract import DtMixin, InitialBase, JsonApiMixin, UuidMixin
from bazis.core.utils.orm import apply_calc_queryset
from bazis.core.utils.query_complex import QueryComplex, QueryComplexItem, QueryToOrm

from .schemas import ATTR_SELECTORS, PermitStructMixin, SelectorField


class PermitModelMixin(UserMixin, PermitStructMixin):
    """
    Mixin for models that include permission handling functionality.
    """

    autogen_selectors_fields = None

    class Meta:
        """
        Meta class to define the PermitModelMixin as an abstract class.
        """

        abstract = True

    @classmethod
    def get_resource_verbose_name(cls) -> str:
        """
        Class method to retrieve the verbose name of the resource.
        """
        return cls._meta.verbose_name

    @classmethod
    def get_selector_fields(cls) -> dict[str, SelectorField]:
        """
        Class method to get selector fields for the model, filtering only those related
        to PermitSelectorMixin.
        """
        fields = {}
        for f in cls._meta.fields:
            if model := getattr(f, 'related_model', None):
                if isinstance(model, str):
                    model = apps.get_model(model)
                if issubclass(model, PermitSelectorMixin):
                    fields[f.name] = SelectorField(
                        name=f.name, label=str(f.verbose_name or f.name), model=model
                    )
        return fields

    @classmethod
    def selector_extending(cls, node: QueryComplexItem) -> QueryComplexItem:
        """
        Class method to check if the model has the specified attributes.
        """
        multi_value = node.value
        if not isinstance(multi_value, (list, set, tuple)):
            multi_value = [multi_value]

        kls, selector = cls.parse_selector(node.key)

        attr_selector = ATTR_SELECTORS(selector)
        if attr_selector in kls.get_fields_info().attributes:
            *parts, _ = node.key.split(LOOKUP_SEP)
            attr_prefix = LOOKUP_SEP.join(parts)
            if attr_prefix:
                attr_prefix = f'{attr_prefix}__'

            node |= {
                f'{attr_prefix}{attr_selector}__overlap': [
                    str(getattr(x, 'pk', x)) for x in multi_value
                ]
            }
        return node

    @classmethod
    def perms_item_apply(cls, qs: QuerySet, perms_item: Iterable) -> QuerySet:
        """
        Class method to apply permission items to a QuerySet, filtering based on
        specified conditions.
        """
        if perms_item and all(it[1] for it in perms_item):
            return QueryToOrm.qs_apply(
                qs, reduce(lambda qc, res: qc | res, [it[1] for it in perms_item])
            )
        return qs

    def check_condition(self, cond: QueryComplex) -> bool:
        """
        Method to check if the instance meets the specified conditions based on field
        values.
        """
        return getattr(self, f'_cond_{hash(cond)}', False)

    @classmethod
    def parse_selector(cls, selector) -> tuple[type['PermitModelMixin'], str]:
        *parts, selector = selector.split(LOOKUP_SEP)

        kls = cls
        for part in parts:
            rel = kls.get_fields_info().relations.get(part)
            if not rel:
                raise ValueError(f'{cls} does not have relation {part}')
            kls = rel.related_model

        return kls, selector

    def prepare_conditions(self, perms_item: Iterable):
        if perms_item:
            qs = type(self).objects.filter(pk=self.pk)
            cases = {}
            for _, cond in perms_item:
                q_orm = QueryToOrm(cond, type(self))
                if q_orm.fields_calc:
                    qs = apply_calc_queryset(qs, q_orm.fields_calc)

                if q_orm.q:
                    cases[f'_cond_{hash(cond)}'] = Case(
                        When(q_orm.q, then=Value(True)),
                        default=Value(False),
                        output_field=BooleanField()
                    )
                else:
                    cases[f'_cond_{hash(cond)}'] = Value(True)

            item = qs.annotate(**cases).first()

            for cond_name in cases.keys():
                setattr(self, cond_name, getattr(item, cond_name))

    @classmethod
    def setup_selectors_fields(cls):
        for model in PermitModelMixin.get_inheritors():
            if model._meta.abstract or model._meta.proxy:
                continue

            selectors = []
            for f_name, f in model.get_fields_info().relations.items():
                if f.reverse:
                    continue

                related_model = f.related_model
                if isinstance(related_model, str):
                    related_model = apps.get_model(related_model)

                if issubclass(related_model, PermitSelectorMixin):
                    selectors.append(f_name)

            if issubclass(model, PermitSelectorMixin):
                selectors.append('pk')

            # Filter fields by autogen_selectors_fields
            if model.autogen_selectors_fields is None:
                selectors = []
            elif model.autogen_selectors_fields:
                selectors = [f for f in selectors if f in model.autogen_selectors_fields]

            if selectors:
                model._meta.original_attrs.setdefault('indexes', [])
                if not getattr(model._meta, 'indexes', None):
                    model._meta.indexes = []

            for field_name in selectors:
                new_field = ATTR_SELECTORS(field_name)
                model.add_to_class(
                    new_field,
                    ArrayField(
                        models.CharField(max_length=255), null=True, blank=True,
                    ),
                )
                index = GinIndex(fields=[new_field])
                index.set_name_with_model(model)
                model._meta.indexes.append(index)


class PermitSelectorMixin(InitialBase):
    """
    Mixin for models that provide selector functionality for permissions.
    """

    class Meta:
        """
        Meta class to define the PermitSelectorMixin as an abstract class.
        """

        abstract = True

    @classmethod
    def get_selector_for_user(cls, user):
        """
        Class method to be implemented for retrieving selectors specific to a user.
        """
        raise NotImplementedError


SelectorField.model_rebuild()


class UserPermitMixin(InitialBase):
    """
    Mixin for user models to handle roles and permissions.
    """

    roles = models.ManyToManyField(
        'permit.Role', blank=True, verbose_name=_('User roles'), related_name='users'
    )
    role_current = models.ForeignKey(
        'permit.Role',
        verbose_name=_('Current user role'),
        related_name='users_current',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        """
        Meta class to define the UserPermitMixin as an abstract class.
        """

        abstract = True

    @classmethod
    def get_queryset(cls, **kwargs):
        """
        Class method to get the QuerySet for the user model, with related role_current
        field.
        """
        return super().get_queryset(**kwargs).select_related('role_current')

    def has_perm(self, perm, obj=None):
        """
        Method to check if the user has a specific permission. Superusers always have
        permissions.
        """
        if self.is_active and self.is_superuser:
            return True
        return False

    def has_perms(self, perm_list, obj=None):
        """
        Method to check if the user has all permissions in a list. Superusers always
        have permissions.
        """
        return all(self.has_perm(perm, obj) for perm in perm_list)

    def has_module_perms(self, app_label):
        """
        Method to check if the user has permissions for a specific app label. Superusers
        always have permissions.
        """
        if self.is_active and self.is_superuser:
            return True
        return False

    @classmethod
    def get_selector_for_user(cls, user):
        """
        Class method to retrieve the selector for a given user.
        """
        return user


class AnonymousUserPermitMixin:
    """
    Mixin for handling permissions and roles for anonymous users.
    """

    @cached_property
    def roles(self):
        """
        Cached property to retrieve roles available for anonymous users.
        """
        return apps.get_model('permit.Role').objects.filter(for_anonymous=True)

    @cached_property
    def role_current(self):
        """
        Cached property to retrieve the current role for an anonymous user.
        """
        return self.roles.first()


class BasePermissionManager(models.Manager):
    """
    Custom manager for BasePermission models, providing additional methods for
    querying.
    """

    def get_by_natural_key(self, slug):
        """
        Retrieve a BasePermission instance using its natural key (slug).
        """
        return self.get(slug=slug)


class BasePermission(JsonApiMixin, UuidMixin, DtMixin):
    """
    Abstract base model for permissions, including common fields and methods.
    """

    slug = models.CharField(_('Label'), max_length=1024, unique=True)

    class Meta:
        """
        Meta options for the BasePermission model, marking it as abstract.
        """

        abstract = True

    objects = BasePermissionManager()

    def __str__(self):
        """
        Return the string representation of the BasePermission instance, which is its
        slug.
        """
        return self.slug

    def natural_key(self) -> tuple:
        """
        Return the natural key for the BasePermission instance as a tuple containing the
        slug.
        """
        return (self.slug,)


class BaseGroup(BasePermission):
    """
    Abstract base model for groups, extending BasePermission with additional fields.
    """

    name = TranslatedFieldWithFallback(models.CharField(_('Name'), max_length=255, blank=True, default=''))

    class Meta:
        """
        Meta options for the BaseGroup model, marking it as abstract.
        """
        abstract = True

    def __str__(self):
        """
        Return the string representation of the BaseGroup instance, which is its name.
        """
        return self.name or super().__str__()


class RoleBase(BaseGroup):
    """
    Concrete model representing a role, inheriting from BaseGroup and adding
    specific fields.
    """

    groups_permission = models.ManyToManyField(
        'permit.GroupPermission',
        verbose_name=_('Permission Groups'),
        related_name='roles',
        blank=True,
    )
    for_anonymous = models.BooleanField(_('For Anonymous Users'), default=False)
    is_system = models.BooleanField(_('System Role'), default=False)

    class Meta:
        """
        Meta options for the Role model, including verbose names for the admin
        interface.
        """
        abstract = True
        verbose_name = _('Role')
        verbose_name_plural = _('Roles')


class GroupPermissionBase(BaseGroup):
    """
    Concrete model representing a group of permissions, inheriting from BaseGroup.
    """

    permissions = models.ManyToManyField(
        'Permission', verbose_name=_('Permissions'), related_name='groups', blank=True
    )

    class Meta:
        """
        Meta options for the GroupPermission model, including verbose names for the
        admin interface.
        """
        abstract = True
        verbose_name = _('Permission Group')
        verbose_name_plural = _('Permission Groups')


class PermissionBase(BasePermission):
    """
    Concrete model representing a single permission, inheriting from BasePermission.
    """

    class Meta:
        """
        Meta options for the Permission model, including verbose names for the admin
        interface.
        """
        abstract = True
        verbose_name = _('Permission')
        verbose_name_plural = _('Permissions')



