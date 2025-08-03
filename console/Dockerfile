FROM ubuntu:22.04
ARG OWNER_UID
ARG DOCKER_GID
ARG project_name
ARG APT_PROXY_IP
ARG APT_OPTIONS
ENV DEBIAN_FRONTEND=noninteractive

#___SNIPPET_APT_PROXY___
RUN #___SNIPPET_APT_INSTALL___ \
python3-pip python3 curl rsync locales pv \
pigz telnet libpq-dev wget lsb-release \
libxml2-dev libxslt-dev pipx gosu git sudo \
ca-certificates curl gnupg lsb-release \
unzip build-essential python3-dev software-properties-common

#___SNIPPET_PYTHON311___

#___SNIPPET_DOCKER___

RUN #___SNIPPET_APT_INSTALL___ \
python3-venv zlib1g-dev


# install postgres
# ___SNIPPET_POSTGRES___
RUN #___SNIPPET_APT_INSTALL___ \
openssh-server && mkdir /var/run/sshd
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

#___SNIPPET_WODOO___

RUN #___SNIPPET_APT_INSTALL___ \
tmux silversearcher-ag && \
useradd -l -m -s /bin/bash -G sudo,docker -p $(openssl passwd -1 odoo) -u ${OWNER_UID} odoo && \
echo 'odoo:odoo' | chpasswd

RUN mkdir ~/.ssh && chmod 700 ~/.ssh
COPY console.key.pub /home/odoo/.ssh/authorized_keys 


RUN chmod 600 /home/odoo/.ssh/authorized_keys && \
mkdir /home/odoo/bin

COPY sshd_config /etc/ssh/sshd_config
# TODO
# RUN sudo chsh -s /bin/rbash odoo

RUN \
ln -s /bin/ls /home/odoo/bin/ls && \
ln -s /bin/cat /home/odoo/bin/cat && \
ln -s /usr/bin/tmux /home/odoo/bin/tmux && \
ln -s /usr/bin/docker /home/odoo/bin/docker && \
export ODOO_BIN=/home/odoo/bin/odoo && \
ln -s $WODOO_ENV_DIR/bin/odoo $ODOO_BIN

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

