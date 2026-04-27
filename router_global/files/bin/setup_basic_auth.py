#!/usr/bin/env python3
"""
Calls the dialog to install ssl certificates.

"""
from pathlib import Path
import subprocess
import inspect
import sys
import json
import os
from pathlib import Path


current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)

file = Path("sites-enabled") / sys.argv[1]
username_passwords = sys.argv[2]
content = file.read_text()


basic_auth = """
auth_basic "Restricted Content";
auth_basic_user_file /htpasswd/{name};
""".format(
    name=sys.argv[1]
)
content = content.replace("# BASIC_AUTH", basic_auth)
file.write_text(content)

htpasswdfile = Path("htpasswd") / sys.argv[1]
content = []

for username, password in json.loads(sys.argv[2]).items():
    hashed_password = subprocess.check_output(
        ["openssl", "passwd", "-apr1", password],
        universal_newlines=True,
        encoding="utf-8",
    ).strip()
    content.append(f"{username}:{hashed_password}")
htpasswdfile.write_text("\n".join(content))
