def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def after_settings(settings, config):
    """Offsite-Backup auf DEVMODE-Maschinen abschalten.

    Ein Entwicklerrechner soll nachts nicht ungefragt Daten zu einem externen
    Speicheranbieter schieben. Wer die Integration lokal testen will, setzt
    OFFSITE_FORCE_IN_DEVMODE=1.
    """
    if settings.get("DEVMODE") == "1" and not _truthy(
        settings.get("OFFSITE_FORCE_IN_DEVMODE", "0")
    ):
        settings["RUN_OFFSITE"] = "0"
