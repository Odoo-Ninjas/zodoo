"""Tests fuer den Pfad-Schutz von zodoo.tools.__rmtree.

Der Schutz soll verhindern, dass irgendwo im Dateisystem geloescht wird,
darf aber die Pfade nicht blocken, die zodoo selbst aufraeumen will -
insbesondere den Filestore einer Test-Datenbank. Genau der wurde vorher
abgelehnt, weshalb sich auf CI-Rechnern tausende Filestores angesammelt
haben.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from zodoo import tools as mod

_rmtree = getattr(mod, "__rmtree")


@pytest.fixture
def config(tmp_path):
    home = tmp_path / "odoo_home"
    data = tmp_path / "data"
    return SimpleNamespace(
        dirs={
            "odoo_home": home,
            "odoo_data_dir": data,
            "run": home / "run",
        }
    )


def test_removes_filestore_of_single_database(config, tmp_path):
    filestore = config.dirs["odoo_data_dir"] / "filestore" / "dbtest1234"
    filestore.mkdir(parents=True)
    (filestore / "somefile").write_text("x")

    _rmtree(config, filestore)

    assert not filestore.exists()


def test_removes_run_directory_of_project(config):
    rundir = config.dirs["odoo_home"] / "run" / "abcdef"
    rundir.mkdir(parents=True)

    _rmtree(config, rundir)

    assert not rundir.exists()


def test_refuses_unrelated_path(config, tmp_path):
    other = tmp_path / "somewhere_else"
    other.mkdir()

    with pytest.raises(Exception):
        _rmtree(config, other)

    assert other.exists()
