"""Tests for `odoo status` output (zodoo.lib_setup._status).

The monitoring dashboard (grafana/loki, see dashboard/docker-compose.yml)
has no host port of its own -- it is published by the proxy under /system
and /logs. `odoo status` therefore has to derive those URLs from
PROXY_PORT so users can find the dashboard without reading nginx configs.
"""

from __future__ import annotations

import click

from zodoo import lib_setup as mod
from zodoo.click_config import Config


class FakeConfig(Config):
    """See test_lib_control.FakeConfig."""

    # Config reads this from the project's MANIFEST - there is none here.
    odoo_version = 16.0

    def __init__(self, **kwargs):
        self._project_name = kwargs.pop("project_name", "zodoo_unit_test")
        self._verbose = False
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = False
        self.quiet = False
        self.restrict = {}
        self.dirs = {}
        self.commands = {}
        defaults = {
            "EXTERNAL_DOMAIN": "myhost",
            "PROXY_PORT": "8069",
            "RUN_DASHBOARD": True,
            "DASHBOARD_PASSWORD": "",
            "dbname": "mydb",
            "db_host": "postgres",
            "db_user": "odoo",
            "odoo_version": 16.0,
            "DEFAULT_DEV_PASSWORD": "1",
            "ODOO_DEMO": True,
            "ODOO_QUEUEJOBS_CHANNELS": "root:1",
            "RUN_ODOO_CRONJOBS": True,
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)
        self.files = {"project_msg": _MissingFile()}


class _MissingFile:
    def exists(self):
        return False


def _run(**kwargs):
    lines = []
    cfg = FakeConfig(**kwargs)
    orig = click.secho

    def fake_secho(text="", nl=True, **kw):
        text = str(text)
        if lines and not lines[-1][1]:
            lines[-1] = (lines[-1][0] + text, nl)
        else:
            lines.append((text, nl))

    click.secho = fake_secho
    try:
        mod._status(cfg)
    finally:
        click.secho = orig
    return [line for line, _ in lines]


def test_status_shows_monitoring_urls():
    lines = _run()
    assert "url: myhost:8069" in lines
    assert "monitoring: myhost:8069/system" in lines
    assert "logs: myhost:8069/logs" in lines


def test_status_hides_monitoring_when_dashboard_off():
    lines = _run(RUN_DASHBOARD=False)
    assert "url: myhost:8069" in lines
    assert not [x for x in lines if "monitoring" in x or "/logs" in x]


def test_status_shows_monitoring_password_when_set():
    lines = _run(DASHBOARD_PASSWORD="secret")
    assert "monitoring password: secret" in lines


def test_status_monitoring_urls_for_every_domain():
    lines = _run(EXTERNAL_DOMAIN="a.example.com,b.example.com")
    assert "monitoring: a.example.com:8069/system" in lines
    assert "            b.example.com:8069/system" in lines


def test_status_without_external_domain_keeps_port_only():
    lines = _run(EXTERNAL_DOMAIN="")
    assert "url: :8069" in lines
    assert "monitoring: :8069/system" in lines
