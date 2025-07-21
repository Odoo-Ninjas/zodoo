import sys
import os
import shutil
from pathlib import Path


owner = os.environ['OWNER_UID']

os.system(f"usermod -u {owner} odoo")

#print(f"Setting ownership of /opt/files to {owner}")
os.system(f"chown '{owner}:{owner}' /opt/files")

# important is especially the .config folder, so that libreoffice works
#print(f"Setting ownership of /home/odoo to {owner}")
os.system(f"chown '{owner}:{owner}' /home/odoo")  # -R too heavy
# CICD compatibility TODO make nicer
os.system(f"chown '{owner}:{owner}' -R /opt/src_cicd_modules")
os.system("git config --global --add safe.directory /opt/src")

cmd, args = None, None
try:
    if sys.argv[1].endswith('.py'):
        # If the first argument is a Python script, execute it with the Python interpreter
        WODOO_PYTHON = os.getenv("WODOO_PYTHON")
        cmd, args  = WODOO_PYTHON, [WODOO_PYTHON] + sys.argv[1:]
    else:
        cmd, args  = sys.argv[1], sys.argv[1:]
    os.execvp(cmd, args)
except Exception as ex:
    print(f"Error executing command: <{cmd}> {args}: \n{ex}")
    sys.exit(1)
