#!/bin/bash
/usr/bin/set_docker_group.sh
usermod -u "${OWNER_UID}" odoo
usermod -aG "${DOCKER_GID}" odoo
echo "export project_name=$project_name" > /home/odoo/env
echo "export PROJECT_NAME=$project_name" > /home/odoo/env
echo "DB_HOST=$DB_HOST" >> /home/odoo/env
echo "DB_PORT=$DB_PORT" >> /home/odoo/env
echo "DB_USER=$DB_USER" >> /home/odoo/env
echo "DB_PWD=$DB_PWD" >> /home/odoo/env
echo "DBNAME=$DBNAME" >> /home/odoo/env

echo "Starting ssh daemon"
/usr/sbin/sshd -D


sleep infinity
