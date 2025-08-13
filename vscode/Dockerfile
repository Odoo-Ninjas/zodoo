FROM ubuntu:22.04

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
    libxmlsec1-dev libffi-dev liblzma-dev  \
    silversearcher-ag \
    ssh \
    vim \
    jq


# --- COPY newer Python version ---
# hadolint ignore=DL3059
RUN add-apt-repository -y ppa:deadsnakes/ppa --no-update
# hadolint ignore=DL3059
RUN #___SNIPPET_APT_INSTALL___ \
    software-properties-common \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3.11-venv

# --- Determine VSCode download link and install ---
RUN export SHELL=/bin/bash && \
arch="$TARGETARCH"; \
if [ "$TARGETARCH" = "amd64" ]; then arch="x64"; fi; \
url="https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-${arch}"; \
echo "Downloading VS Code for ${arch} from: $url"; \
wget -O /tmp/vscode.deb "$url" && \
#___SNIPPET_APT_INSTALL___ \
    /tmp/vscode.deb && rm /tmp/vscode.deb

# --- COPY welcome message ---
COPY welcome.txt /root/welcome.txt

# --- Create user ---
ENV USERNAME=usertemplate1
RUN groupdel $USERNAME || true && \
    groupadd $USERNAME && \
    useradd -g $USERNAME -m $USERNAME -u 400

USER $USERNAME
WORKDIR /home/$USERNAME

# --- User home prep ---
RUN mkdir -p /home/$USERNAME/.vnc && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.vnc

# --- Setup Python tools as user ---
# hadolint ignore=SC2046
RUN python3.11 -m venv venv && \
    . venv/bin/activate && \
    ./venv/bin/python -m pip install $(cat /etc/pip_options) pipx wheel
# hadolint ignore=SC2086
RUN echo 'export PATH=$PATH:$HOME/.local/bin' >> $HOME/.bashrc

# --- VSCode Extensions ---
USER root
ENV EXTENSIONS_DIR=/opt/vscode-extensions
ENV CODE_DATADIR=/opt/datadir

# --- Install gimera ---
RUN ./venv/bin/python -mpip install gimera

# -- Robotframework requirements --
COPY robot.requirements.txt /opt/robot.requirements.txt
COPY bin/make_robotcode_pyenv.sh /usr/local/bin/make_robotcode_pyenv.sh
RUN bash /usr/local/bin/make_robotcode_pyenv.sh
#___SNIPPET_DOCKER___

RUN \
chsh -s /bin/bash $USERNAME && \
cp /etc/skel/.bashrc /home/$USERNAME/.bashrc && \
chown -R $USERNAME:$USERNAME /home/$USERNAME/.vnc

USER root



USER $USERNAME
ENV SHELL=/bin/bash

# RUN /usr/local/bin/odoo completion -x

USER root
RUN mkdir -p /opt/xpra
WORKDIR /opt/xpra

#___SNIPPET_INSTALL_PIPX___

#___SNIPPET_XPRA_INSTALL___

WORKDIR /home

COPY --chown=$USERNAME:$USERNAME settings.json /opt/settings.json.template

#___SNIPPET_WODOO___

# --- Entrypoint ---
ENTRYPOINT ["/bin/bash", "/usr/local/bin/entrypoint.sh"]
COPY bin/ /usr/local/bin/
RUN chmod a+x /usr/local/bin/*.sh /usr/local/bin/*.py

# hadolint ignore=DL3002
USER root
ENV USERNAME=user1
