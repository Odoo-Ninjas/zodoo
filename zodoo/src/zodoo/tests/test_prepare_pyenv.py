"""Regression test for the debug-launch pyenv check in `zodoo/bin/prepare.sh`.

Would have caught the "debugging hangs on every Play" bug:

`launch_docker_debugpy.sh` runs `prepare.sh` with SETUP_PYENV=1 as the
VSCode preLaunchTask. prepare.sh decides whether to run the (expensive,
multi-minute) `odoo setup-pyenv` — which rebuilds the whole robot pyenv
from scratch (`pyenv uninstall -f zodoo-robot` + full pip install).

The guard used to check for a pyenv named ``$PROJECTNAME``, but
`odoo setup-pyenv` only ever creates an env named ``zodoo-robot``
(see lib_setup._setup_robo_pyenv / is_robot_env_installed). So the
check never matched, setup-pyenv ran on *every* Play, and the debug
launch appeared to hang for minutes before debugpy came up.

These tests run the real prepare.sh with fake `pyenv`/`odoo` binaries on
PATH and assert setup-pyenv is invoked iff the `zodoo-robot` env is
missing — independent of PROJECTNAME.
"""

import os
import subprocess
from pathlib import Path

import pytest

PREPARE_SH = Path(__file__).resolve().parents[1] / "bin" / "prepare.sh"


def _make_fakes(tmp_path: Path, pyenv_versions: str) -> Path:
    """Create fake `pyenv` and `odoo` executables in a bin dir.

    Both append every invocation (program + args) to ``<bin>/calls.log``.
    `pyenv versions --bare` prints ``pyenv_versions``; everything else is
    a no-op success.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls_log = bindir / "calls.log"

    pyenv = bindir / "pyenv"
    pyenv.write_text(
        "#!/bin/bash\n"
        f'echo "pyenv $*" >> "{calls_log}"\n'
        'if [[ "$1" == "versions" ]]; then\n'
        f"  printf '%s\\n' {pyenv_versions}\n"
        "fi\n"
        "exit 0\n"
    )
    pyenv.chmod(0o755)

    odoo = bindir / "odoo"
    odoo.write_text(
        "#!/bin/bash\n" f'echo "odoo $*" >> "{calls_log}"\n' "exit 0\n"
    )
    odoo.chmod(0o755)
    return bindir


def _run_prepare(bindir: Path, projectname: str) -> str:
    """Run prepare.sh with the fakes first on PATH; return the calls log."""
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env.update(
        {
            "SETUP_PYENV": "1",
            "DEVMODE": "1",
            # RUN_POSTGRES=1 keeps prepare.sh out of the "non local
            # database!" osascript/powershell alert branch.
            "RUN_POSTGRES": "1",
            "RUN_PROXY_PUBLISHED": "0",
            "PROJECTNAME": projectname,
            "OSTYPE": "linux-gnu",
        }
    )
    subprocess.run(
        ["/bin/bash", str(PREPARE_SH)],
        env=env,
        cwd=str(bindir.parent),
        check=True,
        capture_output=True,
        text=True,
    )
    log = bindir / "calls.log"
    return log.read_text() if log.exists() else ""


@pytest.mark.skipif(
    not PREPARE_SH.exists(), reason="prepare.sh not found in checkout"
)
class TestPreparePyenvGuard:
    def test_skips_setup_when_robot_env_present(self, tmp_path):
        # zodoo-robot exists -> setup-pyenv must NOT run, regardless of
        # there being no pyenv named after the project.
        bindir = _make_fakes(tmp_path, '"3.12.11" "zodoo-robot"')
        calls = _run_prepare(bindir, projectname="someproject")
        assert "odoo setup-pyenv" not in calls, (
            "setup-pyenv ran even though zodoo-robot exists "
            f"(the every-Play-reinstall regression). calls:\n{calls}"
        )

    def test_runs_setup_when_robot_env_missing(self, tmp_path):
        # No zodoo-robot -> setup-pyenv SHOULD run (one-time bootstrap).
        bindir = _make_fakes(tmp_path, '"3.12.11" "someproject"')
        calls = _run_prepare(bindir, projectname="someproject")
        assert "odoo setup-pyenv" in calls, (
            "setup-pyenv did not run although zodoo-robot is missing. "
            f"calls:\n{calls}"
        )

    def test_projectname_pyenv_does_not_satisfy_guard(self, tmp_path):
        # The core of the bug: a pyenv named exactly like the project must
        # NOT be accepted as "robot env present". Only zodoo-robot counts.
        bindir = _make_fakes(tmp_path, '"3.12.11" "debuggingtest"')
        calls = _run_prepare(bindir, projectname="debuggingtest")
        assert "odoo setup-pyenv" in calls, (
            "guard wrongly matched a project-named pyenv instead of "
            f"zodoo-robot. calls:\n{calls}"
        )
