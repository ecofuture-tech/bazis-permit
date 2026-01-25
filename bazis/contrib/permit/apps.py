from django.utils.translation import gettext_lazy as _

from bazis.core.utils.apps import BaseConfig


class PermitConfig(BaseConfig):
    """
    Configuration class for the 'permit' application within the Bazis project. It
    sets the application name and provides a human-readable name for the application
    using Django's translation utilities.
    """

    name = 'bazis.contrib.permit'
    verbose_name = _('Permit')

    def ready(self):
        """
        Method to perform actions when the application is ready, such as importing
        signals.
        """
        super().ready()

        from . import signals  # noqa: F401
        from .models_abstract import PermitModelMixin

        PermitModelMixin.setup_selectors_fields()
