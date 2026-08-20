FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

#___SNIPPET_APT_PROXY___

# restic bringt Verschluesselung und Deduplizierung mit; openssh-client den
# Transport zu einem sftp-Ziel (Storage Box). Mehr braucht der Container nicht -
# er liest nur read-only gemountete Verzeichnisse und schiebt Chiffrat nach
# draussen.
RUN #___SNIPPET_APT_INSTALL___ \
    restic openssh-client ca-certificates tzdata && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*

# Der restic-Cache (Index der bereits uebertragenen Bloecke) macht den
# Unterschied zwischen "dedupliziert inkrementell" und "liest jede Nacht alles
# neu ein" - er wird als Volume gemountet und muss ueber Laeufe hinweg bestehen
# bleiben.
ENV RESTIC_CACHE_DIR=/var/lib/restic/cache
ENV HOME=/var/lib/restic

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["backup"]
