import subprocess
from pathlib import Path
import os


def after_settings(settings, config):
    module_name = "wodoo_logging"
    gimera = Path(os.getcwd()) / "gimera.yml"
    url = "git@github.com:Odoo-Ninjas/wodoo-logging"
    if url in gimera.read_text():
        return
    if not config.RUN_LOGCOLLECTOR:
        return
    manifestfile = Path(os.getcwd()) / "MANIFEST"
    manifest = eval(manifestfile.read_text())
    version = str(manifest["version"])
    path = "addons/wodoo-logging"
    subprocess.check_call(
        [
            "gimera",
            "add",
            "-u",
            url,
            "-b",
            version,
            "-p",
            path,
            "-t",
            "integrated",
        ]
    )
    subprocess.check_call(["gimera", "apply", path])

    if path not in manifest["addons_paths"]:
        manifest["addons_paths"].append(path)
        manifestfile.write_text(str(manifest))
    if module_name not in manifest["install"]:
        manifest["install"].append(module_name)
        manifestfile.write_text(str(manifest))

    subprocess.check_call(["odoo", "rewrite"])
