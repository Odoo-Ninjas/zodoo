FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

#___SNIPPET_APT_PROXY___

# restic provides encryption and deduplication; openssh-client provides the
# transport to an sftp target (Storage Box). The container needs nothing else -
# it only reads read-only mounted directories and pushes ciphertext out.
RUN #___SNIPPET_APT_INSTALL___ \
    restic openssh-client ca-certificates tzdata && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*

# The restic cache (an index of the blocks already transferred) makes the
# difference between "deduplicated and incremental" and "reads everything again
# every night" - it is mounted as a volume and has to survive across runs.
ENV RESTIC_CACHE_DIR=/var/lib/restic/cache
ENV HOME=/var/lib/restic

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["backup"]
