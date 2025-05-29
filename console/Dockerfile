FROM ubuntu:24.04
ARG WODOO_VERSION
ARG OWNER_UID
ARG DOCKER_GID
ARG project_name
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
ENV DEBIAN_FRONTEND=noninteractive
RUN echo "Acquire::http::Proxy \"http://${APT_PROXY_IP}:3142\";" > /etc/apt/apt.conf.d/01proxy
RUN apt update
RUN apt $APT_OPTIONS install -y python3-pip python3 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip

# install docker
# Prepare keyring
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

RUN apt update && apt $APT_OPTIONS install -y python3-venv zlib1g-dev

# change docker group id to match host
RUN groupmod -g 555 $(getent group $DOCKER_GID | cut -d: -f1) || true
RUN groupmod -g $DOCKER_GID docker

# install postgres
RUN apt -y $APT_OPTIONS install && \
export DEBIAN_FRONTEND=noninteractive && \
apt $APT_OPTIONS install -y postgresql postgresql-contrib
RUN sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' && \
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
apt update && \
apt -y $APT_OPTIONS install postgresql-17
RUN apt -y $APT_OPTIONS install openssh-server
RUN mkdir /var/run/sshd
EXPOSE 22

RUN sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && dpkg-reconfigure --frontend=noninteractive locales \
    && update-locale LANG=en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

WORKDIR /root

# Optional: speed up installs
ENV PIP_NO_CACHE_DIR=no
# Set custom PyPI index
RUN pip3 config set global.index-url $PYPI_SERVER
RUN pipx install wodoo==$WODOO_VERSION
RUN apt $APT_OPTIONS install -y tmux


RUN cat /etc/passwd
RUN deluser ubuntu
RUN useradd -m -s /bin/bash -G sudo,docker -p $(openssl passwd -1 odoo) -u ${OWNER_UID} odoo
RUN echo 'odoo:odoo' | sudo chpasswd

USER odoo
RUN pipx install wodoo
RUN mkdir ~/.ssh && chmod 700 ~/.ssh
COPY console.key.pub /home/odoo/.ssh/authorized_keys 


USER root
RUN chmod 600 /home/odoo/.ssh/authorized_keys
RUN mkdir /home/odoo/bin

ADD sshd_config /etc/ssh/sshd_config
# TODO
# RUN sudo chsh -s /bin/rbash odoo

RUN apt $APT_OPTIONS install -y silversearcher-ag
RUN \
ln -s /bin/ls /home/odoo/bin/ls && \
ln -s /bin/cat /home/odoo/bin/cat && \
ln -s /usr/bin/tmux /home/odoo/bin/tmux && \
ln -s /usr/bin/docker /home/odoo/bin/docker && \
ln -s /home/odoo/.local/bin/odoo /home/odoo/bin/odoo

ADD welcome.txt /usr/share/welcome.txt
RUN ln -s /opt/src /home/odoo/$project_name
RUN chmod -x /etc/update-motd.d/* && rm /etc/update-motd.d -Rf 
RUN truncate -s 0 /etc/legal /etc/bash.bashrc
RUN usermod -aG docker odoo
ADD profile.d /home/odoo/.profile
RUN chown odoo:odoo /home/odoo/.profile && chmod a+x /home/odoo/.profile
ADD entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

