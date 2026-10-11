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

from bazis.contrib.users.models_abstract import UserMixin
from bazis.contrib.users.routes import UserRouteSet as UserRouteSetBase
from bazis.core.schemas import CrudAccessAction


class UserRouteSet(UserRouteSetBase):
    """
    The default route of the users (not routed: the routes of bazis-users serve them). The
    users of the sample pick other users (the participants of a meeting): an authenticated
    user sees every user in the relationships, `included` and the filters of the other
    routes; the user routes still show and change only himself (staff every user).
    """

    default_route = True

    @classmethod
    def restrict_queryset(cls, qs, access_action, user=None, **kwargs):
        if user is None:
            user = UserMixin.CTX_USER_REQUEST.get()
        if getattr(user, 'is_authenticated', False) is not True:
            return qs.none()
        if access_action == CrudAccessAction.VIEW or user.is_staff:
            return qs
        return qs.filter(pk=user.pk)
