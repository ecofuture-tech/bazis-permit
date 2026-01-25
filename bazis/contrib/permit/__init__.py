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
TODO: there is a problem now:
if the add action is available for an object, it can be added with a reference to
an external object that the user does not have access to.
this happens because the object does not have filled selectors at the addition stage.

we need a solution that will allow checking the availability of related objects
at the stage of adding or editing the main object.

that is, we need a solution that will make such a permission work:
'entity.extended_entity.item.add.author_parent', # only those who are the author of the
parent record can add entries

"""
