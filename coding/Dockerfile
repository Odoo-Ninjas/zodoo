# hadolint ignore=DL3007
FROM gitpod/openvscode-server:latest

# Switch to root for setup; entrypoint drops to unprivileged user via gosu
# hadolint ignore=DL3002
USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gosu \
    curl \
    jq \
    iputils-ping \
    telnet \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    libmagickwand-dev \
    && rm -rf /var/lib/apt/lists/*

# Download latest VSIX from GitHub releases
RUN mkdir -p /opt/vsix && \
    DOWNLOAD_URL=$(curl -fsSL https://api.github.com/repos/marcwimmer/vscodeextension_browserodoo/releases/latest \
      | jq -r '.assets[] | select(.name | endswith(".vsix")) | .browser_download_url') && \
    curl -fsSL -o /opt/vsix/zebroo.vsix "$DOWNLOAD_URL"

COPY coding/bin/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Install Python extension from Open VSX
RUN PYTHON_EXT_URL=$(curl -fsSL "https://open-vsx.org/api/ms-python/python/latest" \
      | jq -r '.downloads."universal" // .downloads."linux-arm64" // .files.download') && \
    curl -fsSL -o /opt/vsix/ms-python.vsix "$PYTHON_EXT_URL"

# Install Vim extension from Open VSX (disabled by default, enable via ?vim=1 URL param)
RUN VIM_EXT_URL=$(curl -fsSL "https://open-vsx.org/api/vscodevim/vim/latest" \
      | jq -r '.downloads."universal" // .files.download') && \
    curl -fsSL -o /opt/vsix/vim.vsix "$VIM_EXT_URL"

COPY coding/bin/vim-toggle.js /usr/local/bin/vim-toggle.js

# Create robot virtualenv with robot framework requirements
COPY robot/requirements.txt /tmp/robot_requirements.txt
RUN python3 -m venv /opt/robotenv && \
    /opt/robotenv/bin/pip install --no-cache-dir -U pip setuptools wheel && \
    /opt/robotenv/bin/pip install --no-cache-dir -r /tmp/robot_requirements.txt && \
    rm /tmp/robot_requirements.txt && \
    apt-get purge -y build-essential python3-dev && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
