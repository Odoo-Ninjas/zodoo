FROM ubuntu:22.04
ARG WODOO_VERSION
ARG OWNER_UID
ARG DOCKER_GID
ARG project_name
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PYPI_SERVER
ENV DEBIAN_FRONTEND=noninteractive

#___SNIPPET_APT_MIRRORS___

#___SNIPPET_APT_PROXY___
RUN apt-get $APT_OPTIONS install -y python3-pip python3 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip

# install docker
# Prepare keyring

#___SNIPPET_DOCKER___

RUN apt-get update && apt-get $APT_OPTIONS install -y python3-venv zlib1g-dev


# install postgres
# ___SNIPPET_POSTGRES___
RUN apt-get -y $APT_OPTIONS install --no-install-recommends openssh-server && mkdir /var/run/sshd
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
RUN pip3 config set global.index-url $PYPI_SERVER && \
pipx install wodoo==$WODOO_VERSION && \
apt-get $APT_OPTIONS install -y tmux && \
useradd -l -m -s /bin/bash -G sudo,docker -p $(openssl passwd -1 odoo) -u ${OWNER_UID} odoo && \
echo 'odoo:odoo' | chpasswd

USER odoo
RUN pipx install wodoo && \
mkdir ~/.ssh && chmod 700 ~/.ssh
COPY console.key.pub /home/odoo/.ssh/authorized_keys 


USER root
RUN chmod 600 /home/odoo/.ssh/authorized_keys && \
mkdir /home/odoo/bin

COPY sshd_config /etc/ssh/sshd_config
# TODO
# RUN sudo chsh -s /bin/rbash odoo

RUN apt-get $APT_OPTIONS install --no-install-recommends -y silversearcher-ag
RUN \
ln -s /bin/ls /home/odoo/bin/ls && \
ln -s /bin/cat /home/odoo/bin/cat && \
ln -s /usr/bin/tmux /home/odoo/bin/tmux && \
ln -s /usr/bin/docker /home/odoo/bin/docker && \
ln -s /home/odoo/.local/bin/odoo /home/odoo/bin/odoo

COPY welcome.txt /usr/share/welcome.txt
RUN ln -s /opt/src /home/odoo/$project_name
RUN chmod -x /etc/update-motd.d/* && rm /etc/update-motd.d -Rf 
RUN truncate -s 0 /etc/legal /etc/bash.bashrc
RUN usermod -aG docker odoo
COPY profile.d /home/odoo/.profile
RUN chown odoo:odoo /home/odoo/.profile && chmod a+x /home/odoo/.profile
COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

