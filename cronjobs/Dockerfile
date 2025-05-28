FROM ubuntu:24.04
ARG WODOO_VERSION
ARG POSTGRES_VERSION
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
ARG DOCKER_GID
ENV DEBIAN_FRONTEND=noninteractive
RUN echo "Acquire::http::Proxy \"http://${APT_PROXY_IP}:3142\";" > /etc/apt/apt.conf.d/01proxy
RUN apt update && \
apt $APT_OPTIONS install -y python3-pip python3 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip

# Optional: speed up installs
ENV PIP_NO_CACHE_DIR=no
# Set custom PyPI index
RUN pip3 config set global.index-url $PYPI_SERVER

# install docker
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

RUN echo \
  "deb [arch=$(dpkg --print-architecture) \
  signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt update && \
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
RUN groupmod -g 555 $(getent group $DOCKER_GID | cut -d: -f1) || true
RUN groupadd -g $DOCKER_GID docker


# install postgres
RUN apt -y $APT_OPTIONS install && \
export DEBIAN_FRONTEND=noninteractive 
RUN sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' && \
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
apt update && \
apt purge -y postgresql-client

# RUN sed -i -e 's/# eUS.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
#     && dpkg-reconfigure --frontend=noninteractive locales \
#     && update-locale LANG=en_US.UTF-8
# ENV LANG=en_US.UTF-8
# ENV LC_ALL=en_US.UTF-8

WORKDIR /usr/local/bin
RUN apt $APT_OPTIONS install -y python3-lxml

WORKDIR /root
COPY requirements.txt requirements.txt
RUN python3 -mpip install -r requirements.txt --break-system-packages

RUN pipx install wodoo==$WODOO_VERSION
RUN apt $APT_OPTIONS install -y tmux

ADD entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

ADD bin/ /usr/local/bin/
RUN chmod a+x /usr/local/bin/*.py

RUN apt -y $APT_OPTIONS install && \
export DEBIAN_FRONTEND=noninteractive && \
apt $APT_OPTIONS install -y postgresql postgresql-contrib
RUN sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' && \
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
apt update && \
apt purge -y postgresql-client postgresql-client-17 postgresql-client-16

ENV POSTGRES_VERSION=$POSTGRES_VERSION
RUN echo postgres version ist: $POSTGRES_VERSION
RUN \
set -x && \
if [ "$POSTGRES_VERSION" = "17" ]; then \
  apt $APT_OPTIONS install -y postgresql-client-17; \
else \
  apt $APT_OPTIONS install -y postgresql-client-16; \
fi
