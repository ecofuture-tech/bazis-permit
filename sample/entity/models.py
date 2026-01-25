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

from django.db import models
from bazis.core.utils.orm import calc_property, FieldJson
from django.utils.translation import gettext_lazy as _

from bazis_test_utils.models_abstract import (
    ChildEntityBase,
    DependentEntityBase,
    ExtendedEntityBase,
    ParentEntityBase,
)

from bazis.contrib.author.models_abstract import AuthorMixin
from bazis.contrib.permit.models_abstract import PermitModelMixin
from bazis.contrib.users import get_user_model
from bazis.core.models_abstract import DtMixin, JsonApiMixin, UuidMixin
from bazis.core.triggers import FieldsTransferTrigger, FieldTransferSchema
from bazis.core.utils import triggers as bazis_triggers


User = get_user_model()


@bazis_triggers.register(
    FieldsTransferTrigger(
        related_field='parent_entities',
        fields={
            'author_parent': FieldTransferSchema(
                source='author',
            ),
        },
    )
)
class ChildEntity(
    PermitModelMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, ChildEntityBase
):
    """
    Represents a child entity with a foreign key reference to a user and inherited
    mixins for permissions, authoring, timestamps, UUIDs, and JSON API integration.
    """

    author_parent = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)

    class Meta:
        """
        Meta options for the ChildEntity model including verbose names for singular and
        plural forms.
        """

        verbose_name = _('Child entity')
        verbose_name_plural = _('Child entities')


@bazis_triggers.register(
    FieldsTransferTrigger(
        related_field='parent_entity',
        fields={
            'author_parent': FieldTransferSchema(
                source='author',
            ),
        },
    )
)
class DependentEntity(
    PermitModelMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, DependentEntityBase
):
    """
    Represents a dependent entity with foreign key references to a user and a parent
    entity, and inherited mixins for permissions, authoring, timestamps, UUIDs, and
    JSON API integration.
    """

    author_parent = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)
    parent_entity = models.ForeignKey(
        'ParentEntity', on_delete=models.CASCADE, related_name='dependent_entities'
    )

    class Meta:
        """
        Meta options for the DependentEntity model including verbose names for singular
        and plural forms.
        """

        verbose_name = _('Dependent entity')
        verbose_name_plural = _('Dependent entities')


@bazis_triggers.register(
    FieldsTransferTrigger(
        related_field='parent_entity',
        fields={
            'author_parent': FieldTransferSchema(
                source='author',
            ),
        },
    )
)
class ExtendedEntity(
    PermitModelMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, ExtendedEntityBase
):
    """
    Represents an extended entity with a one-to-one reference to a parent entity and
    a foreign key reference to a user, along with inherited mixins for permissions,
    authoring, timestamps, UUIDs, and JSON API integration.
    """
    autogen_selectors_fields = None

    author_parent = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)
    parent_entity = models.OneToOneField(
        'ParentEntity', on_delete=models.CASCADE, related_name='extended_entity'
    )

    class Meta:
        """
        Meta options for the ExtendedEntity model including verbose names for singular
        and plural forms.
        """

        verbose_name = _('Extended entity')
        verbose_name_plural = _('Extended entities')


class ParentEntity(
    PermitModelMixin, AuthorMixin, DtMixin, UuidMixin, JsonApiMixin, ParentEntityBase
):
    """
    Represents a parent entity with a many-to-many relationship to child entities
    and inherited mixins for permissions, authoring, timestamps, UUIDs, and JSON API
    integration.
    """
    autogen_selectors_fields = ['author']

    child_entities = models.ManyToManyField(
        ChildEntity,
        related_name='parent_entities',
        blank=True,
    )

    @calc_property(
        [
            FieldJson(
                source='child_entities',
                fields=['id', 'child_name',],
            ),
        ]
    )
    def childs_detail(self) -> list:
        return [
            {
                'id': child['id'],
                'child_name': child['child_name'],
            }
            for child in self._child_entities
        ]

    @property
    def some_count_property(self) -> int:
        return 1000

    class Meta:
        """
        Meta options for the ParentEntity model including verbose names for singular and
        plural forms.
        """

        verbose_name = _('Parent entity')
        verbose_name_plural = _('Parent entities')
