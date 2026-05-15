#!/bin/bash
set -e

# Fix ownership of socket and log dirs (runs as root before gosu drops to postgres)
mkdir -p /var/run/postgresql /logs
rm -f /var/run/postgresql/.s.PGSQL.*.lock
chown -R 999:999 /var/run/postgresql /logs

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
