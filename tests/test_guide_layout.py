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
The layout of the guide (`bazis/contrib/permit/AGENTS.md`) that bazis-mcp serves section by section:
the introduction, which an agent reads first, is short and maps every `## ` section with
when to read it, and each section fits in one retrieval.
"""

import json
import re
from pathlib import Path

import pytest


GUIDE = (
    Path(__file__).resolve().parent.parent / 'bazis/contrib/permit' / 'AGENTS.md'
).read_text(encoding='utf-8')

#: the most bytes of the JSON string of the introduction, read before the sections
INTRODUCTION_MAX = 10_000
#: the most bytes of the JSON string of a section, under `GUIDE_LIMIT` of bazis-mcp
#: (30,000), above which `package_guide` cuts a section into parts
SECTION_MAX = 25_000


def split(text: str) -> tuple[str, dict[str, str]]:
    """The introduction and the `## ` sections by title, as bazis-mcp splits a guide."""
    introduction, found, title, fenced = '', {}, None, False
    for line in text.splitlines(keepends=True):
        if line.startswith('```'):
            fenced = not fenced
        elif not fenced and line.startswith('## '):
            title = line[3:].strip()
            found[title] = ''
        if title is None:
            introduction += line
        else:
            found[title] += line
    return introduction, found


INTRODUCTION, SECTIONS = split(GUIDE)


def size(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False).encode('utf-8')) - 2


def test_the_introduction_is_short():
    assert size(INTRODUCTION) <= INTRODUCTION_MAX


@pytest.mark.parametrize('title', list(SECTIONS))
def test_a_section_fits_in_one_retrieval(title):
    assert size(SECTIONS[title]) <= SECTION_MAX, f'"{title}": split it'


def test_the_map_lists_every_section_in_order():
    match = re.search(r'^### The sections\n(.*?)(?=^#|\Z)', INTRODUCTION, re.M | re.S)
    assert match
    rows = re.findall(r'^\| ([^|]+?) \|', match.group(1), re.M)
    assert [it for it in rows if it != 'Section'] == list(SECTIONS)
