import inspect
import os
from pathlib import Path
import shutil

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def after_compose(config, settings, yml, globals):
    shutil.copy(
        current_dir.parent / "robot" / "requirements.txt",
        current_dir / "robot.requirements.txt",
    )
    shutil.copy(
        current_dir.parent / "common_snippets" / "set_docker_group.sh",
        current_dir / "bin" / "set_docker_group.sh",
    )

    src = current_dir.parent / "wodoo" / "src"
    dest = current_dir / "wodoo_src"
    globals["tools"].sync_folder(src, dest, excludes=[".git"])
