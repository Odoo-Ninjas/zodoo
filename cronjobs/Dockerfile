FROM ubuntu:22.04
ARG POSTGRES_VERSION
ENV DEBIAN_FRONTEND=noninteractive
ENV POSTGRES_VERSION=$POSTGRES_VERSION
ENV PIP_NO_CACHE_DIR=no

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
python3-pip python3 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip

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

#___SNIPPET_WODOO___ 

COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

COPY bin/ /usr/local/bin/
RUN chmod a+x /usr/local/bin/*.py /usr/local/bin/*.sh

#___SNIPPET_CLEANUP___