#!/usr/local/bin/wodoo_python
import sys
import os
import shutil
from pathlib import Path


owner = os.environ['OWNER_UID']

os.system(f"usermod -u {owner} odoo")

print(f"Setting ownership of /opt/files to {owner}")
os.system(f"chown '{owner}:{owner}' /opt/files")

# important is especially the .config folder, so that libreoffice works
print(f"Setting ownership of /home/odoo to {owner}")
os.system(f"chown -R '{owner}:{owner}' /home/odoo")

try:
    os.execvp(sys.argv[1], sys.argv[1:])
except Exception as ex:
    print(f"Error executing command: {sys.argv[1:]} {ex}")
    sys.exit(1)
