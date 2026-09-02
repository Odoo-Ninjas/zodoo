import platform
import inspect
import os
from pathlib import Path
from string import Template

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _add_volume(service, kind, source, target, read_only=False):
    """Append a mount unless an equivalent one is already there.

    The LONG form, not "source:target", and that is not a style choice: this
    hook runs after `docker compose config`, which is what normalises short
    volume strings into dicts. A string added here is never normalised, and
    `create_directories` then takes its left-hand side for a host path and
    raises NotImplementedError on the volume name. Every other hook in this
    repo emits dicts for the same reason.

    Idempotent because `odoo reload` regenerates the compose file and the
    postgres service is touched by several hooks.
    """
    volumes = service.setdefault("volumes", [])
    for existing in volumes:
        if (
            isinstance(existing, dict)
            and existing.get("source") == source
            and existing.get("target") == target
        ):
            return
    spec = {"type": kind, "source": source, "target": target}
    if read_only:
        spec["read_only"] = True
    volumes.append(spec)


def _stanza(settings):
    """The stanza name, with $PROJECT_NAME resolved.

    default.settings ships PGBR_STANZA=$PROJECT_NAME, but settings
    values are not expanded recursively - only the compose files go through
    variable substitution. Read straight from the settings dict the value is
    still the literal "$PROJECT_NAME", and a stanza by that name would be
    created, archived into, and then not found by anything that resolved it
    properly.
    """
    raw = (settings.get("PGBR_STANZA") or "").strip()
    project = (settings.get("PROJECT_NAME") or "").strip()
    for placeholder in ("${PROJECT_NAME}", "$PROJECT_NAME"):
        if project:
            raw = raw.replace(placeholder, project)
    return raw.strip() or project or "odoo"


def _tls_port(settings):
    """The port this machine listens on for the repo host.

    Deliberately its own setting rather than reusing the repo host's port:
    they are two different listeners on two different machines, in opposite
    directions. Conflating them means a firewall rule written for one silently
    describes the other.
    """
    return (settings.get("PGBR_TLS_SERVER_PORT") or "8432").strip()


def _backup_from(settings):
    """Which machine runs `pgbackrest backup` - and therefore `expire`.

    Only meaningful with a repo host. "here" keeps every connection outbound;
    "repo-host" needs an inbound port but withholds delete rights from this
    machine. See docs/12-pgbackrest.md.
    """
    val = (settings.get("PGBR_BACKUP_FROM") or "here").strip().lower()
    return "repo-host" if val == "repo-host" else "here"


def _retention_lines(settings):
    """repo1-retention-*, emitted only for a LOCAL repository.

    With a repo host these belong over there - see _repo_section.

    Retention is emitted UNCONDITIONALLY, falling back to the documented
    default rather than being left out when the setting is empty.

    This matters more than it looks: pgbackrest without repo1-retention-full
    never expires anything. It says so once, in a log line nobody reads, and
    then quietly keeps every backup forever. That is exactly how the dump
    directory grew to 3.4 TB - a cleanup that was configured but never
    effective. An empty setting therefore means "use the default", never
    "keep everything".
    """
    lines = []
    full_type = (settings.get("PGBR_RETENTION_FULL_TYPE") or "time").strip()
    full = (settings.get("PGBR_RETENTION_FULL") or "").strip() or "14"
    lines.append(f"repo1-retention-full-type={full_type}")
    lines.append(f"repo1-retention-full={full}")

    diff = (settings.get("PGBR_RETENTION_DIFF") or "").strip()
    if diff:
        lines.append(f"repo1-retention-diff={diff}")

    # Empty on purpose keeps the WAL for every retained full backup, i.e. a
    # continuous point-in-time window. Only a value narrows that.
    archive = (settings.get("PGBR_RETENTION_ARCHIVE") or "").strip()
    if archive:
        lines.append(f"repo1-retention-archive={archive}")
        lines.append(
            "repo1-retention-archive-type="
            + (settings.get("PGBR_RETENTION_ARCHIVE_TYPE") or "full").strip()
        )
    return lines


def _cipher_lines(settings):
    """repo1-cipher-*, in [global] on purpose.

    The pgBackRest guide is explicit that encryption settings belong in the
    global section rather than a stanza section, so that `info` can read every
    stanza. It is also explicit that encryption is "always performed
    client-side" - which is the whole point here: the backup server stores
    ciphertext and never learns the passphrase, so neither a compromised
    backup server nor the storage provider underneath it can read a backup.

    Empty passphrase = no encryption, and the caller says so loudly when a
    repo host is configured (see __after_settings.py): that is the case where
    the data leaves this machine.
    """
    passphrase = (settings.get("PGBR_CIPHER_PASS") or "").strip()
    if not passphrase:
        return []
    kind = (settings.get("PGBR_CIPHER_TYPE") or "aes-256-cbc").strip()
    return [
        "",
        "# Client-side encryption. The backup server never sees the",
        "# passphrase - losing it here makes the backups unreadable, so it",
        "# belongs in the hosting record before the first backup runs.",
        f"repo1-cipher-type={kind}",
        f"repo1-cipher-pass={passphrase}",
    ]


def _repo_section(settings):
    """The [global] lines that say where the repository is and how it is reached.

    Three shapes, not one with changed values - which is why this is assembled
    here rather than being a placeholder in the template:

    local repository        repo1-path; this machine owns the storage.

    repo host, pulled       repo1-host plus TLS material, and deliberately NO
    (BACKUP_FROM=repo-host) repo1-path and NO retention. Both belong to the
                            backup server, which runs backup and expire. Not
                            being able to delete is the point of this shape.

    repo host, pushed       repo1-host and no repo1-path, but WITH retention.
    (BACKUP_FROM=here)      This machine runs backup and expire, so this is
                            where retention has to be. It used to be left out
                            here on the theory that the backup server manages
                            the disk and therefore the retention - see below
                            for why that does not work.
    """
    host = (settings.get("PGBR_REPO_HOST") or "").strip()
    lines = []

    if host:
        pulled = _backup_from(settings) == "repo-host"
        lines += [
            f"repo1-host={host}",
            "repo1-host-type="
            + (settings.get("PGBR_REPO_HOST_TYPE") or "tls").strip(),
            "repo1-host-port="
            + (settings.get("PGBR_REPO_HOST_PORT") or "8432").strip(),
            "repo1-host-ca-file=/etc/pgbackrest/cert/ca.crt",
            "repo1-host-cert-file=/etc/pgbackrest/cert/client.crt",
            "repo1-host-key-file=/etc/pgbackrest/cert/client.key",
        ]
        if pulled:
            lines += [
                "",
                "# This machine answers the repo host over TLS; the repo host",
                "# is the side that starts a backup and pulls. tls-server-auth",
                "# names which client certificate may act on which stanza -",
                "# without it any certificate signed by the CA could back up",
                "# any instance.",
                "tls-server-address=0.0.0.0",
                "tls-server-port=" + _tls_port(settings),
                "tls-server-ca-file=/etc/pgbackrest/cert/ca.crt",
                "tls-server-cert-file=/etc/pgbackrest/cert/server.crt",
                "tls-server-key-file=/etc/pgbackrest/cert/server.key",
                f"tls-server-auth={host}=" + _stanza(settings),
            ]
        else:
            lines += [
                "",
                "# Pushed from here: this machine runs backup, and the expire",
                "# step at the end of it. Deliberately WITHOUT retention.",
                "#",
                "# Retention belongs to whoever manages the disk, and that is",
                "# the backup server. Without repo1-retention-* the expire",
                "# step is a no-op, which is exactly right here: the backup",
                "# server runs `pgbackrest --stanza=... expire` from its own",
                "# cron, against its own retention values, in one place.",
                "#",
                "# The PGBR_RETENTION_* settings are therefore ignored",
                "# in this mode - see docs/12-pgbackrest.md.",
            ]
        if not pulled:
            # Aufbewahrung gehoert hierher, nicht auf den Repo-Host.
            #
            # Frueher stand hier nichts, mit der Begruendung: die Maschine,
            # der die Platte gehoert, verwaltet auch die Aufbewahrung. Das
            # klingt richtig und funktioniert trotzdem nicht - `expire` muss
            # `backup.info` LESEN, und die ist clientseitig verschluesselt.
            # Auf dem Repo-Host endet der Versuch mit
            # `FormatError: key/value found outside of section at line 1:
            # Salted__...`, genau wie `verify`. Dass er die Datei nicht
            # oeffnen kann, ist der Sinn des Aufbaus, kein Mangel.
            #
            # Ergebnis bis 2026-08-31: es lief NIRGENDS ein expire. Genau der
            # Fehler, vor dem _retention_lines im Kommentar warnt - eine
            # Aufraeumung, die eingerichtet, aber nie wirksam war.
            #
            # Diese Maschine kann es dagegen: sie hat die Passphrase, und
            # pgBackRest laesst nach jeder Sicherung ohnehin `expire` mit
            # laufen (sichtbar als "expire command end" im Sicherungslog) -
            # es fand bisher nur keine Regel vor. Neue Befugnis entsteht
            # dadurch nicht: `odoo pgbackrest expire` gibt es hier laengst.
            lines += _retention_lines(settings)
        lines += _cipher_lines(settings)
        return "\n".join(lines)

    lines += [
        "repo1-path=/var/lib/pgbackrest",
        "repo1-block=" + (settings.get("PGBR_BLOCK") or "y").strip(),
        "repo1-bundle=" + (settings.get("PGBR_BUNDLE") or "y").strip(),
    ]

    lines += _retention_lines(settings)
    lines += _cipher_lines(settings)
    return "\n".join(lines)


def _render_conf(settings, run_dir):
    template = (current_dir / "pgbackrest.conf.template").read_text()
    values = {
        "PGBR_REPO_SECTION": _repo_section(settings),
        "PGBR_STANZA": _stanza(settings),
        "PGBR_COMPRESS_TYPE": (
            settings.get("PGBR_COMPRESS_TYPE") or "zst"
        ).strip(),
        "PGBR_COMPRESS_LEVEL": (
            settings.get("PGBR_COMPRESS_LEVEL") or "3"
        ).strip(),
        "PGBR_PROCESS_MAX": (settings.get("PGBR_PROCESS_MAX") or "4").strip(),
        "PGBR_ARCHIVE_ASYNC": (
            settings.get("PGBR_ARCHIVE_ASYNC") or "y"
        ).strip(),
        "PGBR_ARCHIVE_PUSH_QUEUE_MAX": (
            settings.get("PGBR_ARCHIVE_PUSH_QUEUE_MAX") or "1GB"
        ).strip(),
        "PGDATA": "/var/lib/postgresql/data/pgdata",
        "DB_PORT": str(settings.get("DB_PORT") or "5432").strip(),
    }
    conf = Template(template).safe_substitute(values)

    target_dir = run_dir / "pgbackrest"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "cert").mkdir(parents=True, exist_ok=True)
    # Die Huelle liegt neben der Konfiguration: dasselbe Verzeichnis ist
    # ohnehin schon nach /etc/pgbackrest gemountet, also braucht es dafuer
    # keine Aenderung an den sechs postgres-Images.
    script_src = current_dir / "archive-push.sh"
    script_dst = target_dir / "archive-push.sh"
    if not script_dst.exists() or script_dst.read_text() != script_src.read_text():
        script_dst.write_text(script_src.read_text())
    script_dst.chmod(0o755)

    conf_file = target_dir / "pgbackrest.conf"
    # Only write when it actually changed: the file is mounted into a running
    # postgres, and rewriting it on every `odoo reload` would churn the mtime
    # for no reason.
    if not conf_file.exists() or conf_file.read_text() != conf:
        conf_file.write_text(conf)
    (run_dir / "pgbackrest.logs").mkdir(parents=True, exist_ok=True)
    return conf_file


def _passphrase_aus_umgebungen_entfernen(yml):
    """PGBR_CIPHER_PASS aus den Dienst-Umgebungen loeschen.

    zodoo haengt jedem Dienst die Einstellungsdatei als `env_file` an, und
    `docker compose config` loest sie auf. Damit steht die Passphrase in der
    erzeugten docker-compose.yml einmal pro Dienst - auf einer produktiven
    Instanz waren es 18 Mal - und in der Umgebung von Grafana, Proxy,
    Konsole, Cronjobs und allem anderen, das sie nie braucht. Die Datei liegt
    mit 0644 auf der Platte.

    Gebraucht wird sie NIRGENDS als Umgebungsvariable: gelesen wird sie beim
    Erzeugen der Konfiguration aus den EINSTELLUNGEN, und getragen wird sie
    von der `pgbackrest.conf`, die dorthin gemountet wird, wo sie hingehoert.
    Also raus damit.

    Was das nicht loest (und was hier auch nicht hingehoert): die
    Einstellungsdatei selbst und die gemountete Konfiguration. Die conf muss
    fuer den Container-Benutzer lesbar bleiben; sie enger zu ziehen geht nur
    ueber das Verzeichnis, nicht ueber die Datei.
    """
    entfernt = 0
    for name, service in (yml.get("services") or {}).items():
        umgebung = service.get("environment")
        if isinstance(umgebung, dict):
            if umgebung.pop("PGBR_CIPHER_PASS", None) is not None:
                entfernt += 1
        elif isinstance(umgebung, list):
            vorher = len(umgebung)
            service["environment"] = [
                e for e in umgebung
                if not (isinstance(e, str) and e.split("=", 1)[0] == "PGBR_CIPHER_PASS")
            ]
            if len(service["environment"]) != vorher:
                entfernt += 1
    return entfernt


def after_compose(config, settings, yml, globals):
    """Wire pgBackRest into postgres.

    Two things have to happen on the postgres side, and both are the reason
    this integration is more invasive than the barman one was:

    1. archive_mode + archive_command. barman streamed its WAL with
       pg_receivewal and needed nothing inside the postgres container at all.
       pgbackrest archives instead, and an archive_command is executed by the
       postgres server process itself - so the binary and the configuration
       have to exist in the postgres container.

    2. The socket directory has to be shared, because pgbackrest reaches
       postgres through a unix socket and has no option to use TCP.

    Everything here is gated on RUN_PGBACKREST=1: with the feature off, the
    postgres service keeps its stock configuration and its stock mounts.
    """
    # ZUERST, und ausdruecklich VOR den Ausstiegen unten: die Passphrase hat
    # in keiner Dienst-Umgebung etwas zu suchen, auch nicht als leerer Wert
    # bei abgeschaltetem pgBackRest. Sonst steht sie in der erzeugten
    # docker-compose.yml wieder ueberall, sobald jemand die Funktion
    # einschaltet und vorher ein reload lief.
    _passphrase_aus_umgebungen_entfernen(yml)

    if not _truthy(settings.get("RUN_PGBACKREST", "0")):
        return
    if "postgres" not in yml.get("services", {}):
        return

    run_dir = Path(settings["HOST_RUN_DIR"])
    _render_conf(settings, run_dir)

    stanza = _stanza(settings)

    # Hand the RESOLVED stanza to the sidecar. The settings file ships
    # PGBR_STANZA=$PROJECT_NAME, and that placeholder reaches the container
    # verbatim - the entrypoint would then create and check a stanza literally
    # called "$PROJECT_NAME" while the configuration file defines the real
    # one, and every command fails with "requires option: pg1-path" because
    # the section it looks for does not exist.
    sidecar = yml.get("services", {}).get("pgbackrest")
    if sidecar is not None:
        sidecar.setdefault("environment", {})["PGBR_STANZA"] = stanza

    # --- postgres server configuration ---------------------------------------
    # archive_mode cannot be changed by a reload, only by a restart - which is
    # exactly what happens when the compose file changes, so this is the right
    # place for it.
    # The archive_command is SINGLE-QUOTED, and it has to be: run.sh turns
    # every POSTGRES_CONFIG entry into a `-c <entry>` fragment and writes them
    # into /start.sh as one bash command line. Unquoted, the spaces split the
    # value into separate arguments and postgres dies at startup with
    # `unrecognized configuration parameter "stanza"`.
    params = [
        "wal_level=replica",
        "archive_mode=on",
        # Ueber die Huelle, nicht direkt: sie holt eine fehlende Stanza einmal
        # nach und versucht erneut. Jeder andere Fehler geht unveraendert
        # durch - ein archive_command, das Probleme verschluckt, wirft WAL weg.
        "archive_command='/etc/pgbackrest/archive-push.sh "
        f"{stanza} %p'",
    ]

    pg = yml["services"]["postgres"]
    env = pg.setdefault("environment", {})
    if isinstance(env, list):
        env_map = {}
        for item in env:
            k, _, v = str(item).partition("=")
            env_map[k] = v
        env = env_map
        pg["environment"] = env

    existing = (
        env.get("POSTGRES_CONFIG") or settings.get("POSTGRES_CONFIG") or ""
    ).strip()
    existing = existing.rstrip(";").strip()
    env["POSTGRES_CONFIG"] = ";".join(
        filter(None, [existing, ";".join(params)])
    )

    # --- postgres side mounts -------------------------------------------------
    # The same configuration file the sidecar reads. One file for both sides:
    # the archive_command and the backup have to agree on where the repository
    # is, and two copies would eventually disagree.
    _add_volume(
        pg, "bind", f"{run_dir}/pgbackrest", "/etc/pgbackrest", read_only=True
    )
    # The socket directory, shared with the sidecar - and on Linux it must be
    # the SAME host directory that zodoo itself talks through.
    #
    # postgres/docker-compose.platform_linux.yml binds
    # $HOST_RUN_DIR/postgres.socket onto /var/run/postgresql, and
    # odoo_config.py connects through exactly that path. Putting a named
    # volume on top of it means the host never sees a socket again: `odoo
    # psql`, `odoo db reset` and everything else that talks to postgres from
    # outside fail with "No such file or directory".
    #
    # That defect was invisible on macOS, where zodoo connects over TCP
    # instead - which is why it survived local testing and only surfaced in CI
    # on Linux. On a Linux server it would have hit every project that turned
    # pgBackRest on.
    #
    # Off Linux there is no host socket to share, so a named volume is the
    # only way to get the socket from postgres to the sidecar.
    if platform.system() == "Linux":
        socket_mount = ("bind", f"{run_dir}/postgres.socket")
    else:
        socket_mount = ("volume", "postgres_socket")
    _add_volume(pg, socket_mount[0], socket_mount[1], "/var/run/postgresql")
    # Und dieselbe Quelle beim Sidecar: die beiden muessen sich denselben
    # Socket teilen, sonst findet pgbackrest die Datenbank nicht.
    sidecar = yml.get("services", {}).get("pgbackrest")
    if sidecar is not None:
        _add_volume(
            sidecar, socket_mount[0], socket_mount[1], "/var/run/postgresql"
        )
    # Spool and logs for the asynchronous archive_command. Both are written by
    # the postgres container, not by the sidecar: archive-push and its async
    # worker run wherever postgres runs.
    _add_volume(pg, "volume", "pgbackrest_spool", "/var/spool/pgbackrest")
    _add_volume(
        pg, "bind", f"{run_dir}/pgbackrest.logs", "/var/log/pgbackrest"
    )

    # With a LOCAL repository the postgres container needs the repository
    # itself, because archive-push runs there - it is the archive_command, and
    # the archive_command is executed by the postgres server process. Without
    # this mount every WAL segment fails with
    #
    #   FileMissingError: unable to open missing file
    #   '/var/lib/pgbackrest/archive/<stanza>/archive.info'
    #
    # and postgres retries forever while pg_wal grows.
    #
    # With a repo host there is nothing to mount: archive-push then talks to
    # the backup server over TLS and never touches a local repository path.
    if not (settings.get("PGBR_REPO_HOST") or "").strip():
        _add_volume(pg, "volume", "pgbackrest_data", "/var/lib/pgbackrest")

    # postgres depends on the sidecar, so that starting postgres alone brings
    # it too.
    #
    # This is not tidiness, it is the difference between working and quietly
    # broken. postgres archives from its first second (archive_mode=on), and
    # the stanza that archive-push writes into is created by the sidecar's
    # entrypoint. Start postgres by itself - `docker compose up -d postgres`,
    # a partial restart, `odoo db reset` - and every WAL push fails with
    # "unable to open missing file .../archive.info". Nothing announces it:
    # postgres keeps serving, the WAL piles up, and the backup that everyone
    # believes exists does not.
    #
    # Deliberately without `condition: service_healthy`, and the sidecar in
    # turn declares no dependency on postgres: both directions at once are a
    # cycle, and compose refuses the project outright with "dependency cycle
    # detected". The sidecar waits in its entrypoint instead - on the socket,
    # which is the path that actually has to work.
    pg.setdefault("depends_on", [])
    deps = pg["depends_on"]
    if isinstance(deps, dict):
        deps.setdefault("pgbackrest", {})
    elif "pgbackrest" not in deps:
        deps.append("pgbackrest")

    # The spool volume has to be DECLARED here as well, not just mounted.
    # It is declared in pgbackrest/docker-compose.yml, but `docker compose
    # config` - which runs before this hook - prunes a named volume that no
    # service uses yet, and only this hook attaches it (to postgres, since
    # that is where archive-push runs). Without re-declaring it compose
    # refuses the whole project with "refers to undefined volume".
    #
    # The name has to be project-scoped by hand for the same reason: the
    # normalisation step that would have done it has already run.
    project = (settings.get("PROJECT_NAME") or "").strip()
    volumes = yml.setdefault("volumes", {})
    if "pgbackrest_spool" not in volumes:
        name = f"{project}_pgbackrest_spool" if project else "pgbackrest_spool"
        volumes["pgbackrest_spool"] = {"name": name}
    # Und der Socket, wo er als Volume gebraucht wird (nicht auf Linux - dort
    # ist es ein Bind auf das Host-Verzeichnis). Aus demselben Grund: seit der
    # statische Mount aus docker-compose.yml raus ist, benutzt ihn zum
    # Zeitpunkt von `docker compose config` niemand mehr, und compose wirft ihn
    # weg. Ohne diese Zeilen scheitert das ganze Projekt mit
    # "service pgbackrest refers to undefined volume postgres_socket".
    if socket_mount[0] == "volume" and "postgres_socket" not in volumes:
        name = f"{project}_postgres_socket" if project else "postgres_socket"
        volumes["postgres_socket"] = {"name": name}

    # --- the inbound side of a repo-host setup --------------------------------
    # Only when the repo host PULLS: it is then the side that runs
    # `pgbackrest backup` and pulls from the TLS server in the sidecar, so that
    # server has to be reachable from outside the compose network. A local
    # repository serves nobody and gets no published port.
    if (settings.get("PGBR_REPO_HOST") or "").strip() and _backup_from(
        settings
    ) == "repo-host":
        sidecar = yml.get("services", {}).get("pgbackrest")
        if sidecar is not None:
            port = _tls_port(settings)
            ports = sidecar.setdefault("ports", [])
            # Long form for the same reason as the volumes above: this runs
            # after `docker compose config`, so nothing normalises a
            # "8432:8432" string any more.
            if not any(
                isinstance(p, dict) and str(p.get("published")) == port
                for p in ports
            ):
                ports.append(
                    {
                        "mode": "ingress",
                        "target": int(port),
                        "published": port,
                        "protocol": "tcp",
                    }
                )
