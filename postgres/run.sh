#!/bin/bash
set -e

# Fix ownership of socket and log dirs (runs as root before gosu drops to postgres)
# /logs is bind-mounted from $HOST_RUN_DIR/postgres.logs; if Docker Desktop
# auto-created the host path as a file the mount succeeds but /logs is a file
# inside the container and `mkdir -p` then fails with a useless message.
for d in /var/run/postgresql /logs; do
    if [ -e "$d" ] && [ ! -d "$d" ]; then
        echo "ERROR: $d exists inside the container but is not a directory." >&2
        echo "       The host bind-mount source was created as a file." >&2
        echo "       Fix on host: rm \$HOST_RUN_DIR/postgres.logs && mkdir \$HOST_RUN_DIR/postgres.logs" >&2
        echo "       Then: docker rm -f <postgres container> && odoo up -d postgres" >&2
        exit 1
    fi
    mkdir -p "$d"
done
rm -f /var/run/postgresql/.s.PGSQL.*.lock
chown -R 999:999 /var/run/postgresql /logs

# Ensure PGDATA's parent is writable by the postgres user. On a fresh volume
# (or after `odoo snap restore` rsyncs into an empty mount) the mountpoint is
# owned by root:root, so the unprivileged `gosu postgres` below cannot create
# the pgdata subdirectory. We only chown the top-level mount; rsync from a
# snapshot preserves per-file ownership of the contents underneath.
if [ -d /var/lib/postgresql/data ]; then
    chown 999:999 /var/lib/postgresql/data
fi

function make_entrypoint_with_params() {
python3 <<EOF
print("Version 1.0")
from pathlib import Path
import os
conf = []
for candi in ['/config', '/config1', '/config2']:
    candi = Path(candi)
    if candi.exists():
        print("Configuration file found at " + str(candi))
        conf += [x for x in candi.read_text().splitlines() if not x.strip().startswith("#")]
conf += (os.getenv('POSTGRES_CONFIG') or '').replace(",", ";").split(";")
# strip whitespace and any trailing ';' so a stray semicolon in a conf file
# cannot turn into a bash command separator in /start.sh below
conf = [x.strip().rstrip(';').strip() for x in conf]
conf = list(filter(lambda x: bool((x or '').strip()) and not (x or '').strip().startswith("#"), conf))

print("Applying configuration:\n" + '\n'.join(conf))

conf = list(map(lambda x: f"-c {x}", map(lambda x1: x1.replace(" = ", "="), conf)))

with open('/start.sh', 'w') as f:
    f.write('/usr/local/bin/docker-entrypoint.sh postgres ' + ' '.join(conf))

EOF
}
make_entrypoint_with_params

if [[ "$1" == "postgres" ]]; then
    exec gosu postgres bash /start.sh
else
    exec gosu postgres "$@"
fi
