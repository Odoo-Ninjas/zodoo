import inspect
import os
from pathlib import Path
from string import Template

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _add_volume(service, spec):
    """Append a volume mapping unless an equivalent one is already there.

    `odoo reload` regenerates the compose file, but the postgres service is
    also touched by other hooks, so this has to stay idempotent rather than
    grow a duplicate mount on every run.
    """
    volumes = service.setdefault("volumes", [])
    for existing in volumes:
        if isinstance(existing, str) and existing == spec:
            return
        if isinstance(existing, dict):
            src = existing.get("source")
            tgt = existing.get("target")
            if f"{src}:{tgt}" == spec.rsplit(":ro", 1)[0]:
                return
    volumes.append(spec)


def _tls_port(settings):
    """The port this machine listens on for the repo host.

    Deliberately its own setting rather than reusing the repo host's port:
    they are two different listeners on two different machines, in opposite
    directions. Conflating them means a firewall rule written for one silently
    describes the other.
    """
    return (settings.get("PGBACKREST_TLS_SERVER_PORT") or "8432").strip()


def _repo_section(settings):
    """The [global] lines that say where the repository is and how it is reached.

    The two modes are not a changed value but a different shape, which is why
    this is assembled here rather than being a placeholder in the template:

    local     repo1-path, and this machine owns the storage.
    repo host repo1-host plus TLS material, and deliberately NO repo1-path -
              the path exists on the backup server. Retention lives there too:
              expiring a backup means deleting from the repository, and not
              being able to do that is the entire point of the topology.
    """
    host = (settings.get("PGBACKREST_REPO_HOST") or "").strip()
    lines = []

    if host:
        lines += [
            f"repo1-host={host}",
            "repo1-host-type="
            + (settings.get("PGBACKREST_REPO_HOST_TYPE") or "tls").strip(),
            "repo1-host-port="
            + (settings.get("PGBACKREST_REPO_HOST_PORT") or "8432").strip(),
            "repo1-host-ca-file=/etc/pgbackrest/cert/ca.crt",
            "repo1-host-cert-file=/etc/pgbackrest/cert/client.crt",
            "repo1-host-key-file=/etc/pgbackrest/cert/client.key",
            "",
            "# This machine answers the repo host over TLS; the repo host is",
            "# the side that starts a backup and pulls. tls-server-auth names",
            "# which client certificate may act on which stanza - without it",
            "# any certificate signed by the CA could back up any instance.",
            "tls-server-address=0.0.0.0",
            "tls-server-port=" + _tls_port(settings),
            "tls-server-ca-file=/etc/pgbackrest/cert/ca.crt",
            "tls-server-cert-file=/etc/pgbackrest/cert/server.crt",
            "tls-server-key-file=/etc/pgbackrest/cert/server.key",
            f"tls-server-auth={host}="
            + (settings.get("PGBACKREST_STANZA") or "odoo").strip(),
        ]
        return "\n".join(lines)

    lines += [
        "repo1-path=/var/lib/pgbackrest",
        "repo1-block=" + (settings.get("PGBACKREST_BLOCK") or "y").strip(),
        "repo1-bundle=" + (settings.get("PGBACKREST_BUNDLE") or "y").strip(),
    ]

    # Retention is emitted UNCONDITIONALLY, falling back to the documented
    # default rather than being left out when the setting is empty.
    #
    # This matters more than it looks: pgbackrest without repo1-retention-full
    # never expires anything. It says so once, in a log line nobody reads, and
    # then quietly keeps every backup forever. That is exactly how the dump
    # directory grew to 3.4 TB - a cleanup that was configured but never
    # effective. An empty setting therefore means "use the default", never
    # "keep everything".
    full_type = (
        settings.get("PGBACKREST_RETENTION_FULL_TYPE") or "time"
    ).strip()
    full = (settings.get("PGBACKREST_RETENTION_FULL") or "").strip() or "14"
    lines.append(f"repo1-retention-full-type={full_type}")
    lines.append(f"repo1-retention-full={full}")

    diff = (settings.get("PGBACKREST_RETENTION_DIFF") or "").strip()
    if diff:
        lines.append(f"repo1-retention-diff={diff}")

    # Empty on purpose keeps the WAL for every retained full backup, i.e. a
    # continuous point-in-time window. Only a value narrows that.
    archive = (settings.get("PGBACKREST_RETENTION_ARCHIVE") or "").strip()
    if archive:
        lines.append(f"repo1-retention-archive={archive}")
        lines.append(
            "repo1-retention-archive-type="
            + (
                settings.get("PGBACKREST_RETENTION_ARCHIVE_TYPE") or "full"
            ).strip()
        )

    return "\n".join(lines)


def _render_conf(settings, run_dir):
    template = (current_dir / "pgbackrest.conf.template").read_text()
    values = {
        "PGBR_REPO_SECTION": _repo_section(settings),
        "PGBACKREST_STANZA": (
            settings.get("PGBACKREST_STANZA") or "odoo"
        ).strip(),
        "PGBACKREST_COMPRESS_TYPE": (
            settings.get("PGBACKREST_COMPRESS_TYPE") or "zst"
        ).strip(),
        "PGBACKREST_COMPRESS_LEVEL": (
            settings.get("PGBACKREST_COMPRESS_LEVEL") or "3"
        ).strip(),
        "PGBACKREST_PROCESS_MAX": (
            settings.get("PGBACKREST_PROCESS_MAX") or "4"
        ).strip(),
        "PGBACKREST_ARCHIVE_ASYNC": (
            settings.get("PGBACKREST_ARCHIVE_ASYNC") or "y"
        ).strip(),
        "PGBACKREST_ARCHIVE_PUSH_QUEUE_MAX": (
            settings.get("PGBACKREST_ARCHIVE_PUSH_QUEUE_MAX") or "1GB"
        ).strip(),
        "PGDATA": "/var/lib/postgresql/data/pgdata",
        "DB_PORT": str(settings.get("DB_PORT") or "5432").strip(),
        "DB_USER": (settings.get("DB_USER") or "odoo").strip(),
    }
    conf = Template(template).safe_substitute(values)

    target_dir = run_dir / "pgbackrest"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "cert").mkdir(parents=True, exist_ok=True)
    conf_file = target_dir / "pgbackrest.conf"
    # Only write when it actually changed: the file is mounted into a running
    # postgres, and rewriting it on every `odoo reload` would churn the mtime
    # for no reason.
    if not conf_file.exists() or conf_file.read_text() != conf:
        conf_file.write_text(conf)
    (run_dir / "pgbackrest.logs").mkdir(parents=True, exist_ok=True)
    return conf_file


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
    if not _truthy(settings.get("RUN_PGBACKREST", "0")):
        return
    if "postgres" not in yml.get("services", {}):
        return

    run_dir = Path(settings["HOST_RUN_DIR"])
    _render_conf(settings, run_dir)

    stanza = (settings.get("PGBACKREST_STANZA") or "odoo").strip()

    # --- postgres server configuration ---------------------------------------
    # archive_mode cannot be changed by a reload, only by a restart - which is
    # exactly what happens when the compose file changes, so this is the right
    # place for it.
    params = [
        "wal_level=replica",
        "archive_mode=on",
        f"archive_command=pgbackrest --stanza={stanza} archive-push %p",
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
    _add_volume(pg, f"{run_dir}/pgbackrest:/etc/pgbackrest:ro")
    # The socket directory, shared with the sidecar (see the volume comment in
    # docker-compose.yml).
    _add_volume(pg, "postgres_socket:/var/run/postgresql")
    # Spool and logs for the asynchronous archive_command. Both are written by
    # the postgres container, not by the sidecar: archive-push and its async
    # worker run wherever postgres runs.
    _add_volume(pg, "pgbackrest_spool:/var/spool/pgbackrest")
    _add_volume(pg, f"{run_dir}/pgbackrest.logs:/var/log/pgbackrest")

    yml.setdefault("volumes", {}).setdefault("pgbackrest_spool", None)
    yml.setdefault("volumes", {}).setdefault("postgres_socket", None)

    # --- the inbound side of a repo-host setup --------------------------------
    # Only with a repo host, and only then: the repo host is the side that runs
    # `pgbackrest backup` and pulls from the TLS server in the sidecar, so that
    # server has to be reachable from outside the compose network. A local
    # repository serves nobody and gets no published port.
    if (settings.get("PGBACKREST_REPO_HOST") or "").strip():
        sidecar = yml.get("services", {}).get("pgbackrest")
        if sidecar is not None:
            port = _tls_port(settings)
            mapping = f"{port}:{port}"
            ports = sidecar.setdefault("ports", [])
            if mapping not in ports:
                ports.append(mapping)
