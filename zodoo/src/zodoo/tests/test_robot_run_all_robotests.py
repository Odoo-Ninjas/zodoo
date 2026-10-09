"""`odoo robot run-all` honours the MANIFEST key ``robotests``.

Before, run-all collected every ``*.robot`` file below the project, so the
self tests of vendored robot libraries and the suites of foreign repos ran
as well. With ``robotests`` set only the matching files run; without the
key nothing changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zodoo import odoo_config
from zodoo import robo_helpers

PROJECT_FILES = [
    "addons/sale_ext/tests/robot/test_order.robot",
    "addons/stock_ext/tests/robot/test_picking.robot",
    "addons/sale_ext/tests/robot/keywords/common.robot",  # never a suite
    "addons_robot/robot_utils/tests/test_basic_functions.robot",
    "addons_vendor/foreign/tests/robot/test_foreign.robot",
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


def _selected(monkeypatch, manifest):
    _with_manifest(monkeypatch, manifest)
    return sorted(map(str, robo_helpers._get_run_all_robottest_files()))


def test_without_key_everything_runs_as_before(project, monkeypatch):
    assert _selected(monkeypatch, {}) == sorted(
        [
            "addons/sale_ext/tests/robot/test_order.robot",
            "addons/stock_ext/tests/robot/test_picking.robot",
            "addons_robot/robot_utils/tests/test_basic_functions.robot",
            "addons_vendor/foreign/tests/robot/test_foreign.robot",
        ]
    )


def test_patterns_restrict_to_project_suites(project, monkeypatch):
    selected = _selected(
        monkeypatch, {"robotests": ["addons/*/tests/robot/*.robot"]}
    )
    assert selected == [
        "addons/sale_ext/tests/robot/test_order.robot",
        "addons/stock_ext/tests/robot/test_picking.robot",
    ]


def test_keywords_stay_excluded_even_if_pattern_matches(project, monkeypatch):
    selected = _selected(monkeypatch, {"robotests": ["addons/**/*.robot"]})
    assert "addons/sale_ext/tests/robot/keywords/common.robot" not in selected


def test_several_patterns_and_single_string(project, monkeypatch):
    assert _selected(
        monkeypatch,
        {
            "robotests": [
                "addons/sale_ext/tests/robot/*.robot",
                "addons_vendor/**/*.robot",
            ]
        },
    ) == [
        "addons/sale_ext/tests/robot/test_order.robot",
        "addons_vendor/foreign/tests/robot/test_foreign.robot",
    ]
    assert _selected(
        monkeypatch, {"robotests": "addons/stock_ext/tests/robot/*.robot"}
    ) == ["addons/stock_ext/tests/robot/test_picking.robot"]


def test_pattern_without_match_selects_nothing(project, monkeypatch):
    assert (
        _selected(monkeypatch, {"robotests": ["does/not/exist/*.robot"]}) == []
    )


def test_other_callers_still_see_all_files(project, monkeypatch):
    """`robot run <file>` and the shell completion keep offering every
    robot file - running a single file stays possible."""
    _with_manifest(
        monkeypatch, {"robotests": ["addons/*/tests/robot/*.robot"]}
    )
    assert len(robo_helpers._get_all_robottest_files(Path(project))) == 4
