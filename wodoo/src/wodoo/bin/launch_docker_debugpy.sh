#!/bin/bash

current_dir=$(dirname "$0")
SETUP_PYENV=1 /bin/bash ${current_dir}/prepare.sh || exit -1


CURRENT_FILE="${CURRENT_FILE#$(pwd)/}"
echo "unit_test:$CURRENT_FILE" > debug
echo Starting docker container for unitteset and waiting for remote debug on localhost:${ODOO_PYTHON_DEBUG_PORT}
[[ -e .unittest.log ]] && rm .unittest.log

if [[ "$CURRENT_FILE" == */tests/* ]]; then
    echo "Identified unittest so running unittest: ${CURRENT_FILE}"
    MODE=unittest
    odoo debug --command '["CAPTURE_UNITTEST_OUTPUT=1", "/odoolib/debug","--wait-for-remote", "--one-action", "unit_test:${CURRENT_FILE}"]' odoo --set-docker-command
else
    echo "Starting web server in debug mode"
    MODE=web
    odoo debug --command '["/odoolib/debug","--wait-for-remote", "--one-action", "debug"]' odoo --set-docker-command
fi

# Wait until debugpy is truly ready by checking for a DAP response (Content-Length header).
# nc -z is not sufficient: it detects the port as open before the debugpy adapter
# subprocess has fully started, causing VSCode to connect too early and fail silently.
echo Waiting for debugpy DAP on localhost:${ODOO_PYTHON_DEBUG_PORT}
python3 - <<EOF
import socket, time, sys, os
port = int(os.environ.get('ODOO_PYTHON_DEBUG_PORT'))
for _ in range(200):
    try:
        s = socket.socket()
        s.settimeout(1)
        s.connect(('127.0.0.1', port))
        data = s.recv(256)
        s.close()
        if b'Content-Length' in data:
            sys.exit(0)
    except Exception:
        pass
    time.sleep(0.2)
sys.exit(1)
EOF

[ $? -eq 0 ] || { echo "Timeout waiting for debugpy"; exit 1; }
echo Container successfully started - remote debugging available.

if [[ "$MODE" == "unittest" ]]; then
    echo Unit-Test should now start
else
    echo Web container started
fi
