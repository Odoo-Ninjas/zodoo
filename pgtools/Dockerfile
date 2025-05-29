FROM ubuntu:22.04

___SNIPPET_APT_PROXY___
___SNIPPET_APT_MIRRORS___

RUN apt-get update -q && \
apt install -y postgresql-server-dev-14 python3-dev \
build-essential git python3-pip procps sockstat pv

ENV PGCLIRC=/var/lib/postgresql/.pgcli.config
RUN pip3 install pip --upgrade && \
pip3 install psycopg2 psutil setuptools pgcli pendulum tabulate pg_activity

ADD pgcli.config "$PGCLIRC"
ADD keyring.config /var/lib/postgresql/.local/share/python_keyring/keyringrc.cfg
RUN chown postgres:postgres /var/lib/postgresql/.local/share/python_keyring/keyringrc.cfg && \
    chown -R postgres:postgres "$PGCLIRC"

ADD entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]