# Changelog

## 1.2.0


- **Feature**: `odoo build` now auto-builds & pushes the prebuilt Python image (registry/zodoo/python:<ver>-<arch>) on registry miss instead of failing with a cryptic Docker `not found` error.


## 1.1.0


- **Feature**: Add --verify/-v option to `odoo backup odoo-db` to validate the produced dump with `pg_restore -l`
- **Fix**: Default `_backup_pgdump(verify=False)` so the existing pytest suite still runs after the verify-option feature; add positive/negative tests for the --verify pass-through.


## 1.0.2


- **Fix**: Stream docker push output live so users see per-layer registry push progress instead of a silent wait


## 1.0.1


- **Fix**: Install gimera from PyPI in coding container; old GitHub repo Odoo-Ninjas/gimera no longer exists


## 1.0.0


- **Feature**: Pull compiled Python from the zodoo registry (multi-arch) instead of compiling from source in every Odoo build. Adds python_prebuilt/ builder image + build.sh script. Odoo v19 Dockerfile switches its python_builder stage to FROM ${ZODOO_REGISTRY_URL}/zodoo/python:${ODOO_PYTHON_VERSION}-${TARGETARCH}. Cross-arch builds via qemu no longer need to compile Python (which segfaults under qemu-aarch64). Also normalizes the --platform argument (was producing linux/linux/arm64).
- **BREAKING**: Consolidate odoo / odoo_cronjobs / odoo_queuejobs / odoo_update into a single container managed by an internal supervisor. odoo_debug stays as a manual-profile service on the same image. — `odoo restart odoo` now restarts the entire odoo container (web + cronjobs + queuejobs). Use `odoo restart odoo_cronjobs` / `odoo restart odoo_queuejobs` (backwards-compat — they now drive the in-container supervisor) or `docker exec <proj>_odoo /opt/venv/bin/python /odoolib/supervisor.py restart <role>` for per-role restarts. `UPDATE_ON_STARTUP=1` is still honoured and now handled by supervisor.py before any role is spawned. Obsolete settings ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER / ODOO_CRON_IN_ONE_CONTAINER are ignored with a warning — toggle RUN_ODOO_CRONJOBS / RUN_ODOO_QUEUEJOBS / RUN_ODOO_WEB to disable individual roles instead.


## Unreleased

- **Feature**: EXTERNAL_DOMAIN accepts a comma-separated list of URLs (e.g. `http://10.8.99.1,http://127.0.0.1`). `odoo status` prints each URL on its own line (with `:PROXY_PORT`) so they stay cmd+clickable in the terminal.

## 0.19.1

- **Fix**: MANIFEST writer aborts instead of overwriting a populated MANIFEST with a near-empty one (would drop install/addons_paths/server-wide-modules). Protects against accidental truncation seen in the wild.

## 0.19.0

- **Feature**: odoo setup upgrade pins to the latest semver tag by default; release workflow now runs pytest before tagging. Set ZODOO_DEVMODE=1 to keep tracking main on dev hosts.
- **Fix**: CI test steps resolve pipx venv path via `pipx environment --value PIPX_LOCAL_VENVS` instead of hardcoding $HOME/.local/pipx — GitHub's ubuntu-latest runner stores pipx venvs under /opt/pipx.
- **Fix**: CI pytest.yml + release.yml pipx inject step now runs from /tmp so pipx no longer treats the package name 'zodoo' as a path (the repo has a ./zodoo/ directory). Broke silently — pytest.yml had been failing on every push for weeks.

## 0.18.1

- **Fix**: odoo status: omit :PROXY_PORT when EXTERNAL_DOMAIN is a hostname (not an IP)

## 0.18.0

- **Feature**: odoo setup upgrade: early-return when git pull has nothing to fetch — no reinstall, no gimera update, no permission fix

## 0.17.0

- **Feature**: perf: cache bashfind + negative-cache NotInAddonsPath in Module.get_by_name — `odoo reload` ~1.4x faster on projects with many uninstalled modules (bvodin-mig18 17.6s → 12.5s), immune to cold-cache pathologies from per-miss `find .` subprocesses

## 0.16.4

- **Fix**: sudo_odoo_cmd: skip sudo prefix when already running as odoo user — fixes 'odoo is not in the sudoers file' when update_on_startup.py + exec_odoo double-wrap in sudo

## 0.16.3

- **Fix**: prepare_run: chown -R writable dirs so files inside (created by root on first invocation) can be overwritten on re-invocation as the odoo user

## 0.16.2

- **Fix**: prepare_run: chown -R writable dirs so files inside (created by root on first invocation) can be overwritten on re-invocation as the odoo user

## 0.16.1

- **Fix**: fix PermissionError on /etc/odoo/config when update_modules.py runs as odoo user

## 0.16.0

- **Feature**: Print zodoo version at startup in run.py and odoo update

## 0.15.1

- **Fix**: fix PermissionError on /etc/odoo/config when update_modules.py runs as odoo user

## 0.15.0

- **Feature**: postgres: add observability (pg_stat_statements tracking, slow-query log, I/O timing), tune autovacuum, disable JIT, lower max_connections to sane default

## 0.14.4

- **Fix**: E2E test fixtures: start postgres before db reset, remove redundant reload from bake test

## 0.14.3

- **Fix**: bake test symlinks gimera cache into isolated HOME to avoid multi-GB re-clone

## 0.14.2

- **Fix**: Config now falls back to os.environ when no settings file exists (fixes DBNAME lookup in k8s containers that only have ENV vars)

## 0.14.1

- **Fix**: `update_on_startup.py` now runs `odoo update` as the odoo user (via shared `sudo_odoo_cmd` helper), fixing missing DBNAME and root-owned file issues in k8s

## 0.14.0

- **Feature**: `odoo setup zodoo-tests` command to run the unit-test suite (--slow for E2E tests)

## 0.13.3

- **Fix**: graceful fallback when docker CLI is not installed (e.g. inside a Kubernetes container)

## 0.13.2

- **Fix**: sudoers env_keep whitelist in common.docker so ENV vars set for root (k8s pod spec / docker -e) reach the odoo user under `sudo -u odoo`

## 0.13.1

- **Internal**: Release workflow: checkout with RELEASE_PAT secret so the release commit + tag can be pushed past the `main` branch protection (default GITHUB_TOKEN is not in the bypass list)

## 0.13.0

- **Feature**: Add 'backup show-dumps' command to list dumps with size and age (default: newest 5)
- **Feature**: Changelog system with patchnotes, automated versioning and GitHub releases
- **Feature**: Add expanded Claude Code permissions (edit, read, git, tmp) with dynamic home paths
- **Fix**: Remove unused wodoo dependency from cronjobs requirements
- **Fix**: Set http_interface=0.0.0.0 in Odoo configs 15-19 so proxy can reach Odoo inside Docker; also always update outdated modules during odoo update
- **Fix**: Sanitize project name: replace special characters to avoid Docker errors
- **Fix**: Skip registry fallback images with wrong architecture instead of pulling arm64 on amd64 hosts
- **Fix**: Add trailing newline to generated requirements.txt and requirements.txt.all
- **Fix**: Preserve /\_custom/ SCSS attachments (website theme fonts/colors) when running remove-web-assets
- **Feature**: Show changelog since last version after `odoo upgrade`

All notable changes to this project will be documented in this file.

## 0.12.2 — April 2026

### Fixes

- Registry push: skip pushing to the shared zodoo registry when `SRC_EXTRA` is unset/0 (i.e. customer source is baked into the image, e.g. `odoo bake` or default builds that include source) — uploading would publish the customer's code under a tag other customers may pull
- Update at startup: if the stored git SHA is not in the current history (typical for baked images that strip `.git`, or after a rebase/squash), fall back to MANIFEST-mode update with a yellow warning instead of crashing with `subprocess.CalledProcessError`

## 0.12.1 — April 2026

### Fixes

- Import `_is_in_container` in `Config.project_name` setter; fixed `NameError` on `odoo` invocation inside baked containers

### Internal

- Registry: cross-architecture builds run as fully detached subprocess instead of waiting threads, so `odoo bake`/push returns immediately while the other-arch build continues in background (log written to `~/.odoo/log/cross_build_<service>_<arch>.log`)
- Add end-to-end pytest (`pytest -m bake`) and GitHub workflow `bake-test` covering `odoo init` → `reload` → `db reset` → `bake`; runs on PR (relevant paths), `workflow_dispatch` (with version input), and weekly schedule
- Release workflow: target `zodoo/src/setup.cfg` and `zodoo/src/zodoo/version.txt` instead of legacy `wodoo/*` paths (the wodoo→zodoo rename had left the version-bump step writing to a non-existent file, breaking every release since)

## 0.12.0 — April 2026

### Features

- Auto-assign free ports (`odoo next`) during `odoo reload` when DEVMODE is active
- Add `--no-zodoo-push` flag to `odoo build` to skip pushing images to zodoo registry
- Add docs link to zodoo registry setup prompt
- Friendly error message on unauthorized registry push (instead of raw traceback) with hints to configure `ZODOO_REGISTRY_*` settings or use a custom registry

### Fixes

- Fix macOS Docker auth: bypass osxkeychain credential helper in non-interactive sessions (SSH, CI)
- Read DEVMODE from project/user/system settings directly during reload (combined settings file gets deleted)
- Handle unauthorized errors on all push paths (main, arch-specific, background cross-platform)
- Remove leftover `pudb` debugger in zodoo-push command

## 0.11.0 — March 2026

### Features

- Changelog system with patchnotes, automated versioning and GitHub releases
- Zodoo registry: automatic account request when credentials are missing
- `--suppress-other-platform-build` flag to skip QEMU cross-build
- Symmetric cross-build support (ARM <-> AMD64) with buildx
- Integrate gimera as source dependency
- Shared filesystem / common filestore option
- `fix_permissions` command to fix directory ownership via Docker container
- Global file lock for `odoo reload` to prevent concurrent runs
- `backup list` command to show available backup files with age and size
- Slim Docker image builds

### Fixes

- Fix pull of architecture-specific images from zodoo registry
- Fix proxy_exchange dir permissions for nginx worker
- Fix 405 error on registry account request (use HTTPS, explicit POST)
- Fix `odoo console`: export DB vars so `odoo update` works via SSH
- Fix `KeyError` in `list_installed_modules`
- Fix docker build during restore to avoid missing postgres image
- Fix race condition in `start_container` when container name already in use
- Fix `fix_permissions`: fallback to `os.getuid()`, remove debug breakpoint
- Fix requirements newline handling
- Add `@retry` to rsync functions, replace `shutil.copytree` with rsync
- Fix volume removal: call `fix_permissions` on mountpoint when `docker volume rm` fails
- Multiple bugfixes across `lib_src.py`, `module_tools.py`, `lib_control.py`
- Exclude `.pyc` and `__pycache__` from zodoo_src sync in cronjobs

## 0.10.0 — February 2026

### Features

- Global settings switch: user-wide and system-wide settings support
- Settings stored in file (settings_in_file)
- Remove zodoo_src container (faster builds)
- Better warmup strategy
- Delegator configuration support
- Profiles as set
- Improved update strategy

### Fixes

- Fix settings evaluation at reload
- Fix typo in reload
- Fix deb cacher
- Fix directory handling
- Safer uninstall process
- More robust uninstall
- Fix SSH cleanup
- Fix purges

## 0.9.0 — January 2026

### Features

- Odoo 19.0 support (templates, demo data, encryption)
- New wkhtml library for v19
- Sort and order improvements for fields

### Fixes

- Fix robo odoo port configuration
- Fix host directory creation
- Fix postgres config evaluation

## 0.8.0 — December 2025

### Features

- `--enable-queuejobs` flag

### Fixes

- Fix pipx installation in `install.sh`
- Fix entrypoint for Odoo 13
- Odoo 13 compatibility improvements

## 0.7.0

- Initial versioned release
