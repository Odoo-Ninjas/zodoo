FROM ubuntu:22.04

ARG OWNER_UID
ARG TARGETARCH

# --- APT: Mirror & Proxy Configuration ---

#___SNIPPET_APT_PROXY___

ENV DEBIAN_FRONTEND=noninteractive

# --- Basic tools and core dependencies ---

RUN #___SNIPPET_APT_INSTALL___ \
    curl \
    gpg \
    git \
    gosu \
    rsync \
    net-tools \
    xvfb \
    wget \
    x11-apps \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    python3-pyinotify \
    python3-pil \
    python3-paramiko \
    coreutils \
    fluxbox \
    xdotool \
    libpq-dev \
    software-properties-common \
    build-essential \
    gnupg-agent  \
    psmisc \
    wmctrl \
    xauth \
    dbus-x11  \
    git curl make build-essential libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev wget llvm libncursesw5-dev xz-utils tk-dev libxml2-dev \
    libxmlsec1-dev libffi-dev liblzma-dev 


# --- COPY newer Python version ---
RUN add-apt-repository -y ppa:deadsnakes/ppa --no-update
RUN #___SNIPPET_APT_INSTALL___ \
    software-properties-common \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3.11-venv 

# --- Determine VSCode download link and install ---
COPY artefacts /opt/artefacts
RUN python3 <<'EOF'
import os
import shutil
suffix = "x64" if os.getenv("TARGETARCH") == "amd64" else os.getenv("TARGETARCH")
shutil.copy("/opt/artefacts/code-" + suffix, "/tmp/vscode.deb")
EOF
RUN #___SNIPPET_APT_INSTALL___ \
    /tmp/vscode.deb

# --- COPY welcome message ---
COPY welcome.txt /root/welcome.txt

# --- Create user ---
ENV USERNAME=user1
RUN userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) || true && \
    groupdel $USERNAME || true && \
    groupadd $USERNAME && \
    useradd -u $OWNER_UID -g $USERNAME -m $USERNAME

USER $USERNAME
WORKDIR /home/$USERNAME

# --- User home prep ---
RUN mkdir -p /home/$USERNAME/.vnc && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.vnc

# --- Setup Python tools as user ---
RUN python3.11 -m venv venv && \
    . venv/bin/activate && \
    ./venv/bin/python -m pip install $(cat /etc/pip_options) pipx
RUN ./venv/bin/python -mpipx install --pip-args="$(< cat /etc/pip_options)" gimera
RUN echo 'export PATH=$PATH:$HOME/.local/bin' >> $HOME/.bashrc


# --- Setup VSCode default config ---
RUN mkdir -p /home/$USERNAME/.config/Code/User
COPY default_vscode_settings.json /tmp/settings

USER root
RUN mv /tmp/settings /home/$USERNAME/.config/Code/User/settings.json && \
    find /home/$USERNAME -not -user $USERNAME -exec chown -R $USERNAME:$USERNAME {} +

# --- VSCode Extensions ---
USER $USERNAME
RUN /usr/bin/code --install-extension ms-python.python && \
    /usr/bin/code --install-extension robocorp.robotframework-lsp && \
    /usr/bin/code --install-extension d-biehl.robotcode && \
    /usr/bin/code --install-extension vscodevim.vim && \
    /usr/bin/code --install-extension MarcWimmerITE.odoobrowserITE 

# --- Docker CLI ---
USER root
#___SNIPPET_DOCKER___


RUN \
chsh -s /bin/bash $USERNAME && \
cp /etc/skel/.bashrc /home/$USERNAME/.bashrc && \
chown -R $USERNAME:$USERNAME /home/$USERNAME/.vnc

USER root
ENV SHELL=/bin/bash


#___SNIPPET_WODOO___

USER $USERNAME
ENV SHELL=/bin/bash

RUN /usr/local/bin/odoo completion -x
RUN $HOME/.local/bin/gimera completion -x

RUN echo '. /tmp/envvars.sh' >> /home/$USERNAME/.bashrc
USER root


#___SNIPPET_INSTALL_PIPX___

#___SNIPPET_XPRA_INSTALL___
USER root
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

USER $USERNAME


COPY robot.requirements.txt /opt/robot.requirements.txt
COPY make_robotcode_pyenv.sh /usr/local/bin/make_robotcode_pyenv.sh
RUN bash /usr/local/bin/make_robotcode_pyenv.sh

COPY --chown=$USERNAME:$USERNAME settings.json /home/$USERNAME/.config/Code/User/settings.json


# --- Entrypoint ---
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
COPY  set_docker_group.sh /usr/local/bin/set_docker_group.sh

USER root