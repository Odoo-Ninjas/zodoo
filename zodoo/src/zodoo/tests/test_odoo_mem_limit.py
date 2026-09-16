"""Unit tests for `_apply_mem_limit` in `odoo/__after_compose.py`.

Would have caught the CAETEC outage of 2026-09-14: the odoo_cronjobs
container leaked ~3.5 GB a day up to 25 GB; when the nightly backup asked
for more, the *host* ran out of memory and the kernel OOM killer shot the
cron process. The container vanished, no Odoo cron ran for a day and a
half, and support mails had to be fetched by hand. LIMIT_MEMORY_HARD_CRON
was set the whole time and did nothing — the role runs with workers = 0,
where Odoo enforces nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
AFTER_COMPOSE = REPO_ROOT / "odoo" / "__after_compose.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "odoo_after_compose", AFTER_COMPOSE
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ac = _load_module()


class _Tools:
    """Stands in for globals["tools"]; returns the odoo_base services."""

    def __init__(self, services):
        self._services = services

    def get_services(self, config, name, yml=None):
        assert name == "odoo_base"
        return list(self._services)


def _yml():
    return {
        "services": {
            "odoo": {},
            "odoo_cronjobs": {},
            "odoo_queuejobs": {},
            "odoo_update": {},
            "odoo_debug": {},
            "postgres": {},
        }
    }


def _apply(settings):
    yml = _yml()
    services = [s for s in yml["services"] if s != "postgres"]
    ac._apply_mem_limit(None, yml, settings, {"tools": _Tools(services)})
    return yml["services"]


def test_unset_means_unlimited():
    services = _apply({})
    assert all("mem_limit" not in s for s in services.values())


def test_default_applies_to_every_role():
    services = _apply({"MEM_LIMIT_ODOO": "16g"})
    assert services["odoo"]["mem_limit"] == "16g"
    assert services["odoo_cronjobs"]["mem_limit"] == "16g"
    assert services["odoo_queuejobs"]["mem_limit"] == "16g"


def test_per_role_overrides_default():
    services = _apply({"MEM_LIMIT_ODOO": "16g", "MEM_LIMIT_ODOO_CRON": "8g"})
    assert services["odoo_cronjobs"]["mem_limit"] == "8g"
    assert services["odoo"]["mem_limit"] == "16g"


def test_per_role_alone_leaves_the_others_unlimited():
    """The CAETEC case: cap the leaking cron, touch nothing else."""
    services = _apply({"MEM_LIMIT_ODOO_CRON": "16g"})
    assert services["odoo_cronjobs"]["mem_limit"] == "16g"
    assert "mem_limit" not in services["odoo"]
    assert "mem_limit" not in services["odoo_queuejobs"]


@pytest.mark.parametrize("name", ["odoo_update", "odoo_debug"])
def test_update_and_debug_are_never_limited(name):
    """Updates/migrations are meant to be memory hungry."""
    services = _apply({"MEM_LIMIT_ODOO": "4g"})
    assert "mem_limit" not in services[name]


def test_untouched_when_nothing_is_configured():
    """No settings at all must not even walk the services."""
    yml = _yml()

    class _Boom:
        def get_services(self, *args, **kwargs):
            raise AssertionError("should not be called")

    ac._apply_mem_limit(None, yml, {}, {"tools": _Boom()})
    assert all("mem_limit" not in s for s in yml["services"].values())


def test_empty_string_is_treated_as_unset():
    services = _apply({"MEM_LIMIT_ODOO": "  ", "MEM_LIMIT_ODOO_CRON": "8g"})
    assert services["odoo_cronjobs"]["mem_limit"] == "8g"
    assert "mem_limit" not in services["odoo"]
