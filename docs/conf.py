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

import inspect
import logging
import os
import sys
from typing import Iterable
import django


logging.basicConfig(level=logging.DEBUG)

sys.path.insert(0, os.path.abspath('..'))
sys.path.insert(1, os.path.abspath('.'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from django.apps import apps
from django.db import models
from django.db.models.fields import related_descriptors
from django.db.models.fields.files import FileDescriptor
from django.db.models.fields.related_descriptors import ForeignKeyDeferredAttribute
from django.db.models.manager import ManagerDescriptor
from django.db.models.query_utils import DeferredAttribute
from django.utils.html import strip_tags
from sphinx.util.inspect import safe_getattr
import bazis  # noqa: F40
from bazis.core.utils.django_types import TYPES_DJANGO_TO_SCHEMA_LOOKUP

try:
    from importlib.metadata import version, PackageNotFoundError
    __version__ = version('bazis-permit')
except PackageNotFoundError:
    __version__ = 'dev'


project = 'bazis-permit'
author = 'ilya.tt07@gmail.com'
release = __version__
version = __version__

extensions = [
    'sphinx.ext.autodoc',  # Core Sphinx library for auto html doc generation from docstrings
    'sphinx.ext.autosummary',  # Create neat summary tables for modules/classes/methods etc
    'sphinx.ext.intersphinx',  # Link to other project's documentation (see mapping below)
    'sphinx.ext.viewcode',  # Add a link to the Python source code for classes, functions etc.
    'sphinx_autodoc_typehints',  # Automatically document param types
    # 'sphinxcontrib_django',
]

# Mappings for sphinx.ext.intersphinx. Projects have to have Sphinx-generated doc! (.inv file)
intersphinx_mapping = {
    'python': ('https://docs.python.org/3/', None),
    'django': (
        'http://docs.djangoproject.com/en/stable/',
        'http://docs.djangoproject.com/en/stable/_objects/',
    ),
}


autosummary_generate = True  # Turn on sphinx.ext.autosummary
autoclass_content = "both"  # Add __init__ doc (ie. params) to class summaries
html_show_sourcelink = False  # Remove 'view source code' from top of page (for html, not python)
autodoc_inherit_docstrings = True  # If no docstring, inherit from base class
set_type_checking_flag = True  # Enable 'expensive' imports for sphinx_autodoc_typehints
nbsphinx_allow_errors = True  # Continue through Jupyter errors
# autodoc_typehints = "description" # Sphinx-native method. Not as good as sphinx_autodoc_typehints
add_module_names = False  # Remove namespaces from class/method signatures

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# -- Options for HTML output -------------------------------------------------

# Readthedocs theme
# on_rtd is whether on readthedocs.org, this line of code grabbed from docs.readthedocs.org...
on_rtd = os.environ.get("READTHEDOCS", None) == "True"
if not on_rtd:  # only import and set the theme if we're building docs locally
    import sphinx_rtd_theme

    html_theme = "sphinx_rtd_theme"
    html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]
html_css_files = ["readthedocs-custom.css"]  # Override some CSS settings

# Pydata theme
# html_theme = "pydata_sphinx_theme"
# html_logo = "_static/logo-company.png"
# html_theme_options = { "show_prev_next": False}
# html_css_files = ['pydata-custom.css']

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']


def django_setup(app):
    django.setup()


def process_docstring(app, what, name, obj, options, lines: list):
    try:

        def add_line_with_nl(line):
            lines.append('\n')
            lines.append(line)

        def django_field_set(dj_field):
            lines.clear()

            if verbose_name := getattr(dj_field, 'verbose_name', None):
                verbose_name = verbose_name.strip()
                lines.append(verbose_name)

            if help_text := getattr(dj_field, 'help_text', None):
                help_text = strip_tags(help_text)
                add_line_with_nl(help_text)

        def get_model(related_path):
            if isinstance(related_path, str):
                if related_path == 'self':
                    return
                related_model = apps.get_model(related_path)
            else:
                related_model = related_path
            return related_model

        def get_class_path(related_path):
            if not (related_model := get_model(related_path)):
                return related_path
            return f'{related_model.__module__}.{related_model.__name__}'

        # for Django models, we add field annotations
        if inspect.isclass(obj) and issubclass(obj, models.Model):
            obj.__annotations__ = dict(obj.__annotations__)

            for field in obj._meta.get_fields():
                attr = getattr(obj, field.name, None)

                if isinstance(attr, DeferredAttribute):
                    try:
                        obj.__annotations__.setdefault(
                            field.name, TYPES_DJANGO_TO_SCHEMA_LOOKUP[field]
                        )
                    except KeyError:
                        obj.__annotations__.setdefault(field.name, type(field))
                elif isinstance(attr, related_descriptors.ForwardManyToOneDescriptor):
                    obj.__annotations__.setdefault(
                        field.name, get_model(attr.field.remote_field.model) or obj
                    )
                elif isinstance(attr, related_descriptors.ReverseOneToOneDescriptor):
                    obj.__annotations__.setdefault(
                        field.name, get_model(attr.related.related_model) or obj
                    )
                elif isinstance(attr, related_descriptors.ReverseManyToOneDescriptor):
                    obj.__annotations__.setdefault(
                        field.name, Iterable[get_model(attr.rel.related_model) or obj]
                    )

        if inspect.isclass(obj):
            obj.__annotations__ = dict(obj.__annotations__)

            for attr_name in dir(obj):
                func = None
                if attr := safe_getattr(obj, attr_name, None):
                    _func = attr
                    while _func := (
                        safe_getattr(_func, 'fget', None)
                        or safe_getattr(_func, 'func', None)
                        or safe_getattr(_func, '__func__', None)
                    ):
                        func = _func
                try:
                    if func and (func_return := inspect.get_annotations(func).get('return')):
                        obj.__annotations__.setdefault(attr_name, func_return)
                except TypeError:
                    pass

                if isinstance(attr, related_descriptors.ForwardManyToOneDescriptor):
                    obj.__annotations__.setdefault(
                        attr_name, get_model(attr.field.remote_field.model) or obj
                    )
                elif isinstance(attr, related_descriptors.ReverseOneToOneDescriptor):
                    obj.__annotations__.setdefault(
                        attr_name, get_model(attr.related.related_model) or obj
                    )
                elif isinstance(attr, related_descriptors.ReverseManyToOneDescriptor):
                    obj.__annotations__.setdefault(
                        attr_name, list[get_model(attr.rel.related_model) or obj]
                    )

        if isinstance(obj, DeferredAttribute):
            django_field_set(obj.field)
        elif isinstance(obj, FileDescriptor):
            django_field_set(obj.field)
            lines.append("rtype: :class:`~django.db.models.fields.files.FieldFile`")
        elif isinstance(obj, related_descriptors.ForwardManyToOneDescriptor):
            django_field_set(obj.field)
            add_line_with_nl(
                f"Foreign key to the model :class:`~{get_class_path(obj.field.remote_field.model)}`"
            )
        elif isinstance(obj, related_descriptors.ReverseOneToOneDescriptor):
            django_field_set(obj.related.field)
            add_line_with_nl(
                f"Reverse key to the model :class:`~{get_class_path(obj.related.related_model)}`"
            )
        elif isinstance(obj, related_descriptors.ReverseManyToOneDescriptor):
            lines.clear()
            add_line_with_nl(
                f"M2M relation with the model :class:`~{get_class_path(obj.rel.related_model)}`"
            )
        elif isinstance(obj, (models.Manager, ManagerDescriptor)):
            # Somehow the 'objects' manager doesn't pass through the docstrings.
            module, cls_name, field_name = name.rsplit(".", 2)
            add_line_with_nl(f"Django manager to the model :class:``{cls_name}``")

        # Return the extended docstring
        return lines
    except Exception:
        import traceback

        traceback.print_exc()
        raise


def skip_member(app, what, name, obj, skip, options):
    # if objects is a raw descriptor, we skip it, as it is most likely from an abstract model
    if name == 'objects' and isinstance(obj, ManagerDescriptor):
        return True
    # do not document the Meta class of the model
    if inspect.isclass(obj) and name == 'Meta':
        return True
    # do not document ..._id fields of the model
    if isinstance(obj, ForeignKeyDeferredAttribute):
        return True


def setup(app):
    app.connect('builder-inited', django_setup)
    app.connect('autodoc-skip-member', skip_member)
    app.connect('autodoc-process-docstring', process_docstring)
