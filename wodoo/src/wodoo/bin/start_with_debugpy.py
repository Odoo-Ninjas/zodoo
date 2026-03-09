#!/usr/bin/env python3
import subprocess
import os

os.environ["ODOO_DEBUGPY"] = "1"
os.environ["ODOO_DEBUGPY_PORT"] = "5679"

PYTHON = "/Users/marcwimmer/.pyenv/versions/odoo16/bin/python3"
WORKSPACE_FOLDER = "/Users/marcwimmer/projects/odoo16"

ARGS = [
    "--log-level=debug",
    "--dev=all",
    "--http-interface=0.0.0.0",
    "--http-port=9098",
    "--database=odoo16",
    "--db_host=127.0.0.1",
    "--db_port=9097",
    "--db_user=odoo",
    "--db_password=odoo",
    "--addons-path=${workspaceFolder}/odoo/odoo/addons,${workspaceFolder}/odoo/addons",
    "--workers=0",
    "--max-cron-threads=0",
    "--data-dir=/Users/marcwimmer/.odoo/files",
    "--load=web",
]

ODOO_BIN = "/Users/marcwimmer/projects/odoo16/odoo/odoo-bin"

resolved_args = [
    a.replace("${workspaceFolder}", WORKSPACE_FOLDER) for a in ARGS
]

cmd = [
    PYTHON,
    "-Xfrozen_modules=off",
    "-m",
    "debugpy",
    "--wait-for-client",
    "--listen",
    f"0.0.0.0:{os.environ['ODOO_DEBUGPY_PORT']}",
    ODOO_BIN,
] + resolved_args

print("Starting odoo on debugpy", flush=True)
subprocess.Popen(cmd, cwd="/Users/marcwimmer/projects/odoo16")
print("Waiting for debugger attach", flush=True)
