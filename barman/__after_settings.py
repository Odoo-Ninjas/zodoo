def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def after_settings(settings, config):
    """Disable Barman by default on DEVMODE machines.

    Continuous WAL streaming + daily base backups are production concerns and
    pure overhead on a developer box. When DEVMODE=1 we force RUN_BARMAN=0 so
    the service isn't even merged into the compose (and postgres keeps its
    stock config). A developer who wants to test the integration locally can
    opt back in with BARMAN_FORCE_IN_DEVMODE=1.
    """
    if settings.get("DEVMODE") == "1" and not _truthy(
        settings.get("BARMAN_FORCE_IN_DEVMODE", "0")
    ):
        settings["RUN_BARMAN"] = "0"

    # Barman streams WAL from, and recovers into, the zodoo-managed postgres
    # (its compose `depends_on: postgres` and the recover volume-swap both
    # require it). With an external postgres (RUN_POSTGRES=0) the barman service
    # can't be wired up - disable it with a clear message instead of letting the
    # compose merge fail on a dangling depends_on.
    if _truthy(settings.get("RUN_BARMAN", "0")) and not _truthy(
        settings.get("RUN_POSTGRES", "0")
    ):
        import click

        click.secho(
            "RUN_BARMAN=1 needs a zodoo-managed postgres (RUN_POSTGRES=1); "
            "disabling barman for this project.",
            fg="red",
        )
        settings["RUN_BARMAN"] = "0"
