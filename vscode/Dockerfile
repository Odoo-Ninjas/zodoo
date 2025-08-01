FROM ubuntu:22.04

ARG OWNER_UID
ARG DOCKER_GID
ARG TARGETARCH
ARG APT_OPTIONS

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
    dbus-x11 


# --- COPY newer Python version ---
RUN add-apt-repository -y ppa:deadsnakes/ppa --no-update
RUN #___SNIPPET_APT_INSTALL___ \
    software-properties-common \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3.11-venv

# --- Determine VSCode download link and install ---
RUN python3 <<'EOF'
import os
from pathlib import Path
downloadlink = Path("/tmp/downloadlink")
link = "https://artefacts.zebroo.de/simplicissimus_agatha_christie/code-"
link += "x64" if os.getenv("TARGETARCH") == "amd64" else os.getenv("TARGETARCH")
downloadlink.write_text(link)
EOF

RUN echo "Download link: $(cat /tmp/downloadlink)" && \
    wget --progress=dot:giga -O /tmp/vscode.deb "$(cat /tmp/downloadlink)" && \
    #___SNIPPET_APT_INSTALL___ \
    /tmp/vscode.deb

# --- COPY welcome message ---
COPY welcome.txt /root/welcome.txt

# --- Create user ---
ENV USERNAME=user1
RUN userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) || true && \
    groupdel $USERNAME || true && \
    groupadd $USERNAME && \
    useradd -u $OWNER_UID -g $USERNAME -m $USERNAME

# --- User home prep ---
RUN mkdir -p /home/$USERNAME/.vnc && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.vnc

# --- Setup Python tools as user ---
USER $USERNAME
WORKDIR /home/$USERNAME

RUN python3.11 -m venv venv && \
    . venv/bin/activate && \
    ./venv/bin/python -m pip install pipx && \
    pipx install --pip-args="$PIP_OPTIONS" gimera
RUN echo 'export PATH=$PATH:$HOME/.local/bin' >> $HOME/.bashrc


# --- Setup VSCode default config ---
RUN mkdir -p /home/$USERNAME/.config/Code/User
COPY default_vscode_settings.json /tmp/settings

USER root
RUN mv /tmp/settings /home/$USERNAME/.config/Code/User/settings.json && \
    find /home/$USERNAME -not -user $USERNAME -exec chown -R $USERNAME:$USERNAME {} +

# --- VSCode Extensions ---
USER $USERNAME
RUN /usr/bin/code --install-extension ms-python.python || true && \
    /usr/bin/code --install-extension robocorp.robotframework-lsp || true && \
    /usr/bin/code --install-extension vscodevim.vim || true && \
    /usr/bin/code --install-extension MarcWimmerITE.odoobrowserITE || true

# --- Docker CLI ---
USER root
#___SNIPPET_DOCKER___

# --- Group fix and user shell ---
RUN usermod -aG docker $USERNAME && \
    chsh -s /bin/bash $USERNAME && \
    cp /etc/skel/.bashrc /home/$USERNAME/.bashrc && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.vnc

# --- Install Google Chrome ---
USER root
RUN wget --progress=dot:giga https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    dpkg -i google-chrome-stable_current_amd64.deb || true && \
    apt-get install -y -f

# --- Entrypoint ---
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

USER root
ENV SHELL=/bin/bash


#___SNIPPET_WODOO___
USER $USERNAME
#___SNIPPET_WODOO_USER___

USER $USERNAME
ENV SHELL=/bin/bash

RUN /usr/local/bin/odoo completion -x
RUN $HOME/.local/bin/gimera completion -x

RUN echo '. /tmp/envvars.sh' >> /home/$USERNAME/.bashrc
USER root

#___SNIPPET_INSTALL_PIPX___

#___SNIPPET_XPRA_INSTALL___