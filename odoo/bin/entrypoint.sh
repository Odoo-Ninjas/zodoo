#!/bin/bash
set -e
xtract() {
	local archive="$1"
	local target_dir="$2"

	if [[ -f "$archive" ]]; then
		cd "$target_dir"
		tar -I zstd -xpf "$archive" \
			--preserve-permissions \
			--same-owner \
			--xattrs --xattrs-include='*' \
			--acls
		rm -f "$archive"
	fi
}
xtract /opt/venv.tar.gz /opt
xtract /usr/share.tar.gz /usr

chown $OWNER_UID /home/odoo/.config -R
exec "$WODOO_PYTHON" /odoolib/entrypoint.py "$@"
