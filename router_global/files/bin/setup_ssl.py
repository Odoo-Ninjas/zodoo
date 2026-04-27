#!/usr/bin/env python3
"""
Calls the dialog to install ssl certificates.

"""
from pathlib import Path
import shutil
import subprocess
import inspect
import sys
import os
from pathlib import Path
current_dir = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))

file = Path("sites-enabled") / sys.argv[1]
content = file.read_text()

if "listen 443 ssl" not in content:
    for domain in sys.argv[1].split(" "):
        domain = domain.strip()
        if not domain:
            continue
        subprocess.run([
            'docker-compose',
            'exec',
            'router',
            'certbot',
            '--nginx',
            '-d',
            domain,
            '--non-interactive',
            '--agree-tos',
            '-m',
            'marc@itewimmer.de',  # TODO configurable
        ], cwd=current_dir.parent)