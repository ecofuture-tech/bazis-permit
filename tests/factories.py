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

from bazis_test_utils import factories_abstract
from entity.models import ChildEntity, DependentEntity, ExtendedEntity, ParentEntity


class ChildEntityFactory(factories_abstract.ChildEntityFactoryAbstract):
    """
    Factory class for creating instances of ChildEntity, inheriting from
    ChildEntityFactoryAbstract.
    """

    class Meta:
        """
        Meta class specifying the model for ChildEntityFactory as ChildEntity.
        """

        model = ChildEntity


class DependentEntityFactory(factories_abstract.DependentEntityFactoryAbstract):
    """
    Factory class for creating instances of DependentEntity, inheriting from
    DependentEntityFactoryAbstract.
    """

    class Meta:
        """
        Meta class specifying the model for DependentEntityFactory as DependentEntity.
        """

        model = DependentEntity


class ExtendedEntityFactory(factories_abstract.ExtendedEntityFactoryAbstract):
    """
    Factory class for creating instances of ExtendedEntity, inheriting from
    ExtendedEntityFactoryAbstract.
    """

    class Meta:
        """
        Meta class specifying the model for ExtendedEntityFactory as ExtendedEntity.
        """

        model = ExtendedEntity


class ParentEntityFactory(factories_abstract.ParentEntityFactoryAbstract):
    """
    Factory class for creating instances of ParentEntity, inheriting from
    ParentEntityFactoryAbstract.
    """

    class Meta:
        """
        Meta class specifying the model for ParentEntityFactory as ParentEntity.
        """

        model = ParentEntity
