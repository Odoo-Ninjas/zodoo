#!/bin/bash
set -e

# When Barman is enabled, allow physical replication connections
# (pg_basebackup + pg_receivewal) from the docker network.
#
# The official postgres image only grants replication from localhost, and a
# regular `host all all all <method>` line does NOT cover the special
# `replication` pg_hba "database" — replication connections need their own
# entry. Without it, `barman backup` / `barman receive-wal` fail with
# "Impossible to start the backup". We reuse the same auth method as the
# regular host line, so this widens nothing beyond existing password auth.
#
# Runs only on a fresh data dir (initdb phase). Existing clusters that enable
# Barman later need this line added to pg_hba.conf manually + a reload.
if [ "${RUN_BARMAN:-0}" = "1" ]; then
    method="${POSTGRES_HOST_AUTH_METHOD:-md5}"
    if ! grep -qE '^\s*host\s+replication\s+all\s+all\s' "$PGDATA/pg_hba.conf"; then
        echo "host replication all all ${method}" >> "$PGDATA/pg_hba.conf"
        echo "barman: added pg_hba entry 'host replication all all ${method}'"
    fi
fi
