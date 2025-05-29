FROM ubuntu:24.04
ARG TARGETARCH
ARG OWNER_UID
ARG DOCKER_GID
ARG APT_PROXY_IP
ARG APT_OPTIONS

ENV DEBIAN_FRONTEND=noninteractive
ENV WORKDIR=/opt/robot
ENV ROBOT_THREADS=1
ENV PATH="$PATH:/opt/robot/.local/bin"


#___SNIPPET_APT_MIRRORS___
#___SNIPPET_APT_PROXY___

RUN apt update
RUN apt $APT_OPTIONS install -y wget unzip python3
RUN apt $APT_OPTIONS install -y python3-pip python3-magic libmagickwand-dev xvfb curl
RUN apt $APT_OPTIONS install -y  sudo curl software-properties-common pipx 

COPY ./requirements.txt /tmp/requirements.txt
RUN python3 -mpip install setuptools python-dotenv --break-system-packages
RUN python3 -mpip install --no-cache-dir -r /tmp/requirements.txt --break-system-packages
RUN rm -rf /tmp/requirements.txt


#___SNIPPET_FIREFOX___


WORKDIR $WORKDIR

RUN userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) || true
RUN useradd -rm -s /bin/bash -d /opt/robot -g root -G sudo -u $OWNER_UID robot
RUN echo 'robot ALL=NOPASSWD:SETENV: ALL' > /etc/sudoers.d/robot

RUN mkdir -p /opt/robot/.ssh && \
chmod 500 /opt/robot/.ssh  && \
chown robot /opt/robot && \
chown robot /opt/robot/.ssh -R 

	
#___SNIPPET_DOCKER___

# -------------------------------------------
# Setup Wodoo Framework
# postgres


USER robot
RUN \
mkdir /opt/robot/.local/pipx -p && \
pipx install wodoo --force
RUN pip install --no-cache-dir debugpy pudb --break-system-packages
#--------------------------------------------
USER root

RUN find /opt/robot -not -user robot -exec chown robot {} \;
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