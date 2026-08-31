#!/bin/bash
#
# pgBackRest sidecar.
#
# This container is the machine-side half of the backup. It exists because
# pgbackrest insists on being co-located with the cluster: it reads PGDATA
# directly and reaches postgres through a unix socket, with no option to do
# either over the network. In a compose setup that co-location has to be
# manufactured, which is what the two shared mounts do - the postgres data
# volume and postgres' socket directory both appear here.
#
# The configuration is NOT written here. It is rendered on the host by
# __after_compose.py into $HOST_RUN_DIR/pgbackrest/ and mounted read-only into
# this container AND into the postgres container. One file, one source of
# truth - and it exists before postgres starts, so the archive_command cannot
# fire into a missing configuration on the very first boot.
#
# Two modes, decided by PGBR_REPO_HOST:
#
#   local repo   The repository lives in this container's volume. This machine
#                owns the backups, which is fine for development and testing
#                and is the only mode that works without a backup server.
#                Backups are driven from here (`odoo pgbackrest backup`).
#
#   repo host    The repository lives on the backup server. Backups are driven
#                from THERE - the repo host connects to the TLS server started
#                below and pulls. This machine holds no passphrase and has no
#                delete rights; all it can do on its own is push WAL. That is
#                the property the restic path could not provide.
#
set -e

: "${DB_PORT:=5432}"
: "${DB_USER:=postgres}"
: "${PGDATA:=/var/lib/postgresql/data/pgdata}"
: "${PGBR_STANZA:=odoo}"
: "${PGBR_REPO_HOST:=}"
: "${PGBR_BACKUP_FROM:=here}"

CONF=/etc/pgbackrest/pgbackrest.conf

pgbr_die() {
    echo "pgbackrest: $*" >&2
    exit 1
}

[ -f "$CONF" ] || pgbr_die \
    "No configuration at $CONF. It is rendered by __after_compose.py into
\$HOST_RUN_DIR/pgbackrest/ - run 'odoo reload' and start the stack again."

# pgbackrest refuses to run as root and wants to own its working directories.
# The uid is 999, the same as postgres in the postgres image, which is what
# lets this container read PGDATA without a chown that would upset postgres.
mkdir -p /var/lib/pgbackrest /var/log/pgbackrest /var/spool/pgbackrest
chown -R 999:999 /var/lib/pgbackrest /var/log/pgbackrest /var/spool/pgbackrest

# Die TLS-Schluessel auf den pgbackrest-Benutzer umschreiben.
#
# pgBackRest verweigert einen Schluessel, der ihm nicht gehoert ("key file ...
# must be owned by the 'pgbackrest' user or root") -- zu Recht. Geschrieben
# werden sie von `odoo pgbackrest register` als Betriebsbenutzer (uid 1000),
# und der DARF den Besitz nicht auf 999 vergeben; das kann nur root.
#
# Kopieren waere kein Ausweg: der Schluessel ist 0600 und gehoert 1000, ein
# Prozess als 999 kann ihn nicht einmal lesen.
#
# postgres startet ueber depends_on nach diesem Container, sein
# archive_command findet die Dateien also bereits gerichtet vor.
#
# Am 31.08.2026 gefunden: die Anmeldung meldete Erfolg, `pgbackrest check`
# brach mit Fehler 42 ab, das WAL-Archiv lief in den Zeitueberlauf -- und
# nachts waere die Sicherung still ausgefallen.
if [ -d /etc/pgbackrest/cert ]; then
    chown -R 999:999 /etc/pgbackrest/cert 2>/dev/null || \
        echo "pgbackrest: WARNUNG - /etc/pgbackrest/cert liess sich nicht auf den pgbackrest-Benutzer umschreiben (read-only eingehaengt?). pgBackRest wird den Schluessel ablehnen." >&2
    chmod 700 /etc/pgbackrest/cert 2>/dev/null || true
    for k in client.key server.key; do
        [ -f "/etc/pgbackrest/cert/$k" ] && chmod 600 "/etc/pgbackrest/cert/$k"
    done
fi

# --- wait for postgres --------------------------------------------------------
# Via the socket, not TCP: the socket is what pgbackrest itself will use, so
# waiting on it proves the path that matters rather than a different one.
echo "pgbackrest: waiting for the postgres socket in /var/run/postgresql ..."
until gosu pgbackrest pg_isready -h /var/run/postgresql -p "${DB_PORT}" \
        -U "${DB_USER}" >/dev/null 2>&1; do
    sleep 2
done
echo "pgbackrest: postgres is up"

if [ -n "$PGBR_REPO_HOST" ] && [ "$PGBR_BACKUP_FROM" = "repo-host" ]; then
    # ----------------------------------------------------- repo host, pulled --
    # Deliberately NO stanza-create here. With the repo host driving, the
    # stanza, the backups and the expiry all live over there; this side only
    # ever answers. Creating a stanza from here would need write access to the
    # repository, which is exactly what this shape is designed to withhold.
    for f in ca.crt server.crt server.key; do
        [ -f "/etc/pgbackrest/cert/$f" ] || pgbr_die \
            "TLS material /etc/pgbackrest/cert/$f is missing. It belongs in
\$HOST_RUN_DIR/pgbackrest/cert/ (ca.crt, server.crt, server.key, client.crt,
client.key; the keys mode 0600) and is issued by the backup server.

There is no enrolment command yet - the certificates are placed by hand for
now. Until that exists, leave PGBR_REPO_HOST empty to use the local
repository."
    done
    echo "pgbackrest: serving for repo host ${PGBR_REPO_HOST} (TLS)"
    exec gosu pgbackrest pgbackrest server
fi

# ------------------------------------------------- pushed from this machine --
# Either the repository is local, or it is on the backup server and we push to
# it. Both cases are the same from here: this side drives the backup, so it
# creates the stanza and later expires it.
if [ -n "$PGBR_REPO_HOST" ]; then
    # Only the client certificate is needed when pushing - nothing listens
    # here, so there is no server certificate to present.
    for f in ca.crt client.crt client.key; do
        [ -f "/etc/pgbackrest/cert/$f" ] || pgbr_die \
            "TLS material /etc/pgbackrest/cert/$f is missing. It belongs in
\$HOST_RUN_DIR/pgbackrest/cert/ (ca.crt, client.crt, client.key; the key mode
0600) and is issued by the backup server.

There is no enrolment command yet - the certificates are placed by hand for
now. Until that exists, leave PGBR_REPO_HOST empty to use the local
repository."
    done
    echo "pgbackrest: pushing to repo host ${PGBR_REPO_HOST} (TLS, outbound only)"
fi

# Idempotent: stanza-create on a repository that already has this stanza is an
# error, stanza-upgrade is the right call after a postgres major upgrade, and
# neither is worth aborting the container over - `odoo pgbackrest check` is
# where a real problem should surface, with a readable message.
echo "pgbackrest: ensuring stanza '${PGBR_STANZA}'"
gosu pgbackrest pgbackrest --stanza="${PGBR_STANZA}" stanza-create 2>/dev/null \
    || gosu pgbackrest pgbackrest --stanza="${PGBR_STANZA}" stanza-upgrade 2>/dev/null \
    || true

# Prove the archiving path end to end right away rather than at 2 a.m.: a
# forced segment switch makes postgres hand a real segment to the
# archive_command, and `check` verifies it arrived in the repository.
gosu pgbackrest pgbackrest --stanza="${PGBR_STANZA}" check || \
    echo "pgbackrest: check failed - archiving is not working yet, see
'odoo pgbackrest check' for the reason." >&2

# Nothing to serve in local mode, but the container has to stay alive so
# `docker compose exec` works - that is how every `odoo pgbackrest ...` command
# reaches the binary.
echo "pgbackrest: ready"
exec tail -f /dev/null
