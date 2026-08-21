#!/usr/bin/env python3
"""Ensure the SSL block is present in sites-enabled/<domain>.

If the file already has 'listen 443 ssl', do nothing.
Otherwise:
  - If a Let's Encrypt cert already exists for the domain, run
    'certbot install' to deploy it (NO ACME API call — safe vs rate
    limits).
  - Only if no cert exists, run 'certbot --nginx' to request a new one.

This avoids accidentally renewing certs on every deploy.
"""
import inspect
import os
import shutil
import subprocess
import sys
from pathlib import Path

current_dir = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))
project_dir = current_dir.parent

domain_arg = sys.argv[1]
file = Path("sites-enabled") / domain_arg
content = file.read_text() if file.exists() else ""

if "listen 443 ssl" in content:
    sys.exit(0)


def _compose():
    """The compose CLI this host has.

    Hosts built on Ubuntu 20.04 carry the old standalone docker-compose (v1);
    newer ones only ship the 'docker compose' plugin. v1 keeps priority so
    nothing changes where it is still installed.
    """
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


def _has_existing_cert(d):
    return (project_dir / "letsencrypt" / "live" / d).is_dir()


for domain in domain_arg.split(" "):
    domain = domain.strip()
    if not domain:
        continue
    if _has_existing_cert(domain):
        # No ACME call: just deploy the existing cert into the nginx
        # config (safe vs Let's Encrypt rate limits).
        subprocess.run([
            *_compose(), 'exec', '-T', 'router',
            'certbot', 'install',
            '--cert-name', domain,
            '--nginx',
            '--non-interactive',
        ], cwd=project_dir, check=True)
    else:
        # New domain — request a fresh cert.
        subprocess.run([
            *_compose(), 'exec', '-T', 'router',
            'certbot', '--nginx',
            '-d', domain,
            '--non-interactive',
            '--agree-tos',
            '-m', 'marc@itewimmer.de',  # TODO configurable
        ], cwd=project_dir, check=True)
