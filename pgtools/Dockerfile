FROM ubuntu:22.04


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
ENTRYPOINT ["/entrypoint.sh"]


RUN rm -Rf \
/usr/lib/gcc \
/usr/lib/aarch*/libLLVM* \
/usr/bin/containerd \
/usr/bin/ctr \
/usr/bin/runc \
/usr/lib/aarch*/perl \
/usr/include/llvm-14 \
/usr/lib/llvm-14

RUN apt-get purge -y build-essential gcc

RUN find / -name __pycache__ -exec rm -Rf {} \; || true
#___SNIPPET_CLEANUP___