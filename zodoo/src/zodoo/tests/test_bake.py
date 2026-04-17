"""End-to-end test for the `odoo bake` flow.

Walks through the full user journey:

    odoo src init <path> <version>
    odoo reload
    odoo -f db reset
    odoo bakery bake KEY=VALUE ...

and verifies the bake artefact (`{project}.env`) and the docker images.

Heavy: requires Docker, gimera, network access (clones Odoo + addons).
Self-skips via `requires_full_stack` when Docker / `odoo` CLI is missing,
so it is safe to run as part of a plain `pytest` invocation.

Versions tested are taken from the `ZODOO_BAKE_TEST_VERSIONS` env var
(comma-separated, e.g. `15.0,19.0`); defaults to `19.0`.
"""

import os
import subprocess
from pathlib import Path

import pytest

from .conftest import _run, requires_full_stack

DEFAULT_VERSIONS = os.environ.get("ZODOO_BAKE_TEST_VERSIONS", "19.0").split(
    ","
)


@pytest.fixture
def isolated_home():
    """Uses the real HOME — test relies on a unique project_name
    (``baketest<version>``) instead of HOME isolation, which had too
    many edge cases (missing docker cli-plugins, no gimera cache,
    settings file paths, ...).
    """
    yield Path.home()


@pytest.mark.slow
@requires_full_stack
@pytest.mark.parametrize("version", DEFAULT_VERSIONS)
def test_bake_flow(version, isolated_home, tmp_path):
    project_name = f"baketest{version.replace('.', '')}"
    # The dir name must match project_name because `make_customs` runs an
    # internal `odoo reload` without `-p`, which derives the project name
    # from the current directory.
    project_dir = tmp_path / project_name
    project_dir.mkdir()

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

        # 2) Reload + build — init's internal reload runs without `-p`
        #    (derives project_name from cwd), then we need to build
        #    images so `db reset` can start postgres.
        _run(
            ["odoo", "-p", project_name, "reload"],
            cwd=project_dir,
            timeout=long_timeout,
        )
        _run(
            ["odoo", "-p", project_name, "build", "--no-zodoo-pull"],
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

        # 7) Regression guard for the K8s-style startup flow.  The
        # baked image is used in production as a root→sudo-u-odoo
        # chain; we exercise the same chain locally to catch:
        #   - PermissionError on /etc/odoo/config/* when templates
        #     are copied as root and later re-copied as odoo
        #     (fix/chown-config-files-recursive)
        #   - "odoo is not in the sudoers file" when sudo_odoo_cmd
        #     double-wraps sudo while already running as odoo
        #     (fix/sudo-odoo-cmd-skip-when-already-odoo)
        odoo_image = next(
            (line for line in images if f"{project_name}-odoo:" in line),
            None,
        )
        if odoo_image:
            run_result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-e",
                    "ODOO_SUDO_CMD=1",
                    "-e",
                    "IS_ODOO_DEBUG=1",  # prepare_run then exit, no DB needed
                    "-e",
                    "DBNAME=baketest",
                    "--entrypoint",
                    "/bin/bash",
                    odoo_image,
                    "-c",
                    # Run update_on_startup.py to exercise:
                    # root → sudo_odoo_cmd("/odoolib/odoo update") → odoo
                    # → /odoolib/odoo update → update_modules.py
                    # → exec_odoo() → sudo_odoo_cmd(odoo-bin) [MUST NOT re-wrap]
                    "python3 /odoolib/update_on_startup.py || true",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            combined = run_result.stdout + run_result.stderr
            assert "PermissionError" not in combined, (
                "Permission bug re-introduced (see "
                "fix/chown-config-files-recursive):\n" + combined[-2000:]
            )
            assert "not in the sudoers file" not in combined, (
                "sudo double-wrap bug re-introduced (see "
                "fix/sudo-odoo-cmd-skip-when-already-odoo):\n"
                + combined[-2000:]
            )

    finally:
        # Best-effort teardown so a failed run does not leave containers behind.
        subprocess.run(
            ["odoo", "-p", project_name, "down", "-v"],
            cwd=str(project_dir),
            timeout=300,
        )
