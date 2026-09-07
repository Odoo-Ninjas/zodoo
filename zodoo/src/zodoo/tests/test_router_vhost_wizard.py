"""Tests for the `odoo router vhost new` wizard helpers.

The point of the wizard is that what comes out of it renders into a valid
nginx config, so the last test feeds the assembled vhost through the real
`render_configs.py` and checks that no field stayed empty - that used to be
the failure mode: a missing field rendered as "" and produced
`server :;` / `proxy_pass http://$var_;`.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from .. import lib_router
from ..lib_router import (
    _UPSTREAM_NAME_RE,
    _ask_protection,
    _ask_upstream_fields,
)


def _answer(monkeypatch, *answers):
    """Feed inquirer.prompt one canned answer dict per call."""
    queue = list(answers)
    monkeypatch.setattr(
        lib_router.inquirer, "prompt", lambda *a, **kw: queue.pop(0)
    )
    return queue


@pytest.mark.parametrize("name", ["odoo", "kunde_odoo", "a1_2"])
def test_upstream_name_accepts_plain_names(name):
    assert _UPSTREAM_NAME_RE.match(name)


@pytest.mark.parametrize(
    "name", ["kunde.zebroo.de", "kunde-odoo", "kunde odoo", ""]
)
def test_upstream_name_rejects_what_nginx_cannot_use(name):
    """It becomes `set $var_<name>` - a dot or dash makes nginx refuse the
    config, and that only shows up at reload time."""
    assert not _UPSTREAM_NAME_RE.match(name)


def test_upstream_fields_are_numbers(monkeypatch):
    _answer(
        monkeypatch,
        {
            "upstream_name": "kunde_odoo",
            "upstream_server": "192.168.77.130",
            "upstream_port": "6000",
            "timeout": "600",
        },
    )
    fields = _ask_upstream_fields("kunde.zebroo.de")
    assert fields["upstream_port"] == 6000
    assert fields["timeout"] == 600
    assert isinstance(fields["upstream_port"], int)


def test_protection_writes_allowlist_as_string(monkeypatch):
    """allowed_ips is a comma separated STRING in the template, not a list."""
    _answer(
        monkeypatch,
        {
            "allowed_ips": " 10.222.0.0/22, 192.168.77.0/24 ",
            "want_basic_auth": False,
        },
        {"allowlist_public_paths": ""},
    )
    vhost = {}
    _ask_protection(vhost)
    assert vhost["allowed_ips"] == "10.222.0.0/22, 192.168.77.0/24"
    assert "basic_auth" not in vhost


def test_protection_writes_basic_auth_as_dict(monkeypatch):
    _answer(
        monkeypatch,
        {"allowed_ips": "", "want_basic_auth": True},
        {"user": "zebroo", "password": "geheim"},
    )
    vhost = {}
    _ask_protection(vhost)
    assert vhost["basic_auth"] == {"zebroo": "geheim"}
    assert "allowed_ips" not in vhost


def test_no_allowlist_means_no_keys(monkeypatch):
    _answer(monkeypatch, {"allowed_ips": "", "want_basic_auth": False})
    vhost = {}
    _ask_protection(vhost)
    assert vhost == {}


def _router_dir():
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "router_global" / "render_configs.py"
        if candidate.exists():
            return candidate.parent
    return None


@pytest.mark.parametrize("template", ["upstream", "upstream_direct_odoo"])
def test_wizard_output_renders_to_a_complete_config(
    monkeypatch, tmp_path, template
):
    """End of the chain: the wizard's vhost must render without leaving holes."""
    router_dir = _router_dir()
    if router_dir is None:
        pytest.skip("router_global not next to the package (installed copy)")

    _answer(
        monkeypatch,
        {
            "upstream_name": "kunde_odoo",
            "upstream_server": "192.168.77.130",
            "upstream_port": "6000",
            "timeout": "600",
        },
    )
    vhost = {"template": template, "server_name": "kunde.zebroo.de"}
    vhost.update(_ask_upstream_fields(vhost["server_name"]))

    proc = subprocess.run(
        [
            sys.executable,
            str(router_dir / "render_configs.py"),
            str(router_dir / "templates"),
            str(tmp_path),
        ],
        input=json.dumps([vhost]),
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    rendered = (tmp_path / "kunde.zebroo.de").read_text()
    assert "server 192.168.77.130:6000;" in rendered
    assert "proxy_pass http://$var_kunde_odoo;" in rendered
    assert "proxy_connect_timeout   600;" in rendered
    # the symptoms of a silently missing field
    for hole in ("server :;", "$var_;", "proxy_connect_timeout   ;"):
        assert hole not in rendered
