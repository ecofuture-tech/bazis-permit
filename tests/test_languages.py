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

import os
import subprocess
import sys
from pathlib import Path

import pytest


SAMPLE = Path(__file__).resolve().parent.parent / 'sample'


@pytest.mark.parametrize('languages', ['[["en", "English"]]', '[["de", "German"], ["en", "English"]]'])
def test_migrations_do_not_depend_on_the_languages_of_the_project(languages):
    """
    The translated fields of the package have the columns of its migrations whatever the
    languages of the project: makemigrations must not write a migration into the package.
    """
    # no database: makemigrations does not need one
    env = {**os.environ, 'BS_LANGUAGES': languages, 'BS_DATABASES__DEFAULT__NAME': 'permit_no_such_database'}
    done = subprocess.run(
        [sys.executable, 'manage.py', 'makemigrations', 'permit', '--check', '--dry-run'],
        cwd=SAMPLE, env=env, capture_output=True, text=True, timeout=300,
    )

    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]


def test_the_languages_follow_the_order_of_the_project(settings):
    from bazis.contrib.permit.models_abstract import translated_languages

    settings.LANGUAGES = [('ru', 'Russian'), ('de', 'German'), ('en', 'English')]
    assert translated_languages('en', 'ru') == ['ru', 'en']
    settings.LANGUAGES = [('de', 'German')]
    assert translated_languages('en', 'ru') == ['en', 'ru']


def test_a_language_without_a_column():
    """
    In a language the field has no column for, the name is read and written in the
    fallback language (it was set as an attribute that is not saved).
    """
    from django.utils import translation

    from bazis.contrib.permit.models import Role
    from bazis.contrib.permit.models_abstract import LANGUAGES, translated_column

    fallback = f'name_{LANGUAGES[0]}'
    role = Role()
    with translation.override('de'):
        role.name = 'Admin'
        assert role.name == 'Admin'
    assert getattr(role, fallback) == 'Admin'
    assert 'name_de' not in vars(role)

    assert translated_column('name', ['en', 'ru'], 'en-us') == 'name_en'
    assert translated_column('name', ['en', 'ru'], 'ru') == 'name_ru'
    assert translated_column('name', ['en', 'ru'], 'de') == 'name_en'
