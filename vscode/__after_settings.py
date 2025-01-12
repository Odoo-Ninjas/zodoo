import random
import stat
import os
import platform
from pathlib import Path
import inspect


def after_settings(settings, config):
    customs_dir = config.CUSTOMS_DIR
    settings['HOST_SRC_PATH'] = customs_dir