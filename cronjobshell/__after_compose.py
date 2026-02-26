import inspect
import os
from pathlib import Path

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)
dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))


def after_compose(config, settings, yml, globals):
    src = current_dir.parent / "wodoo" / "src"
    dest = current_dir.parent / "cronjobs" / "wodoo_src"
    globals["tools"].sync_folder(src, dest, excludes=[".git"])
