#!/bin/bash
rm -f /var/run/fluentd.sock/sock || true

exec /bin/entrypoint.sh "$@"
