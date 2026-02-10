FROM ubuntu:22.04
ARG POSTGRES_VERSION
ENV DEBIAN_FRONTEND=noninteractive
ENV POSTGRES_VERSION=$POSTGRES_VERSION
ENV PIP_NO_CACHE_DIR=no

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

#___SNIPPET_APT_PROXY___
#___SNIPPET_UPDATE_CA_CERTIFICATES___
#___SNIPPET_UBUNTU_ARCHIVES_HTTPS___

RUN #___SNIPPET_APT_INSTALL___ \
python3-pip python3 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip ncdu python3-lxml \
build-essential gcc python3-dev tmux

# install docker
#___SNIPPET_DOCKER___


# install postgres
#___SNIPPET_POSTGRES___


WORKDIR /usr/local/bin

WORKDIR /root
COPY requirements.txt requirements.txt

RUN python3 -mpip install $(cat /etc/pip_options) -r requirements.txt

#___SNIPPET_WODOO___ 

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

COPY bin/ /usr/local/bin/
RUN chmod a+x /usr/local/bin/*.py /usr/local/bin/*.sh

RUN apt-get purge -y build-essential gcc
#___SNIPPET_CLEANUP___
RUN rm -Rf \
/usr/lib/gcc \
/usr/bin/containerd \
/usr/bin/ctr \
/usr/bin/runc \
/usr/lib/aarch*/perl \
/usr/libexec/docker/cli-plugins \
/usr/lib/git-core

RUN find / -name __pycache__ -exec rm -Rf {} \; || true

RUN cd /opt && tar -cf - wodoo_pipx wodoo | gzip -9 > venv.tar.gz && rm -Rf wodoo_pipx wodoo && cd -