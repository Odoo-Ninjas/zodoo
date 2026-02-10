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
unzip libpq-dev

# install docker
#___SNIPPET_DOCKER___


# install postgres
#___SNIPPET_POSTGRES___


WORKDIR /usr/local/bin

RUN #___SNIPPET_APT_INSTALL___ \
python3-lxml

WORKDIR /root
COPY requirements.txt requirements.txt

RUN #___SNIPPET_APT_INSTALL___ \
build-essential gcc python3-dev tmux && \
python3 -mpip install $(cat /etc/pip_options) -r requirements.txt

#___SNIPPET_PYTHON311___
#___SNIPPET_WODOO___

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

COPY bin/ /usr/local/bin/
RUN chmod a+x /usr/local/bin/*.py /usr/local/bin/*.sh

RUN #___SNIPPET_APT_INSTALL___ \
ncdu

RUN apt-get purge -y build-essential gcc
#___SNIPPET_CLEANUP___
RUN rm -Rf \
/usr/lib/gcc \
/usr/lib/aarch*/libLLVM* \
/usr/bin/containerd \
/usr/bin/ctr \
/usr/bin/runc \
/usr/lib/aarch*/perl

RUN find / -name __pycache__ -exec rm -Rf {} \; || true