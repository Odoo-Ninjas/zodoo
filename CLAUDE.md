# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# zodoo – Odoo Docker Framework

Source for the Docker images and project templates that the `odoo` CLI builds against. Users install via `bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)` which clones this repo to `~/.odoo/images/` and pipx-installs `zodoo/src/` as the `odoo` command.

## Repo layout (high-level)

| Directory                                                                 | Contents                                                                                            |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `zodoo/src/`                                                              | Python CLI (`zodoo` package). The `odoo` command on the host comes from here.                       |
| `odoo/`                                                                   | Odoo Docker image (Dockerfile parts, compose templates, default settings, entrypoint)               |
| `odoo/config/<version>/`                                                  | Per-Odoo-version Dockerfile fragments. `common.docker` is appended for >= 14.0                      |
| `cronjobs/`, `cronjobshell/`, `postgres/`, `proxy/`, `mail/`, `redis/`, … | Service Docker images, each with a `default.settings` and `docker-compose.yml`                      |
| `templates/customs_template/<version>/`                                   | Project init templates (copied 1:1 by `odoo src init` — files added here ship in every new project) |
| `templates/module_template/`                                              | Module scaffold (used by `odoo src make-module`)                                                    |
| `.patchnotes/`                                                            | Per-branch YAML patchnote files (required by pre-commit + CI)                                       |
| `.github/workflows/`                                                      | `pytest.yml` (unit tests on PR), `bake-test.yml` (heavy E2E)                                        |

## Architecture — what runs where

When a user runs `odoo` on the host, several layers interact:

1. **Host CLI** (pipx-installed `zodoo` from `zodoo/src/`) — Click-based commands. Reads `~/.odoo/settings.<project>` and per-project state in `~/.odoo/run/<project>/`.
2. **`odoo reload`** ([`zodoo/src/zodoo/lib_composer.py`](zodoo/src/zodoo/lib_composer.py)) — merges all enabled service `docker-compose.yml` snippets + `common.docker` fragments into `~/.odoo/run/<project>/docker-compose.yml`. Settings are rendered into per-service `environment:` blocks (containers don't read settings files at runtime — they get env vars).
3. **`odoo build`** — builds the per-project Docker images.
4. **`odoo up -d`** — wraps `docker compose up` with the generated yml. `--no-build` is passed by default, so the image must already exist.
5. **Inside the Odoo container** the entrypoint chain is:
   - `entrypoint.sh` → `entrypoint.py` → `run.py` → eventually `exec_odoo()` in [`odoo/bin/tools.py`](odoo/bin/tools.py)
   - Everything up to `exec_odoo` runs as **root**
   - `exec_odoo` starts the Odoo process via `sudo -E -H -u odoo` (when `ODOO_SUDO_CMD=1`, which is the default)
   - `sudo` strips most env vars unless they are in the `env_keep` whitelist installed by [`odoo/config/common.docker`](odoo/config/common.docker) (`/etc/sudoers.d/zodoo-env-passthrough`). All `default.settings` keys + `DBNAME`, `PROJECT_NAME`, `CUSTOMS_DIR`, `DOCKER_HOST_RUN_DIR`, `ZODOO_*` are whitelisted.
   - If `UPDATE_ON_STARTUP=1`, `run.py` first calls `update_on_startup.py` which runs `odoo update` via the same `sudo_odoo_cmd` helper.

## Common gotchas

- **Settings file vs env vars**: Inside containers the settings file usually isn't present (k8s deployments). `Config.__getattribute__` ([`zodoo/src/zodoo/click_config.py`](zodoo/src/zodoo/click_config.py)) falls back to `os.environ` when no settings file is configured AND the process is in a container.
- **Module-level subprocess calls**: Avoid running `subprocess.run` at import time — the CLI must work inside containers without Docker installed. See `_resolve_docker_compose_bin()` in [`zodoo/src/zodoo/consts.py`](zodoo/src/zodoo/consts.py) for the lazy + cached pattern.
- **`/odoolib/odoo` inside containers** — shell wrapper around the CLI (`exec $ZODOO_PYTHON /opt/zodoo_pipx/venvs/zodoo/bin/odoo "$@"`). Used by entrypoint scripts.
- **`cronjobs` vs `cronjobshell` vs `odoo_cronjobs`**:
  - `cronjobs` — generic cron daemon, only present in compose when `RUN_CRONJOBS=1`
  - `cronjobshell` — sleep-container for interactive debugging (`docker exec`)
  - `odoo_cronjobs` — Odoo's own queuejob/cron worker (different concept)

## Working on this repo

### Prerequisites

- Docker (CLI + daemon, `docker compose` v2 plugin)
- Python 3.10–3.12 (3.13 not supported yet)
- pipx, gimera (`pipx install gimera`)

### Run zodoo from source

```bash
cd zodoo/src
pipx install -e . --force
```

### Tests

The pytest suite lives in `zodoo/src/zodoo/tests/`. Two test categories — fast unit tests by default, opt-in slow E2E tests:

```bash
# Fast unit tests (~0.3s, 94 tests, no Docker needed):
odoo setup zodoo-tests

# Heavy E2E tests (require Docker, ~20-30 min — clones Odoo, builds images):
odoo setup zodoo-tests --slow

# Single test (extra args pass through):
odoo setup zodoo-tests -k cronjob_driven -v -s

# Or directly via pytest (must use the pipx venv's python):
cd zodoo/src
~/.local/pipx/venvs/zodoo/bin/python -m pytest -m "not slow"
```

Slow tests share session-scoped fixtures (`odoo_project_19`, `odoo_project_19_running` in [`zodoo/src/zodoo/tests/conftest.py`](zodoo/src/zodoo/tests/conftest.py)) so the heavy `odoo src init` / `build` happens once per session.

### Build images from scratch (skip the zodoo registry)

```bash
odoo build <name> --no-zodoo-pull
```

### Test image changes locally

Either `rsync -av --exclude='.git' ./ ~/.odoo/images/` or `export ODOO_IMAGES=$(pwd)`.

**Changed a `Dockerfile` or a file it `COPY`s? Run `odoo reload` before `odoo build`.**
`odoo build` builds from the *generated* Dockerfile under
`~/.odoo/run/<project>/Dockerfiles/<service>`, which only `odoo reload`
rewrites. Without the reload the build reports `DONE` from cache and the change
is silently absent from the image - which then shows up much later as a missing
file or a missing binary inside the container.

## Branch / commit / PR workflow

**Always work on a feature branch** — `main` is protected and direct commits are rejected by the release workflow. For every PR:

1. `git checkout -b <type>/<short-name>` (e.g. `fix/sudoers-env-passthrough`, `feat/zodoo-tests-command`)
2. Add a **patchnote** at `.patchnotes/<branch-name>.yml` (the `Check patchnotes exist` pre-commit hook fails the commit otherwise). Format:
   ```yaml
   type: fix # feature | fix | breaking | docs | internal
   description: "Short description of the change"
   breaking: false
   ```
3. Commit (pre-commit will run `black`, `autoflake`, etc. and may reformat — re-stage and re-commit if so).
4. Push + `gh pr create --base main`.

The remote uses **SSH** (`git@github.com:Odoo-Ninjas/zodoo.git`) — pushing workflow file changes via the HTTPS remote is rejected because the OAuth token lacks `workflow` scope.

## Releasing — towncrier

The CLI uses **towncrier** for changelog management. Inside `zodoo/src/`:

- Changelog fragments live in `zodoo/src/changelog.d/`
- Filename format: `<short-description>.<type>.md` — types: `bugfix`, `feature`, `misc`
- **Never edit `zodoo/src/CHANGELOG.md` directly** — towncrier rebuilds it on release
- Build the changelog and bump the version:

  ```bash
  cd zodoo/src
  towncrier build --version <new_version> --yes
  # update setup.cfg + zodoo/version.txt to match
  git add CHANGELOG.md setup.cfg zodoo/version.txt changelog.d/
  git commit -m "release <new_version>"
  git push
  ```

The `.patchnotes/` (repo root) and `changelog.d/` (zodoo CLI) systems are **separate** — patchnotes track repo-level changes per PR, towncrier fragments track CLI changelog entries that ship to end users.

## Deploy

`odoo setup upgrade` on a host runs `git pull` on `~/.odoo/images/` + reinstalls zodoo via pipx. Container images then need a separate `odoo build odoo` per project to pick up changes (running containers stay on the old image until they're restarted).

## Documentation

Full docs: [`docs/`](./docs/README.md). Online at https://docs.zebroo.de/docs/zodoo (not reachable from sandboxed environments — use the local `docs/` folder).
