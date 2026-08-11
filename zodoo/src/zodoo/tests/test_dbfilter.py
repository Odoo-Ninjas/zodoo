"""ODOO_DBFILTER reaches both config paths, and the DB manager warns.

Background: our templates set db_name but no dbfilter. Odoo then uses
db_name as an allowlist (odoo/http.py, db_filter()), so with
ODOO_ENABLE_DB_MANAGER=1 a newly created database exists in postgres but is
invisible in the manager, unreachable over HTTP and no longer deletable --
database.py checks against the same list. There was no setting to change
that: `grep -ci dbfilter settings.txt` was 0.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_VERSIONS = ["12", "13", "14", "15", "16", "17", "18", "19"]


def _template(version):
    return (
        REPO_ROOT / "odoo" / "config" / version / "config" / "common"
    ).read_text()


class TestTemplates:
    def test_every_maintained_version_has_the_placeholder(self):
        for version in TEMPLATE_VERSIONS:
            assert "dbfilter = __ODOO_DBFILTER__" in _template(
                version
            ), f"odoo/config/{version}/config/common misses the dbfilter line"

    def test_placeholder_sits_with_list_db(self):
        """They belong together - whoever changes one looks at the other."""
        for version in TEMPLATE_VERSIONS:
            lines = _template(version).splitlines()
            i = lines.index("list_db = __ENABLE_DB_MANAGER__")
            assert lines[i + 1] == "dbfilter = __ODOO_DBFILTER__"


class TestSettingIsRegistered:
    def test_default_settings_defines_it_empty(self):
        text = (REPO_ROOT / "odoo" / "default.settings").read_text()
        assert re.search(
            r"^ODOO_DBFILTER=\s*$", text, re.M
        ), "default must be empty = behave exactly as before"

    def test_settings_txt_documents_it(self):
        text = (
            REPO_ROOT / "zodoo" / "src" / "zodoo" / "settings.txt"
        ).read_text()
        assert "ODOO_DBFILTER" in text
        assert ".*" in text, "must say how to open it up for the db manager"


class TestSubstitution:
    """What _replace_params_in_config does with the placeholder."""

    @staticmethod
    def _substitute(template, setting):
        return template.replace("__ODOO_DBFILTER__", (setting or "").strip())

    def test_empty_setting_yields_an_inert_line(self):
        out = self._substitute("dbfilter = __ODOO_DBFILTER__", "")
        assert out == "dbfilter = "

    def test_value_is_passed_through(self):
        out = self._substitute("dbfilter = __ODOO_DBFILTER__", ".*")
        assert out == "dbfilter = .*"

    def test_no_placeholder_survives(self):
        for version in TEMPLATE_VERSIONS:
            out = self._substitute(_template(version), "^mydb$")
            assert "__ODOO_DBFILTER__" not in out


def _after_compose():
    """__after_compose.py is a hook file, not a package module - load by path."""
    import importlib.util

    path = REPO_ROOT / "odoo" / "__after_compose.py"
    spec = importlib.util.spec_from_file_location("after_compose_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDbManagerWarning:
    """The user-facing half: say that the manager will only see one database."""

    @staticmethod
    def _warn(settings, capsys):
        _after_compose()._warn_db_manager_without_dbfilter(settings)
        return capsys.readouterr().out

    def test_manager_off_stays_quiet(self, capsys):
        out = self._warn(
            {"ODOO_ENABLE_DB_MANAGER": "0", "DBNAME": "mydb"}, capsys
        )
        assert out == ""

    def test_manager_on_without_dbfilter_warns(self, capsys):
        out = self._warn(
            {"ODOO_ENABLE_DB_MANAGER": "1", "DBNAME": "mydb"}, capsys
        )
        assert "mydb" in out
        assert "ODOO_DBFILTER=.*" in out, "must say how to fix it"

    def test_dbfilter_pinned_to_the_project_db_still_warns(self, capsys):
        """Explicitly writing ^mydb$ has the same effect as writing nothing."""
        out = self._warn(
            {
                "ODOO_ENABLE_DB_MANAGER": "1",
                "DBNAME": "mydb",
                "ODOO_DBFILTER": "^mydb$",
            },
            capsys,
        )
        assert "ODOO_DBFILTER=.*" in out

    def test_open_dbfilter_stays_quiet(self, capsys):
        out = self._warn(
            {
                "ODOO_ENABLE_DB_MANAGER": "1",
                "DBNAME": "mydb",
                "ODOO_DBFILTER": ".*",
            },
            capsys,
        )
        assert out == ""
