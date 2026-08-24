def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def after_settings(settings, config):
    """Switch offsite backup off on DEVMODE machines.

    A developer box should not push data to an external storage provider
    overnight without being asked. Anyone wanting to test the integration
    locally sets OFFSITE_FORCE_IN_DEVMODE=1.
    """
    if settings.get("DEVMODE") == "1" and not _truthy(
        settings.get("OFFSITE_FORCE_IN_DEVMODE", "0")
    ):
        settings["RUN_OFFSITE"] = "0"

    # The minutely WAL job only has something to do when a write-only database
    # target is configured. Left defined, it starts the CLI 1440 times a day on
    # every instance to return immediately - measured at 0.44 s per start, so
    # about 10 minutes of CPU per day and instance for nothing, and roughly 18
    # CPU-hours a day across a hundred instances.
    #
    # An empty CRONJOB_* value is skipped by the cron daemon (`if not job:
    # continue`), so clearing it removes the job rather than breaking it.
    if not (
        (settings.get("OFFSITE_WO_URL") or "").strip()
        and (settings.get("OFFSITE_WO_DB_RECIPIENT") or "").strip()
    ):
        settings["CRONJOB_OFFSITE_WAL"] = ""
