#!/bin/bash
# Output each environment variable as an `env` directive

mkdir -p /var/log/nginx
touch /var/log/nginx/access.json /var/log/nginx/error.log
chmod 666 /var/log/nginx/access.json /var/log/nginx/error.log

env | while IFS='=' read -r var _; do
    echo "env $var;"
done > /etc/envvars.conf
# setup config files
python3 /usr/local/bin/setup_config_files.py || exit 1

# run construction site
python3 /usr/local/bin/static_webserver.py $CONSTRUCTION_SITE_PORT /opt/construction_site/index.html &

# fix rights;-
chmod a+r -R "$CONF_DIR" "$LUA_DIR"
chown nobody:nobody -R "$CONF_DIR" "$LUA_DIR"
chmod 777 "$PROXY_EXCHANGE" 2>/dev/null || true
# static is mounted read-only from the host; do not chown/chmod it
# to avoid changing ownership of host files

# Cap the structured JSON access log. It is only a tail buffer for Alloy
# (which ships to Loki with retention); nginx cannot self-rotate and there is
# no logrotate in this image, so without this the file would grow without
# bound and fill the dashboard_nginx_logs volume (even when the dashboard is
# disabled). Truncating in place is safe with nginx's append-mode access_log:
# the next write lands at the new end. Alloy tails continuously, so the unread
# window lost on truncation is negligible for metrics/search.
ACCESS_LOG="/var/log/nginx/access.json"
ACCESS_LOG_MAX_MB="${PROXY_ACCESS_LOG_MAX_MB:-50}"
(
    while true; do
        sz=$(wc -c <"$ACCESS_LOG" 2>/dev/null || echo 0)
        if [ "${sz:-0}" -gt $((ACCESS_LOG_MAX_MB * 1024 * 1024)) ]; then
            : >"$ACCESS_LOG"
        fi
        sleep 60
    done
) &

/usr/local/openresty/bin/openresty -g 'daemon off;'
