FROM ubuntu:22.04 AS builder


#___SNIPPET_APT_PROXY___


RUN #___SNIPPET_APT_INSTALL___ \
python3-dev \
build-essential git python3-pip procps sockstat pv ncdu curl pgp lsb-release

#___SNIPPET_POSTGRES___

ENV PGCLIRC=/var/lib/postgresql/.pgcli.config
RUN pip3 install $(cat /etc/pip_options) pip --upgrade && \
pip3 install $(cat /etc/pip_options) psycopg2 psutil setuptools pgcli pendulum tabulate pg_activity

COPY pgcli.config "$PGCLIRC"
COPY keyring.config /var/lib/postgresql/.local/share/python_keyring/keyringrc.cfg

RUN groupadd -r postgres \
 && useradd -r -g postgres -d /var/lib/postgresql -s /bin/bash postgres \
 && mkdir -p /var/lib/postgresql \
 && chown -R postgres:postgres /var/lib/postgresql

RUN chown postgres:postgres /var/lib/postgresql/.local/share/python_keyring/keyringrc.cfg && \
    chown -R postgres:postgres "$PGCLIRC"

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

# cleanup in builder so the final COPY gets clean files
RUN apt-get purge -y build-essential gcc g++ python3-dev && \
apt-get autoremove -y && \
apt-get clean -y && \
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /var/log/* \
/usr/share/doc /usr/share/man /usr/share/icons /usr/share/vim \
/usr/share/perl /usr/share/poppler /usr/share/i18n \
/usr/lib/gcc /usr/lib/git-core /usr/include /var/cache \
/usr/lib/aarch*/libLLVM* /usr/lib/aarch*/perl /usr/lib/aarch*/gconv \
/usr/lib/llvm-14 /usr/lib/systemd \
/usr/bin/perl /usr/bin/perl5* \
/usr/lib/aarch*/perl-base /usr/lib/aarch*/libperl* \
/root/.cache && \
find /usr -name '*.a' -delete && \
find / -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
ln -sf /usr/lib/postgresql/*/bin/psql /usr/local/bin/psql && \
ln -sf /usr/lib/postgresql/*/bin/pg_dump /usr/local/bin/pg_dump && \
ln -sf /usr/lib/postgresql/*/bin/pg_restore /usr/local/bin/pg_restore

# --- Final stage: single layer copy ---
FROM scratch
ENV PGCLIRC=/var/lib/postgresql/.pgcli.config
COPY --from=builder / /
ENTRYPOINT ["/entrypoint.sh"]
