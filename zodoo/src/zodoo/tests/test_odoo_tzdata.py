"""The Odoo >= 20 runtime image must ship the system time zone database.

From 20.0 on Odoo builds its time zone selection from
``zoneinfo.available_timezones()`` instead of ``pytz``. Odoo's
``requirements.txt`` only pulls the ``tzdata`` wheel on Windows and assumes
the OS provides ``/usr/share/zoneinfo``. Our images use a prebuilt Python on
a bare Ubuntu base, so without the ``tzdata`` deb the selection is empty:
``base`` demo data fails on ``tz='Europe/Brussels'`` and no module gets demo
data, and users cannot pick a time zone at all.

Reads the real Dockerfiles - no docker needed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import zodoo

CONFIG_DIR = Path(zodoo.__file__).parents[3] / "odoo" / "config"
FIRST_ZONEINFO_VERSION = 20

APT_INSTALL_BLOCK = re.compile(
    r"^RUN #___SNIPPET_APT_INSTALL___ \\\n((?:.*\\\n)*.*)$", re.MULTILINE
)


def _zoneinfo_dockerfiles():
    for version_dir in sorted(CONFIG_DIR.iterdir()):
        if not version_dir.name.isdigit():
            continue
        if int(version_dir.name) < FIRST_ZONEINFO_VERSION:
            continue
        for name in ("Dockerfile", "Dockerfile.base"):
            path = version_dir / name
            if path.exists():
                yield path


def _runtime_apt_packages(dockerfile_text):
    """Packages of the first apt install in the final (runtime) stage."""
    stages = re.split(r"^FROM .*$", dockerfile_text, flags=re.MULTILINE)
    match = APT_INSTALL_BLOCK.search(stages[-1])
    assert match, "no apt install in the runtime stage"
    return {
        token for token in match.group(1).replace("\\", " ").split() if token
    }


def test_there_is_something_to_check():
    """Guard against the parametrization silently collecting nothing."""
    assert list(_zoneinfo_dockerfiles())


@pytest.mark.parametrize(
    "dockerfile",
    list(_zoneinfo_dockerfiles()),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_runtime_stage_installs_tzdata(dockerfile):
    assert "tzdata" in _runtime_apt_packages(dockerfile.read_text())


def test_parser_reads_the_runtime_stage_only():
    text = (
        "FROM base AS build_pip\n"
        "RUN #___SNIPPET_APT_INSTALL___ \\\n"
        "    tzdata\n"
        "FROM base\n"
        "RUN #___SNIPPET_APT_INSTALL___ \\\n"
        "            curl \\\n"
        "            locales\n"
        "RUN echo done\n"
    )
    assert _runtime_apt_packages(text) == {"curl", "locales"}
