#!/bin/bash
set -ex
echo 'starting up router'
cron &
nginx -g 'daemon off;'