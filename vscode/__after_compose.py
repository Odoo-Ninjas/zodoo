import inspect
import os
from pathlib import Path
import shutil
current_dir = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))

def after_compose(config, settings, yml, globals):
    shutil.copy(current_dir.parent / 'robot' / 'requirements.txt', current_dir / 'robot.requirements.txt')