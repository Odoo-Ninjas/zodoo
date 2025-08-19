#!/bin/bash
# Output each environment variable as an `env` directive


env | while IFS='=' read -r var _; do
    echo "env $var;"
done > /etc/envvars.conf
# setup config files
python3 /usr/local/bin/setup_config_files.py || exit 1

# fix rights;-
chmod a+r -R "$CONF_DIR" "$LUA_DIR" /usr/local/openresty/nginx/static
chown nobody:nobody -R "$CONF_DIR" "$LUA_DIR" /usr/local/openresty/nginx/static

/usr/local/openresty/bin/openresty -g 'daemon off;'
