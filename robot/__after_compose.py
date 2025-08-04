import sys
from copy import deepcopy
import re
import base64
import click
import yaml
import inspect
import os
import subprocess
import shutil
from pathlib import Path
import inspect
import os
from pathlib import Path
current_dir = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))
dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))


def after_compose(config, settings, yml, globals):
    shutil.copy(
        current_dir.parent / "common_snippets" / "set_docker_group.sh",
        current_dir / "set_docker_group.sh",
    )
    # store also in clear text the requirements
    from wodoo.tools import get_services
    from pathlib import Path
    if not yml.get('services', {}).get('robot'):
        return
    service = yml['services']['robot']
    if 'build' in service:
        service['build']['args']['OWNER_UID'] = config.owner_uid
