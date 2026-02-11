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
	cd /opt
	tar \
		--use-compress-program=zstd \
		--extract \
		--file=/opt/venv.tar.gz \
		--preserve-permissions \
		--same-owner \
		--xattrs \
		--acls
	rm /opt/venv.tar.gz
fi
if [[ -f /usr/share.tar.gz ]]; then
	cd /usr
	tar \
		--use-compress-program=zstd \
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
