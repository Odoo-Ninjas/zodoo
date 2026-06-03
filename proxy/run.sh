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

/usr/local/openresty/bin/openresty -g 'daemon off;'
