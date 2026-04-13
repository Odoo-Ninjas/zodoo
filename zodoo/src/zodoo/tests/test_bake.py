"""End-to-end test for the `odoo bake` flow.

Walks through the full user journey:

    odoo src init <path> <version>
    odoo reload
    odoo -f db reset
    odoo bakery bake KEY=VALUE ...

and verifies the bake artefact (`{project}.env`) and the docker images.

Heavy: requires Docker, gimera, network access (clones Odoo + addons).
Marked with the `bake` marker so it is opt-in (`pytest -m bake`).

Versions tested are taken from the `ZODOO_BAKE_TEST_VERSIONS` env var
(comma-separated, e.g. `15.0,19.0`); defaults to `19.0`.
"""

import os
import shutil
import subprocess

import pytest

DEFAULT_VERSIONS = os.environ.get("ZODOO_BAKE_TEST_VERSIONS", "19.0").split(
    ","
)


def _has_docker():
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


def _has_odoo_cli():
    return shutil.which("odoo") is not None


requires_full_stack = pytest.mark.skipif(
    not _has_docker() or not _has_odoo_cli(),
    reason="needs docker daemon and 'odoo' CLI on PATH",
)


def _run(cmd, *, cwd, env=None, timeout=None, check=True):
    """Run a shell command, streaming output to stdout for CI logs."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    print(f"\n$ {' '.join(cmd)}    (cwd={cwd})", flush=True)
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=full_env,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}"
        )
    return result


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Override HOME so ~/.odoo/ does not collide with the developer's setup."""
    home = tmp_path / "home"
    (home / ".odoo").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ODOO_HOME", str(home / ".odoo"))
    yield home


@pytest.fixture
def project_dir(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    return p


@pytest.mark.bake
@requires_full_stack
@pytest.mark.parametrize("version", DEFAULT_VERSIONS)
def test_bake_flow(version, isolated_home, project_dir):
    project_name = f"baketest{version.replace('.', '')}"

    # 30 minute cap per heavy step; covers Odoo clone + docker build on cold cache.
    long_timeout = 60 * 30

    try:
        # 1) Initialise a fresh project. `odoo src init` ends with sys.exit(0)
        #    after running an internal `odoo reload`, so there is no need to
        #    invoke reload separately — but we do it again below to be explicit.
        _run(
            [
                "odoo",
                "-f",
                "-p",
                project_name,
                "src",
                "init",
                str(project_dir),
                version,
            ],
            cwd=project_dir.parent,
            timeout=long_timeout,
        )

        # 2) Explicit reload — idempotent; ensures images are built.
        _run(
            ["odoo", "-p", project_name, "reload"],
            cwd=project_dir,
            timeout=long_timeout,
        )

        # 3) Reset database.
        _run(
            ["odoo", "-f", "-p", project_name, "db", "reset"],
            cwd=project_dir,
            timeout=long_timeout,
        )

        # 4) Bake — this is the actual assertion target.
        _run(
            [
                "odoo",
                "-p",
                project_name,
                "bakery",
                "bake",
                "ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER=1",
            ],
            cwd=project_dir,
            timeout=long_timeout,
        )

        # 5) Bake should have produced <project_name>.env in the customs dir.
        env_file = project_dir / f"{project_name}.env"
        assert (
            env_file.exists()
        ), f"bake did not create the env file at {env_file}"
        env_content = env_file.read_text()
        assert "ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER=1" in env_content
        assert "SHA_IN_DOCKER=1" in env_content
        assert "SRC_EXTRA=0" in env_content

        # 6) Docker images for the project should now exist locally.
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        images = result.stdout.splitlines()
        assert any(project_name in line for line in images), (
            f"no docker image tagged with project '{project_name}' found.\n"
            f"available:\n{result.stdout}"
        )

    finally:
        # Best-effort teardown so a failed run does not leave containers behind.
        subprocess.run(
            ["odoo", "-p", project_name, "down", "-v"],
            cwd=str(project_dir),
            timeout=300,
        )
