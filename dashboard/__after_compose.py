"""Prometheus je Projekt konfigurieren, statt fuer alle dieselbe Datei.

Bisher haengt ``dashboard/config/prometheus.yml`` schreibgeschuetzt aus dem
gemeinsamen Images-Verzeichnis in den Container -- dieselbe Datei fuer jedes
Projekt auf der Maschine. Fuer die Messpunkte reicht das: die sind ueberall
gleich. Fuer ``remote_write`` reicht es nicht, denn Ziel, Zugang und der
eigene Name sind je Maschine verschieden.

Hier wird deshalb eine Kopie nach ``$HOST_RUN_DIR/dashboard/prometheus.yml``
gerendert und der Mount darauf umgebogen -- denselben Weg gehen schon die
Dockerfiles und die Compose-Datei.

Dazu bekommt der node_exporter den textfile-Collector: `odoo
backup-metrics` legt dort Kennzahlen zur Sicherung ab, und ohne den
Collector laege die Datei nur herum.

Wichtig: das Umbiegen von prometheus.yml passiert NUR, wenn
remote_write eingeschaltet ist. Ohne die
Einstellung bleibt alles beim Alten, inklusive des bisherigen Mounts. Eine
Aenderung, die auch dort etwas tut, wo sie nichts zu tun hat, ist eine
Aenderung mit unnoetigem Radius.
"""

import inspect
import os
from pathlib import Path

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)

ZIEL_IM_CONTAINER = "/etc/prometheus/prometheus.yml"

KOPF = """# ACHTUNG: erzeugt von zodoo (dashboard/__after_compose.py).
# Aenderungen hier ueberlebt kein `odoo reload`.
# Die Vorlage liegt in $ODOO_IMAGES/dashboard/config/prometheus.yml,
# die Werte kommen aus den DASHBOARD_REMOTE_WRITE_*-Einstellungen.
"""


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _wert(settings, name):
    return (settings.get(name) or "").strip()


def _mount_umbiegen(dienst, neue_quelle):
    """Die Quelle des prometheus.yml-Mounts auf die gerenderte Datei zeigen.

    Gesucht wird ueber das Ziel im Container, nicht ueber die Quelle: die
    Quelle ist zu diesem Zeitpunkt bereits von `docker compose config`
    aufgeloest worden und enthaelt den expandierten $ODOO_IMAGES-Pfad.

    Findet sich der Mount nicht, meldet das der Aufrufer -- laut, siehe dort.
    Still weiterzulaufen hiesse: Prometheus liest weiter die gemeinsame
    Datei, remote_write ist wirkungslos, und niemand merkt es. Die Instanz
    laeuft ja.
    """
    for eintrag in dienst.get("volumes") or []:
        if isinstance(eintrag, dict):
            if eintrag.get("target") == ZIEL_IM_CONTAINER:
                eintrag["source"] = str(neue_quelle)
                return True
        elif isinstance(eintrag, str):
            # Kurzform "quelle:ziel[:ro]" -- sollte nach der Normalisierung
            # nicht mehr vorkommen, aber lieber behandelt als uebersehen.
            teile = eintrag.split(":")
            if len(teile) >= 2 and teile[1] == ZIEL_IM_CONTAINER:
                teile[0] = str(neue_quelle)
                dienst["volumes"][dienst["volumes"].index(eintrag)] = ":".join(teile)
                return True
    return False


def _rendern(settings, run_dir):
    """Die Vorlage lesen, ergaenzen und nur bei Aenderung schreiben."""
    import yaml

    vorlage = current_dir / "config" / "prometheus.yml"
    daten = yaml.safe_load(vorlage.read_text()) or {}

    # Der eigene Name. Ohne ihn kommt dieser Code gar nicht erst dran
    # (siehe __after_settings.py), deshalb hier kein zweiter Rueckfall --
    # ein Rueckfall waere genau das Verhalten, das wir verhindern wollen.
    instanz = _wert(settings, "DASHBOARD_REMOTE_WRITE_INSTANZ")
    daten.setdefault("global", {}).setdefault("external_labels", {})[
        "instanz"
    ] = instanz

    ziel = {"url": _wert(settings, "DASHBOARD_REMOTE_WRITE_URL")}

    benutzer = _wert(settings, "DASHBOARD_REMOTE_WRITE_USER")
    if benutzer:
        ziel["basic_auth"] = {
            "username": benutzer,
            "password": _wert(settings, "DASHBOARD_REMOTE_WRITE_PASSWORD"),
        }

    # Bewusst kleiner als die Vorgaben: das hier laeuft auf einer
    # Kundenmaschine neben Odoo und Postgres. Ist die Ablage kurz weg,
    # soll Prometheus warten und nicht Speicher fuellen -- deshalb ein
    # begrenzter Puffer statt der voreingestellten Schwaerme.
    ziel["queue_config"] = {
        "capacity": 5000,
        "max_shards": 3,
        "max_samples_per_send": 1000,
    }

    daten["remote_write"] = [ziel]

    text = KOPF + yaml.safe_dump(daten, sort_keys=False, allow_unicode=True)

    ordner = run_dir / "dashboard"
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / "prometheus.yml"

    # Nur bei echter Aenderung schreiben: die Datei haengt in einem
    # laufenden Container, und jedes `odoo reload` wuerde sonst ihre
    # Zeitstempel anfassen, ohne dass sich etwas geaendert hat.
    if not datei.exists() or datei.read_text() != text:
        datei.write_text(text)

    # Lesbar fuer alle: der Prometheus-Container laeuft als nobody und
    # kaeme an eine 0600-Datei nicht heran. Der Zugang darin ist ohnehin
    # nur fuer diese eine Maschine gut -- die Ablage haengt beim Schreiben
    # das Label "instanz" selbst an, eine Maschine kann sich damit nicht
    # als eine andere ausgeben. Und wer auf dieser Maschine mitliest, ist
    # ihr Besitzer.
    datei.chmod(0o644)
    return datei


def _textfile_einhaengen(yml, run_dir):
    """node_exporter den textfile-Collector geben.

    Dort legt `odoo backup-metrics` ab, wie es um die Sicherung steht. Ohne
    den Collector wuerde die Datei geschrieben und nie gelesen -- und das
    waere die schlechteste aller Varianten: es saehe nach Ueberwachung aus.

    Laeuft unabhaengig von remote_write: die Werte sind auch auf einer
    einzelnen Maschine nuetzlich, im Grafana vor Ort.
    """
    dienst = (yml.get("services") or {}).get("node_exporter")
    if not dienst:
        return
    ordner = run_dir / "dashboard" / "textfile"
    ordner.mkdir(parents=True, exist_ok=True)

    schalter = "--collector.textfile.directory=/textfile"
    befehl = dienst.setdefault("command", [])
    if isinstance(befehl, list) and schalter not in befehl:
        befehl.append(schalter)

    ziel = "/textfile"
    volumes = dienst.setdefault("volumes", [])
    vorhanden = any(
        (isinstance(v, dict) and v.get("target") == ziel)
        or (isinstance(v, str) and f":{ziel}" in v)
        for v in volumes
    )
    if not vorhanden:
        # Lange Form, nicht "quelle:ziel": dieser Haken laeuft NACH
        # `docker compose config`, das Kurzformen normalisiert. Ein hier
        # angehaengter String wird nicht mehr normalisiert, und
        # create_directories haelt dann die linke Seite fuer einen Hostpfad.
        volumes.append(
            {
                "type": "bind",
                "source": str(ordner),
                "target": ziel,
                "read_only": True,
            }
        )


def after_compose(config, settings, yml, globals):
    if not _truthy(settings.get("RUN_DASHBOARD", "0")):
        return

    run_dir = Path(settings["HOST_RUN_DIR"])
    _textfile_einhaengen(yml, run_dir)

    if not _wert(settings, "DASHBOARD_REMOTE_WRITE_URL"):
        return

    dienst = (yml.get("services") or {}).get("prometheus")
    if not dienst:
        return

    datei = _rendern(settings, run_dir)

    if not _mount_umbiegen(dienst, datei):
        # Zweigleisig, und das mit Absicht: lib_composer faengt jede Ausnahme
        # aus diesem Haken ab und macht daraus eine gelbe Zeile "Warning:
        # after_compose failed". Das geht in einem `odoo reload` unter. Die
        # rote Zeile davor geht es nicht.
        import click

        click.secho(
            f"dashboard: der Mount fuer {ZIEL_IM_CONTAINER} war im "
            "prometheus-Dienst nicht zu finden -- remote_write ist damit "
            "WIRKUNGSLOS. Prometheus liest weiter die gemeinsame Vorlage, "
            "diese Maschine taucht in der zentralen Ablage nicht auf.",
            fg="red",
        )
        raise Exception(
            f"prometheus.yml-Mount ({ZIEL_IM_CONTAINER}) nicht gefunden -- "
            "remote_write waere wirkungslos."
        )
