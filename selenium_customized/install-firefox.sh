#!/usr/bin/env bash
set -euo pipefail
set -x

FIREFOX_VERSION=${FIREFOX_VERSION:-latest}
ARCH=$TARGETARCH
ARCH_NAME=$([[ "$ARCH" == "amd64" ]] && echo "x86_64" || echo "aarch64")
INSTALL_VIA_APT="false"

if [[ "$ARCH" == "amd64" || "$FIREFOX_VERSION" == "latest" || "${FIREFOX_VERSION%%.*}" -ge 136 ]]; then
  if [[ "$FIREFOX_VERSION" =~ ^(latest|beta-latest|nightly-latest|devedition-latest|esr-latest)$ ]]; then
    bash /opt/bin/install-firefox-apt.sh
    CLEAN_VER="${FIREFOX_VERSION/-latest/}"
    CLEAN_VER="${FIREFOX_VERSION/latest/}"
    . /etc/proxy_settings
    #apt-get $APT_OPTIONS install -y "firefox${CLEAN_VER}"
    apt-get $(cat /etc/apt_options) install -y "firefox${CLEAN_VER}"
    INSTALL_VIA_APT="true"
    [[ "$CLEAN_VER" =~ ^(beta|nightly|devedition|esr)$ ]] && ln -fs "$(which firefox${CLEAN_VER})" /usr/bin/firefox
  else
    exit 1  # not tested yet
    FIREFOX_DOWNLOAD_URL="https://download-installer.cdn.mozilla.net/pub/firefox/releases/$FIREFOX_VERSION/linux-$ARCH_NAME/en-US/firefox-$FIREFOX_VERSION.deb"
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "$FIREFOX_DOWNLOAD_URL")
    [[ "$CODE" == "404" ]] && FIREFOX_DOWNLOAD_URL="https://download-installer.cdn.mozilla.net/pub/firefox/releases/$FIREFOX_VERSION/linux-$ARCH_NAME/en-US/firefox-$FIREFOX_VERSION.tar.bz2"
  fi
else
  exit 1  # not tested yet
  if [[ "$FIREFOX_VERSION" == "latest" && -z "${FIREFOX_DOWNLOAD_URL:-}" ]]; then
    FIREFOX_VERSION="nightly-latest"
    bash /opt/bin/install-firefox-apt.sh
    CLEAN_VER="${FIREFOX_VERSION/-latest/}"
    . /etc/proxy_settings
    apt-get $APT_OPTIONS install -y "firefox${CLEAN_VER}"
    INSTALL_VIA_APT="true"
    [[ "$CLEAN_VER" == "nightly" ]] && ln -fs "$(which firefox${CLEAN_VER})" /usr/bin/firefox
  fi
fi

apt-get update -qqy
apt-get upgrade -yq