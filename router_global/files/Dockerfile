FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y nginx nginx-extras autossh net-tools iputils-ping wget curl cron ssl-cert pip

# certbot samt Plugins AUS EINER QUELLE. Vorher kam certbot aus apt und wurde
# durch certbot-dns-ionos (pip) auf 5.x hochgezogen, waehrend die Plugins bei
# der apt-Version 1.21 blieben. Die Folge war kein Versionshinweis, sondern
# ein Abbruch mitten im Ausstellen:
#
#   certbot.errors.Error: Unsupported RSA key length: 1024
#
# Das alte nginx-Plugin legt fuer einen frischen 443-Block einen
# Platzhalter-Schluessel mit 1024 Bit an, und den lehnt die neue
# cryptography-Bibliothek ab. Das Zertifikat war dann zwar geholt, aber nicht
# eingebaut -- der vhost blieb ohne TLS.
RUN pip install --quiet certbot certbot-nginx certbot-dns-rfc2136 certbot-dns-ionos

ADD run.sh /run.sh
ADD bin/ /usr/local/bin/
RUN chmod a+x /run.sh /usr/local/bin/sync_traefik_certs.py

RUN echo "@monthly certbot renew >> /var/log/cron.log 2>&1" >/etc/cron.d/certbot-renew
RUN crontab /etc/cron.d/certbot-renew

CMD ./run.sh
