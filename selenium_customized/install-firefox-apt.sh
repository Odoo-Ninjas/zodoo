#!/bin/bash

install -d -m 0755 /etc/apt/keyrings

wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O- | \
  tee /etc/apt/keyrings/packages.mozilla.org.asc >/dev/null

echo "Installing Mozilla GPG key..."
wget -qO - https://packages.mozilla.org/apt/repo-signing-key.gpg \
  | gpg --dearmor -o /usr/share/keyrings/mozilla-archive-keyring.gpg

echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
  | tee -a /etc/apt/sources.list.d/mozilla.list >/dev/null

echo '
Package: *
Pin: origin packages.mozilla.org
Pin-Priority: 1000
' | tee /etc/apt/preferences.d/mozilla

apt-get update