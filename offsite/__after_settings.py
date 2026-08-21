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
