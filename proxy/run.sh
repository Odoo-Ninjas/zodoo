#!/bin/bash
# Output each environment variable as an `env` directive


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
# static is mounted read-only from the host; do not chown/chmod it
# to avoid changing ownership of host files

/usr/local/openresty/bin/openresty -g 'daemon off;'
