FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y nginx nginx-extras autossh net-tools iputils-ping wget certbot python3-certbot-nginx cron ssl-cert
ADD run.sh /run.sh
RUN chmod a+x /run.sh
CMD ./run.sh


RUN echo "@monthly certbot renew --nginx >> /var/log/cron.log 2>&1" >/etc/cron.d/certbot-renew;
RUN crontab /etc/cron.d/certbot-renew;