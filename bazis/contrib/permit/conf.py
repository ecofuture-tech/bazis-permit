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

import warnings

from django.utils.translation import gettext_lazy as _

from pydantic import Field, field_validator

from bazis.core.utils.schemas import BazisSettings


class Settings(BazisSettings):
    """
    Represents the settings configuration for the application, extending
    BazisSettings to include a specific permission cache expiry time.
    """

    BAZIS_PERMISSION_CACHE_EXPIRE: int = Field(
        7, title=_('Time to store user permissions, sec'), json_schema_extra={'dynamic': True}
    )
    #: deprecated, removed in bazis-permit 3.0: no effect, the core checks the objects the
    #: relationships reference (bazis 2.7)
    BAZIS_PERMIT_RELATIONS_VIEW_CHECK: bool | None = Field(
        None,
        title=_('Created and changed items can reference only the objects the user can view'),
    )

    @field_validator('BAZIS_PERMIT_RELATIONS_VIEW_CHECK')
    @classmethod
    def relations_view_check_deprecated(cls, value):
        if value is not None:
            warnings.warn(
                'BAZIS_PERMIT_RELATIONS_VIEW_CHECK is deprecated, has no effect and will be '
                'removed in bazis-permit 3.0: the core checks the related objects.',
                DeprecationWarning,
                stacklevel=2,
            )
        return value


settings = Settings()
