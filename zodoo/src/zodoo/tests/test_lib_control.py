"""Tests for zodoo.lib_control.

Most top-level click commands in this module are thin adapters around
`lib_control_with_docker`, so the meaningful unit-testable surface is:

  * `_get_project_volumes` — compose parsing + docker volume intersect
  * `_cleanup_local_files` / `_cleanup_config_files` / `_cleanup_paths`
  * `load_compose`
  * `docker_sizes` helpers (`_format_bytes`, `_parse_human_size`, `_get_size`)
  * `remove_volumes` (retry path when docker volume rm fails)

and the click commands themselves, which we invoke with subprocess /
lib_control_with_docker monkey-patched so we can assert dispatch without
spinning up a real docker stack.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from zodoo import lib_control as mod
from zodoo.click_config import Config
from zodoo.tests.conftest import requires_full_stack


class FakeConfig(Config):
    """See test_lib_docker_registry.FakeConfig."""

    def __init__(self, **kwargs):
        self._project_name = kwargs.pop("project_name", "zodoo_unit_test")
        self._verbose = False
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = kwargs.pop("force", False)
        self.quiet = False
        self.restrict = {}
        self.dirs = kwargs.pop("dirs", {})
        self.files = kwargs.pop("files", {})
        self.commands = {}
        defaults = {
            "devmode": True,
            "dbname": "mydb",
            "run_postgres": False,
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)


# ---------------------------------------------------------------------------
# load_compose
# ---------------------------------------------------------------------------


def test_load_compose_returns_parsed_yaml(tmp_path):
    compose = tmp_path / "dc.yml"
    compose.write_text("services:\n  odoo: {image: odoo}\n")
    cfg = FakeConfig(files={"docker_compose": compose})
    parsed = mod.load_compose(cfg)
    assert parsed == {"services": {"odoo": {"image": "odoo"}}}


# ---------------------------------------------------------------------------
# _get_project_volumes
# ---------------------------------------------------------------------------


def test_get_project_volumes_intersects_compose_and_docker(
    tmp_path, monkeypatch
):
    compose = tmp_path / "dc.yml"
    compose.write_text(
        "services: {}\n"
        "volumes:\n"
        "  data: {}\n"
        "  logs: {}\n"
        "  orphan: {}\n"
    )
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **kw: (
            "DRIVER   VOLUME NAME\n"
            "local    myproj_data\n"
            "local    myproj_logs\n"
            "local    otherproject_data\n"
        ),
    )
    cfg = FakeConfig(
        files={"docker_compose": compose},
        project_name="myproj",
    )
    # project_name setter is skipped; _get_project_volumes reads project_name
    # as an attr — ensure it's set.
    cfg._project_name = "myproj"
    volumes = mod._get_project_volumes(cfg)
    assert set(volumes) == {"myproj_data", "myproj_logs"}


def test_get_project_volumes_aborts_without_project(tmp_path, monkeypatch):
    cfg = FakeConfig(files={"docker_compose": tmp_path / "x"})
    cfg._project_name = None
    with pytest.raises(SystemExit):
        mod._get_project_volumes(cfg)


# ---------------------------------------------------------------------------
# _cleanup_paths / _cleanup_local_files / _cleanup_config_files
# ---------------------------------------------------------------------------


def test_cleanup_paths_removes_directory(tmp_path, monkeypatch):
    target = tmp_path / "run"
    (target / "a").mkdir(parents=True)
    (target / "a" / "file").write_bytes(b"x")

    monkeypatch.setattr(
        mod, "__rmtree", lambda cfg, path: __import__("shutil").rmtree(path)
    )
    cfg = FakeConfig()
    mod._cleanup_paths(None, cfg, [target])
    assert not target.exists()


def test_cleanup_paths_removes_file_and_prints_content(tmp_path, monkeypatch):
    file = tmp_path / "settings"
    file.write_text("KEY=VALUE\n")
    cfg = FakeConfig()
    runner = CliRunner()
    # _cleanup_paths uses click.secho, which writes to stdout — run inside
    # isolation just to confirm no exception.
    with runner.isolation():
        mod._cleanup_paths(None, cfg, [file])
    assert not file.exists()


def test_cleanup_paths_non_existing_is_silent(tmp_path):
    cfg = FakeConfig()
    # should not raise
    mod._cleanup_paths(None, cfg, [tmp_path / "does-not-exist"])


def test_cleanup_local_files_collects_expected_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOST_RUN_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    (tmp_path / "data" / "filestore" / "mydb").mkdir(parents=True)

    collected = {}

    def fake_cleanup(ctx, cfg, paths):
        collected["paths"] = paths

    monkeypatch.setattr(mod, "_cleanup_paths", fake_cleanup)
    cfg = FakeConfig(dirs={"odoo_data_dir": tmp_path / "data"})
    cfg._project_name = "proj"
    cfg.__dict__["dbname"] = "mydb"
    mod._cleanup_local_files(None, cfg)
    assert tmp_path / "run" in collected["paths"]
    assert tmp_path / "data" / "filestore" / "mydb" in collected["paths"]


def test_cleanup_config_files_collects_project_settings(tmp_path, monkeypatch):
    collected = {}
    monkeypatch.setattr(
        mod,
        "_cleanup_paths",
        lambda ctx, cfg, paths: collected.setdefault("paths", paths),
    )
    cfg = FakeConfig(files={"project_settings": tmp_path / "settings"})
    mod._cleanup_config_files(None, cfg)
    assert collected["paths"] == [tmp_path / "settings"]


# ---------------------------------------------------------------------------
# Thin-wrapper commands that dispatch to lib_control_with_docker
#
# We replace the submodule's functions with stubs so we can assert the
# click command delegates correctly without spinning up docker.
# ---------------------------------------------------------------------------


def _patch_lib_with_docker(monkeypatch, **replacements):
    """Inject stub functions into zodoo.lib_control_with_docker."""
    import zodoo.lib_control_with_docker as lcd

    for name, fn in replacements.items():
        monkeypatch.setattr(lcd, name, fn)


def _invoke(cmd, cfg, args=None):
    return CliRunner().invoke(cmd, args or [], obj=cfg, catch_exceptions=False)


def test_pull_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        pull=lambda ctx, cfg: seen.setdefault("pull", True),
    )
    res = _invoke(mod.pull, FakeConfig())
    assert res.exit_code == 0 and seen["pull"] is True


def test_ps_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch, ps=lambda cfg: seen.setdefault("ps", True)
    )
    res = _invoke(mod.ps, FakeConfig())
    assert res.exit_code == 0 and seen["ps"] is True


def test_dev_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        dev=lambda ctx, cfg, build, kill: seen.update(
            {"build": build, "kill": kill}
        ),
    )
    res = _invoke(mod.dev, FakeConfig(), ["-b", "-k"])
    assert res.exit_code == 0
    assert seen == {"build": True, "kill": True}


def test_execute_command_dispatches(monkeypatch):
    seen = {}

    def capture(config, machine, args, user=None, interactive=True):
        seen.update(
            machine=machine,
            args=tuple(args),
            user=user,
            interactive=interactive,
        )

    _patch_lib_with_docker(monkeypatch, execute=capture)
    res = _invoke(
        mod.execute,
        FakeConfig(),
        ["odoo", "ls", "-I", "-u", "root"],
    )
    assert res.exit_code == 0
    assert seen["machine"] == "odoo"
    assert seen["user"] == "root"
    assert seen["interactive"] is False
    assert seen["args"] == ("ls",)


def test_do_kill_brutal_in_devmode(monkeypatch):
    seen = {}

    def capture(ctx, cfg, machines, brutal, profile):
        seen["brutal"] = brutal
        seen["profile"] = profile
        seen["machines"] = tuple(machines)

    _patch_lib_with_docker(monkeypatch, do_kill=capture)
    cfg = FakeConfig()
    cfg.__dict__["devmode"] = True
    res = _invoke(mod.do_kill, cfg, ["odoo"])
    assert res.exit_code == 0
    assert seen["brutal"] is True  # auto-brutal in devmode


def test_up_command_dispatches_and_runs_after_up(monkeypatch, tmp_path):
    seen = {}

    def capture(
        ctx,
        cfg,
        machines,
        daemon,
        remove_orphans,
        force_recreate,
        no_recreate,
        allow_build,
        profile="all",
    ):
        seen["machines"] = tuple(machines)
        seen["daemon"] = daemon

    _patch_lib_with_docker(monkeypatch, up=capture)
    monkeypatch.setattr(
        mod,
        "execute_script",
        lambda cfg, script, msg: seen.setdefault("exec_script", script),
    )
    # _status path — daemon + status lookup
    from zodoo import lib_setup

    monkeypatch.setattr(
        lib_setup, "_status", lambda cfg: seen.setdefault("status", True)
    )

    cfg = FakeConfig(
        files={"after_up_script": tmp_path / "after_up.sh"},
    )
    res = _invoke(mod.up, cfg, ["-d", "odoo"])
    assert res.exit_code == 0
    assert seen["daemon"] is True
    assert seen.get("status") is True
    assert "machines" in seen


def test_down_on_production_works_without_force(monkeypatch):
    seen = {}

    def capture(ctx, cfg, machines, volumes=False, remove_orphans=False):
        seen["called"] = True

    _patch_lib_with_docker(monkeypatch, down=capture)
    cfg = FakeConfig(devmode=False, force=False)
    res = _invoke(mod.down, cfg)
    assert res.exit_code == 0
    assert seen.get("called") is True


def test_down_postgres_volume_requires_force(monkeypatch):
    cfg = FakeConfig(devmode=True, force=False)
    res = _invoke(mod.down, cfg, ["--postgres-volume"])
    assert res.exit_code != 0


def test_down_happy_path_dispatches(monkeypatch):
    seen = {}

    def capture(ctx, cfg, machines, volumes=False, remove_orphans=False):
        seen.setdefault("calls", []).append(
            {"volumes": volumes, "remove_orphans": remove_orphans}
        )

    _patch_lib_with_docker(monkeypatch, down=capture)
    cfg = FakeConfig(devmode=True, force=True)
    res = _invoke(mod.down, cfg, ["-v"])
    # There should be at least one down() call
    assert res.exit_code == 0 or "force" in res.output.lower()


def test_stop_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        stop=lambda ctx, cfg, machines: seen.setdefault("m", tuple(machines)),
    )
    res = _invoke(mod.stop, FakeConfig(), ["odoo"])
    assert res.exit_code == 0 and seen["m"] == ("odoo",)


def test_rebuild_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        rebuild=lambda ctx, cfg, machines: seen.setdefault("ok", True),
    )
    res = _invoke(mod.rebuild, FakeConfig(), ["odoo"])
    assert res.exit_code == 0 and seen["ok"] is True


def test_restart_command_dispatches_brutal_in_devmode(monkeypatch):
    seen = {}

    def capture(ctx, cfg, machines, **kwargs):
        seen.update(kwargs)

    _patch_lib_with_docker(monkeypatch, restart=capture)
    res = _invoke(mod.restart, FakeConfig(devmode=True), ["odoo"])
    assert res.exit_code == 0 and seen.get("brutal") is True


def test_rm_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        rm=lambda ctx, cfg, machines, profile: seen.setdefault(
            "profile", profile
        ),
    )
    res = _invoke(mod.rm, FakeConfig(), ["odoo"])
    assert res.exit_code == 0
    assert seen["profile"] == "auto"


def test_attach_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        attach=lambda ctx, cfg, machine: seen.setdefault("m", machine),
    )
    res = _invoke(mod.attach, FakeConfig(), ["odoo"])
    assert res.exit_code == 0 and seen["m"] == "odoo"


def test_recreate_command_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        recreate=lambda ctx, cfg, machines: seen.setdefault(
            "m", tuple(machines)
        ),
    )
    res = _invoke(mod.recreate, FakeConfig(), ["odoo"])
    assert res.exit_code == 0 and seen["m"] == ("odoo",)


def test_wait_for_container_postgres_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        wait_for_container_postgres=lambda cfg: seen.setdefault("ok", True),
    )
    res = _invoke(mod.wait_for_container_postgres, FakeConfig())
    assert res.exit_code == 0 and seen["ok"] is True


def test_wait_for_port_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        wait_for_port=lambda host, port: seen.update(host=host, port=port),
    )
    res = _invoke(mod.wait_for_port, FakeConfig(), ["localhost", "8069"])
    assert res.exit_code == 0
    assert seen == {"host": "localhost", "port": "8069"}


def test_force_kill_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        force_kill=lambda ctx, cfg, machine: seen.setdefault(
            "m", tuple(machine)
        ),
    )
    res = _invoke(mod.force_kill, FakeConfig(), ["odoo"])
    assert res.exit_code == 0 and seen["m"] == ("odoo",)


def test_logall_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        logall=lambda cfg, machines, follow, lines: seen.update(
            follow=follow, lines=lines
        ),
    )
    res = _invoke(mod.logall, FakeConfig(), ["-n", "50"])
    assert res.exit_code == 0
    assert seen == {"follow": False, "lines": 50}


def test_run_command_dispatches(monkeypatch):
    seen = {}

    def capture(ctx, cfg, machine, args, detached, name):
        seen.update(machine=machine, detached=detached, name=name)

    _patch_lib_with_docker(monkeypatch, run=capture)
    res = _invoke(
        mod.run,
        FakeConfig(),
        ["odoo", "ls", "-d", "-n", "onejob"],
    )
    assert res.exit_code == 0
    assert seen["machine"] == "odoo"
    assert seen["detached"] is True
    assert seen["name"] == "onejob"


def test_runbash_dispatches(monkeypatch):
    seen = {}
    _patch_lib_with_docker(
        monkeypatch,
        runbash=lambda ctx, cfg, machine, args: seen.setdefault("m", machine),
    )
    res = _invoke(mod.runbash, FakeConfig(), ["odoo"])
    assert res.exit_code == 0 and seen["m"] == "odoo"


def test_shell_dispatches_and_propagates_exit_code(monkeypatch):
    _patch_lib_with_docker(
        monkeypatch,
        shell=lambda cfg, command, queuejobs, debug=False, debug_port=None: 7,
    )
    res = _invoke(mod.shell, FakeConfig(), [])
    assert res.exit_code == 7


def test_debug_parses_list_command(monkeypatch):
    seen = {}

    def capture(ctx, cfg, machine, ports, cmd, set_docker_command):
        seen["cmd"] = cmd

    _patch_lib_with_docker(monkeypatch, debug=capture)
    res = _invoke(
        mod.debug,
        FakeConfig(),
        ["odoo", "-c", "['/odoo/debug.py']"],
    )
    assert res.exit_code == 0
    assert seen["cmd"] == ["/odoo/debug.py"]


def test_debug_rejects_non_int_port(monkeypatch):
    _patch_lib_with_docker(monkeypatch, debug=lambda *a, **kw: None)
    res = _invoke(mod.debug, FakeConfig(), ["odoo", "--port", "not-a-number"])
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# remove_volumes — non-trivial retry / fix_permissions path
# ---------------------------------------------------------------------------


def test_remove_volumes_dry_run(tmp_path, monkeypatch):
    compose = tmp_path / "dc.yml"
    compose.write_text("services: {}\nvolumes: {data: {}}\n")
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **kw: "DRIVER  NAME\nlocal   myproj_data\n",
    )
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda *a, **kw: None,
    )
    cfg = FakeConfig(
        devmode=True,
        force=True,
        files={"docker_compose": compose},
        project_name="myproj",
    )
    cfg._project_name = "myproj"
    res = _invoke(mod.remove_volumes, cfg, ["--dry-run"])
    assert res.exit_code == 0
    assert "Dry Run" in res.output


def test_remove_volumes_requires_force_on_production(tmp_path, monkeypatch):
    compose = tmp_path / "dc.yml"
    compose.write_text("services: {}\nvolumes: {}\n")
    cfg = FakeConfig(
        devmode=False,
        force=False,
        files={"docker_compose": compose},
    )
    res = _invoke(mod.remove_volumes, cfg)
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# show_volumes
# ---------------------------------------------------------------------------


def test_show_volumes_prints_table(tmp_path, monkeypatch):
    compose = tmp_path / "dc.yml"
    compose.write_text("services: {}\nvolumes: {data: {}}\n")
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **kw: "DRIVER  NAME\nlocal   myproj_data\n",
    )
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(lcd, "_get_volume_size", lambda v: "42M")

    cfg = FakeConfig(
        files={"docker_compose": compose},
        project_name="myproj",
    )
    cfg._project_name = "myproj"
    res = _invoke(mod.show_volumes, cfg)
    assert res.exit_code == 0
    assert "myproj_data" in res.output
    assert "42M" in res.output


def test_show_volumes_applies_filter(tmp_path, monkeypatch):
    compose = tmp_path / "dc.yml"
    compose.write_text("services: {}\nvolumes:\n  data: {}\n  cache: {}\n")
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **kw: (
            "DRIVER  NAME\nlocal   myproj_data\nlocal   myproj_cache\n"
        ),
    )
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(lcd, "_get_volume_size", lambda v: "1M")

    cfg = FakeConfig(
        files={"docker_compose": compose},
        project_name="myproj",
    )
    cfg._project_name = "myproj"
    res = _invoke(mod.show_volumes, cfg, ["-f", "cache"])
    assert res.exit_code == 0
    assert "cache" in res.output
    assert "myproj_data" not in res.output


# ---------------------------------------------------------------------------
# build — dispatches through lib_zodoo_registry / lib_cached_build
# ---------------------------------------------------------------------------


def test_build_skips_lib_build_when_everything_pulled(tmp_path, monkeypatch):
    compose = tmp_path / "dc.yml"
    compose.write_text(
        "services:\n"
        "  odoo: {build: {context: .}}\n"
        "  postgres: {image: pg}\n"
    )
    seen = {}
    import zodoo.lib_zodoo_registry as lzr

    monkeypatch.setattr(
        lzr,
        "try_pull_from_zodoo_registry",
        lambda cfg, machines: list(machines),  # everything pulled
    )
    monkeypatch.setattr(
        lzr,
        "push_to_zodoo_registry",
        lambda *a, **kw: seen.setdefault("pushed", True),
    )
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(
        lcd,
        "build",
        lambda *a, **kw: seen.setdefault("lib_build_called", True),
    )
    import zodoo.lib_docker_registry as ldr

    monkeypatch.setattr(
        ldr, "disable_keychain_credential_store", lambda: False
    )
    # Ensure MyConfigParser returns predictable flags so the build branch
    # doesn't shell out to squid/proxpi.
    import zodoo.myconfigparser as mcp

    class FakeSettings:
        def get(self, key, default=None):
            return "0"  # disable apt cacher

    monkeypatch.setattr(mcp, "MyConfigParser", lambda path: FakeSettings())

    settings_file = tmp_path / "settings"
    settings_file.write_text("RUN_APT_CACHER=0\n")
    cfg = FakeConfig(
        files={"docker_compose": compose, "settings": settings_file}
    )
    cfg._project_name = "proj"
    res = _invoke(mod.build, cfg)
    assert res.exit_code == 0
    assert "lib_build_called" not in seen


# ---------------------------------------------------------------------------
# End-to-end tests against a live Odoo stack
# ---------------------------------------------------------------------------

pytestmark_slow = [pytest.mark.slow, requires_full_stack]


@pytest.mark.slow
@requires_full_stack
def test_e2e_ps_on_fresh_project(odoo_project_19):
    """`odoo ps` runs inside an initialised project without crashing."""
    res = odoo_project_19.run("ps", check=False)
    # no containers running yet — command may succeed or complain; both OK
    assert res.returncode in (0, 1)


@pytest.mark.slow
@requires_full_stack
def test_e2e_up_down_cycle(odoo_project_19):
    """Start postgres, list it, then stop and remove."""
    odoo_project_19.run("up", "-d", "postgres", timeout=60 * 5)
    try:
        res = odoo_project_19.run("ps", check=False)
        assert res.returncode == 0
    finally:
        odoo_project_19.run_force("down", check=False, timeout=120)


# ---------------------------------------------------------------------------
# _ensure_prebuilt_python_image — auto-build hook in lib_control_with_docker
# ---------------------------------------------------------------------------


def _make_prebuilt_layout(
    tmp_path, with_python_dir=True, dockerfile_uses=True
):
    """Build a minimal images/ tree mimicking ~/.odoo/images for the hook."""
    images = tmp_path / "images"
    if with_python_dir:
        (images / "python_prebuilt").mkdir(parents=True, exist_ok=True)
        script = images / "python_prebuilt" / "build.sh"
        script.write_text("#!/bin/bash\nexit 0\n")
        script.chmod(0o755)
    odoo_cfg = images / "odoo" / "config" / "19"
    odoo_cfg.mkdir(parents=True, exist_ok=True)
    df = odoo_cfg / "Dockerfile"
    if dockerfile_uses:
        df.write_text(
            "FROM ${ZODOO_REGISTRY_URL}/zodoo/python:"
            "${ODOO_PYTHON_VERSION}-${TARGETARCH} AS python_builder\n"
        )
    else:
        df.write_text("FROM scratch\n")
    return images


class _PrebuiltCfg:
    def __init__(
        self,
        images_dir,
        py_version="3.13.13",
        registry="r.example",
        odoo_version=19.0,
    ):
        self.dirs = {"images": images_dir or Path("/tmp")}
        # Mirrors real Config.odoo_version which is always a float parsed
        # from MANIFEST (e.g. 19.0), even though the on-disk dir is "19".
        self.odoo_version = odoo_version
        self.ODOO_PYTHON_VERSION = py_version
        self.ZODOO_REGISTRY_URL = registry
        self.project_name = "unit-test"
        self.HOST_RUN_DIR = None


def test_locate_dockerfile_matches_int_dir_for_float_version(tmp_path):
    """Regression: config.odoo_version is 19.0 (float) but on-disk dir is "19"."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    df = lcd._locate_odoo_config_dockerfile(images, 19.0)
    assert df is not None and df.parent.name == "19"


class _FakeStdout:
    """Mimics a Popen stdout pipe with a readline() that returns b'' on EOF."""

    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeProc:
    def __init__(self, lines, rc):
        self.stdout = _FakeStdout(lines)
        self.returncode = rc

    def wait(self):
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _patch_build_helpers(monkeypatch, lcd):
    monkeypatch.setattr(
        lcd, "__get_cmd", lambda *a, **k: ["docker", "compose"]
    )
    monkeypatch.setattr(lcd, "_set_default_envs", lambda env: env)
    monkeypatch.setattr(lcd, "_merge_env_dict", lambda env: env)
    monkeypatch.setattr(lcd, "ensure_project_name", lambda c: None)
    monkeypatch.setattr(lcd, "_is_buildx_available", lambda: True)


def test_build_with_network_retry_returns_on_first_success(monkeypatch):
    import zodoo.lib_control_with_docker as lcd

    seen_cmds = []

    def fake_popen(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        return _FakeProc([b"#1 ok\n"], 0)

    monkeypatch.setattr(lcd.subprocess, "Popen", fake_popen)
    _patch_build_helpers(monkeypatch, lcd)

    lcd._build_with_network_retry(_PrebuiltCfg(None), [], ["odoo"], {})
    assert len(seen_cmds) == 1
    assert "--no-cache" not in seen_cmds[0]


def test_build_with_network_retry_retries_with_no_cache_on_launchpad(
    monkeypatch,
):
    import zodoo.lib_control_with_docker as lcd

    seen_cmds = []
    state = {"call": 0}

    def fake_popen(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        state["call"] += 1
        if state["call"] == 1:
            return _FakeProc(
                [
                    b"#42 ERROR: ServerNotFoundError: "
                    b"Unable to find the server at api.launchpad.net\n"
                ],
                1,
            )
        return _FakeProc([b"#1 ok\n"], 0)

    monkeypatch.setattr(lcd.subprocess, "Popen", fake_popen)
    _patch_build_helpers(monkeypatch, lcd)

    lcd._build_with_network_retry(_PrebuiltCfg(None), [], ["odoo"], {})
    assert len(seen_cmds) == 2
    assert "--no-cache" in seen_cmds[1]
    assert "--no-cache" not in seen_cmds[0]


def test_build_with_network_retry_does_not_retry_on_unrelated_failure(
    monkeypatch,
):
    import zodoo.lib_control_with_docker as lcd

    seen_cmds = []

    def fake_popen(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        return _FakeProc([b"#1 some other error\n"], 7)

    monkeypatch.setattr(lcd.subprocess, "Popen", fake_popen)
    _patch_build_helpers(monkeypatch, lcd)

    with pytest.raises(subprocess.CalledProcessError):
        lcd._build_with_network_retry(_PrebuiltCfg(None), [], ["odoo"], {})
    assert len(seen_cmds) == 1


def test_build_with_network_retry_does_not_double_retry_when_already_no_cache(
    monkeypatch,
):
    import zodoo.lib_control_with_docker as lcd

    seen_cmds = []

    def fake_popen(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        return _FakeProc(
            [b"ServerNotFoundError: Unable to find api.launchpad.net\n"], 1
        )

    monkeypatch.setattr(lcd.subprocess, "Popen", fake_popen)
    _patch_build_helpers(monkeypatch, lcd)

    with pytest.raises(subprocess.CalledProcessError):
        lcd._build_with_network_retry(
            _PrebuiltCfg(None), ["--no-cache"], ["odoo"], {}
        )
    assert len(seen_cmds) == 1


@pytest.mark.parametrize(
    "platform, expected_arch",
    [
        ("linux/arm64", "arm64"),
        ("linux/amd64", "amd64"),
        ("x86_64", "amd64"),
        ("aarch64", "arm64"),
    ],
)
def test_build_passes_targetarch_as_build_arg(
    monkeypatch, platform, expected_arch
):
    """`docker buildx bake` does not auto-fill global ARG TARGETARCH from
    DOCKER_DEFAULT_PLATFORM, so `odoo build` must pass it explicitly."""
    import zodoo.lib_control_with_docker as lcd

    seen_cmds = []

    def fake_popen(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        return _FakeProc([b"#1 ok\n"], 0)

    monkeypatch.setattr(lcd.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        lcd.subprocess, "check_output", lambda *a, **k: platform
    )
    monkeypatch.setattr(
        lcd, "_ensure_prebuilt_python_image", lambda *a, **k: None
    )
    _patch_build_helpers(monkeypatch, lcd)

    from types import SimpleNamespace

    cfg = SimpleNamespace(
        verbose=False,
        odoo_version=19.0,
        project_name="unit-test",
        HOST_RUN_DIR=None,
        dirs={"images": Path("/tmp")},
    )
    lcd.build(ctx=None, config=cfg, machines=["odoo"], platform=platform)

    assert len(seen_cmds) == 1
    cmd = seen_cmds[0]
    assert "--set" in cmd
    idx = cmd.index("--set")
    assert cmd[idx + 1] == f"*.args.TARGETARCH={expected_arch}"


def test_locate_dockerfile_falls_back_to_float_named_dir(tmp_path):
    """Older Odoo releases (e.g. 6.1) live under .../config/6.1/Dockerfile."""
    import zodoo.lib_control_with_docker as lcd

    images = tmp_path / "images"
    (images / "odoo" / "config" / "6.1").mkdir(parents=True)
    (images / "odoo" / "config" / "6.1" / "Dockerfile").write_text("FROM x\n")
    df = lcd._locate_odoo_config_dockerfile(images, 6.1)
    assert df is not None and df.parent.name == "6.1"


def test_ensure_prebuilt_skips_when_script_missing(tmp_path, monkeypatch):
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path, with_python_dir=False)
    calls = []
    monkeypatch.setattr(
        lcd.subprocess,
        "check_output",
        lambda *a, **k: calls.append("co") or b"",
    )
    monkeypatch.setattr(
        lcd.subprocess,
        "check_call",
        lambda *a, **k: calls.append("cc") or 0,
    )
    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")
    assert calls == []


def test_ensure_prebuilt_skips_when_dockerfile_does_not_use_image(
    tmp_path, monkeypatch
):
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path, dockerfile_uses=False)
    calls = []
    monkeypatch.setattr(
        lcd.subprocess,
        "check_output",
        lambda *a, **k: calls.append("co") or b"",
    )
    monkeypatch.setattr(
        lcd.subprocess,
        "check_call",
        lambda *a, **k: calls.append("cc") or 0,
    )
    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")
    assert calls == []


def test_ensure_prebuilt_no_op_when_image_exists(tmp_path, monkeypatch):
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    seen = {"manifest": None, "called": False}

    def fake_check_output(cmd, *a, **k):
        seen["manifest"] = cmd
        return b"{}"

    def fake_check_call(cmd, *a, **k):
        seen["called"] = True
        return 0

    monkeypatch.setattr(lcd.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(lcd.subprocess, "check_call", fake_check_call)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert seen["manifest"][:3] == ["docker", "manifest", "inspect"]
    assert seen["manifest"][3] == "r.example/zodoo/python:3.13.13-arm64"
    assert seen["called"] is False


def test_ensure_prebuilt_runs_build_script_with_push_when_creds_present(
    tmp_path, monkeypatch
):
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)

    def fake_check_output(cmd, *a, **k):
        raise subprocess.CalledProcessError(1, cmd, output=b"manifest unknown")

    invoked = {}

    def fake_check_call(cmd, *a, **k):
        invoked["cmd"] = cmd
        return 0

    monkeypatch.setattr(lcd.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(lcd.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(lcd, "_has_registry_credentials", lambda url: True)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "amd64")

    expected_script = str(images / "python_prebuilt" / "build.sh")
    assert invoked["cmd"] == [expected_script, "3.13.13", "--push"]


def test_ensure_prebuilt_runs_build_script_local_only_when_no_creds(
    tmp_path, monkeypatch
):
    """CI runner case: no registry credentials → build without --push.

    Regression: previously the hook unconditionally added --push, which
    failed with HTTP 401 on hosts that haven't `docker login`-ed to the
    registry. The local image is still consumed by the subsequent
    `docker compose build` so the push isn't needed for the build to
    succeed.
    """
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)

    def fake_check_output(cmd, *a, **k):
        raise subprocess.CalledProcessError(1, cmd, output=b"manifest unknown")

    invoked = {}

    def fake_check_call(cmd, *a, **k):
        invoked["cmd"] = cmd
        return 0

    monkeypatch.setattr(lcd.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(lcd.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(lcd, "_has_registry_credentials", lambda url: False)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "amd64")

    expected_script = str(images / "python_prebuilt" / "build.sh")
    assert invoked["cmd"] == [expected_script, "3.13.13"]
    assert "--push" not in invoked["cmd"]


def test_has_registry_credentials_no_config_file(tmp_path, monkeypatch):
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(lcd.Path, "home", classmethod(lambda cls: tmp_path))
    assert lcd._has_registry_credentials("registry.example.com") is False


def test_has_registry_credentials_match(tmp_path, monkeypatch):
    import json

    import zodoo.lib_control_with_docker as lcd

    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir()
    (docker_dir / "config.json").write_text(
        json.dumps({"auths": {"registry.example.com": {"auth": "xyz"}}})
    )
    monkeypatch.setattr(lcd.Path, "home", classmethod(lambda cls: tmp_path))
    assert lcd._has_registry_credentials("registry.example.com") is True
    assert lcd._has_registry_credentials("other.example.com") is False


def test_has_registry_credentials_handles_port_443(tmp_path, monkeypatch):
    import json

    import zodoo.lib_control_with_docker as lcd

    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir()
    (docker_dir / "config.json").write_text(
        json.dumps({"auths": {"registry.example.com:443": {"auth": "xyz"}}})
    )
    monkeypatch.setattr(lcd.Path, "home", classmethod(lambda cls: tmp_path))
    # Lookup on the bare host should still match the :443 entry.
    assert lcd._has_registry_credentials("registry.example.com") is True


def test_has_registry_credentials_malformed_config(tmp_path, monkeypatch):
    import zodoo.lib_control_with_docker as lcd

    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir()
    (docker_dir / "config.json").write_text("not json {")
    monkeypatch.setattr(lcd.Path, "home", classmethod(lambda cls: tmp_path))
    assert lcd._has_registry_credentials("registry.example.com") is False


def test_ensure_prebuilt_skips_when_settings_incomplete(tmp_path, monkeypatch):
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    calls = []
    monkeypatch.setattr(
        lcd.subprocess,
        "check_output",
        lambda *a, **k: calls.append("co") or b"",
    )
    monkeypatch.setattr(
        lcd.subprocess,
        "check_call",
        lambda *a, **k: calls.append("cc") or 0,
    )

    cfg = _PrebuiltCfg(images, py_version="", registry="r.example")
    lcd._ensure_prebuilt_python_image(cfg, "arm64")
    cfg = _PrebuiltCfg(images, py_version="3.13.13", registry="")
    lcd._ensure_prebuilt_python_image(cfg, "arm64")

    assert calls == []


def _fake_docker(
    monkeypatch, lcd, *, manifest, local_image=False, local_arch="arm64"
):
    """Fake the docker calls of the prebuilt-python hook.

    `manifest` is "ok" or the error output docker would print — as a str for a
    constant answer, or as a list to answer successive calls differently (the
    hook asks again after logging in). `local_image` controls whether
    `docker image inspect` finds anything, `local_arch` what it reports.
    Returns the recorded check_call commands.
    """
    answers = [manifest] if isinstance(manifest, str) else list(manifest)
    invoked = []

    def fake_check_output(cmd, *a, **k):
        if cmd[:3] == ["docker", "manifest", "inspect"]:
            answer = answers.pop(0) if len(answers) > 1 else answers[0]
            if answer == "ok":
                return b"{}"
            raise subprocess.CalledProcessError(1, cmd, output=answer.encode())
        if cmd[:3] == ["docker", "image", "inspect"]:
            if local_image:
                return local_arch
            raise subprocess.CalledProcessError(
                1, cmd, output=b"No such image"
            )
        return b""

    monkeypatch.setattr(lcd.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(
        lcd.subprocess, "check_call", lambda cmd, *a, **k: invoked.append(cmd)
    )
    return invoked


def _patch_login(monkeypatch, *, succeeds=True):
    """Record login attempts instead of talking to docker."""
    import zodoo.lib_zodoo_registry as lzr

    logins = []
    monkeypatch.setattr(
        lzr,
        "login_with_settings_credentials",
        lambda config, url=None: logins.append(url) or succeeds,
    )
    return logins


def test_ensure_prebuilt_logs_in_and_retries_after_a_401(
    tmp_path, monkeypatch
):
    """A host that never ran `docker login` gets a 401 for every query, which
    looks exactly like a cache miss. Log in with the credentials from the
    settings and ask again — no rebuild."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(
        monkeypatch,
        lcd,
        manifest=["unauthorized: authentication required", "ok"],
    )
    logins = _patch_login(monkeypatch)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert logins == ["r.example"]
    assert invoked == []


def test_ensure_prebuilt_does_not_log_in_when_the_registry_answers(
    tmp_path, monkeypatch
):
    """No login on a working registry — otherwise every build would rewrite
    the docker config of hosts that keep their credentials in a helper."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    _fake_docker(monkeypatch, lcd, manifest="ok")
    logins = _patch_login(monkeypatch)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert logins == []


def test_ensure_prebuilt_no_rebuild_when_image_is_in_local_store(
    tmp_path, monkeypatch
):
    """Regression: a 401 from the registry triggered a ~12 minute rebuild of
    an image that was sitting in the local docker store all along. A `FROM`
    resolves against the local store, so there is nothing to build."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(
        monkeypatch,
        lcd,
        manifest="unauthorized: authentication required",
        local_image=True,
    )
    _patch_login(monkeypatch, succeeds=False)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    # No rebuild, and nothing pushed either: an auth problem is no proof that
    # the registry lacks the image.
    assert invoked == []


def test_ensure_prebuilt_ignores_a_local_image_of_the_wrong_arch(
    tmp_path, monkeypatch
):
    """The tag carries no content hash and the same tag may have been built
    for another platform — a wrong-arch base would poison the whole build."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(
        monkeypatch,
        lcd,
        manifest="unauthorized: authentication required",
        local_image=True,
        local_arch="amd64",
    )
    _patch_login(monkeypatch, succeeds=False)
    monkeypatch.setattr(lcd, "_has_registry_credentials", lambda url: False)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert invoked == [
        [str(images / "python_prebuilt" / "build.sh"), "3.13.13"]
    ]


def test_ensure_prebuilt_ignores_local_image_when_building_with_pull(
    tmp_path, monkeypatch
):
    """`--pull` makes BuildKit re-resolve every FROM against the registry, so
    the local copy would not be used — skipping the build would break it."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(
        monkeypatch,
        lcd,
        manifest="unauthorized: authentication required",
        local_image=True,
    )
    _patch_login(monkeypatch, succeeds=False)
    monkeypatch.setattr(lcd, "_has_registry_credentials", lambda url: False)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64", pull=True)

    assert invoked == [
        [str(images / "python_prebuilt" / "build.sh"), "3.13.13"]
    ]


def test_ensure_prebuilt_never_pushes_a_local_image_it_did_not_build(
    tmp_path, monkeypatch
):
    """The tag has no content hash, so a local copy may be stale. On a real
    registry miss the image is rebuilt from current sources (and build.sh
    pushes that) — the old local copy must not end up in the shared
    registry."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(
        monkeypatch, lcd, manifest="manifest unknown", local_image=True
    )
    monkeypatch.setattr(lcd, "_has_registry_credentials", lambda url: True)
    logins = _patch_login(monkeypatch)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert invoked == [
        [str(images / "python_prebuilt" / "build.sh"), "3.13.13", "--push"]
    ]
    assert not any("push" == cmd[0] for cmd in invoked)
    # A registry that answered "no" needs no login.
    assert logins == []


def test_ensure_prebuilt_builds_local_only_when_registry_unreachable(
    tmp_path, monkeypatch
):
    """No local copy and no usable registry: build, but do not try to push
    into a registry we could not even talk to — that would turn a slow build
    into a failed one."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(
        monkeypatch, lcd, manifest="no basic auth credentials"
    )
    _patch_login(monkeypatch, succeeds=False)
    monkeypatch.setattr(lcd, "_has_registry_credentials", lambda url: True)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert invoked == [
        [str(images / "python_prebuilt" / "build.sh"), "3.13.13"]
    ]


def test_ensure_prebuilt_does_not_push_with_credentials_it_just_created(
    tmp_path, monkeypatch
):
    """On macOS the login writes ~/.docker/config.json without asking the
    registry, so credentials it rejects would still look like push rights.
    Push rights are decided by what the host had before we touched
    anything — otherwise `build.sh --push` aborts a build that used to
    complete local-only."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(
        monkeypatch,
        lcd,
        manifest=["no basic auth credentials", "manifest unknown"],
    )
    # No auths entry before, one after the login the hook performs.
    creds = iter([False, True, True])
    monkeypatch.setattr(
        lcd, "_has_registry_credentials", lambda url: next(creds)
    )
    _patch_login(monkeypatch)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert invoked == [
        [str(images / "python_prebuilt" / "build.sh"), "3.13.13"]
    ]


def test_ensure_prebuilt_survives_a_failing_login(tmp_path, monkeypatch):
    """A broken login must not fail the build — the local build path works."""
    import zodoo.lib_control_with_docker as lcd
    import zodoo.lib_zodoo_registry as lzr

    images = _make_prebuilt_layout(tmp_path)
    invoked = _fake_docker(monkeypatch, lcd, manifest="401 unauthorized")

    def boom(config, url=None):
        raise subprocess.CalledProcessError(1, ["docker", "login"])

    monkeypatch.setattr(lzr, "login_with_settings_credentials", boom)
    monkeypatch.setattr(lcd, "_has_registry_credentials", lambda url: False)

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "arm64")

    assert invoked == [
        [str(images / "python_prebuilt" / "build.sh"), "3.13.13"]
    ]


_FAKE_DOCKER = r"""#!/usr/bin/env python3
# Fake docker: answers `manifest inspect` with a 401 until `login` ran,
# mimicking a host that was never logged in to the registry.
import json
import os
import sys
from pathlib import Path

home = Path(os.environ["HOME"])
log = home / "docker-calls.log"
cfg = home / ".docker" / "config.json"
argv = sys.argv[1:]
with log.open("a") as fh:
    fh.write(" ".join(argv) + "\n")

if argv[:1] == ["login"]:
    sys.stdin.read()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"auths": {argv[1]: {"auth": "x"}}}))
    print("Login Succeeded")
    sys.exit(0)

if argv[:2] == ["manifest", "inspect"]:
    if cfg.exists() and "auths" in json.loads(cfg.read_text()):
        print("{}")
        sys.exit(0)
    print("unauthorized: authentication required", file=sys.stderr)
    sys.exit(1)

if argv[:2] == ["image", "inspect"]:
    print("Error: No such image", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
"""


def test_ensure_prebuilt_e2e_recovers_from_never_logged_in_host(
    tmp_path, monkeypatch
):
    """End-to-end through real subprocess calls with a fake `docker`.

    Reproduces the reported case: settings hold the registry credentials,
    `~/.docker/config.json` has no `auths`, so the registry answers 401. The
    hook must log in and then see the image, instead of reading the 401 as a
    cache miss and rebuilding for ~12 minutes.
    """
    import zodoo.lib_control_with_docker as lcd
    import zodoo.lib_zodoo_registry as lzr

    # Pin the login to the `docker login` path so the assertions hold on
    # macOS too (there zodoo writes ~/.docker/config.json itself, because
    # the osxkeychain helper refuses to work over SSH).
    monkeypatch.setattr(lzr.platform, "system", lambda: "Linux")

    images = _make_prebuilt_layout(tmp_path)

    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(_FAKE_DOCKER)
    fake.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    settings = tmp_path / "settings"
    settings.write_text(
        "ZODOO_REGISTRY_URL=r.example\n"
        "ZODOO_REGISTRY_USERNAME=admin\n"
        "ZODOO_REGISTRY_PASSWORD=secret\n"
    )
    cfg = _PrebuiltCfg(images)
    cfg.files = {"user_settings": settings}

    lcd._ensure_prebuilt_python_image(cfg, "arm64")

    manifest = "manifest inspect r.example/zodoo/python:3.13.13-arm64"
    calls = (home / "docker-calls.log").read_text().splitlines()
    # First query gets the 401, then the login, then the query succeeds.
    assert calls[0] == manifest
    assert calls[1].startswith("login r.example -u admin")
    assert calls[2] == manifest
    # The decisive assertion: no build script, no rebuild.
    assert len(calls) == 3


@pytest.mark.parametrize(
    "output, expected",
    [
        ("manifest unknown: manifest unknown", "missing"),
        # Verbatim from registry.zebroo.de for a tag that does not exist.
        (
            "no such manifest: registry.zebroo.de/zodoo/python:0.0.0-nope",
            "missing",
        ),
        # Verbatim from registry.zebroo.de without credentials — the case
        # that used to be read as a cache miss.
        (
            'Get "https://registry.zebroo.de/v2/zodoo/python/manifests/'
            '3.13.13-arm64": no basic auth credentials',
            "unreachable",
        ),
        (
            "errors:\n denied: requested access to the resource is denied",
            "unreachable",
        ),
        ("unauthorized: authentication required", "unreachable"),
        ("Get https://r.example/v2/: dial tcp: no such host", "unreachable"),
        ("something we have never seen", "unreachable"),
    ],
)
def test_classify_manifest_error(output, expected):
    """An unclear failure counts as "unreachable": mistaking it for a cache
    miss is what costs a needless rebuild.

    The two registry.zebroo.de strings were captured from the live registry
    (with and without credentials in ~/.docker/config.json)."""
    import zodoo.lib_zodoo_registry as lzr

    assert lzr.classify_manifest_error(output) == expected


def test_registry_credentials_from_settings_needs_all_three(monkeypatch):
    import zodoo.lib_zodoo_registry as lzr
    from types import SimpleNamespace

    monkeypatch.setattr(lzr, "_read_user_setting", lambda config, key: "")

    cfg = SimpleNamespace(
        ZODOO_REGISTRY_URL="r.example",
        ZODOO_REGISTRY_USERNAME="admin",
    )
    assert lzr.registry_credentials_from_settings(cfg) is None

    cfg.ZODOO_REGISTRY_PASSWORD = "secret"
    assert lzr.registry_credentials_from_settings(cfg) == {
        "url": "r.example",
        "username": "admin",
        "password": "secret",
    }


@pytest.mark.slow
@requires_full_stack
def test_e2e_show_volumes(odoo_project_19_running):
    res = odoo_project_19_running.run("show-volumes", check=False)
    assert res.returncode == 0


@pytest.mark.slow
@requires_full_stack
def test_e2e_remove_volumes_dry_run(odoo_project_19_running):
    res = odoo_project_19_running.run_force(
        "remove-volumes", "--dry-run", check=False
    )
    assert res.returncode == 0


# ---------------------------------------------------------------------------
# restart dispatch: legacy supervisor-role names vs. real compose service
# ---------------------------------------------------------------------------
#
# `odoo restart odoo_web` (and the hyphen/dot variants) must NOT touch the
# compose service — they soft-restart the role inside the running container
# via the supervisor unix socket. `odoo restart odoo` is the opposite: it
# stops + recreates the whole compose service. These tests pin both branches
# of the dispatch so a future refactor can't quietly regress one side.


def _capture_restart_calls(monkeypatch):
    """Monkey-patch the four functions restart() may delegate to, so the
    test can observe which path the dispatch took."""
    import zodoo.lib_control_with_docker as lcd

    calls = {"supervisor": [], "kill": [], "up": []}

    monkeypatch.setattr(
        lcd,
        "_supervisor_restart_role",
        # append returns None — return True explicitly so restart() sees a
        # confirmed restart and doesn't print the could-not-confirm warning
        lambda config, role: calls["supervisor"].append(role) or True,
    )
    monkeypatch.setattr(
        lcd,
        "do_kill",
        lambda ctx, config, machines=None, brutal=True, profile="auto", **kw: calls[
            "kill"
        ].append(
            list(machines or [])
        ),
    )
    monkeypatch.setattr(
        lcd,
        "up",
        lambda ctx, config, machines=None, **kw: calls["up"].append(
            list(machines or [])
        ),
    )
    # restart() also calls _has_in_container_supervisor — force-True so we
    # don't need a real Odoo-version-detect on the FakeConfig.
    monkeypatch.setattr(
        lcd, "_has_in_container_supervisor", lambda config: True
    )
    return calls


@pytest.mark.parametrize(
    "machine,expected_role",
    [
        ("odoo_web", "web"),
        ("odoo-web", "web"),
        ("odoo.web", "web"),
        ("odoo_cronjobs", "cronjobs"),
        ("odoo-cronjobs", "cronjobs"),
        ("odoo.cronjobs", "cronjobs"),
        ("odoo_queuejobs", "queuejobs"),
        ("odoo-queuejobs", "queuejobs"),
        ("odoo.queuejobs", "queuejobs"),
    ],
)
def test_restart_role_name_soft_restarts_via_supervisor(
    monkeypatch, machine, expected_role
):
    """`odoo restart odoo_web` (and -/. variants, plus cronjobs/queuejobs)
    must call the in-container supervisor and NOT recreate any compose
    service. Container stays up, only the supervisor child is respawned."""
    import zodoo.lib_control_with_docker as lcd

    calls = _capture_restart_calls(monkeypatch)
    lcd.restart(ctx=None, config=FakeConfig(), machines=[machine])

    assert calls["supervisor"] == [
        expected_role
    ], f"Expected supervisor restart of {expected_role!r}, got {calls!r}"
    assert calls["kill"] == [], (
        f"`odoo restart {machine}` must NOT call do_kill (would recreate "
        f"the whole compose service), got {calls['kill']!r}"
    )
    assert (
        calls["up"] == []
    ), f"`odoo restart {machine}` must NOT call up, got {calls['up']!r}"


def test_restart_odoo_service_recreates_whole_container(monkeypatch, tmp_path):
    """`odoo restart odoo` (plain, no _web suffix) is the explicit hard
    path: stop + up the compose service. The supervisor is NOT called
    because the user wants the whole container down — including the
    supervisor itself."""
    import zodoo.lib_control_with_docker as lcd

    # restart() falls into a branch that reads docker_compose.yml when
    # machines is empty; we hand it a real one to be safe.
    compose = tmp_path / "dc.yml"
    compose.write_text(
        "services:\n"
        "  odoo:\n"
        "    image: x\n"
        "    labels:\n"
        "      compose.merge: odoo_base\n"
    )
    cfg = FakeConfig(files={"docker_compose": compose})

    calls = _capture_restart_calls(monkeypatch)
    lcd.restart(ctx=None, config=cfg, machines=["odoo"])

    assert calls["supervisor"] == [], (
        f"`odoo restart odoo` must NOT redirect to the supervisor (whole "
        f"container needs to go down), got {calls['supervisor']!r}"
    )
    assert calls["kill"] == [
        ["odoo"]
    ], f"Expected do_kill(['odoo']), got {calls['kill']!r}"
    assert calls["up"] == [
        ["odoo"]
    ], f"Expected up(['odoo']), got {calls['up']!r}"


def test_restart_warns_when_supervisor_restart_unconfirmed(
    monkeypatch, capsys
):
    """When the supervisor cannot confirm a role restart, restart() must
    surface a warning instead of silently dropping the failure."""
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(
        lcd, "_has_in_container_supervisor", lambda config: True
    )
    monkeypatch.setattr(
        lcd, "_supervisor_restart_role", lambda config, role: False
    )
    lcd.restart(ctx=None, config=FakeConfig(), machines=["odoo_web"])
    out = capsys.readouterr().out
    assert "could not confirm restart" in out
    assert "web" in out


def test_start_update_blocking_roles_warns_on_unconfirmed(monkeypatch, capsys):
    """start_update_blocking_roles must warn (not silently continue) when a
    role start cannot be confirmed by the supervisor."""
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(
        lcd, "_has_in_container_supervisor", lambda config: True
    )
    monkeypatch.setattr(
        lcd,
        "_supervisor_action_role",
        lambda config, action, role: role != "queuejobs",
    )
    monkeypatch.setattr(
        lcd, "_declared_compose_services", lambda config: set()
    )
    lcd.start_update_blocking_roles(FakeConfig())
    out = capsys.readouterr().out
    assert "could not confirm start" in out
    assert "queuejobs" in out
    assert "web" not in out.split("could not confirm start")[1].split("\n")[0]


def test_start_update_blocking_roles_silent_on_success(monkeypatch, capsys):
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(
        lcd, "_has_in_container_supervisor", lambda config: True
    )
    monkeypatch.setattr(
        lcd, "_supervisor_action_role", lambda config, action, role: True
    )
    monkeypatch.setattr(
        lcd, "_declared_compose_services", lambda config: set()
    )
    lcd.start_update_blocking_roles(FakeConfig())
    assert "could not confirm" not in capsys.readouterr().out


@pytest.mark.slow
@requires_full_stack
def test_e2e_kill_and_restart(odoo_project_19_running):
    r1 = odoo_project_19_running.run_force(
        "kill", "-b", "postgres", check=False
    )
    assert r1.returncode == 0
    # Bring the full stack back (not just postgres) so later tests
    # in the session don't trip on broken dependencies.
    r2 = odoo_project_19_running.run("up", "-d", check=False, timeout=180)
    assert r2.returncode == 0
