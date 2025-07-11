#!/usr/bin/env wodoo_python
from pathlib import Path
import tempfile
import os
import sys
from wodoo.odoo_config import current_version
from tools import exec_odoo
from tools import prepare_run

prepare_run()

os.environ['PYTHONBREAKPOINT'] = 'pudb.set_trace'
params = sys.argv

# make path relative to links, so that test is recognized by odoo
cmd = [
    '--stop-after-init',
]
if current_version() >= 11.0:
    cmd += ["--shell-interface=ipython"]

if '--queuejobs' in sys.argv:
    os.environ["TEST_QUEUE_JOB_NO_DELAY"] = "1"
    params.remove("--queuejobs")

if len(params) > 1:
    odoo_cmd = params[-1]
else:
    odoo_cmd = ""

os.environ["ODOO_SHELL_CMD"] = odoo_cmd
stdin = odoo_cmd if odoo_cmd else None # 'echo "$ODOO_SHELL_CMD"'

exec_odoo(
    "config_shell",
    *cmd,
    odoo_shell=True,
    stdin=stdin,
    dokill=False,
)
