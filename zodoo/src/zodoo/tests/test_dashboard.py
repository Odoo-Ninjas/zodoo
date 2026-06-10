"""Unit tests for the monitoring dashboard service.

Fast, no Docker: they exercise the dashboard generator and the custom Odoo
metrics exporter's pure helpers. The exporter's third-party imports
(psycopg2, prometheus_client) are stubbed so the module loads in the plain
test venv.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

# repo root: .../zodoo/src/zodoo/tests/test_dashboard.py -> parents[4]
REPO_ROOT = Path(__file__).resolve().parents[4]
DASHBOARDS = REPO_ROOT / "dashboard" / "grafana" / "dashboards"
GENERATOR = REPO_ROOT / "dashboard" / "grafana" / "generate_dashboard.py"
EXPORTER = REPO_ROOT / "dashboard" / "exporter" / "app.py"


def test_committed_dashboards_are_valid_json():
    for name, min_panels in (("zodoo-overview", 20), ("zodoo-logs", 3)):
        data = json.loads((DASHBOARDS / f"{name}.json").read_text())
        assert data["uid"] == name
        panels = [p for p in data["panels"] if p.get("type") != "row"]
        assert len(panels) >= min_panels


def test_generator_matches_committed(tmp_path):
    """The committed JSON must equal a fresh generator run (no drift)."""
    workdir = tmp_path / "grafana"
    (workdir / "dashboards").mkdir(parents=True)
    shutil.copy(GENERATOR, workdir / "generate_dashboard.py")

    subprocess.run(
        [sys.executable, str(workdir / "generate_dashboard.py")],
        check=True,
        cwd=tmp_path,
    )

    for name in ("zodoo-overview", "zodoo-logs"):
        generated = json.loads(
            (workdir / "dashboards" / f"{name}.json").read_text()
        )
        committed = json.loads((DASHBOARDS / f"{name}.json").read_text())
        assert generated == committed, (
            f"{name}.json is out of date -- rerun "
            "dashboard/grafana/generate_dashboard.py"
        )


def _load_exporter(monkeypatch):
    """Import dashboard/exporter/app.py with its heavy deps stubbed."""
    monkeypatch.setitem(sys.modules, "psycopg2", mock.MagicMock())
    pc = types.ModuleType("prometheus_client")
    pc.start_http_server = lambda *a, **k: None
    core = types.ModuleType("prometheus_client.core")
    core.REGISTRY = mock.MagicMock()
    core.GaugeMetricFamily = mock.MagicMock()
    pc.core = core
    monkeypatch.setitem(sys.modules, "prometheus_client", pc)
    monkeypatch.setitem(sys.modules, "prometheus_client.core", core)

    spec = importlib.util.spec_from_file_location(
        "dash_exporter_app", EXPORTER
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_queuejob_workers_parsing(monkeypatch):
    app = _load_exporter(monkeypatch)
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "root:2,foo:4")
    assert app._queuejob_workers() == 6.0
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "root:1")
    assert app._queuejob_workers() == 1.0
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "")
    assert app._queuejob_workers() == 0.0
    # malformed entries are ignored, not fatal
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "garbage,root:3")
    assert app._queuejob_workers() == 3.0


def test_float_env_handles_missing_and_bad(monkeypatch):
    app = _load_exporter(monkeypatch)
    monkeypatch.setenv("SOME_INT", "4")
    assert app._float_env("SOME_INT") == 4.0
    monkeypatch.delenv("SOME_MISSING", raising=False)
    assert app._float_env("SOME_MISSING") != app._float_env(
        "SOME_MISSING"
    )  # NaN
    monkeypatch.setenv("SOME_BAD", "notanumber")
    assert app._float_env("SOME_BAD") != app._float_env("SOME_BAD")  # NaN
