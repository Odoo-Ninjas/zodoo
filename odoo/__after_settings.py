import stat
import sys
import os
import click
import platform
import subprocess
from pathlib import Path
import inspect


def after_settings(settings, config):
    from wodoo import odoo_config

    if settings.get("ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER") == "1":
        settings["RUN_ODOO_QUEUEJOBS"] = "0"
        settings["RUN_ODOO_CRONJOBS"] = "0"

    if settings.get("ODOO_CRON_IN_ONE_CONTAINER") == "1":
        if settings.get("ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER") == "1":
            click.secho(
                (
                    "Conflicting settings: "
                    "ODOO_CRON_IN_WEB_CONTAINER and "
                    "ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER"
                ),
                fg="red",
            )
            sys.exit(-1)

    # Build Short version for packaging
    settings["ODOO_PYTHON_VERSION_SHORT"] = ".".join(
        settings["ODOO_PYTHON_VERSION"].split(".")[:2]
    )

    m = odoo_config.MANIFEST()
    settings["SERVER_WIDE_MODULES"] = ",".join(
        m.get("server-wide-modules", None) or ["web"]
    )

    # if odoo does not exist yet and version is given then we setup gimera and clone it

    settings["ODOO_VERSION"] = str(odoo_config.current_version())
    settings.write()

    # replace any env variable
    if not settings["ODOO_FILES"]:
        settings["ODOO_FILES"] = str(Path(settings["HOST_RUN_DIR"]) / "files")
