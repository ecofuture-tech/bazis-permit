from django.utils.translation import gettext_lazy as _

from pydantic import Field

from bazis.core.utils.schemas import BazisSettings


class Settings(BazisSettings):
    """
    Represents the settings configuration for the application, extending
    BazisSettings to include a specific permission cache expiry time.
    """

    BAZIS_PERMISSION_CACHE_EXPIRE: int = Field(
        7, title=_('Time to store user permissions, sec'), dynamic=True
    )


settings = Settings()
