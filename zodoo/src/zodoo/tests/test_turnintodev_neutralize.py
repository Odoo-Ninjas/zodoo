"""Tests for picking up Odoo's own neutralize.sql files in DEVMODE.

A restored production database still had enabled payment providers, live IAP
tokens and webhooks because only turndb2dev.sql ran. The module files Odoo
uses for `odoo-bin neutralize` must be collected the way Odoo does it.
"""

from __future__ import annotations

from zodoo import lib_turnintodev as mod


def _module(addons_path, name, neutralize=None):
    module_dir = addons_path / name
    (module_dir / "data").mkdir(parents=True)
    if neutralize is not None:
        (module_dir / "data" / "neutralize.sql").write_text(neutralize)
    return module_dir


def test_collects_neutralize_sql_of_installed_modules(tmp_path):
    core = tmp_path / "odoo" / "addons"
    _module(core, "payment", "UPDATE payment_provider SET state = 'disabled';")
    _module(core, "sale")  # no neutralize.sql
    _module(core, "iap", "UPDATE iap_account SET account_token = 'x';")

    sqls = mod._collect_odoo_neutralize_sql(["iap", "payment", "sale"], [core])

    assert [x["file"] for x in sqls] == [
        core / "iap" / "data" / "neutralize.sql",
        core / "payment" / "data" / "neutralize.sql",
    ]
    assert {x["mode"] for x in sqls} == {"plain"}


def test_first_addons_path_wins(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _module(first, "discord_bot")  # overriding copy without neutralize.sql
    _module(second, "discord_bot", "DELETE FROM discord_instance;")

    assert (
        mod._collect_odoo_neutralize_sql(["discord_bot"], [first, second])
        == []
    )


def test_skips_modules_missing_in_addons_paths(tmp_path):
    core = tmp_path / "odoo" / "addons"
    core.mkdir(parents=True)

    assert mod._collect_odoo_neutralize_sql(["gone_module"], [core]) == []
