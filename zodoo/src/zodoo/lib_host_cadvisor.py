"""Ein cadvisor fuer die ganze Maschine statt einer je Instanz.

cadvisor misst Container: CPU, Speicher, Netz. Gemessen wird dabei immer
ALLES, was auf der Maschine laeuft -- der Prozess haengt am Docker-Daemon
und an /sys, nicht an einem Projekt. Definiert war er bisher trotzdem im
Stapel jeder Instanz, und damit lief er so oft wie es Instanzen gibt.

Auf cicd-3dm mit 99 Containern waren das fuenf Stueck, die im Halbminutentakt
jeweils dieselben 99 Container abgefragt haben: dieselbe Arbeit, fuenfmal,
rund um die Uhr. Gemessen 30 Prozent eines Kerns pro Container -- nicht wegen
ZFS (die Maschine faehrt overlay2), sondern schlicht wegen der Menge.

Hier laeuft deshalb genau einer, ausserhalb der Projekt-Stapel:

    Name      zodoo_cadvisor
    Netz      zodoo_monitoring (extern, gehoert keinem Projekt)

Jede Instanz haengt ihren Prometheus zusaetzlich in dieses Netz und fragt
ihn unter seinem Namen ab. Damit ist der Behaelter nicht mehr an das Leben
einer einzelnen Instanz gebunden: `odoo down` einer Instanz nimmt den
anderen nicht die Messung weg.

Wer ihn anlegt: der Erste, der hochfaehrt (siehe `ensure` -- aufgerufen aus
`up`). Das ist bewusst kein eigener Dienst und kein systemd: es soll nichts
zu installieren geben, damit eine Maschine nicht halb eingerichtet sein
kann. Der Aufruf ist auch dann guenstig, wenn alles laeuft -- ein
`docker inspect`.

Geaendert wird der Behaelter nur, wenn sich seine Beschreibung aendert:
Abbild, Argumente und Mounts stehen unten, ihr Fingerabdruck haengt als
Label am Behaelter. Stimmt er nicht mehr, wird neu angelegt; sonst bleibt
alles stehen. So zieht ein zodoo-Update den cadvisor mit, ohne dass jemand
daran denken muss.
"""

import hashlib
import json
import shutil
import subprocess

import click

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup

CONTAINER = "zodoo_cadvisor"
NETZ = "zodoo_monitoring"
LABEL = "zodoo.cadvisor.spec"

ABBILD = "gcr.io/cadvisor/cadvisor:v0.49.1"

# Dieselben Argumente wie zuvor im Stapel der Instanz, siehe
# dashboard/docker-compose.yml und CHANGELOG zu v11.4.x:
# disk/diskIO aus (auf ZFS-Hosts iteriert cadvisor dafuer ueber tausende
# Layer-Datasets und haelt zwei zfs-Prozesse dauerhaft auf 100%), und
# Housekeeping auf 30s statt 1s.
ARGUMENTE = [
    "--disable_metrics=disk,diskIO",
    "--housekeeping_interval=30s",
    "--docker_only=true",
    "--store_container_labels=false",
]

MOUNTS = [
    "/:/rootfs:ro",
    "/var/run:/var/run:ro",
    "/sys:/sys:ro",
    "/var/lib/docker:/var/lib/docker:ro",
    "/var/run/docker.sock:/var/run/docker.sock:ro",
]


def fingerabdruck():
    """Kurzer Hash ueber alles, was den Behaelter ausmacht."""
    beschreibung = json.dumps(
        {"image": ABBILD, "args": ARGUMENTE, "mounts": MOUNTS, "net": NETZ},
        sort_keys=True,
    )
    return hashlib.sha256(beschreibung.encode("utf-8")).hexdigest()[:12]


def _docker(*args, check=True):
    return subprocess.run(
        ["docker", *args],
        check=check,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _zustand():
    """(existiert, laeuft, fingerabdruck) des Behaelters."""
    res = _docker(
        "inspect",
        "--format",
        "{{.State.Running}}\t{{index .Config.Labels " + f'"{LABEL}"' + "}}",
        CONTAINER,
        check=False,
    )
    if res.returncode:
        return (False, False, "")
    zeile = (res.stdout or "").strip().splitlines()[-1]
    teile = zeile.split("\t")
    laeuft = teile[0].strip() == "true"
    marke = teile[1].strip() if len(teile) > 1 else ""
    if marke == "<no value>":
        marke = ""
    return (True, laeuft, marke)


def netz_anlegen():
    """Das gemeinsame Netz muss VOR dem compose-up da sein.

    Die Instanzen binden es als `external` ein -- fehlt es, scheitert
    `docker compose up` der ganzen Instanz, nicht nur die Messung. Deshalb
    ist ein Fehler hier keiner, ueber den man hinweggehen darf.
    """
    if _docker("network", "inspect", NETZ, check=False).returncode == 0:
        return
    res = _docker("network", "create", NETZ, check=False)
    if res.returncode:
        # Zwei Instanzen koennen gleichzeitig hochfahren; dann hat die
        # andere das Netz in der Zwischenzeit angelegt. Das ist kein Fehler.
        if _docker("network", "inspect", NETZ, check=False).returncode == 0:
            return
        from .tools import abort

        abort(f"Netz {NETZ} liess sich nicht anlegen:\n{res.stdout}")


def _anlegen():
    _docker("rm", "-f", CONTAINER, check=False)
    befehl = [
        "run",
        "-d",
        "--name",
        CONTAINER,
        "--restart",
        "unless-stopped",
        "--privileged",
        "--network",
        NETZ,
        "--label",
        f"{LABEL}={fingerabdruck()}",
    ]
    for mount in MOUNTS:
        befehl += ["-v", mount]
    befehl += [ABBILD, *ARGUMENTE]
    _docker(*befehl)


def ensure(config=None):
    """Netz und Behaelter sicherstellen. Aus `up` heraus aufgerufen.

    Der Behaelter selbst darf scheitern, ohne dass die Instanz stehen
    bleibt: dann fehlen Container-Messwerte, aber Odoo laeuft. Das Netz
    darf es nicht (siehe `netz_anlegen`).
    """
    if not shutil.which("docker"):
        # Die CLI laeuft auch IM Container, wo es kein docker gibt (siehe
        # CLAUDE.md). Dort gibt es nichts anzulegen -- und ein Fehler hier
        # wuerde einen Start verhindern, der mit Messwerten nichts zu tun
        # hat.
        return

    netz_anlegen()

    existiert, laeuft, marke = _zustand()
    try:
        if not existiert or marke != fingerabdruck():
            _anlegen()
        elif not laeuft:
            _docker("start", CONTAINER)
    except subprocess.CalledProcessError as e:
        click.secho(
            f"cadvisor ({CONTAINER}) liess sich nicht starten -- die "
            "Container-Messwerte dieser Maschine bleiben leer, die Instanz "
            f"laeuft weiter:\n{e.output}",
            fg="yellow",
        )


@cli.group(
    name="host-cadvisor",
    cls=AliasedGroup,
    help="Der gemeinsame cadvisor dieser Maschine (alle Instanzen teilen ihn).",
)
@pass_config
def host_cadvisor(config):
    pass


@host_cadvisor.command(name="status")
@pass_config
def status(config):
    existiert, laeuft, marke = _zustand()
    if not existiert:
        click.secho(
            f"{CONTAINER} gibt es nicht. Er entsteht beim naechsten "
            "`odoo up` einer Instanz mit RUN_DASHBOARD=1.",
            fg="yellow",
        )
        return
    click.secho(
        f"{CONTAINER}: {'laeuft' if laeuft else 'gestoppt'}, "
        f"Stand {marke or '?'} (erwartet {fingerabdruck()})",
        fg="green" if laeuft and marke == fingerabdruck() else "yellow",
    )
    click.echo(_docker("logs", "--tail", "5", CONTAINER, check=False).stdout)


@host_cadvisor.command(name="restart")
@pass_config
def restart(config):
    ensure(config)
    _docker("restart", CONTAINER, check=False)
    click.secho(f"{CONTAINER} neu gestartet.", fg="green")


@host_cadvisor.command(name="remove")
@pass_config
def remove(config):
    """Behaelter entfernen (das Netz bleibt -- die Instanzen binden es ein)."""
    _docker("rm", "-f", CONTAINER, check=False)
    click.secho(
        f"{CONTAINER} entfernt. Bis zum naechsten `odoo up` fehlen der "
        "ganzen Maschine die Container-Messwerte.",
        fg="yellow",
    )
