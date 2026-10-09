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

"""
The roles of the sample declared in the code (bazis.contrib.permit.declare): `migrate`
creates them, marked `managed`, and keeps them as declared.
"""

from django.utils.translation import gettext_lazy as _

from bazis.contrib.permit.declare import Group, Role


GROUPS = [
    # the meetings of the teams the user is a member of, invited as a guest team, without
    # their description
    Group(
        'declared_guest_meetings',
        _('Meetings of the guest teams'),
        ['entity.meeting.item.view.guest_teams__members', 'entity.meeting.field.view.all.description.disable'],
    ),
]

ROLES = [
    Role('declared_guest', _('Guest'), ['declared_guest_meetings']),
]
