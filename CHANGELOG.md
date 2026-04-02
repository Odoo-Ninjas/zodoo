# Changelog

All notable changes to this project will be documented in this file.

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
- Exclude `.pyc` and `__pycache__` from wodoo_src sync in cronjobs

## 0.10.0 — February 2026

### Features

- Global settings switch: user-wide and system-wide settings support
- Settings stored in file (settings_in_file)
- Remove wodoo_src container (faster builds)
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
