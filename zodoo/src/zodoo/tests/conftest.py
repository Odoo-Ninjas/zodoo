"""Shared pytest fixtures for the zodoo test-suite.

The heavy `odoo_project_19` fixture runs `odoo src init 19.0` + `reload`
in a throwaway HOME exactly once per session — amortised across all tests
that exercise lib_control / lib_backup / lib_docker_registry against a
real docker stack.

If Docker / the `odoo` CLI is missing, the fixture is skipped; unit-only
tests continue to work because they don't depend on it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


def _has_docker() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def _has_odoo_cli() -> bool:
    return shutil.which("odoo") is not None


requires_full_stack = pytest.mark.skipif(
    not _has_docker() or not _has_odoo_cli(),
    reason="needs docker daemon and 'odoo' CLI on PATH",
)


def _run(cmd, *, cwd, env=None, timeout=None, check=True):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    cmd_str = " ".join(str(x) for x in cmd)
    print(f"\n$ {cmd_str}    (cwd={cwd})", flush=True)
    result = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        env=full_env,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", flush=True)
    if check and result.returncode != 0:
        raise AssertionError(
            f"Command failed (exit {result.returncode}): {cmd_str}\n"
            f"--- stdout (last 2000 chars) ---\n{(result.stdout or '')[-2000:]}\n"
            f"--- stderr (last 2000 chars) ---\n{(result.stderr or '')[-2000:]}"
        )
    return result


@dataclass
class OdooProject:
    """Handle for the shared 19.0 project built once per session."""

    name: str
    path: Path
    home: Path
    version: str = "19.0"

    def run(self, *args, check=True, timeout=None):
        """Run `odoo -p <name> <args...>` in the project dir."""
        return _run(
            ["odoo", "-p", self.name, *args],
            cwd=self.path,
            timeout=timeout,
            check=check,
        )

    def run_force(self, *args, check=True, timeout=None):
        """Run `odoo -f -p <name> <args...>` — bypasses confirmation prompts."""
        return _run(
            ["odoo", "-f", "-p", self.name, *args],
            cwd=self.path,
            timeout=timeout,
            check=check,
        )


def _resolve_images_dir() -> Path | None:
    """Locate the zodoo-images repo (contains templates/, cronjobs/, odoo/...).

    Resolution order:
      1. ZODOO_IMAGES_DIR env var (explicit override, useful in CI)
      2. ~/.odoo/images (the canonical install location)
      3. <repo>/../../../.. from this file (when tests live inside a
         checked-out images repo, i.e. zodoo/src/zodoo/tests/conftest.py)

    Returns None if nothing usable is found — callers that need it can
    skip the test.
    """
    override = os.environ.get("ZODOO_IMAGES_DIR")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    # canonical location used by install.sh
    candidates.append(Path.home() / ".odoo" / "images")
    # relative-to-checkout fallback (this file → images/zodoo/src/zodoo/tests/)
    candidates.append(Path(__file__).resolve().parents[4])

    for c in candidates:
        if (c / "templates" / "customs_template").is_dir():
            return c
    return None


@pytest.fixture(scope="session")
def _session_home(tmp_path_factory):
    """Session-scoped HOME.

    Previously this tried to fully isolate HOME with symlinks for
    ``~/.odoo/images``, ``~/.cache/gimera`` and ``~/.docker``, but zodoo
    has too many implicit assumptions about the real HOME (settings file
    discovery, docker CLI plugin config, git identity, …) to make that
    reliably work across all versions.

    Instead we now keep the real HOME and rely on each test using a
    unique project name (``zodoo_pytest_19``, ``baketest19_0``, ...).
    Cleanup happens via ``odoo -p <project> down -v`` at session end.
    """
    yield Path.home()


@pytest.fixture(scope="session")
def odoo_project_19(_session_home, tmp_path_factory, request):
    """Build a fresh Odoo 19.0 project once per session.

    Heavy: ~minutes to clone Odoo + build images. Skipped when the
    docker / odoo toolchain is unavailable, so unit-only runs stay fast.
    """
    if not (_has_docker() and _has_odoo_cli()):
        pytest.skip("needs docker daemon and 'odoo' CLI on PATH")

    name = "zodoo_pytest_19"
    # Dir name must match project name — see test_bake.py comment for why.
    project_dir = tmp_path_factory.mktemp("pyt") / name
    project_dir.mkdir()
    long_timeout = 60 * 30

    # `odoo src init` bootstraps the project and runs an internal reload.
    _run(
        [
            "odoo",
            "-f",
            "-p",
            name,
            "src",
            "init",
            str(project_dir),
            "19.0",
        ],
        cwd=project_dir.parent,
        timeout=long_timeout,
    )

    project = OdooProject(name=name, path=project_dir, home=_session_home)

    # Reload + build — init's internal reload runs without `-p` so it uses
    # the dir name; we do it again with the correct `-p` to make sure the
    # settings/compose files are written under `name`. Then build images
    # so `up -d` (which uses --no-build) can actually start containers.
    project.run("reload", timeout=long_timeout)
    project.run("build", "--no-zodoo-pull", timeout=long_timeout)

    try:
        yield project
    finally:
        # best-effort teardown so a failed session doesn't leave containers around
        try:
            project.run_force("down", "-v", check=False, timeout=300)
        except Exception:
            pass


@pytest.fixture(scope="session")
def odoo_project_19_running(odoo_project_19):
    """Builds on odoo_project_19 but also brings the stack up with a fresh DB.

    Extra cost over `odoo_project_19`: first `db reset` is ~2-5 minutes
    (container spin-up + initial Odoo install). Subsequent tests piggy-
    back on the running stack.
    """
    long_timeout = 60 * 20
    # Postgres must be running before db reset can work.
    odoo_project_19.run("up", "-d", "postgres", timeout=long_timeout)
    odoo_project_19.run_force("db", "reset", timeout=long_timeout)
    odoo_project_19.run("up", "-d", timeout=long_timeout)
    try:
        yield odoo_project_19
    finally:
        try:
            odoo_project_19.run_force("down", check=False, timeout=300)
        except Exception:
            pass


@pytest.fixture(scope="session")
def pgbackrest_project(_session_home, tmp_path_factory):
    """A dedicated, disposable 19.0 project with pgBackRest enabled and running.

    Separate from ``odoo_project_19`` because a restore is destructive (it
    stops the stack and overwrites the postgres data directory), so it must
    not run against a project other tests share. Heavy: a full ``src init`` +
    build + ``db reset`` (docker layers from the other project are reused, so
    the marginal cost is mostly container spin-up).
    """
    if not (_has_docker() and _has_odoo_cli()):
        pytest.skip("needs docker daemon and 'odoo' CLI on PATH")

    name = "zodoo_pytest_pgbackrest"
    project_dir = tmp_path_factory.mktemp("pytpgbr") / name
    project_dir.mkdir()
    long_timeout = 60 * 30

    _run(
        ["odoo", "-f", "-p", name, "src", "init", str(project_dir), "19.0"],
        cwd=project_dir.parent,
        timeout=long_timeout,
    )
    project = OdooProject(name=name, path=project_dir, home=_session_home)

    # Enable pgBackRest before reload so the archive_command and the shared
    # mounts land in postgres and the sidecar is merged into the compose.
    # Force it on despite DEVMODE.
    # Write the per-project settings file directly (same approach as the
    # cronjob E2E test) - `odoo setting KEY VALUE` with a space does NOT write,
    # it needs KEY=VALUE, so file-append is the unambiguous way.
    settings_path = Path.home() / ".odoo" / f"settings.{name}"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("a") as fh:
        fh.write("\nRUN_PGBACKREST=1\nPGBR_FORCE_IN_DEVMODE=1\n")

    project.run("reload", timeout=long_timeout)
    project.run("build", "--no-zodoo-pull", timeout=long_timeout)
    project.run("up", "-d", "postgres", timeout=60 * 20)
    project.run_force("db", "reset", timeout=60 * 20)
    project.run("up", "-d", timeout=60 * 20)  # brings up pgbackrest too

    try:
        yield project
    finally:
        try:
            project.run_force("down", "-v", check=False, timeout=300)
        except Exception:
            pass


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: end-to-end test against a live Odoo stack; requires "
        "Docker + gimera + network. Runtime: minutes per session. "
        "Run explicitly with `pytest -m slow` or `pytest -m 'slow or not slow'`.",
    )


def pytest_collection_modifyitems(config, items):
    """Deselect @slow tests by default; opt-in via `-m slow` or env var."""
    if config.getoption("-m") or os.environ.get("ZODOO_RUN_SLOW") == "1":
        return
    skip_slow = pytest.mark.skip(
        reason="slow/E2E test — run with `pytest -m slow` or ZODOO_RUN_SLOW=1"
    )
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
