FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y nginx nginx-extras autossh net-tools iputils-ping wget certbot python3-certbot-nginx python3-certbot-dns-rfc2136 cron ssl-cert pip
RUN pip install certbot-dns-ionos --quiet

ADD run.sh /run.sh
ADD bin/ /usr/local/bin/
RUN chmod a+x /run.sh /usr/local/bin/sync_traefik_certs.py

RUN echo "@monthly certbot renew >> /var/log/cron.log 2>&1" >/etc/cron.d/certbot-renew
RUN crontab /etc/cron.d/certbot-renew

CMD ./run.sh
