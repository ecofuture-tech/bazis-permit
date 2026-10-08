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

try:
    from importlib.metadata import PackageNotFoundError, version
    __version__ = version('bazis-permit')
except PackageNotFoundError:
    __version__ = 'dev'


"""
Related objects of created and changed items:

- the core (Bazis 2.7) allows an item to reference only the objects the user can view
  (`restrict_queryset` of `PermitRouteBase`, the default route of a protected model);
  `PermitRouteBase.relation_targets_check = False` turns it off for a route;
- `check` permissions are verified on the saved item, whose selectors are filled at that
  point: e.g. 'entity.extended_entity.item.check.author_parent' allows creating and
  changing extended entities only for the author of the parent record;
- `field` permissions with `filter:` restrict the objects a relation can reference.
"""
