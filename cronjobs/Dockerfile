FROM ubuntu:22.04
ARG WODOO_VERSION
ARG POSTGRES_VERSION
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
ARG DOCKER_GID
ENV DEBIAN_FRONTEND=noninteractive
ENV POSTGRES_VERSION=$POSTGRES_VERSION
ENV PIP_NO_CACHE_DIR=no

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

#___SNIPPET_APT_MIRRORS___
#___SNIPPET_APT_PROXY___

RUN apt-get install --no-install-recommends -y python3-pip python3 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip

# Set custom PyPI index
# ___SNIPPET_PYPI_SERVER___

# install docker
#___SNIPPET_DOCKER___


# install postgres
#___SNIPPET_POSTGRES___


WORKDIR /usr/local/bin
RUN apt-get $APT_OPTIONS install -y --no-install-recommends python3-lxml

WORKDIR /root
COPY requirements.txt requirements.txt
RUN apt-get -y $APT_OPTIONS install -y --no-install-recommends build-essential gcc python3-dev && \
python3 -mpip install -r requirements.txt && \
pipx install wodoo==$WODOO_VERSION && \
apt-get $APT_OPTIONS install --no-install-recommends -y tmux

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

COPY bin/ /usr/local/bin/
RUN chmod a+x /usr/local/bin/*.py


#___SNIPPET_CLEANUP___