from pathlib import Path

import click

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import abort
from .tools import __get_cmd

# Dateiname des Dumps, den der Offsite-Lauf ohne Barman selbst zieht.
#
# Fester Name mit Absicht: die Datei wird bei jedem Lauf ueberschrieben,
# statt sich in DUMPS_PATH zu stapeln. Fuer restic ist das kein Nachteil - es
# dedupliziert gegen den Stand der Vornacht und legt nur die Differenz ab.
OFFSITE_DB_DUMP = "offsite-db.dump"


@cli.group(
    cls=AliasedGroup,
    help="Verschluesseltes Offsite-Backup (restic, Regelfall unser Backup-Server).",
)
@pass_config
def offsite(config):
    pass


def _ensure_offsite(config):
    if not getattr(config, "run_offsite", False):
        abort(
            "Offsite-Backup ist nicht aktiviert. RUN_OFFSITE=1 setzen (auf "
            "DEVMODE-Maschinen zusaetzlich OFFSITE_FORCE_IN_DEVMODE=1), dann "
            "`odoo reload && odoo build offsite`."
        )
    if not (config.OFFSITE_REPO or "").strip():
        abort(
            "OFFSITE_REPO ist leer - es ist kein Offsite-Ziel hinterlegt.\n"
            "Fuer unseren Backup-Server einfach `odoo offsite register` laufen "
            "lassen; das beantragt einen Bereich und hinterlegt alles Noetige.\n"
            "Von Hand, z.B. eine Hetzner Storage Box:\n"
            "  OFFSITE_REPO=sftp:u123456@u123456.your-storagebox.de:23/zodoo/projekt"
        )


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _offsite_run(config, args, env=None):
    """Startet den offsite-Container fuer einen einzelnen Lauf.

    Der Service liegt im Profil "manual" (kein Dauerlaeufer), deshalb hier
    profile="all" statt des Standardprofils - sonst kennt `docker compose run`
    den Service nicht.
    """
    import subprocess

    _ensure_offsite(config)
    # Fester Containername = Ausschluss paralleler Laeufe: docker verweigert
    # einen zweiten Container gleichen Namens. Darauf stuetzt sich der
    # Entrypoint, wenn er eine haengende Sperre aufbricht - ohne diesen
    # Ausschluss koennte er die Sperre eines noch laufenden Backups brechen.
    name = f"{config.project_name}_offsite_run"
    cmd = __get_cmd(config, profile="all") + [
        "run",
        "--rm",
        "-T",
        "--name",
        name,
    ]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += ["offsite"]
    cmd += args
    return subprocess.check_call(cmd)


def _dump_db_for_offsite(config):
    """Frischen Datenbank-Dump fuer den Offsite-Lauf ziehen.

    Laeuft Barman, ist die Datenbank ueber WAL + Basisbackup schon im Archiv
    und hier ist nichts zu tun. Laeuft es nicht, faende der Container nur den
    Filestore vor - und ein Archiv aus lauter Anhaengen sieht aus wie ein
    Backup, bis jemand wiederherstellen will.

    Gibt den Dateinamen zurueck, den der Container einsammeln soll.
    """
    from .lib_backup import _backup_pgdump

    dumps = Path(config.dumps_path)
    dumps.mkdir(parents=True, exist_ok=True)
    final = dumps / OFFSITE_DB_DUMP
    # Erst daneben schreiben, dann umbenennen: bricht der Dump ab, bleibt der
    # Stand des Vorlaufs liegen, statt dass beide Staende fehlen.
    tmp = dumps / (OFFSITE_DB_DUMP + ".new")
    if tmp.exists():
        tmp.unlink()

    click.secho(
        f"offsite: kein Barman aktiv - ziehe einen frischen Dump nach {final}",
        fg="yellow",
    )
    _backup_pgdump(
        config,
        tmp,
        config.DBNAME,
        config.DB_HOST,
        config.DB_PORT,
        config.DB_USER,
        config.DB_PWD,
        "custom",
        # Unkomprimiert (-Z0), und das ist hier kein Versehen: restic vergleicht
        # den Dump mit dem der Vornacht und legt nur die geaenderten Bloecke ab
        # - komprimiert wird danach ohnehin ueber OFFSITE_COMPRESSION. Ein
        # gzip-Dump aendert sich dagegen auf ganzer Laenge und landet jede
        # Nacht komplett neu im Repository.
        0,
        1,
        False,
        False,
        (),
    )
    tmp.replace(final)
    return final.name


@offsite.command(
    name="backup",
    help="Jetzt ein Offsite-Backup ziehen (derselbe Lauf wie der Cronjob).",
)
@pass_config
def offsite_backup(config):
    # Haengt im gemeinsamen Cronjobs-Daemon (CRONJOB_OFFSITE_BACKUP) und
    # laeuft damit auf JEDEM Projekt. Ohne Offsite-Konfiguration muss das ein
    # stiller Erfolg sein, sonst meldet jedes andere Projekt jede Nacht einen
    # Cron-Fehler.
    if not getattr(config, "run_offsite", False):
        click.secho(
            "Offsite-Backup ist nicht aktiviert (RUN_OFFSITE=0); uebersprungen.",
            fg="yellow",
        )
        return
    if not (config.OFFSITE_REPO or "").strip():
        click.secho(
            "Offsite-Backup ist aktiviert, aber OFFSITE_REPO ist leer - "
            "es wird nichts gesichert.",
            fg="red",
        )
        return

    # Ohne Barman gibt es keinen Datenbankstand, den der Container einsammeln
    # koennte - also legen wir ihn hier an. Mit OFFSITE_INCLUDE_DUMPS=1 ist
    # DUMPS_PATH ohnehin komplett dabei, dann waere es doppelte Arbeit.
    env = {}
    if not _truthy(getattr(config, "run_barman", "0")) and not _truthy(
        getattr(config, "OFFSITE_INCLUDE_DUMPS", "0")
    ):
        env["OFFSITE_DB_DUMP"] = _dump_db_for_offsite(config)

    _offsite_run(config, ["backup"], env=env)


@offsite.command(
    name="init",
    help="Repository anlegen (passiert beim ersten Backup automatisch).",
)
@pass_config
def offsite_init(config):
    _offsite_run(config, ["init"])


@offsite.command(name="list", help="Archive im Offsite-Repository auflisten.")
@pass_config
def offsite_list(config):
    _offsite_run(config, ["list"])


@offsite.command(name="info", help="Repository-Kennzahlen (Groesse, Dedup).")
@pass_config
def offsite_info(config):
    _offsite_run(config, ["info"])


@offsite.command(
    name="check",
    help="Integritaet pruefen - liest die Daten neu (dauert und kostet Traffic).",
)
@pass_config
def offsite_check(config):
    _offsite_run(config, ["check"])


@offsite.command(
    name="prune",
    help=(
        "Aufbewahrungsregeln jetzt anwenden. Bei append-only-Zielen (unser "
        "Backup-Server) geht das nur dort, nicht von hier."
    ),
)
@pass_config
def offsite_prune(config):
    _offsite_run(config, ["prune"])


@offsite.command(
    name="restic",
    help="Beliebiges restic-Kommando im Repository ausfuehren (Notausgang).",
    context_settings=dict(ignore_unknown_options=True),
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@pass_config
def offsite_restic(config, args):
    _offsite_run(config, ["restic"] + list(args))


# --------------------------------------------------------------------------- #
# Anmeldung am Backup-Server
# --------------------------------------------------------------------------- #
def _enroll_dir(config):
    """Verzeichnis, das read-only in den Container gehaengt wird."""
    d = Path(config.HOST_RUN_DIR) / "offsite"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _area_name(config, name):
    """Bereichsname aus dem Projektnamen ableiten.

    Der Server erlaubt a-z, 0-9, _ und -, Beginn mit einem Buchstaben. Ein
    Projektname wie "ZO-05123_Kunde" wird also klein geschrieben und bereinigt,
    statt beim Server mit einer Fehlermeldung abzuprallen.
    """
    import re

    raw = (name or config.project_name or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]", "-", raw).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if cleaned and not cleaned[0].isalpha():
        cleaned = "p" + cleaned
    if not re.match(r"^[a-z][a-z0-9_-]{1,40}$", cleaned or ""):
        abort(
            f"Aus '{raw}' laesst sich kein gueltiger Bereichsname bilden. "
            "Mit --name einen angeben (a-z, 0-9, _ und -, Beginn mit Buchstabe)."
        )
    return cleaned


def _enroll_ssl_context(cert_file):
    """TLS-Kontext fuer den Anmeldedienst.

    Der Backup-Server hat ein selbst ausgestelltes Zertifikat. Liegt es schon
    hier, wird dagegen geprueft. Beim ERSTEN Kontakt gibt es nichts zu pruefen -
    dann wird das Zertifikat geholt, gepinnt und sein Fingerabdruck angezeigt,
    damit man ihn einmal gegen den Server halten kann. Danach faellt jede
    Aenderung auf. Dasselbe Verfahren wie bei ssh (accept-new).
    """
    import ssl

    if cert_file.exists():
        ctx = ssl.create_default_context(cafile=str(cert_file))
        # Das Zertifikat laeuft auf den Namen "restic-backup" und traegt die
        # IP-Adressen als SAN; geprueft wird also gegen genau dieses Zertifikat.
        return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _enroll_call(config, method, path, payload=None):
    import json as _json
    import urllib.error
    import urllib.request

    base = (getattr(config, "OFFSITE_ENROLL_URL", "") or "").rstrip("/")
    if not base:
        abort(
            "OFFSITE_ENROLL_URL ist leer - der Anmeldedienst des Backup-Servers "
            "ist nicht hinterlegt."
        )
    cert = _enroll_dir(config) / "rest-server.crt"
    data = _json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(
            req, timeout=30, context=_enroll_ssl_context(cert)
        ) as resp:
            return _json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        abort(f"Anmeldedienst antwortet mit {exc.code}: {body[:300]}")
    except urllib.error.URLError as exc:
        abort(
            f"Anmeldedienst {base} nicht erreichbar: {exc.reason}.\n"
            "Der Dienst ist nur ueber das zebroo-VPN erreichbar - haengt diese "
            "Maschine mit dem Backup-Server in einer gemeinsamen VPN-Gruppe?"
        )


@offsite.command(
    name="register",
    help=(
        "Kundenbereich auf dem Backup-Server beantragen und die Zugangsdaten "
        "abholen. Beim ersten Aufruf entsteht eine Anfrage, die ein Admin dort "
        "freigibt; derselbe Aufruf holt danach alles Noetige ab."
    ),
)
@click.option(
    "--name",
    default=None,
    help="Bereichsname (Vorgabe: aus dem Projektnamen abgeleitet).",
)
@click.option("--note", default="", help="Notiz fuer den Admin.")
@pass_config
def offsite_register(config, name, note):
    import json as _json
    import socket
    import ssl
    import urllib.request

    from .tools import update_setting

    area = _area_name(config, name)
    edir = _enroll_dir(config)
    cert = edir / "rest-server.crt"
    state_file = edir / "enroll.json"

    # Serverzertifikat zuerst: ohne es kann restic den Server nicht pruefen,
    # und der Fingerabdruck gehoert beim ersten Kontakt angesehen.
    if not cert.exists():
        base = (config.OFFSITE_ENROLL_URL or "").rstrip("/")
        req = urllib.request.Request(base + "/api/ca")
        with urllib.request.urlopen(
            req, timeout=30, context=_enroll_ssl_context(cert)
        ) as resp:
            pem = resp.read()
        cert.write_bytes(pem)
        cert.chmod(0o644)
        import hashlib

        der = ssl.PEM_cert_to_DER_cert(pem.decode())
        fp = hashlib.sha256(der).hexdigest()
        fp = ":".join(fp[i : i + 2] for i in range(0, len(fp), 2)).upper()
        click.secho(
            "Serverzertifikat beim ersten Kontakt uebernommen und gepinnt.\n"
            f"  SHA256 {fp}\n"
            "Einmal gegen den Backup-Server halten; jede spaetere Aenderung "
            "bricht die Verbindung ab.",
            fg="yellow",
        )

    state = {}
    if state_file.exists():
        state = _json.loads(state_file.read_text())

    # Bringt die Maschine ihre Passphrase schon mit (Shop/zCICD legen sie je
    # Projekt im Backend ab), soll der Server keinen zweiten Schluessel
    # erfinden - sonst gibt es zwei Wahrheiten fuer dasselbe Repository.
    own_key = bool((config.OFFSITE_PASSPHRASE or "").strip())

    if state.get("area") != area or not state.get("request_id"):
        answer = _enroll_call(
            config,
            "POST",
            "/api/request",
            {
                "area": area,
                "hostname": socket.gethostname(),
                "project": config.project_name,
                "note": note,
                "own_repo_key": own_key,
            },
        )
        state = {
            "area": area,
            "request_id": answer["request_id"],
            "token": answer.get("pickup_token", state.get("token", "")),
        }
        state_file.write_text(_json.dumps(state, indent=2))
        state_file.chmod(0o600)
        click.secho(
            f"Bereich '{area}' beantragt (Anfrage {state['request_id']}).\n"
            f"{answer.get('note', '')}\n"
            "Nach der Freigabe denselben Befehl noch einmal aufrufen.",
            fg="green",
        )
        return

    answer = _enroll_call(
        config,
        "GET",
        f"/api/status?request_id={state['request_id']}&token={state['token']}",
    )
    status = answer.get("status")
    if status == "pending":
        click.secho(
            f"Anfrage {state['request_id']} fuer '{area}' liegt noch zur Freigabe."
            + (f"\n{answer['note']}" if answer.get("note") else ""),
            fg="yellow",
        )
        return
    if status == "rejected":
        state_file.unlink(missing_ok=True)
        abort(f"Die Anfrage fuer '{area}' wurde abgelehnt.")
    if status == "delivered":
        abort(
            "Die Zugangsdaten wurden schon einmal abgeholt - der Server gibt sie "
            "nur einmal heraus. Sie liegen in 1Password; von dort in die "
            "Settings uebernehmen (OFFSITE_REPO, OFFSITE_REST_USER, "
            "OFFSITE_REST_PASSWORD, OFFSITE_PASSPHRASE)."
        )
    if status != "approved":
        abort(f"Unerwartete Antwort des Anmeldedienstes: {answer}")

    if answer.get("ca_cert"):
        cert.write_text(answer["ca_cert"])
        cert.chmod(0o644)

    update_setting(config, "OFFSITE_REPO", answer["repo_url"])
    update_setting(config, "OFFSITE_REST_USER", answer["user"])
    update_setting(config, "OFFSITE_REST_PASSWORD", answer["password"])
    if answer.get("repo_key"):
        update_setting(config, "OFFSITE_PASSPHRASE", answer["repo_key"])
    update_setting(config, "RUN_OFFSITE", "1")
    # Die Anfrage ist erledigt; der Zustand wird nicht mehr gebraucht und soll
    # nicht als vermeintlich offene Anfrage liegenbleiben.
    state_file.unlink(missing_ok=True)

    click.secho(
        f"Bereich '{area}' ist eingerichtet und in den Settings hinterlegt.",
        fg="green",
    )
    if not answer.get("repo_key"):
        click.secho(
            "Die Passphrase dieser Maschine wurde beibehalten (sie kam vom "
            "Backend, nicht vom Server).",
            fg="yellow",
        )
    click.secho(
        "Naechste Schritte:\n"
        "  odoo reload && odoo build offsite\n"
        "  odoo offsite backup      # erster Lauf, legt das Repository an\n\n"
        "Der Repo-Key liegt in 1Password (Vault Infrastructure-Backup) - ohne "
        "ihn ist die Sicherung wertlos. Der Backup-Server kennt ihn nicht.",
        fg="green",
    )
