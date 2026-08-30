"""Kennzahlen zur Sicherung, damit ein Ausfall auffaellt statt zu warten.

Warum es das braucht: eine Instanz, deren Sicherung nicht laeuft, sieht von
aussen aus wie jede andere. Sie antwortet, die Kurven sind gruen, und der
Unterschied faellt genau einmal auf -- an dem Tag, an dem jemand
wiederherstellen will. Am 29.08.2026 stand auf einer frisch aufgesetzten
Maschine die Anmeldung am Backup-Server auf "wartet auf Freigabe", und es
gab keine einzige Stelle, an der man das gesehen haette.

Geschrieben wird eine Datei fuer den textfile-Collector des node_exporter.
Der liest sie bei jedem Abruf mit, und damit stehen die Werte im lokalen
Prometheus -- und ueber remote_write in der zentralen Ablage.

Bewusst wird NICHT das Alter ausgerechnet, sondern der Zeitpunkt der letzten
Sicherung ausgegeben. Das Alter bildet man mit ``time() - <zeitpunkt>``; so
altert der Wert auch dann weiter, wenn dieser Befehl selbst nicht mehr
laeuft. Eine vorberechnete Alterszahl stuende in dem Fall fuer immer still
auf ihrem letzten Wert und saehe gesund aus.

Genau dagegen steht auch ``zodoo_backup_metrics_written_timestamp_seconds``:
altert dieser Wert, laeuft der Schreiber nicht mehr, und alles andere in der
Datei ist ab da nur noch Erinnerung.

Offsite: hier steht nur, ob es eingeschaltet ist. Einen Zeitpunkt gibt es
nicht -- ``offsite list`` liefert Text fuers Auge, und die Zustandsdatei ist
leer. Eine Null hinzuschreiben waere schlimmer als die Luecke: sie saehe aus
wie eine Messung.
"""

import json
import os
import subprocess
import time

import click

from .cli import cli, pass_config

DATEINAME = "zodoo-backup.prom"


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _zeile(name, wert, labels=None):
    if labels:
        teile = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{teile}}} {wert}"
    return f"{name} {wert}"


def _pgbackrest_werte(config):
    """(erfolg, neueste, neueste_voll, anzahl) aus `pgbackrest info`."""
    from .lib_pgbackrest import _pgbr_capture

    try:
        roh = _pgbr_capture(config, ["--output", "json", "info"])
    except (subprocess.CalledProcessError, OSError) as fehler:
        click.secho(f"pgbackrest info fehlgeschlagen: {fehler}", fg="yellow")
        return False, None, None, 0
    try:
        daten = json.loads(roh)
    except json.JSONDecodeError:
        click.secho("pgbackrest info lieferte kein gueltiges JSON", fg="yellow")
        return False, None, None, 0

    neueste = None
    neueste_voll = None
    anzahl = 0
    for stanza in daten:
        for sicherung in stanza.get("backup", []):
            stop = (sicherung.get("timestamp") or {}).get("stop")
            if not stop:
                continue
            anzahl += 1
            if neueste is None or stop > neueste:
                neueste = stop
            if sicherung.get("type") == "full":
                if neueste_voll is None or stop > neueste_voll:
                    neueste_voll = stop
    return True, neueste, neueste_voll, anzahl


@cli.command(
    name="backup-metrics",
    help=(
        "Kennzahlen zur Sicherung fuer den textfile-Collector schreiben. "
        "Laeuft aus den Cronjobs; von Hand nuetzlich, um zu sehen, was die "
        "Ueberwachung ueber diese Instanz erfaehrt."
    ),
)
@click.option(
    "--stdout",
    is_flag=True,
    help="Nur ausgeben, nichts schreiben.",
)
@pass_config
def backup_metrics(config, stdout):
    pgbr_an = _truthy(getattr(config, "run_pgbackrest", "0"))
    offsite_an = _truthy(getattr(config, "run_offsite", "0"))

    zeilen = [
        "# HELP zodoo_backup_enabled Ist diese Sicherungsart eingeschaltet.",
        "# TYPE zodoo_backup_enabled gauge",
        _zeile("zodoo_backup_enabled", int(pgbr_an), {"art": "pgbackrest"}),
        _zeile("zodoo_backup_enabled", int(offsite_an), {"art": "offsite"}),
    ]

    if pgbr_an:
        erfolg, neueste, neueste_voll, anzahl = _pgbackrest_werte(config)
        zeilen += [
            "# HELP zodoo_backup_query_success Liess sich der Zustand lesen.",
            "# TYPE zodoo_backup_query_success gauge",
            _zeile(
                "zodoo_backup_query_success",
                int(erfolg),
                {"art": "pgbackrest"},
            ),
        ]
        if erfolg:
            zeilen += [
                "# HELP zodoo_backup_count Anzahl der Sicherungen im Repository.",
                "# TYPE zodoo_backup_count gauge",
                _zeile("zodoo_backup_count", anzahl, {"art": "pgbackrest"}),
            ]
            # Fehlt eine Sicherung, wird die Zeile WEGGELASSEN statt auf 0
            # gesetzt. Eine 0 hiesse "1970 gesichert" und ergaebe ein
            # gigantisches Alter -- richtig gelesen, aber jeder Schwellenwert
            # wuerde sie mit einer echten alten Sicherung verwechseln. Fehlt
            # sie, faellt in PromQL `absent()` darauf an, und das ist die
            # ehrlichere Frage: es gibt gar keine.
            if neueste:
                zeilen += [
                    "# HELP zodoo_backup_last_success_timestamp_seconds "
                    "Ende der juengsten Sicherung (Alter: time() - Wert).",
                    "# TYPE zodoo_backup_last_success_timestamp_seconds gauge",
                    _zeile(
                        "zodoo_backup_last_success_timestamp_seconds",
                        neueste,
                        {"art": "pgbackrest"},
                    ),
                ]
            if neueste_voll:
                zeilen += [
                    "# HELP zodoo_backup_last_full_timestamp_seconds "
                    "Ende der juengsten VOLLstaendigen Sicherung.",
                    "# TYPE zodoo_backup_last_full_timestamp_seconds gauge",
                    _zeile(
                        "zodoo_backup_last_full_timestamp_seconds",
                        neueste_voll,
                        {"art": "pgbackrest"},
                    ),
                ]

    zeilen += [
        "# HELP zodoo_backup_metrics_written_timestamp_seconds Wann diese "
        "Datei zuletzt geschrieben wurde. Altert der Wert, laeuft der "
        "Schreiber nicht mehr und alles darueber ist veraltet.",
        "# TYPE zodoo_backup_metrics_written_timestamp_seconds gauge",
        _zeile(
            "zodoo_backup_metrics_written_timestamp_seconds", int(time.time())
        ),
    ]
    text = "\n".join(zeilen) + "\n"

    if stdout:
        click.echo(text)
        return

    run_dir = config.dirs.get("run")
    if not run_dir:
        click.secho(
            "Kein Laufverzeichnis bekannt -- nichts geschrieben.", fg="yellow"
        )
        return
    ordner = run_dir / "dashboard" / "textfile"
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / DATEINAME

    # Erst daneben, dann umbenennen: der node_exporter liest die Datei bei
    # jedem Abruf und darf sie nie halb beschrieben vorfinden. Die Endung
    # ist wichtig -- der Collector nimmt nur *.prom, die Nebendatei sieht er
    # also gar nicht erst.
    neben = ordner / (DATEINAME + ".neu")
    neben.write_text(text)
    neben.chmod(0o644)
    os.replace(neben, ziel)
    click.secho(f"Sicherungs-Kennzahlen geschrieben: {ziel}", fg="green")
