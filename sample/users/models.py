from bazis.contrib.permit.models_abstract import (
    AnonymousUserPermitMixin,
    PermitSelectorMixin,
    UserPermitMixin,
)
from bazis.contrib.users.models_abstract import AnonymousUserAbstract, UserAbstract
from bazis.core.models_abstract import JsonApiMixin, UuidMixin


class User(UserPermitMixin, PermitSelectorMixin, UuidMixin, UserAbstract, JsonApiMixin):
    """
    Represents a user in the system, incorporating permissions, UUID, and user-
    specific attributes.
    """

    pass


class AnonymousUser(AnonymousUserPermitMixin, AnonymousUserAbstract):
    """
    Represents an anonymous user in the system, incorporating permissions and
    anonymous user-specific attributes.
    """

    pass
