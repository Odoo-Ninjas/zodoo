#!/bin/bash
/bin/bash /odoolib/xtract_system_libs.sh || exit 1

chown $OWNER_UID /home/odoo/.config -R
exec "$WODOO_PYTHON" /odoolib/entrypoint.py "$@"
