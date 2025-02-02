#!/bin/bash
usermod -aG "$(stat -c '%G' "/var/run/docker.sock")" odoo
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