FROM ubuntu:24.04
ARG OWNER_UID
ARG DOCKER_GID
ARG TARGETARCH

RUN echo "Acquire::http::Proxy \"http://${APT_PROXY_IP}:3142\";" > /etc/apt/apt.conf.d/01proxy
RUN apt update && apt install -y curl
RUN apt install -y gpg x11vnc xvfb xauth git gosu net-tools rsync
RUN python3 <<'EOF'

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
RUN apt update && apt upgrade -y
ADD welcome.txt /root/welcome.txt

ENV USERNAME=user1
RUN userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) || true 
RUN groupdel $USERNAME || true
RUN groupadd $USERNAME || true
RUN useradd -u $OWNER_UID -g $USERNAME -m $USERNAME
RUN  \
mkdir -p /home/$USERNAME/.vnc && \
chown $USERNAME:$USERNAME /home/$USERNAME/.vnc -R
RUN apt install -y x11-apps python3-pip python3-venv fluxbox xdotool

RUN apt install -y postgresql-server-dev-16
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.9 python3.9-dev python3.9-distutils python3.9-venv

USER $USERNAME
RUN cd /home/$USERNAME && \
python3.9 -mvenv venv && \
. venv/bin/activate && \
./venv/bin/python -mpip install pipx && \
pipx install wodoo && \
pipx install gimera


RUN mkdir -p "/home/$USERNAME/.config/Code/User"
ADD default_vscode_settings.json /tmp/settings

USER root
RUN mv /tmp/settings "/home/$USERNAME/.config/Code/User/settings.json"
RUN find /home/$USERNAME -not -user $USERNAME -exec chown -R $USERNAME:$USERNAME {} \;

USER $USERNAME
# ADD some extensions here
RUN  /usr/bin/code --install-extension ms-python.python || true
RUN /usr/bin/code --install-extension robocorp.robotframework-lsp || true
RUN /usr/bin/code --install-extension vscodevim.vim || true
RUN /usr/bin/code --install-extension MarcWimmerITE.odoobrowserITE || true

USER root

# install docker cli
RUN apt install -y ca-certificates curl gnupg lsb-release
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
RUN echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
RUN apt update && apt install docker-ce docker-ce-cli containerd.io -y
# change docker group id to match host
RUN getent group $DOCKER_GID && groupmod -g 555 $(getent group $DOCKER_GID | cut -d: -f1) || true
RUN groupmod -g $DOCKER_GID docker
RUN usermod -aG docker user1

RUN chsh -s /bin/bash $USERNAME
RUN cp /etc/skel/.bashrc /home/$USERNAME/.bashrc
RUN chown $USERNAME:$USERNAME /home/$USERNAME/.vnc -R
USER $USERNAME
ENV SHELL=bin/bash
RUN echo "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/$USERNAME/.local/bin" >> /home/$USERNAME/.bashrc
RUN echo ". /tmp/envvars.sh" >> /home/$USERNAME/.bashrc
RUN ~/.local/bin/odoo completion -x
RUN ~/.local/bin/gimera completion -x

USER root
ENTRYPOINT ["/bin/bash",  "/entrypoint.sh"]

ENV DEBIAN_FRONTEND=noninteractive

# Update the package list and install necessary dependencies
RUN apt install -y wget
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN dpkg -i google-chrome-stable_current_amd64.deb || true
RUN apt install -y -f
