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
set -ex
ls /opt -lht
if [[ -f /opt/venv.tar.gz ]]; then
	cd /opt
	tar \
		-z \
		--extract \
		--file=/opt/venv.tar.gz \
		--preserve-permissions \
		--same-owner \
		--xattrs \
		--acls
	rm /opt/venv.tar.gz
	ls -lhtra /opt
	if [[ ! -d /opt/venv ]]; then
		echo "Fehler beim entpacken"
		exit -1
	fi
fi
if [[ -f /usr/share.tar.gz ]]; then
	cd /usr
	tar \
		-z \
		--extract \
		--file=/usr/share.tar.gz \
		--preserve-permissions \
		--same-owner \
		--xattrs \
		--acls
	rm /usr/share.tar.gz
	ls -lhtra /usr
fi
chown $OWNER_UID /home/odoo/.config -R
exec "$WODOO_PYTHON" /odoolib/entrypoint.py "$@"
