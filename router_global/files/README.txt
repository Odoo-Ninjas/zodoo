Certbot:

./interactive.sh
certbot renew --nginx

---

Traefik Cert Sync (einmalig beim Start):

Wenn Traefik als vorgelagerter Reverse Proxy läuft und Zertifikate in einer
acme.json ablegt, kann der router_global diese beim Start automatisch übernehmen.

Ablauf:
  run.sh ruft sync_traefik_certs.py einmalig auf → schreibt Cert/Key nach
  /etc/ssl/custom_ssl/<domain>.crt und .key → nginx nutzt diese direkt.

Konfiguration via .env:

  TRAEFIK_ACME_JSON=/pfad/zu/traefik/acme.json
    Pfad zur acme.json von Traefik (muss ins Container-Volume gemountet sein).
    Wenn nicht gesetzt oder Datei nicht vorhanden, wird der Sync übersprungen.

---

IONOS DNS-01 Challenge (certbot-dns-ionos):

Ermöglicht Wildcard-Zertifikate und Zertifikate ohne HTTP-Erreichbarkeit.

Voraussetzung: IONOS API-Key anlegen unter
  https://developer.hosting.ionos.de/keys

Credentials-Datei anlegen (z.B. /etc/letsencrypt/ionos.ini):

  dns_ionos_prefix = <Public Prefix aus API-Key>
  dns_ionos_secret = <Secret aus API-Key>

  chmod 600 /etc/letsencrypt/ionos.ini

Zertifikat ausstellen:

  certbot certonly \
    --authenticator dns-ionos \
    --dns-ionos-credentials /etc/letsencrypt/ionos.ini \
    -d example.com -d "*.example.com"

Erneuerung läuft automatisch via @monthly Cron (certbot renew).
