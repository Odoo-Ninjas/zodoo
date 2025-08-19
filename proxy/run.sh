#!/bin/bash
# Output each environment variable as an `env` directive


env | while IFS='=' read -r var _; do
    echo "env $var;"
done > /etc/envvars.conf
# setup config files
python3 /usr/local/bin/setup_config_files.py || exit 1

# fix rights;-
chmod a+r -R /usr/local/openresty
chown nobody:nobody /usr/local/openresty -R
set -x
if [[ "$DEVMODE" == "1" ]]; then
    chmod a+rw -R /usr/local/openresty
    find /usr/local/openresty -exec chmod a+x {} \;
fi

/usr/local/openresty/bin/openresty -g 'daemon off;'
