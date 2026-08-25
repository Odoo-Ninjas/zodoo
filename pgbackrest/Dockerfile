FROM ubuntu:24.04

ARG POSTGRES_VERSION=17
ENV POSTGRES_VERSION=$POSTGRES_VERSION
ENV DEBIAN_FRONTEND=noninteractive

#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
    ca-certificates curl gnupg lsb-release procps gosu gettext-base openssl

# Adds the pgdg apt repository and installs postgresql-client-$POSTGRES_VERSION.
# We need psql here for the restore-point / switch-wal helpers, and libpq for
# the backup itself (pgbackrest calls pg_backup_start/stop over a normal
# connection).
#___SNIPPET_POSTGRES___

# pgbackrest from pgdg rather than the distribution: block-level incrementals
# (2.46+) and the TLS server mode (2.37+) are exactly the two features this
# integration is built on, and Ubuntu ships a version too old for both.
RUN #___SNIPPET_APT_INSTALL___ \
    pgbackrest && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*

# pg client binaries live under /usr/lib/postgresql/<v>/bin - expose them.
RUN ln -sf /usr/lib/postgresql/*/bin/psql /usr/local/bin/psql && \
    ln -sf /usr/lib/postgresql/*/bin/pg_isready /usr/local/bin/pg_isready

# pgbackrest insists on running as a non-root user and on owning its
# directories. The uid matters: this container reads PGDATA out of the postgres
# volume, where everything belongs to uid 999 (the postgres image's postgres
# user). Sharing that uid is what lets the backup read the data directory
# without a chown that would upset postgres itself.
RUN groupadd -g 999 pgbackrest 2>/dev/null || true && \
    useradd -u 999 -g 999 -m -s /bin/bash pgbackrest 2>/dev/null || true && \
    mkdir -p /var/lib/pgbackrest /var/log/pgbackrest /var/spool/pgbackrest \
             /etc/pgbackrest /etc/pgbackrest/cert && \
    chown -R 999:999 /var/lib/pgbackrest /var/log/pgbackrest \
                     /var/spool/pgbackrest /etc/pgbackrest

# pgbackrest.conf is deliberately NOT baked in: it is rendered on the host by
# __after_compose.py and mounted read-only into this container and into the
# postgres container, so both sides read the same file.
COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
