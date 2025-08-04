FROM ubuntu:22.04


#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
postgresql-server-dev-14 python3-dev \
build-essential git python3-pip procps sockstat pv

ENV PGCLIRC=/var/lib/postgresql/.pgcli.config
RUN pip3 install $(cat /etc/pip_options) pip --upgrade && \
pip3 install $(cat /etc/pip_options) psycopg2 psutil setuptools pgcli pendulum tabulate pg_activity

COPY pgcli.config "$PGCLIRC"
COPY keyring.config /var/lib/postgresql/.local/share/python_keyring/keyringrc.cfg
RUN chown postgres:postgres /var/lib/postgresql/.local/share/python_keyring/keyringrc.cfg && \
    chown -R postgres:postgres "$PGCLIRC"

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]