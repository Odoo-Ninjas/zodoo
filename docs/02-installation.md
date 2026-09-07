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

## Why the base images are pinned to old distributions

Each Odoo generation gets a base of its own era, and that is deliberate — old
Odoo needs old Python:

| Odoo | base |
| --- | --- |
| 11 | `debian:buster` |
| 12, 13, 14 | `debian:bullseye` |
| 15 – 19 | `ubuntu:22.04` |

Moving 12–14 to bookworm is not a hardening step, it is a break: bookworm
ships Python 3.11, and Odoo 12 (2018) does not run on it. **"Get off the old
distribution" is the wrong goal for these images.**

### What actually breaks, and when

Not the running container — the **build**. When Debian moves a release out of
`deb.debian.org` into `archive.debian.org`, every `apt-get` in that image
starts failing with *"does not have a Release file"*.

That has already happened to **buster**: the bare `debian:buster` image cannot
`apt-get update` any more. `odoo/config/11` survives because it rewrites its
sources first — the recipe is at the top of its Dockerfile:

```dockerfile
RUN sed -i 's|deb.debian.org|archive.debian.org|g' /etc/apt/sources.list && \
    sed -i 's|security.debian.org|archive.debian.org|g' /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until && \
    apt-get -o Acquire::Retries=3 update
```

`Check-Valid-Until "false"` is not optional: the Release files in the archive
are expired by definition, and apt refuses them without it.

### bullseye: do not switch yet

Checked on 07.09.2026:

| | |
| --- | --- |
| `deb.debian.org` bullseye + bullseye-security | 200 — still served in full |
| `archive.debian.org/debian` bullseye, bullseye-updates | 200 |
| `archive.debian.org/debian-security` bullseye-security | **404 — not archived yet** |

So the live mirror is complete and the archive is not. Applying the buster
recipe to bullseye **today breaks the build** — `apt-get update` returns 100
because the security suite disappears. Verified, not assumed.

Flip it when `deb.debian.org` stops serving bullseye, and check the security
suite separately at that moment: it may still have to point at
`security.debian.org` for a while.

### A trap worth knowing

`odoo/config/11` line 151 adds a source as `/etc/apt/sources.list.d/dmtx` —
**without a `.list` suffix**. apt only reads `*.list` (and `*.sources`) there,
so the line has never had any effect; `libdmtx0b` comes from buster main
instead. Measured: without the suffix apt never mentions the URL and returns 0,
with it the URL appears three times and apt returns 100.
