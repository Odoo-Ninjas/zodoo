FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

#___SNIPPET_APT_PROXY___

# borgbackup bringt die Verschluesselung mit (repokey-blake2), openssh-client
# den Transport zur Storage Box. Mehr braucht der Container nicht - er liest
# nur read-only gemountete Verzeichnisse und schiebt Chiffrat nach draussen.
RUN #___SNIPPET_APT_INSTALL___ \
    borgbackup openssh-client ca-certificates tzdata && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*

# Borg legt Cache und Repo-Kenner (security dir) hierhin; als Volume gemountet,
# damit die Deduplizierung ueber Laeufe hinweg funktioniert.
ENV BORG_BASE_DIR=/var/lib/borg
ENV BORG_CACHE_DIR=/var/lib/borg/cache
ENV BORG_SECURITY_DIR=/var/lib/borg/security
ENV BORG_KEYS_DIR=/var/lib/borg/keys

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["backup"]
