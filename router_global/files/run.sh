#!/bin/bash
set -ex
echo 'starting up router'

# Sync certs from Traefik acme.json if configured
if [ -n "$TRAEFIK_ACME_JSON" ] && [ -f "$TRAEFIK_ACME_JSON" ]; then
    python3 /usr/local/bin/sync_traefik_certs.py "$TRAEFIK_ACME_JSON" /etc/ssl/custom_ssl || true
fi

cron &
nginx -g 'daemon off;'
