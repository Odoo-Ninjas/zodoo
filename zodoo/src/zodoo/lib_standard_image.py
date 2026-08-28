"""Standard-Image-Modus: das offizielle odoo:<version> statt unseres Images.

Der Rest des Stacks (Proxy, Postgres, pgBackRest, Monitoring) laeuft unveraendert
weiter -- siehe odoo/__after_compose.py:_apply_standard_odoo_image. Was im
offiziellen Image fehlt, ist alles, was wir in unser Image hineinbauen:
/odoolib, der In-Container-Supervisor und die zodoo-CLI. Die Befehle, die
darauf zeigen, brechen dort mit einem "No such file"-Fehler aus dem Container
ab; hier stehen die Ersatzwege und die klaren Absagen.
"""

import click

from .tools import __dcrun
from .tools import abort


def is_standard_image(config):
    return str(getattr(config, "odoo_standard_image", "") or "").strip() in (
        "1",
        "true",
        "True",
    )


def abort_if_standard_image(config, command, hint=None):
    """Einen Befehl absagen, der zwingend unser Image braucht.

    Lieber hier eine verstaendliche Meldung als weiter unten ein
    "exec: /odoolib/...: not found" aus dem Container.
    """
    if not is_standard_image(config):
        return
    text = (
        f"„{command}“ gibt es im Standard-Image-Modus nicht: der Befehl "
        "laeuft in unserem eigenen Odoo-Image (/odoolib), das offizielle "
        "Image von Docker Hub bringt das nicht mit."
    )
    if hint:
        text += f"\n{hint}"
    abort(text)


def update(config, modules, non_interactive=True):
    """Module im offiziellen Image installieren/aktualisieren.

    Ersetzt /odoolib/update_modules.py durch das mitgelieferte Odoo-CLI.
    -i und -u zusammen: -i ueberspringt bereits installierte Module, -u
    ueberspringt nicht installierte -- so deckt ein Aufruf beide Faelle ab,
    ohne vorher den Installationsstand abzufragen.
    """
    mods = ",".join(m for m in modules if m) or "base"
    params = [
        "odoo",
        "odoo",
        "-c",
        "/etc/odoo/odoo.conf",
        "-d",
        config.dbname,
        "-i",
        mods,
        "-u",
        mods,
        "--stop-after-init",
        # Ohne das laeuft der Cron in einem Update-Container mit und
        # arbeitet auf einer halb migrierten Datenbank.
        "--max-cron-threads=0",
    ]
    click.secho(f"Standard-Image: aktualisiere {mods}", fg="green")
    returncode, output = __dcrun(
        config,
        params,
        returnproc=True,
        interactive=False,
        write_to_console=True,
    )
    return returncode
