import secrets
import string


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def generate_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def after_settings(settings, config):
    import click

    # Mirror logsio_web: auto-generate the dashboard gate password on real
    # instances, but leave it empty in DEVMODE (gate then stays open).
    if not settings.get("DASHBOARD_PASSWORD") and settings["DEVMODE"] != "1":
        settings["DASHBOARD_PASSWORD"] = generate_password(12)

    # ------------------------------------------------------------------
    # remote_write: Schutzplanken
    # ------------------------------------------------------------------
    url = (settings.get("DASHBOARD_REMOTE_WRITE_URL") or "").strip()
    if not url:
        return

    # Ohne Dashboard gibt es keinen Prometheus, der etwas schicken koennte.
    if not _truthy(settings.get("RUN_DASHBOARD", "0")):
        click.secho(
            "DASHBOARD_REMOTE_WRITE_URL ist gesetzt, aber RUN_DASHBOARD=0 -- "
            "ohne den lokalen Prometheus gibt es nichts zu schicken. "
            "remote_write bleibt aus.",
            fg="yellow",
        )
        settings["DASHBOARD_REMOTE_WRITE_URL"] = ""
        return

    # Eine Kiste unter dem Schreibtisch gehoert nicht in die Flottensicht --
    # dieselbe Regel wie bei pgbackrest und offsite.
    if settings.get("DEVMODE") == "1" and not _truthy(
        settings.get("DASHBOARD_REMOTE_FORCE_IN_DEVMODE", "0")
    ):
        settings["DASHBOARD_REMOTE_WRITE_URL"] = ""
        return

    # Der wichtigste Riegel. Ohne eigenen Namen laegen die Messwerte der
    # ganzen Flotte uebereinander, und man saehe es nicht: die Kurven waeren
    # da, nur eben von allen Maschinen gemischt. Lieber gar nicht schicken.
    if not (settings.get("DASHBOARD_REMOTE_WRITE_INSTANZ") or "").strip():
        click.secho(
            "DASHBOARD_REMOTE_WRITE_INSTANZ fehlt: ohne eigenen Namen wuerden "
            "die Messwerte dieser Maschine mit denen aller anderen "
            "verschmelzen. remote_write bleibt aus.\n"
            "  -> den eindeutigen Maschinennamen setzen, NICHT den "
            "Projektnamen ($PROJECT_NAME heisst ueberall gleich).",
            fg="red",
        )
        settings["DASHBOARD_REMOTE_WRITE_URL"] = ""
        return

    # Ohne Zugangsdaten laeuft es weiter -- es gibt Ablagen ohne Anmeldung.
    # Gegen eine, die eine verlangt, quittiert Prometheus jeden Versuch mit
    # 401, und zwar ausschliesslich im eigenen Log. Also einmal sagen.
    if not (settings.get("DASHBOARD_REMOTE_WRITE_USER") or "").strip():
        click.secho(
            "remote_write ohne Benutzer: verlangt die Ablage eine Anmeldung, "
            "scheitert jeder Versuch mit 401 -- sichtbar nur im "
            "Prometheus-Log dieser Maschine.",
            fg="yellow",
        )
