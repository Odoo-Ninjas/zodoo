import re
import base64
import click
import yaml
import inspect
import os
from pathlib import Path
import shutil

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def after_compose(config, settings, yml, globals):
    # set postgres version
    V = settings["POSTGRES_VERSION"]
    if "postgres" in yml["services"] and yml["services"]["postgres"].get("build"):
        yml["services"]["postgres"]["build"]["dockerfile"] = f"Dockerfile.{V}"

    # if a named postgres volume is used, make it as external with name
    if settings["NAMED_ODOO_POSTGRES_VOLUME"]:
        yml["volumes"]["odoo_postgres_volume"] = {
            "external": True,
            "name": settings["NAMED_ODOO_POSTGRES_VOLUME"],
        }
