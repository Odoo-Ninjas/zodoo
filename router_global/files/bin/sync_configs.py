#!/usr/bin/env python3
"""Sync rendered vhost configs into sites-enabled and clean up removed ones.

Equivalent to ansible task 4800-generate-configs.yml. Reads from
sites-incoming/, writes to sites-available/ and sites-enabled/, tracks
deployed state in sites-last-deployed/. Cleans up letsencrypt artifacts of
removed vhosts. Exits 10 if a reload is required, 0 if no change.
"""
import shutil
import sys
from pathlib import Path

path_available = Path("sites-available")
path_incoming = Path("sites-incoming")
path_enabled = Path("sites-enabled")
path_lastdeployed = Path("sites-last-deployed")

for p in (path_available, path_incoming, path_enabled, path_lastdeployed):
    p.mkdir(exist_ok=True)

changed = False

incoming_names = {x.name for x in path_incoming.glob("*")}
to_remove = []
for path in (path_enabled, path_available):
    for file in path.glob("*"):
        if file.name not in incoming_names:
            file.unlink()
            to_remove.append(file.name)

for name in to_remove:
    changed = True
    for folder in (
        path_lastdeployed,
        Path("letsencrypt/live"),
        Path("letsencrypt/archive"),
        Path("letsencrypt/renewal"),
    ):
        folder = folder / name
        for candidate in (folder, Path(str(folder) + ".conf")):
            if candidate.exists():
                if candidate.is_file():
                    candidate.unlink()
                else:
                    shutil.rmtree(candidate)

for file in path_incoming.glob("*"):
    shutil.copy(file, path_available / file.name)

for file in path_available.glob("*"):
    last_deployed = path_lastdeployed / file.name
    enabled_file = path_enabled / file.name
    local_changed = (
        not last_deployed.exists()
        or not enabled_file.exists()
        or last_deployed.read_text() != file.read_text()
    )
    if local_changed:
        changed = True
        enabled_file.write_text(file.read_text())
        last_deployed.write_text(file.read_text())

print("requires restart" if changed else "no change")
sys.exit(10 if changed else 0)
