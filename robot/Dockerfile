FROM ubuntu:24.04
ARG TARGETARCH
ARG OWNER_UID
ARG WODOO_VERSION
ARG DOCKER_GID

ENV DEBIAN_FRONTEND=noninteractive
RUN apt update -q && \
apt install -y wget unzip python3 \
python3-pip python3-magic libmagickwand-dev xvfb curl \
sudo curl software-properties-common pipx 

COPY ./requirements.txt /tmp/requirements.txt
RUN python3 -mpip install setuptools --break-system-packages
RUN python3 -mpip install --no-cache-dir -r /tmp/requirements.txt --break-system-packages
RUN rm -rf /tmp/requirements.txt


# Download and install Firefox
RUN add-apt-repository ppa:mozillateam/ppa && \
printf 'Package: *\nPin: release o=LP-PPA-mozillateam\nPin-Priority: 1001\n' | sudo tee /etc/apt/preferences.d/mozilla-firefox
RUN cat /etc/apt/preferences.d/mozilla-firefox
RUN \
apt remove firefox && \
apt update && \
apt install -y firefox

ENV WORKDIR=/opt/robot
ENV ROBOT_THREADS=1

WORKDIR $WORKDIR

RUN userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) || true
RUN useradd -rm -s /bin/bash -d /opt/robot -g root -G sudo -u $OWNER_UID robot
RUN echo 'robot ALL=NOPASSWD:SETENV: ALL' > /etc/sudoers.d/robot
RUN \
	apt install -y \
	firefox gpg x11vnc xvfb xauth \
	git gosu net-tools rsync x11-apps python3-pip python3-venv xdotool \
	firefox-esr xvfb x11-utils x11-xserver-utils mesa-utils libgl1-mesa-dri \
	fonts-dejavu-core fonts-dejavu-core fonts-liberation \ 
	libpci3 curl pipx gosu openbox ca-certificates curl gnupg lsb-release \
	ssh 

RUN mkdir -p /opt/robot/.ssh && \
chmod 500 /opt/robot/.ssh  && \
chown robot /opt/robot && \
chown robot /opt/robot/.ssh -R 

	

# -------------------------------------------
# Setup Wodoo Framework
# postgres
ENV DEBIAN_FRONTEND=noninteractive
RUN \
	apt update && \
	apt install -y postgresql postgresql-contrib
RUN \
	sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' && \
	wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
	echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
	apt update && \
	apt -y install postgresql-14 libpq-dev

# install docker cli
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
RUN echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
RUN \
	apt update && \
	apt install docker-ce docker-ce-cli containerd.io -y && \
	usermod -aG docker robot
RUN groupmod -g 555 $(getent group $DOCKER_GID | cut -d: -f1) || true
RUN cat /etc/group
RUN groupmod -g $DOCKER_GID docker
RUN usermod -aG docker robot

#--------------------------------------------

USER robot
ENV WODOO_VERSION=$WODOO_VERSION
RUN \
mkdir /opt/robot/.local/pipx -p && \
pipx install wodoo==$WODOO_VERSION --force
RUN pip install debugpy pudb --break-system-packages
ENV PATH="$PATH:/opt/robot/.local/bin"
USER root

RUN find /opt/robot -not -user robot -exec chown robot {} \;
COPY ssh_config /opt/robot/.ssh/config
RUN chown robot /opt/robot/.ssh/config  



# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# INSTALL CODE
RUN python3 <<'EOF'
# V3

import os
from pathlib import Path
downloadlink = Path("/tmp/downloadlink")
# link = ("https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-")
link = "https://artefacts.zebroo.de/simplicissimus_agatha_christie/code-"
if os.getenv("TARGETARCH") == "amd64": 
    link += "x64"
else:
    link += os.getenv("TARGETARCH")
downloadlink.write_text(link)
EOF

RUN echo "Download link: $(cat /tmp/downloadlink)"
RUN apt install -y wget
RUN wget -O /tmp/vscode.deb "$(cat /tmp/downloadlink)"

RUN apt install -y /tmp/vscode.deb
# ADD some extensions here
USER robot
RUN /usr/bin/code --install-extension ms-python.python || true
RUN /usr/bin/code --install-extension robocorp.robotframework-lsp || true
RUN /usr/bin/code --install-extension vscodevim.vim || true
RUN /usr/bin/code --install-extension MarcWimmerITE.odoobrowserITE || true
USER root

# INSTALL CODE END
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

ADD openbox/rc.xml  /opt/robot/.config/openbox/rc.xml
ADD openbox/menu.xml  /opt/robot/.config/openbox/menu.xml


# ###########################
# Scripties
RUN touch /opt/robot/.hushlogin
COPY robotest.py ./
COPY entrypoint.sh ./
COPY entrypoint_cobot.sh ./
RUN chmod a+x entrypoint*.sh
ENTRYPOINT ["/opt/robot/entrypoint.sh"]
ADD openbox/welcome.txt /etc/welcome.txt

ADD conky.txt /opt/robot/.conkyrc
RUN apt update && apt install -y \
    wget \
    unzip \
    curl \
    gnupg 
