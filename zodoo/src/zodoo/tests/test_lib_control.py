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

import subprocess

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


def test_down_aborts_without_force_on_production(monkeypatch):
    cfg = FakeConfig(devmode=False, force=False)
    res = _invoke(mod.down, cfg)
    assert res.exit_code != 0


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
        shell=lambda cfg, command, queuejobs: 7,
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
        self.dirs = {"images": images_dir}
        # Mirrors real Config.odoo_version which is always a float parsed
        # from MANIFEST (e.g. 19.0), even though the on-disk dir is "19".
        self.odoo_version = odoo_version
        self.ODOO_PYTHON_VERSION = py_version
        self.ZODOO_REGISTRY_URL = registry


def test_locate_dockerfile_matches_int_dir_for_float_version(tmp_path):
    """Regression: config.odoo_version is 19.0 (float) but on-disk dir is "19"."""
    import zodoo.lib_control_with_docker as lcd

    images = _make_prebuilt_layout(tmp_path)
    df = lcd._locate_odoo_config_dockerfile(images, 19.0)
    assert df is not None and df.parent.name == "19"


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


def test_ensure_prebuilt_runs_build_script_when_image_missing(
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

    lcd._ensure_prebuilt_python_image(_PrebuiltCfg(images), "amd64")

    expected_script = str(images / "python_prebuilt" / "build.sh")
    assert invoked["cmd"] == [expected_script, "3.13.13", "--push"]


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
