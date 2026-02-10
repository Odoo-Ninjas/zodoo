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
if [[ -f /opt/venv.tar.gz ]]; then
	cd /opt
	tar xfz venv.tar.gz &
	rm venv.tar.gz
fi
if [[ -f /usr/share.tar.gz ]]; then
	cd /usr
	tar xfz /usr/share.tar.gz &
	rm /usr/share.tar.gz
fi
wait

chown $OWNER_UID /home/odoo/.config -R
exec "$WODOO_PYTHON" /odoolib/entrypoint.py "$@"
