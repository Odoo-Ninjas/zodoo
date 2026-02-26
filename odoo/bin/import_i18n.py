#!/usr/bin/env wodoo_python
import os
import sys
import subprocess
from wodoo.module_tools import Module

if len(sys.argv) == 1:
    print("Usage: import_i18n de_DE pofilepath")
    sys.exit(-1)
if len(sys.argv) == 2:
    print("Language Code and/or Path missing!")
    print("")
    print(
        "Please provide the path relative to customs e.g. modules/mod1/i18n/de.po"
    )
    sys.exit(-1)

LANG = sys.argv[1]
FILEPATH = sys.argv[2]
if not FILEPATH.startswith("/"):
    FILEPATH = f"/opt/src/{FILEPATH}"

os.chdir("/opt/src")
module = Module(FILEPATH)

# use this function to handle unloaded server wide modules
# e.g. api.fieldonchange
subprocess.check_call(
    [
        os.getenv("WODOO_PYTHON"),
        "/odoolib/update_modules.py",
        module.name,
        "--i18n",
        "--only-i18n",
    ]
)
