FROM debian:bullseye

# Why the package sources are pinned to a snapshot
#
# squid-deb-proxy only ever existed in bullseye - it was dropped from Debian
# and is in neither bookworm nor trixie. So this image cannot simply follow a
# newer release; it has to keep building against bullseye, which went EOL at
# the end of August 2026.
#
# Since then the bullseye-security binaries are disappearing from the live
# mirrors while bullseye-security is NOT yet on archive.debian.org (which
# still ends at buster). During the move the CDN answers inconsistently: the
# package index lists a version whose .deb is already gone, so
# `apt-get install` dies with a pile of 404s - and it does so intermittently,
# depending on which edge node answers. That is what broke the release build
# of v11.3.1 on 2026-09-07.
#
# snapshot.debian.org serves a frozen point in time and therefore has index
# and pool from the same moment. `Check-Valid-Until` has to go off because a
# snapshot's Release file is deliberately old.
#
# Consequence to be aware of: security updates are frozen at SNAPSHOT_DATE.
# For a build cache on our own network that is acceptable - raise the date
# when the image is rebuilt on purpose.
ARG SNAPSHOT_DATE=20260824T000000Z

# Install squid-deb-proxy
RUN printf '%s\n' \
      "deb http://snapshot.debian.org/archive/debian/${SNAPSHOT_DATE} bullseye main" \
      "deb http://snapshot.debian.org/archive/debian/${SNAPSHOT_DATE} bullseye-updates main" \
      "deb http://snapshot.debian.org/archive/debian-security/${SNAPSHOT_DATE} bullseye-security main" \
      > /etc/apt/sources.list && \
    printf 'Acquire::Check-Valid-Until "false";\n' \
      > /etc/apt/apt.conf.d/99snapshot && \
    apt-get update -y && \
    apt-get install -y --no-install-recommends \
      squid-deb-proxy \
      squid-deb-proxy-client && \
    apt-get clean

# Copy init script
COPY entrypoint.sh /data/entrypoint.sh
COPY squid/etc/extra-sources.acl /data/squid/etc/extra-sources.acl
COPY squid/etc/mirror-dstdomain.acl.d/* /data/squid/etc/mirror-dstdomain.acl.d
RUN chmod +x /data/entrypoint.sh

# Handle user and paths
RUN ln -sf /data/squid/cache /var/cache/squid-deb-proxy
RUN ln -sf /data/squid/log/access.log /var/log/squid-deb-proxy/access.log
RUN ln -sf /data/squid/log/store.log /var/log/squid-deb-proxy/store.log
RUN ln -sf /data/squid/log/cache.log /var/log/squid-deb-proxy/cache.log
RUN ln -sf /data/squid/etc/extra-sources.acl /etc/squid-deb-proxy/mirror-dstdomain.acl.d/20-extra-sources.acl

EXPOSE 8000/tcp

ENTRYPOINT ["/bin/bash", "/data/entrypoint.sh"]

COPY squid/etc/10-extra.conf /etc/squid-deb-proxy/conf.d/10-extra.conf
