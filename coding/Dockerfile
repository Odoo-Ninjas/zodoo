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

# Suppress .pyc generation BEFORE any pip install so __pycache__ never
# materialises in /opt/robotenv. Same flag is re-stated below for runtime.
ENV PYTHONDONTWRITEBYTECODE=1

# Create robot virtualenv with robot framework requirements and zodoo's
# pip deps. zodoo itself is NOT installed — its source is bind-mounted at
# /opt/zodoo at runtime and made importable via a .pth file. This way
# zodoo CLI changes don't trigger an image rebuild.
COPY robot/requirements.txt /tmp/robot_requirements.txt
COPY zodoo/src/zodoo/requirements.txt /tmp/zodoo_requirements.txt
RUN python3 -m venv /opt/robotenv && \
    /opt/robotenv/bin/pip install --no-cache-dir -U pip setuptools wheel && \
    /opt/robotenv/bin/pip install --no-cache-dir -r /tmp/robot_requirements.txt && \
    /opt/robotenv/bin/pip install --no-cache-dir lxml==4.9.3 && \
    /opt/robotenv/bin/pip install --no-cache-dir -r /tmp/zodoo_requirements.txt && \
    /opt/robotenv/bin/pip install --no-cache-dir gimera && \
    SITE_PACKAGES="$(ls -d /opt/robotenv/lib/python*/site-packages)" && \
    echo /opt/zodoo > "$SITE_PACKAGES/zodoo_src.pth" && \
    rm /tmp/zodoo_requirements.txt /tmp/robot_requirements.txt && \
    apt-get purge -y build-essential gcc g++ python3-dev libpq-dev || true && \
    apt-get autoremove -y || true && \
    apt-get clean -y || true && \
    find /opt/robotenv /usr -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find /usr -name '*.a' -delete && \
    rm -rf \
        /var/lib/apt/lists/* /tmp/* /var/tmp/* /var/log/* \
        /usr/share/doc /usr/share/man /usr/share/icons /usr/share/vim \
        /usr/share/perl /usr/share/poppler /usr/share/i18n \
        /usr/share/cmake /usr/share/cmake-3.22 /usr/share/python-wheels \
        /usr/share/emacs /usr/share/emacsen-common /usr/share/java \
        /usr/share/iso-codes /usr/share/javascript \
        /usr/lib/gcc /usr/lib/git-core /usr/include /var/cache \
        /usr/lib/aarch64-linux-gnu/libasan.so* \
        /usr/lib/aarch64-linux-gnu/libtsan.so* \
        /usr/lib/aarch64-linux-gnu/liblsan.so* \
        /usr/lib/aarch64-linux-gnu/libubsan.so* \
        /usr/lib/aarch64-linux-gnu/libhwasan.so* \
        /usr/bin/cmake /usr/bin/cpack /usr/bin/ctest \
        /usr/bin/meson /usr/bin/ninja \
        /root/.cache
ENV PATH="/opt/robotenv/bin:$PATH"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
