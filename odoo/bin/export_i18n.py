#!/usr/bin/env wodoo_python
import click
import shutil
import tempfile
import os
import sys
import grp
import pwd
import subprocess
from wodoo.module_tools import Module
from wodoo.odoo_config import current_version
from pathlib import Path
from tools import exec_odoo
from tools import _run_shell_cmd

if len(sys.argv) == 1:
    print("Usage: export_i18n de_DE module")
    sys.exit(-1)

LANG = sys.argv[1]
MODULES = sys.argv[2]

# definitly in version 15+
from wodoo.odoo_config import customs_dir, MANIFEST
manifest = MANIFEST()
if float(manifest['version']) < 18.0:
    if "_" in LANG:
        LANG = LANG.split("_")[0]

# only export in base langs here
# 13.0 import just de_DE did not import with specifying a translation file

def _get_lang_export_line(module, lang):
    filename = tempfile.mktemp(suffix='.po')
    code = (
        "try:\n"
        " from odoo.tools import trans_export\n"
        "except ImportError:\n"
        " from odoo.tools.translate import trans_export\n"
        f"with open('{filename}', 'wb') as buf:\n"
        f'   trans_export("{lang}", ["{module.name}"], buf, "po", env.cr) \n'
    )
    return code, filename


root = Path(os.environ['CUSTOMS_DIR'])
for module in MODULES.split(","):
    os.chdir(root)
    module = Module.get_by_name(MODULES)

    path = root / module.path / 'i18n'
    path.mkdir(exist_ok=True)

    code, filename = _get_lang_export_line(module, LANG)
    filename = Path(filename)
    rc = _run_shell_cmd(code)
    if rc:
        click.secho(f"Error exporting language of {module}", fg='red')
        sys.exit(-1)

    dest_path = root / module.path / 'i18n' / "{}.po".format(LANG)
    shutil.copy(str(filename), str(dest_path))
    filename.unlink()
    odoo_user = pwd.getpwnam(os.environ["ODOO_USER"]).pw_uid
    gid = int(os.getenv("OWNER_GID", odoo_user))
    os.chown(str(dest_path), odoo_user, gid)
    os.chown(str(dest_path.parent), odoo_user, gid)
