# zodoo – Odoo Docker Framework

This is the **zodoo repository** — the source for Docker images and project templates used by the `odoo` CLI.

> Looking for how to use zodoo in your Odoo project? See [`docs/03-quickstart.md`](./docs/03-quickstart.md) or the full [documentation index](./docs/README.md).

## What this repo contains

| Directory                                     | Contents                                                                   |
| --------------------------------------------- | -------------------------------------------------------------------------- |
| `odoo/`                                       | Odoo Docker image (Dockerfile, docker-compose templates, default settings) |
| `postgres/`, `proxy/`, `mail/`, `redis/`, ... | Service Docker images                                                      |
| `templates/customs_template/`                 | Project init templates (copied by `odoo init`)                             |
| `templates/module_template/`                  | Module scaffold templates (used by `odoo src make-module`)                 |
| `wodoo/`                                      | Git submodule → Python CLI source (`wodoo` package)                        |
| `docs/`                                       | Full documentation                                                         |
| `install.sh`                                  | One-line installer script                                                  |

## Architecture

Users install zodoo via:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
```

This:

1. Clones this repo to `~/.odoo/images/`
2. Installs the `wodoo` Python package (from `wodoo/src/`) via `pipx` → provides the `odoo` command

## Changelog / Releasing

Changes to the `wodoo` CLI are tracked with **towncrier**.

- Changelog fragments live in `wodoo/src/changelog.d/`
- Fragment filename format: `<short-description>.<type>.md`
  - Types: `bugfix`, `feature`, `misc`
  - Example: `preserve-custom-scss.bugfix.md`
- To build the changelog and bump the version:

```bash
cd wodoo/src
towncrier build --version <new_version> --yes
# then update setup.cfg and wodoo/version.txt to match
git add CHANGELOG.md setup.cfg wodoo/version.txt changelog.d/
git commit -m "release <new_version>"
git push
```

**Always use towncrier for changelog entries — do not edit `CHANGELOG.md` directly.**

## Working on this repo

### Prerequisites

- Docker
- Python 3.10–3.12
- pipx
- gimera (`pipx install gimera`)

### Run wodoo from source (for development)

```bash
cd wodoo/src
pipx install -e . --force
```

### Submodule (wodoo)

The `wodoo/` directory is a git submodule pointing to the wodoo Python package repo.

```bash
git submodule update --init
```

### Project templates

`templates/customs_template/{version}/` is copied 1:1 into new projects by `odoo src init`.

When adding files here (like `CLAUDE.md`), they appear in every new project created with `odoo init`.

Versions: `9.0`, `11.0`, `12.0`, `13.0`, `14.0`, `15.0`, `16.0`, `17.0`, `18.0`, `19.0`

### Building containers from scratch

```bash
odoo build <name> --no-zodoo-pull
```

### Testing changes locally

```bash
# Apply changes to ~/.odoo/images (since that's what users have):
rsync -av --exclude='.git' ./ ~/.odoo/images/

# Or: point ODOO_IMAGES to this checkout:
export ODOO_IMAGES=$(pwd)
```

## Documentation

Full docs: [`docs/`](./docs/README.md)

Online: https://docs.zebroo.de/docs/zodoo

> **Note for AI assistants (Claude Code, Cursor, etc.):** The docs site `docs.zebroo.de` is not accessible from sandboxed environments. All documentation is available in the `docs/` folder in this repository.
