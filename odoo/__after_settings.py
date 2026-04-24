import click
from pathlib import Path


def after_settings(settings, config):
    from zodoo import odoo_config

    # ODOO_*_IN_ONE_CONTAINER is obsolete: web, cronjobs and queuejobs now
    # always share a single container, managed by supervisor.py. Warn on
    # legacy usage so stale settings files can be cleaned up.
    for obsolete in (
        "ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER",
        "ODOO_CRON_IN_ONE_CONTAINER",
    ):
        if settings.get(obsolete) == "1":
            click.secho(
                f"Setting {obsolete}=1 is obsolete and ignored — web, "
                "cronjobs and queuejobs now always run in a single odoo "
                "container. Toggle RUN_ODOO_CRONJOBS / RUN_ODOO_QUEUEJOBS / "
                "RUN_ODOO_WEB to disable individual roles.",
                fg="yellow",
            )

    m = odoo_config.MANIFEST()
    settings["SERVER_WIDE_MODULES"] = ",".join(
        m.get("server-wide-modules", None) or ["web"]
    )

    # if odoo does not exist yet and version is given then we setup gimera and clone it

    settings["ODOO_VERSION"] = str(odoo_config.current_version())
    # Build Short version for packaging
    if float(settings["ODOO_VERSION"]) >= 13.0:
        settings["ODOO_PYTHON_VERSION_SHORT"] = ".".join(
            settings["ODOO_PYTHON_VERSION"].split(".")[:2]
        )

    settings.write()

    # replace any env variable
    if not settings["ODOO_FILES"]:
        settings["ODOO_FILES"] = str(Path(settings["HOST_RUN_DIR"]) / "files")
