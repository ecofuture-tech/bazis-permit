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
