FROM ubuntu:22.04
ARG TARGETARCH
ARG OWNER_UID
ARG DOCKER_GID
ARG APT_PROXY_IP
ARG APT_OPTIONS
ARG PIP_OPTIONS

ENV DEBIAN_FRONTEND=noninteractive
ENV WORKDIR=/opt/robot
ENV ROBOT_THREADS=1
ENV PATH="$PATH:/opt/robot/.local/bin"



#___SNIPPET_APT_PROXY___

RUN #___SNIPPET_APT_INSTALL___ \
wget unzip python3 \
python3-pip python3-magic libmagickwand-dev xvfb curl \
sudo curl software-properties-common pipx build-essential python3-dev \
gnupg-agent

COPY ./requirements.txt /tmp/requirements.txt
RUN python3 -mpip install -U pip
RUN python3 -mpip install $PIP_OPTIONS setuptools python-dotenv 
RUN python3 -mpip install $PIP_OPTIONS -r /tmp/requirements.txt 
RUN rm -rf /tmp/requirements.txt


#___SNIPPET_FIREFOX___


WORKDIR $WORKDIR

RUN userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) || true
RUN useradd -rm -s /bin/bash -d /opt/robot -g root -G sudo -u $OWNER_UID robot
RUN echo 'robot ALL=NOPASSWD:SETENV: ALL' > /etc/sudoers.d/robot


	
#___SNIPPET_DOCKER___
RUN usermod -aG $DOCKER_GID robot

#___SNIPPET_WODOO___

USER root
RUN find /opt/robot/.* -not -user robot -exec chown -R robot -Rv {} \; >/devnull 2>&1

USER robot
RUN pip install setuptools==65.6.0 && \
pip install $PIP_OPTIONS debugpy pudb --break-system-packages
RUN mkdir -p /opt/robot/.ssh && \
chmod 500 /opt/robot/.ssh
#--------------------------------------------
USER root

RUN find /opt/robot -not -user robot -exec chown robot {} \; >/devnull 2>&1
COPY ssh_config /opt/robot/.ssh/config
RUN chown robot /opt/robot/.ssh/config  


#___SNIPPET_VSCODE___
# COPY some extensions here
USER robot
#___SNIPPET_VSCODE_EXTENSIONS___


USER root
COPY openbox/rc.xml  /opt/robot/.config/openbox/rc.xml
COPY openbox/menu.xml  /opt/robot/.config/openbox/menu.xml


# ###########################
# Scripties
RUN touch /opt/robot/.hushlogin
COPY robotest.py ./
COPY entrypoint.sh ./
COPY entrypoint_cobot.sh ./
RUN chmod a+x entrypoint*.sh
COPY openbox/welcome.txt /etc/welcome.txt

COPY conky.txt /opt/robot/.conkyrc

ENTRYPOINT ["/opt/robot/entrypoint.sh"]