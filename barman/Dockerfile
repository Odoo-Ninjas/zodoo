FROM ubuntu:22.04

ARG POSTGRES_VERSION=17
ENV POSTGRES_VERSION=$POSTGRES_VERSION
ENV DEBIAN_FRONTEND=noninteractive

#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
    ca-certificates curl gnupg lsb-release procps gosu gettext-base

# Adds the pgdg apt repository and installs postgresql-client-$POSTGRES_VERSION
# (provides pg_basebackup / pg_receivewal matching the server major version).
#___SNIPPET_POSTGRES___

# Barman + the streaming/cloud helper commands live in the pgdg repo set up above.
RUN #___SNIPPET_APT_INSTALL___ \
    barman barman-cli && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*

# pg client binaries are installed under /usr/lib/postgresql/<v>/bin - expose them.
RUN ln -sf /usr/lib/postgresql/*/bin/pg_basebackup /usr/local/bin/pg_basebackup && \
    ln -sf /usr/lib/postgresql/*/bin/pg_receivewal /usr/local/bin/pg_receivewal && \
    ln -sf /usr/lib/postgresql/*/bin/pg_isready /usr/local/bin/pg_isready

COPY barman.conf.template /etc/barman.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
