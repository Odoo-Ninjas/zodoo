# Installation

## Prerequisites

- **Docker** (Docker Desktop on Mac, Docker Engine on Linux)
- **git**
- **Python 3.10–3.12** (Python 3.13 not yet supported)
- **pipx** (for isolated CLI tool installation)

On macOS:

```bash
brew install git pipx rsync
brew install --cask docker
```

On Ubuntu/Debian:

```bash
sudo apt-get install git pipx rsync docker.io docker-buildx docker-compose-v2
```

`docker-buildx` is easy to miss and hard to diagnose: Docker 29 (Ubuntu 26.04)
enables BuildKit by default but the `docker.io` package does not pull buildx in.
`odoo build` then aborts with "BuildKit is enabled but the buildx component is
missing or broken", the base image is never built, and the next step tries to
pull it from Docker Hub — which surfaces as a misleading
`pull access denied ... odoo_base_<version>_...`.

## Install zodoo

One-liner installer (installs zodoo CLI + clones zodoo images to `~/.odoo/images`):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
```

This installs the `odoo` command via `pipx` and sets up `~/.odoo/images/`.

## Optional: Passwordless sudo for dev machines

Required for btrfs/zfs snapshots and some file operations:

```bash
cat << 'EOF' > /etc/sudoers.d/odoo
Cmnd_Alias ODOO_COMMANDS_ODOO = /usr/bin/find *, /var/lib/zodoo_env/bin/odoo *, /usr/bin/btrfs subvolume *, /usr/bin/mkdir *, /usr/bin/mv *, /usr/bin/rsync *, /usr/bin/rm *, /usr/bin/du *, /usr/local/bin/odoo *, /usr/bin/btrfs subvol show *, /usr/sbin/gosu *
odoo ALL=NOPASSWD:SETENV: ODOO_COMMANDS_ODOO
EOF
```

## Verify installation

```bash
odoo --version
odoo --help
```

## Shell tab completion

```bash
odoo completion -x >> ~/.bashrc   # bash
odoo completion -x >> ~/.zshrc    # zsh
source ~/.bashrc
```

## Upgrade zodoo

```bash
odoo upgrade
```

This pulls the latest `~/.odoo/images` from git and reinstalls the `zodoo` package.

## Cleanup / Reinstall

If you had a previous installation (e.g. old "wodoo"):

```bash
rm -Rf ~/.odoo/images
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
```
