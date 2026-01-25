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
