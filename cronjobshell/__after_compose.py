import json
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

def after_compose(config, settings, yml, globals):
    src = current_dir.parent / 'wodoo' / 'src'
    dest = current_dir.parent / 'cronjobs' / 'wodoo_src'
    globals['tools'].sync_folder(src, dest, excludes=['.git'])