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
    && rm -rf /var/lib/apt/lists/*

# Download latest VSIX from GitHub releases
RUN mkdir -p /opt/vsix && \
    DOWNLOAD_URL=$(curl -fsSL https://api.github.com/repos/marcwimmer/vscodeextension_browserodoo/releases/latest \
      | jq -r '.assets[] | select(.name | endswith(".vsix")) | .browser_download_url') && \
    curl -fsSL -o /opt/vsix/zebroo.vsix "$DOWNLOAD_URL"

COPY bin/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Install Python extension from Open VSX
RUN PYTHON_EXT_URL=$(curl -fsSL "https://open-vsx.org/api/ms-python/python/latest" \
      | jq -r '.downloads."universal" // .downloads."linux-arm64" // .files.download') && \
    curl -fsSL -o /opt/vsix/ms-python.vsix "$PYTHON_EXT_URL"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
