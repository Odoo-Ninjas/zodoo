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
    # Skip all write operations if images dir is not actually writable.
    # Use a real write test (not just os.access) since ACLs/namespaces
    # can cause os.access to return True while writes fail.
    import tempfile as _tmpfile, os as _os
    try:
        with _tmpfile.NamedTemporaryFile(dir=str(current_dir), delete=True):
            pass
    except (PermissionError, OSError):
        return
    # Skip all write operations if robot service is not configured.
    if not yml.get("services", {}).get("robot"):
        return
    try:
        shutil.copyfile(
            current_dir.parent / "common_snippets" / "set_docker_group.sh",
            current_dir / "set_docker_group.sh",
        )
    except PermissionError:
        pass  # read-only images dir on CI runners
    try:
        src = current_dir.parent / "zodoo" / "src"
        dest = current_dir / "zodoo_src"
        import time
        import random

        for attempt in range(5):
            try:
                globals["tools"].sync_folder(src, dest, excludes=[".git"])
                break
            except PermissionError:
                break  # read-only images dir on CI runners
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(random.uniform(0.5, 3.0))
    except Exception:
        pass  # read-only images dir or rsync failure on CI runners

    # store also in clear text the requirements
    if not yml.get("services", {}).get("robot"):
        return
    service = yml["services"]["robot"]
    if "build" in service:
        service["build"]["args"]["OWNER_UID"] = config.owner_uid
