import os
import shutil
from tools import prepare_run
import subprocess
import sys

WODOO_PYTHON = os.getenv("WODOO_PYTHON")

print("Updating modules")
prepare_run()
os.environ["DOCKER_MACHINE"] = "1"

from pathlib import Path

manifest = eval(Path("/opt/src/MANIFEST").read_text())

try:
    subprocess.run(
        ["/odoolib/odoo", "update", "--no-progress"],
        check=True,
        cwd="/opt/src",
    )
except subprocess.CalledProcessError as e:
    if os.getenv("PERSIST_UPDATE_LOG"):
        shutil.copy("/opt/src/update.log", os.getenv("PERSIST_UPDATE_LOG"))
    sys.exit(-1)
