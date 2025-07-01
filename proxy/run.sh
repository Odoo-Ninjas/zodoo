#!/bin/bash
# Output each environment variable as an `env` directive
env | while IFS='=' read -r var _; do
    echo "env $var;"
done > /etc/envvars.conf

# fix rights;- 
chmod a+r -R /usr/local/openresty

/usr/local/openresty/bin/openresty -g 'daemon off;'