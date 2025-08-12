import time
import hashlib
from packaging.requirements import Requirement
from packaging.markers import Marker
from packaging.specifiers import SpecifierSet
import hashlib
from copy import deepcopy
from datetime import datetime
import shutil
import re
import base64
import click
import inspect
import os
import subprocess
from pathlib import Path

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)
dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

MINIMAL_MODULES = []  # to include its dependencies

my_cache = {}

def _add_missing_mapping(source, target, service):
    shall_exist = f"{source}:{target}"
    for mapping in service['volumes']:
        if mapping['source'] == source and mapping['target'] == target:
            break
    else:
        service['volumes'].append({
            'source': source,
            'target': target, 
            'type': 'bind', 
            })

def after_compose(config, settings, yml, globals):
    # store also in clear text the requirements
    shutil.copy(
        current_dir.parent / "common_snippets" / "set_docker_group.sh",
        current_dir / "set_docker_group.sh",
    )

    if 'console' not in yml['services']:
        return
    console = yml['services']['console']
    path = settings.get("ODOO_IMAGES")
    _add_missing_mapping(path, path, console)
    path = settings.get("HOST_RUN_DIR")
    _add_missing_mapping(path, path, console)