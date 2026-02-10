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
set -e
if [[ -f /opt/venv.tar.gz ]]; then
	mv /opt/venv.tar.gz /tmp/venv.tar.gz
	tar \
		-z \
		--extract \
		--file=/tmp/venv.tar.gz \
		--preserve-permissions \
		--same-owner \
		--xattrs \
		--acls \
		-C /opt
	rm /tmp/venv.tar.gz
fi
chown $OWNER_UID /home/odoo/.config -R
exec "$WODOO_PYTHON" /odoolib/entrypoint.py "$@"
