#!/bin/bash
/usr/bin/set_docker_group.sh
usermod -u "${OWNER_UID}" odoo
usermod -aG "${DOCKER_GID}" odoo
echo "export project_name=$project_name" > /home/odoo/env
echo "export PROJECT_NAME=$project_name" >> /home/odoo/env
echo "export DB_HOST=$DB_HOST" >> /home/odoo/env
echo "export DB_PORT=$DB_PORT" >> /home/odoo/env
echo "export DB_USER=$DB_USER" >> /home/odoo/env
echo "export DB_PWD=$DB_PWD" >> /home/odoo/env
echo "export DBNAME=$DBNAME" >> /home/odoo/env

echo "-----------------------------------"
echo "Console access with /console possible username admin and password"
echo "$CONSOLE_PASSWORD"
echo "-----------------------------------"

echo "Starting ssh daemon"
/usr/sbin/sshd -D
sleep infinity
