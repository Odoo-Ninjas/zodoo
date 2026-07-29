#!/opt/zodoo_pipx/venvs/zodoo/bin/python3
import os
import sys
import time as _time
import click
from zodoo.odoo_config import current_version
from tools import exec_odoo
from tools import prepare_run

_t0 = _time.monotonic()


def _ts(label):
    click.secho(
        f"[shell.py] {label:50s}  +{_time.monotonic() - _t0:.3f}s",
        fg="green",
    )


_ts("script start (container is up)")

_ts("prepare_run: start")
prepare_run()
_ts("prepare_run: done")

os.environ["PYTHONBREAKPOINT"] = "pudb.set_trace"
params = sys.argv

# Debug mode: wrap the odoo shell in debugpy and wait for VSCode to attach.
# Enabled via `odoo odoo-shell --debug` (sets ODOO_SHELL_DEBUG=1 + publishes
# the debug port on the one-off run container). exec_odoo()'s
# remote_debug/wait_for_remote add `python -mdebugpy --listen 0.0.0.0:5678
# --wait-for-client`. A daemon thread polls that in-container port and prints
# a sentinel once debugpy is actually accepting connections, so the VSCode
# background preLaunchTask can fire the attach race-free (the port is open
# before we signal, unlike a plain "about to start" echo).
_shell_debug = os.environ.get("ODOO_SHELL_DEBUG") == "1"
if _shell_debug:
    import socket
    import threading

    _DEBUGPY_PORT = 5678  # in-container listen port (see tools.__python_exe)
    _READY_SENTINEL = "ZODOO_DEBUGPY_SHELL_READY"

    def _announce_when_ready():
        for _ in range(600):  # ~120s
            try:
                with socket.create_connection(
                    ("127.0.0.1", _DEBUGPY_PORT), timeout=1
                ):
                    pass
            except OSError:
                _time.sleep(0.2)
                continue
            print(_READY_SENTINEL, flush=True)
            return
        print(f"{_READY_SENTINEL}:TIMEOUT", flush=True)

    threading.Thread(target=_announce_when_ready, daemon=True).start()
    click.secho(
        "Shell debug mode: waiting for VSCode to attach debugpy ...",
        fg="yellow",
    )

# make path relative to links, so that test is recognized by odoo
cmd = [
    "--stop-after-init",
]
if current_version() >= 11.0:
    cmd += ["--shell-interface=ipython"]

if "--queuejobs" in sys.argv:
    os.environ["TEST_QUEUE_JOB_NO_DELAY"] = "1"
    params.remove("--queuejobs")

if len(params) > 1:
    odoo_cmd = params[-1]
else:
    odoo_cmd = ""

os.environ["ODOO_SHELL_CMD"] = odoo_cmd
stdin = odoo_cmd if odoo_cmd else None  # 'echo "$ODOO_SHELL_CMD"'

if stdin:
    # Wrap command so exceptions produce a non-zero exit code.
    # IPython/Odoo shell swallow exceptions (including SystemExit),
    # so we use os._exit() which cannot be intercepted.
    stdin = (
        "import os as _os, traceback as _tb\n"
        "try:\n"
        f"    exec(compile({repr(stdin)}, '<shell>', 'exec'))\n"
        "except SystemExit as _e:\n"
        "    _os._exit(_e.code if isinstance(_e.code, int) else 1)\n"
        "except Exception:\n"
        "    _tb.print_exc()\n"
        "    _os._exit(1)\n"
    )

_ts("exec_odoo (odoo-bin shell): start")
rc, _ = exec_odoo(
    "config_shell",
    *cmd,
    odoo_shell=True,
    stdin=stdin,
    dokill=False,
    remote_debug=_shell_debug,
    wait_for_remote=_shell_debug,
)
_ts("exec_odoo (odoo-bin shell): done")
sys.exit(rc)
