import inspect
import os
import shutil
from pathlib import Path
import inspect
import os
from pathlib import Path

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)
dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))


def after_compose(config, settings, yml, globals):
    shutil.copy(
        current_dir.parent / "common_snippets" / "set_docker_group.sh",
        current_dir / "set_docker_group.sh",
    )
    src = current_dir.parent / "wodoo" / "src"
    dest = current_dir / "wodoo_src"
    globals["tools"].sync_folder(src, dest, excludes=[".git"])

    # store also in clear text the requirements
    if not yml.get("services", {}).get("robot"):
        return
    service = yml["services"]["robot"]
    if "build" in service:
        service["build"]["args"]["OWNER_UID"] = config.owner_uid
