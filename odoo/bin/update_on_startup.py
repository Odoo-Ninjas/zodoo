import os
import shutil
from tools import prepare_run, sudo_odoo_cmd
import subprocess
import sys

ZODOO_PYTHON = os.getenv("ZODOO_PYTHON")

print("Updating modules")
prepare_run()

from pathlib import Path

manifest_path = Path("/opt/src/MANIFEST")
if not manifest_path.exists():
    print(
        "ERROR: /opt/src/MANIFEST not found — source code is missing from "
        "the container. Was the image baked without source (SRC_EXTRA=1)?"
    )
    sys.exit(-1)

manifest = eval(manifest_path.read_text())

try:
    subprocess.run(
        sudo_odoo_cmd(["/odoolib/odoo", "update", "--no-progress"]),
        check=True,
        cwd="/opt/src",
    )
except subprocess.CalledProcessError as e:
    if os.getenv("PERSIST_UPDATE_LOG"):
        shutil.copy("/opt/src/update.log", os.getenv("PERSIST_UPDATE_LOG"))
    sys.exit(-1)
