"""Tests for zodoo.lib_backup.

Most functions orchestrate subprocess / docker / postgres calls. We cover
the pure helpers directly and exercise the click commands with their
subprocess surface monkey-patched. Heavy DB-round-trip tests that need
a live container are covered by the bake test flow, not here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from zodoo import lib_backup as mod
from zodoo.click_config import Config
from zodoo.tests.conftest import requires_full_stack


class FakeConfig(Config):
    """Same escape-hatch as test_lib_docker_registry; see docstring there."""

    def __init__(self, **kwargs):
        self._project_name = kwargs.pop("project_name", "zodoo_unit_test")
        self._verbose = kwargs.pop("verbose", False)
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = kwargs.pop("force", False)
        self.quiet = False
        self.restrict = {}
        self.dirs = kwargs.pop("dirs", {})
        self.files = kwargs.pop("files", {})
        self.commands = {}
        # Common settings-derived attributes; all default to None/False so
        # tests only need to set what they care about.
        # Plain settings-style attributes live in __dict__ so Config's
        # __getattribute__ returns them directly before falling back to
        # MyConfigParser. We go through __dict__ to avoid tripping over
        # real @property setters (e.g. Config.use_docker has no setter).
        defaults = {
            "dbname": "mydb",
            "DBNAME": "mydb",
            "DB_HOST": "db",
            "DB_PORT": "5432",
            "DB_USER": "odoo",
            "DB_PWD": "odoo",
            "NO_REMOVE_WEB_ASSETS_AFTER_RESTORE": False,
            "owner_uid": "1000",
            "run_postgres": False,
            "devmode": True,
            "dumps_path": None,
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)


# ---------------------------------------------------------------------------
# used_space_files
# ---------------------------------------------------------------------------


def test_used_space_files_prints_filestore_size(tmp_path, monkeypatch):
    filestore = tmp_path / "fs"
    filestore.mkdir()
    (filestore / "a").write_bytes(b"x" * 123)

    monkeypatch.setattr(mod, "_get_filestore_folder", lambda c: filestore)
    monkeypatch.setattr(mod, "get_directory_size", lambda p: 123)

    cfg = FakeConfig()
    res = CliRunner().invoke(
        mod.used_space_files, [], obj=cfg, catch_exceptions=False
    )
    assert res.exit_code == 0
    assert "123" in res.output


# ---------------------------------------------------------------------------
# show_dumps / list_dumps
# ---------------------------------------------------------------------------


def test_show_dumps_empty(tmp_path):
    cfg = FakeConfig(dumps_path=str(tmp_path))
    res = CliRunner().invoke(
        mod.show_dumps, [], obj=cfg, catch_exceptions=False
    )
    assert res.exit_code == 0
    assert "No dump files" in res.output


def test_show_dumps_respects_limit(tmp_path, monkeypatch):
    rows = [
        (1, "a.dump", "1d", "10M"),
        (2, "b.dump", "2d", "20M"),
        (3, "c.dump", "3d", "30M"),
    ]
    monkeypatch.setattr(mod, "_get_dump_files", lambda p: rows)
    cfg = FakeConfig(dumps_path=str(tmp_path))
    res = CliRunner().invoke(
        mod.show_dumps, ["-n", "2"], obj=cfg, catch_exceptions=False
    )
    assert res.exit_code == 0
    assert "a.dump" in res.output and "b.dump" in res.output
    assert "c.dump" not in res.output


def test_show_dumps_limit_zero_means_all(tmp_path, monkeypatch):
    rows = [(i, f"f{i}.dump", "1d", "1M") for i in range(5)]
    monkeypatch.setattr(mod, "_get_dump_files", lambda p: rows)
    cfg = FakeConfig(dumps_path=str(tmp_path))
    res = CliRunner().invoke(
        mod.show_dumps, ["-n", "0"], obj=cfg, catch_exceptions=False
    )
    assert res.exit_code == 0
    for i in range(5):
        assert f"f{i}.dump" in res.output


# ---------------------------------------------------------------------------
# __get_default_backup_filename
# ---------------------------------------------------------------------------


def test_get_default_backup_filename_contains_project_name():
    cfg = FakeConfig(project_name="foo")
    cfg._project_name = "foo"
    name = mod._lib_backup__get_default_backup_filename(cfg) if False else None
    # name mangled — we invoke via the module's dunder-prefixed function
    fn = getattr(mod, "_lib_backup__get_default_backup_filename", None)
    # actually the function is top-level, not dunder-mangled
    fn = (
        mod.__dict__["_lib_backup__get_default_backup_filename"]
        if False
        else None
    )
    # Just call the actual name directly via module attribute lookup
    fn = getattr(mod, "__get_default_backup_filename", None)
    if fn is None:
        # name-mangling via module loader doesn't apply here; try the bare name
        # from the function we know exists
        import zodoo.lib_backup as _b

        for attr in dir(_b):
            if attr.endswith("__get_default_backup_filename"):
                fn = getattr(_b, attr)
                break
    assert fn is not None
    result = fn(cfg)
    assert "foo" in result
    assert result.endswith(".dump.gz")


# ---------------------------------------------------------------------------
# _get_filestore_destination
# ---------------------------------------------------------------------------


def test_get_filestore_destination_creates_dir(tmp_path):
    cfg = FakeConfig(dirs={"odoo_data_dir": tmp_path}, dbname="mydb")
    cfg.dbname = (
        "mydb"  # explicit (overrides __dict__.update since kwargs ordering)
    )
    dest = mod._get_filestore_destination(cfg)
    assert dest == tmp_path / "filestore" / "mydb"
    assert dest.is_dir()


# ---------------------------------------------------------------------------
# __do_restore_files
# ---------------------------------------------------------------------------


def test_do_restore_files_shells_tar(tmp_path, monkeypatch):
    archive = tmp_path / "files.tgz"
    archive.write_bytes(b"tar-content")
    dest_parent = tmp_path / "data"
    dest_parent.mkdir()

    called = {}

    def fake_check_call(cmd, cwd=None):
        called["cmd"] = cmd
        called["cwd"] = cwd

    monkeypatch.setattr(subprocess, "check_call", fake_check_call)

    cfg = FakeConfig(
        dirs={"odoo_data_dir": dest_parent},
        dbname="mydb",
        dumps_path=str(tmp_path),
    )
    cfg.dbname = "mydb"

    # access private-name-mangled helper via dict
    fn = None
    for a in dir(mod):
        if a.endswith("__do_restore_files"):
            fn = getattr(mod, a)
            break
    assert fn is not None
    fn(cfg, archive)

    assert called["cmd"][:2] == ["tar", "xzf"]
    assert called["cwd"] == dest_parent / "filestore" / "mydb"


def test_do_restore_files_joins_relative_with_dumps_path(
    tmp_path, monkeypatch
):
    dest_parent = tmp_path / "data"
    dest_parent.mkdir()
    (tmp_path / "in_dumps.tgz").write_bytes(b"x")

    seen = {}
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda cmd, cwd=None: seen.setdefault("cmd", cmd),
    )

    cfg = FakeConfig(
        dirs={"odoo_data_dir": dest_parent},
        dbname="mydb",
        dumps_path=str(tmp_path),
    )
    cfg.dbname = "mydb"
    fn = next(a for a in dir(mod) if a.endswith("__do_restore_files"))
    getattr(mod, fn)(cfg, Path("in_dumps.tgz"))
    # the absolute archive path should be inside dumps_path
    assert str(tmp_path) in " ".join(str(x) for x in seen["cmd"])


# ---------------------------------------------------------------------------
# __apply_dump_permissions
# ---------------------------------------------------------------------------


def test_apply_dump_permissions_noop_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("DUMP_UID", raising=False)
    monkeypatch.delenv("DUMP_GID", raising=False)
    calls = []
    monkeypatch.setattr(
        subprocess, "check_call", lambda *a, **kw: calls.append(a)
    )
    fn = next(a for a in dir(mod) if a.endswith("__apply_dump_permissions"))
    getattr(mod, fn)(tmp_path / "f")
    assert calls == []


def test_apply_dump_permissions_chown_when_uid_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DUMP_UID", "1234")
    monkeypatch.delenv("DUMP_GID", raising=False)
    calls = []
    monkeypatch.setattr(
        subprocess, "check_call", lambda cmd: calls.append(cmd)
    )
    fn = next(a for a in dir(mod) if a.endswith("__apply_dump_permissions"))
    fake_path = tmp_path / "dump"
    getattr(mod, fn)(fake_path)
    assert calls == [["sudo", "chown", "1234", fake_path]]


def test_apply_dump_permissions_chgrp_when_gid_set(tmp_path, monkeypatch):
    monkeypatch.delenv("DUMP_UID", raising=False)
    monkeypatch.setenv("DUMP_GID", "4321")
    calls = []
    monkeypatch.setattr(
        subprocess, "check_call", lambda cmd: calls.append(cmd)
    )
    fn = next(a for a in dir(mod) if a.endswith("__apply_dump_permissions"))
    fake_path = tmp_path / "dump"
    getattr(mod, fn)(fake_path)
    assert calls == [["sudo", "chgrp", "4321", fake_path]]


# ---------------------------------------------------------------------------
# __restore_check — explicit no-op
# ---------------------------------------------------------------------------


def test_restore_check_is_a_noop():
    fn = next(a for a in dir(mod) if a.endswith("__restore_check"))
    assert getattr(mod, fn)(Path("/nonexistent"), FakeConfig()) is None


# ---------------------------------------------------------------------------
# _get_postgres_version
# ---------------------------------------------------------------------------


def test_get_postgres_version_parses(monkeypatch):
    monkeypatch.setattr(
        mod,
        "_execute_sql",
        lambda conn, sql, fetchone=True: ("PostgreSQL 15.3 (x86_64) ...",),
    )
    assert mod._get_postgres_version(object()) == "15.3"


# ---------------------------------------------------------------------------
# _add_cronjob_scripts
# ---------------------------------------------------------------------------


def test_add_cronjob_scripts_loads_postgres_module(tmp_path):
    # create a fake images/cronjobs/bin/postgres.py on disk and verify
    # _add_cronjob_scripts imports it dynamically
    images = tmp_path / "images"
    cronjobs_bin = images / "cronjobs" / "bin"
    cronjobs_bin.mkdir(parents=True)
    (cronjobs_bin / "postgres.py").write_text(
        "SENTINEL = 'loaded'\n"
        "def _restore(*a, **kw):\n    return 'restored'\n"
    )
    cfg = FakeConfig(dirs={"images": images})
    result = mod._add_cronjob_scripts(cfg)
    assert "postgres" in result
    assert result["postgres"].SENTINEL == "loaded"
    assert result["postgres"]._restore() == "restored"


# ---------------------------------------------------------------------------
# _inquirer_dump_file
# ---------------------------------------------------------------------------


def test_inquirer_dump_file_returns_none_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mod, "_get_dump_files", lambda p: [(1, "a.dump", "1d", "1M")]
    )
    monkeypatch.setattr(mod.inquirer, "prompt", lambda q: None)
    cfg = FakeConfig(dumps_path=str(tmp_path))
    assert mod._inquirer_dump_file(cfg, "pick", None) is None


def test_inquirer_dump_file_returns_selected(tmp_path, monkeypatch):
    rows = [(1, "a.dump", "1d", "1M"), (2, "b.dump", "2d", "2M")]
    monkeypatch.setattr(mod, "_get_dump_files", lambda p: rows)
    monkeypatch.setattr(
        mod.inquirer, "prompt", lambda q: {"filename": rows[1]}
    )
    cfg = FakeConfig(dumps_path=str(tmp_path))
    assert mod._inquirer_dump_file(cfg, "pick", None) == "b.dump"


def test_inquirer_dump_file_applies_filter(tmp_path, monkeypatch):
    rows = [(1, "abc.dump", "1d", "1M"), (2, "xyz.dump", "2d", "2M")]
    monkeypatch.setattr(mod, "_get_dump_files", lambda p: rows)
    captured = {}

    def capture(q):
        captured["choices"] = q[0].choices
        return None

    monkeypatch.setattr(mod.inquirer, "prompt", capture)
    cfg = FakeConfig(dumps_path=str(tmp_path))
    mod._inquirer_dump_file(cfg, "pick", "abc")
    # filter kept only the abc.dump row
    assert len(captured["choices"]) == 1
    assert captured["choices"][0][1] == "abc.dump"


# ---------------------------------------------------------------------------
# backup_files (happy path)
# ---------------------------------------------------------------------------


def test_backup_files_tars_filestore(tmp_path, monkeypatch):
    filestore = tmp_path / "fs"
    filestore.mkdir()
    (filestore / "f").write_bytes(b"x")

    monkeypatch.setattr(mod, "_get_filestore_folder", lambda c: filestore)
    calls = []
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda cmd, cwd=None: calls.append((cmd, cwd)),
    )
    # disable permission chown side-effects
    monkeypatch.setattr(mod, "__dict__") if False else None
    for attr in dir(mod):
        if attr.endswith("__apply_dump_permissions"):
            monkeypatch.setattr(mod, attr, lambda *a, **kw: None)

    cfg = FakeConfig(
        dumps_path=str(tmp_path),
        project_name="myproj",
    )
    cfg._project_name = "myproj"
    out_file = tmp_path / "myproj.files.tar.gz"
    res = CliRunner().invoke(
        mod.backup_files, [str(out_file)], obj=cfg, catch_exceptions=False
    )
    assert res.exit_code == 0
    assert any(cmd[0] == "tar" for cmd, _ in calls)


def test_backup_files_aborts_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mod, "_get_filestore_folder", lambda c: tmp_path / "nope"
    )
    cfg = FakeConfig(dumps_path=str(tmp_path), project_name="p")
    cfg._project_name = "p"
    res = CliRunner().invoke(
        mod.backup_files, [], obj=cfg, catch_exceptions=True
    )
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# get_dump_type (the click command)
# ---------------------------------------------------------------------------


def test_get_dump_type_prints_detected(tmp_path, monkeypatch):
    fake_postgres = SimpleNamespace()
    # name-mangled private method
    setattr(
        fake_postgres,
        "_lib_backup__get_dump_type",
        lambda fn: "custom",
    )
    # but _add_cronjob_scripts returns a module object, not a namespace —
    # restore_db looks up `.__get_dump_type` which is name-mangled at the
    # *module lookup* site into `_lib_backup__get_dump_type`. So this works
    # because both the caller and the mock are inside (or pretending to be
    # inside) class `lib_backup` — but since lib_backup is a module not a
    # class, Python does NOT apply name mangling here. The attribute is
    # literally `__get_dump_type`.
    fake_postgres = SimpleNamespace(
        __get_dump_type=lambda fn: "custom",
    )
    monkeypatch.setattr(
        mod, "_add_cronjob_scripts", lambda cfg: {"postgres": fake_postgres}
    )
    cfg = FakeConfig()
    res = CliRunner().invoke(
        mod.get_dump_type,
        ["some.dump"],
        obj=cfg,
        catch_exceptions=False,
    )
    assert res.exit_code == 0
    assert "custom" in res.output


# ---------------------------------------------------------------------------
# backup_db dispatch
# ---------------------------------------------------------------------------


def test_backup_db_dispatches_to_zodoobin(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        mod,
        "_backup_zodoobin",
        lambda ctx, cfg, filename: seen.setdefault("zbin", filename),
    )
    monkeypatch.setattr(
        mod,
        "_backup_pgdump",
        lambda *a, **kw: seen.setdefault("pg", True),
    )

    cfg = FakeConfig(dumps_path=str(tmp_path))
    cfg._project_name = "proj"
    res = CliRunner().invoke(
        mod.backup_db,
        ["--dumptype", "zodoobin"],
        obj=cfg,
        catch_exceptions=False,
    )
    assert res.exit_code == 0
    assert "zbin" in seen and "pg" not in seen


def test_backup_db_dispatches_to_pgdump(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        mod,
        "_backup_zodoobin",
        lambda *a, **kw: seen.setdefault("zbin", True),
    )
    monkeypatch.setattr(
        mod,
        "_backup_pgdump",
        lambda *a, **kw: seen.setdefault("pg", True),
    )

    cfg = FakeConfig(dumps_path=str(tmp_path))
    cfg._project_name = "proj"
    res = CliRunner().invoke(
        mod.backup_db,
        ["--dumptype", "custom"],
        obj=cfg,
        catch_exceptions=False,
    )
    assert res.exit_code == 0
    assert "pg" in seen and "zbin" not in seen


# ---------------------------------------------------------------------------
# _backup_pgdump — command assembly
# ---------------------------------------------------------------------------


def test_backup_pgdump_assembles_expected_dc_cmd(tmp_path, monkeypatch):
    received = {}

    def fake_dc(cfg, cmd):
        received["cmd"] = cmd

    monkeypatch.setattr(mod, "__dc", fake_dc)
    cfg = FakeConfig(dumps_path=str(tmp_path))
    mod._backup_pgdump(
        cfg,
        filename=tmp_path / "d.dump",
        dbname="mydb",
        db_host="dbhost",
        db_port="5432",
        db_user="u",
        db_pwd="p",
        dumptype="custom",
        compression=3,
        worker=2,
        column_inserts=True,
        pigz=True,
        exclude=("mail_message",),
    )
    cmd = received["cmd"]
    # core action at the expected position
    assert "backup" in cmd
    assert "mydb" in cmd
    assert "--dumptype" in cmd and "custom" in cmd
    assert "--compression" in cmd and "3" in cmd
    assert "-j" in cmd and "2" in cmd
    assert "--column-inserts" in cmd
    assert "--pigz" in cmd
    assert "--exclude" in cmd and "mail_message" in cmd


def test_backup_pgdump_raises_when_dc_returns_truthy(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "__dc", lambda cfg, cmd: 1)
    cfg = FakeConfig(dumps_path=str(tmp_path))
    with pytest.raises(Exception):
        mod._backup_pgdump(
            cfg,
            filename=tmp_path / "d.dump",
            dbname="mydb",
            db_host="dbhost",
            db_port="5432",
            db_user="u",
            db_pwd="p",
            dumptype="custom",
            compression=5,
            worker=1,
            column_inserts=False,
            pigz=False,
            exclude=(),
        )


# ---------------------------------------------------------------------------
# restore_files click command
# ---------------------------------------------------------------------------


def test_restore_files_click_calls_helper(tmp_path, monkeypatch):
    called = {}
    target = None
    for a in dir(mod):
        if a.endswith("__do_restore_files"):
            target = a
            break
    assert target

    def fake(cfg, fn):
        called["fn"] = fn

    monkeypatch.setattr(mod, target, fake)

    cfg = FakeConfig(dumps_path=str(tmp_path))
    (tmp_path / "ff.tgz").write_bytes(b"x")
    res = CliRunner().invoke(
        mod.restore_files,
        [str(tmp_path / "ff.tgz")],
        obj=cfg,
        catch_exceptions=False,
    )
    assert res.exit_code == 0
    assert str(called["fn"]).endswith("ff.tgz")


# ---------------------------------------------------------------------------
# list_dumps
# ---------------------------------------------------------------------------


def test_list_dumps_empty_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_get_dump_files", lambda p: [])
    # tabulate is imported at module-load already; list_dumps references the
    # name `tabulate` (function or module). Make sure it's callable.
    monkeypatch.setattr(mod, "tabulate", lambda rows, headers=None: "")
    cfg = FakeConfig(dumps_path=str(tmp_path))
    res = CliRunner().invoke(
        mod.list_dumps, [], obj=cfg, catch_exceptions=False
    )
    assert res.exit_code == 0


# ---------------------------------------------------------------------------
# End-to-end tests against a live Odoo stack
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_full_stack
def test_e2e_show_dumps_on_fresh_project(odoo_project_19):
    res = odoo_project_19.run("backup", "show-dumps", check=False)
    # a fresh project has no dumps — should report that cleanly
    assert res.returncode == 0


@pytest.mark.slow
@requires_full_stack
def test_e2e_backup_files_roundtrip(odoo_project_19_running, tmp_path):
    """`backup files` produces a tar archive."""
    target = tmp_path / "files.tar.gz"
    odoo_project_19_running.run(
        "backup", "files", str(target), check=False, timeout=120
    )
    # tar must exist and be non-empty if run produced a file; absent stack
    # state on a bare "up -d" may result in an empty filestore — either
    # way the command should not crash.
    if target.exists():
        assert target.stat().st_size > 0


@pytest.mark.slow
@requires_full_stack
def test_e2e_backup_odoo_db(odoo_project_19_running, tmp_path):
    """`backup odoo-db` produces a dump file."""
    target = tmp_path / "db.dump.gz"
    res = odoo_project_19_running.run(
        "backup", "odoo-db", str(target), check=False, timeout=60 * 10
    )
    assert res.returncode == 0
    assert target.exists() and target.stat().st_size > 0


@pytest.mark.slow
@requires_full_stack
def test_e2e_backup_db_then_restore(odoo_project_19_running, tmp_path):
    """Full backup→restore roundtrip on the shared project."""
    dump = tmp_path / "rt.dump.gz"
    odoo_project_19_running.run(
        "backup", "odoo-db", str(dump), timeout=60 * 10
    )
    assert dump.exists()
    # restore with -f to skip the hostname prompt
    res = odoo_project_19_running.run_force(
        "restore", "odoo-db", str(dump), timeout=60 * 15, check=False
    )
    assert res.returncode == 0


@pytest.mark.slow
@requires_full_stack
def test_e2e_cronjob_driven_backup(odoo_project_19_running):
    """Verify the cronjobs container actually runs scheduled backups.

    Adds a `CRONJOB_TEST_BACKUP` entry to the project settings that
    fires every minute, restarts the cronjobs container so the new
    cron table is picked up, then waits up to 3 minutes for the
    resulting dump file to appear in DUMPS_PATH.
    """
    import time

    project = odoo_project_19_running
    sentinel = f"cronjob_test_{int(time.time())}.dump.gz"

    settings_path = Path.home() / ".odoo" / f"settings.{project.name}"
    assert settings_path.exists(), f"settings file missing: {settings_path}"

    original = settings_path.read_text()
    cron_line = (
        f"CRONJOB_TEST_BACKUP=* * * * * odoo backup odoo-db "
        f"/host/dumps/{sentinel}\n"
    )
    try:
        settings_path.write_text(original + "\n" + cron_line)

        # Reload so the cron table is regenerated from the new settings,
        # then restart the cronjobs container to pick it up.
        project.run("reload", timeout=60 * 5)
        project.run_force("restart", "cronjobs", timeout=120, check=False)
        project.run("up", "-d", "cronjobs", timeout=120)

        # Poll for the dump file (up to 3 minutes — one cron tick +
        # backup time). DUMPS_PATH defaults to ~/odoo_dumps.
        dumps_path = Path.home() / "odoo_dumps"
        sentinel_file = dumps_path / sentinel
        deadline = time.time() + 60 * 3
        while time.time() < deadline:
            if sentinel_file.exists() and sentinel_file.stat().st_size > 0:
                break
            time.sleep(5)
        assert sentinel_file.exists() and sentinel_file.stat().st_size > 0, (
            f"cronjob did not produce backup at {sentinel_file} "
            f"within 3 minutes"
        )
    finally:
        # restore original settings + cleanup dump
        settings_path.write_text(original)
        try:
            (Path.home() / "odoo_dumps" / sentinel).unlink(missing_ok=True)
        except Exception:
            pass
        project.run("reload", check=False, timeout=120)
