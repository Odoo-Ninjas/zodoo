#!/bin/bash
# path="/usr/local/bin/wodoo_python"
# export CUSTOMS_DIR=/opt/src
# if [[ ! -e "$path" ]]; then
# 	tee -a "$path" > /dev/null <<- EOT
# 		#!/bin/bash
# 		cd $(dirname "$WODOO_PYTHON")
# 		./python3 $( echo '"$@"' )
# 	EOT
# 	chmod a+x "$path"
# fi
set -x
exec "$WODOO_PYTHON" /odoolib/entrypoint.py "$@"
