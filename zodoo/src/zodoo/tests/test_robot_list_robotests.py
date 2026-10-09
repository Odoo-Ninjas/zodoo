"""`odoo robot list` and `odoo module list-robot-test-files` honour the
MANIFEST key ``robotests`` like `odoo robot run-all` does.

zCICD collects its robot suites through `list-robot-test-files`, so without
this it still ran the self tests of vendored robot libraries and the suites
of foreign repos. Without the key every robot file is listed as before.
"""

from __future__ import annotations

import inspect

import pytest

from zodoo import lib_module
from zodoo import lib_robot
from zodoo import odoo_config

PROJECT_FILES = [
    "addons/sale_ext/tests/robot/test_order.robot",
    "addons/sale_ext/tests/robot/keywords/common.robot",  # never a suite
    "addons_robot/robot_utils/tests/test_basic_functions.robot",
]


@pytest.fixture
def project(tmp_path, monkeypatch):
    for rel in PROJECT_FILES:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("*** Test Cases ***\n")
    monkeypatch.setattr(odoo_config, "customs_dir", lambda: tmp_path)
    return tmp_path


def _with_manifest(monkeypatch, data):
    class FakeManifest:
        def get(self, key, default):
            return data.get(key, default)

    monkeypatch.setattr(odoo_config, "MANIFEST", lambda: FakeManifest())


def _listed(command, capsys):
    """Run the command body and return the files between the ``!!!``
    markers (the format zCICD parses)."""
    func = inspect.unwrap(command.callback)
    args = [None] * len(inspect.signature(func).parameters)
    func(*args)
    out = capsys.readouterr().out
    return sorted(filter(bool, out.split("!!!")[1].split("\n")))


COMMANDS = [lib_robot.do_list, lib_module.list_robot_test_files]


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_without_key_everything_is_listed(
    project, monkeypatch, capsys, command
):
    _with_manifest(monkeypatch, {})
    assert _listed(command, capsys) == [
        "addons/sale_ext/tests/robot/test_order.robot",
        "addons_robot/robot_utils/tests/test_basic_functions.robot",
    ]


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_patterns_restrict_the_listing(project, monkeypatch, capsys, command):
    _with_manifest(
        monkeypatch, {"robotests": ["addons/*/tests/robot/*.robot"]}
    )
    assert _listed(command, capsys) == [
        "addons/sale_ext/tests/robot/test_order.robot",
    ]
