#!/bin/bash
set -e

: "${DB_HOST:=postgres}"
: "${DB_PORT:=5432}"
: "${DB_USER:=odoo}"
: "${DB_PWD:=odoo}"
: "${BARMAN_RETENTION:=RECOVERY WINDOW OF 7 DAYS}"

export DB_HOST DB_PORT DB_USER BARMAN_RETENTION

BARMAN_HOME=/var/lib/barman

# --- global config -----------------------------------------------------------
cat > /etc/barman.conf <<EOF
[barman]
barman_user = barman
configuration_files_directory = /etc/barman.d
barman_home = ${BARMAN_HOME}
log_file = ${BARMAN_HOME}/barman.log
log_level = INFO
EOF

# --- per-server config (rendered from template) ------------------------------
mkdir -p /etc/barman.d
envsubst < /etc/barman.conf.template > /etc/barman.d/odoo.conf

# --- credentials for barman user (.pgpass; no password on the command line) ---
PGPASS="${BARMAN_HOME}/.pgpass"
echo "${DB_HOST}:${DB_PORT}:*:${DB_USER}:${DB_PWD}" > "$PGPASS"
chmod 600 "$PGPASS"

mkdir -p "$BARMAN_HOME" /etc/barman.d
chown -R barman:barman "$BARMAN_HOME" /etc/barman.d

# --- wait for postgres -------------------------------------------------------
echo "barman: waiting for postgres at ${DB_HOST}:${DB_PORT} ..."
until gosu barman pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" >/dev/null 2>&1; do
    sleep 2
done
echo "barman: postgres is up"

# --- first-time setup: create the replication slot and start streaming -------
# `create_slot = auto` lets barman create the slot, but we kick it explicitly so
# WAL streaming begins immediately and a switch-wal proves the path end-to-end.
gosu barman barman receive-wal --create-slot odoo 2>/dev/null || true
gosu barman barman cron || true
gosu barman barman switch-wal --force --archive odoo 2>/dev/null || true

echo "barman: entering maintenance loop (barman cron every 30s)"
# `barman cron` (re)spawns the receive-wal streaming worker, moves streamed WAL
# into the catalog, and runs retention maintenance. A short interval keeps the
# streamer alive and the archived WAL fresh (matters for prompt PITR targets).
while true; do
    gosu barman barman cron || true
    sleep 30
done
