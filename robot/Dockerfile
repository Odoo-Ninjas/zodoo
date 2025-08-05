FROM ubuntu:22.04
ARG TARGETARCH

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
RUN python3 -mpip install $(cat /etc/pip_options) setuptools python-dotenv 
RUN python3 -mpip install $(cat /etc/pip_options) -r /tmp/requirements.txt 
RUN rm -rf /tmp/requirements.txt


#___SNIPPET_FIREFOX___


WORKDIR $WORKDIR

RUN useradd -rm -s /bin/bash -d /opt/robot -g root -G sudo robot
RUN echo 'robot ALL=NOPASSWD:SETENV: ALL' > /etc/sudoers.d/robot

#___SNIPPET_DOCKER___


USER root
#___SNIPPET_WODOO___
#RUN find /opt/robot/.* -not -user robot -exec chown -R robot -Rv {} \; >/dev/null 2>&1

RUN mkdir -p /opt/robot/.local && chown robot /opt/robot /opt/robot/.local
USER robot
RUN pip install setuptools==65.6.0 && \
pip install $(cat /etc/pip_options) debugpy pudb --break-system-packages
RUN mkdir -p /opt/robot/.ssh && \
chmod 500 /opt/robot/.ssh
#--------------------------------------------
USER root

#RUN find /opt/robot -not -user robot -exec chown robot {} \; >/dev/null 2>&1
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
RUN chmod a+x entrypoint*.sh
COPY openbox/welcome.txt /etc/welcome.txt

COPY conky.txt /opt/robot/.conkyrc
COPY set_docker_group.sh /usr/local/bin/set_docker_group.sh

ENTRYPOINT ["/opt/robot/entrypoint.sh"]
