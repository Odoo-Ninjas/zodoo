# Local Odoo Development Setup on Windows

Because zodoo relies on Docker, bash, `rsync`, and Unix-style symlinks, the
recommended (and supported) way to run it on Windows is **inside WSL2
(Windows Subsystem for Linux)**. Native PowerShell / CMD setups are not
supported.

## Prerequisites

- Windows 10 (build 19041+) or Windows 11.
- Access to the Odoo repository you want to work with.
- **WSL2 with Ubuntu** installed — provides the Linux environment zodoo needs.
- **Docker Desktop for Windows** with WSL2 integration enabled — runs the Odoo
  and Postgres containers. See the
  [Docker Desktop installation guide](https://docs.docker.com/desktop/setup/install/windows-install/).
- **Windows Terminal** (recommended) — a clean tabbed terminal that integrates
  with WSL.

> **Work from inside WSL, not from `C:\`.** Keep your project repositories
> under your WSL home directory (e.g. `~/projects`), not under `/mnt/c/...`.
> Cross-filesystem access through `/mnt/c` is dramatically slower and breaks
> zodoo's file-watching and `rsync` flows.

## 1. Install WSL2 and Ubuntu

Open PowerShell **as Administrator** and run:

```powershell
wsl --install -d Ubuntu
# Installs WSL2 with the Ubuntu distribution as the default Linux environment.
# After install you'll be asked to reboot, then to create a Linux username and password.
```

Verify WSL2 is the active version:

```powershell
wsl --set-default-version 2
# Ensures any future distribution uses WSL2 (not the legacy WSL1), which Docker Desktop requires.

wsl -l -v
# Lists installed distributions and their WSL version. Ubuntu should show VERSION 2.
```

From this point on, every command in this guide runs inside the **Ubuntu
(WSL) terminal**, not PowerShell.

## 2. Install Docker Desktop & enable WSL Integration

1. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
2. Open Docker Desktop → **Settings → General** → enable **"Use the WSL 2 based engine"**.
3. Go to **Settings → Resources → WSL Integration** → enable integration with your **Ubuntu** distro.
4. Apply & restart Docker Desktop.

Verify Docker works from inside WSL:

```bash
docker version
# Should show both Client and Server versions without errors.
# "Cannot connect to the Docker daemon" means the WSL Integration toggle needs re-checking.
```

## 3. Install system dependencies inside WSL

```bash
sudo apt update && sudo apt upgrade -y

sudo apt install -y git curl rsync pipx build-essential
# git    -> to clone the Odoo repository
# curl   -> used by the zodoo installer
# rsync  -> required by zodoo to sync source folders into the Odoo container
# pipx   -> isolates the zodoo Python CLI
# build-essential -> compilers needed by some Python wheels

pipx ensurepath
# Adds ~/.local/bin to PATH so the `odoo` command is found after install.
# Close and reopen the terminal afterwards.
```

*(Optional but recommended)* install **pyenv** to manage Python versions,
since newer Odoo releases require Python >= 3.10:

```bash
curl https://pyenv.run | bash
# Installs pyenv. Follow the on-screen instructions to add it to your shell rc file.

pyenv install 3.12.13
```

## 4. Clone the Odoo repository

Inside WSL, under your Linux home (e.g. `~/projects`):

```bash
mkdir -p ~/projects && cd ~/projects
git clone <github url>
# The cloned folder becomes your project directory — every `odoo ...` command
# below must be run from inside it.
```

> **Line endings.** If the repo contains Windows-style CRLF line endings,
> configure git inside WSL to keep LF:
>
> ```bash
> git config --global core.autocrlf input
> ```

## 5. Install zodoo

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
# Registers the global `odoo` CLI via pipx, using the system Python provided by Ubuntu.
```

To pin zodoo to a specific Python version (recommended for newer Odoo
releases that drop 3.9 support), reinstall it pointing at a
`pyenv`-managed interpreter:

```bash
pipx reinstall wodoo --python ~/.pyenv/versions/3.12.13/bin/python3
```

## 6. Configure and start the project

```bash
odoo setting DEVMODE 1 -s
# Enables development mode system-wide (-s) across every zodoo project on this machine.

odoo setting ODOO_DEMO 1
# Loads Odoo's demo data when the database is initialised.

odoo reload   # regenerate docker-compose + settings from the manifest
odoo build    # build the Docker images (first run can take several minutes)
odoo up -d    # start Odoo, Postgres and side services in the background
```

Reset the database for a clean dev slate:

```bash
odoo -f db reset
```

Or restore a customer dump:

```bash
odoo -f restore odoo-db <dump-path>
```

## Applying code changes

Whenever you modify module code (Python, XML views, security rules, data
files), the running instance won't reflect the change until the module is
reloaded into the database:

```bash
odoo update
# Installs/updates every module listed under `install` in the project MANIFEST.
```

The module must be listed under `install` in the project's `MANIFEST` —
otherwise `odoo update` skips it.

Tips:

- `odoo update <module_name>` updates a single module faster than a full update.
- Pure Python changes are often picked up live by `odoo dev` (build + up +
  watch) without a full update; **structural** changes (models, fields,
  views, security, data) always need `odoo update`.
- If a change still doesn't show up, hard-refresh the browser
  (**Ctrl + Shift + R**) to bypass Odoo's asset cache.

## Troubleshooting

### Leftover Wodoo installation

```bash
rm -Rf ~/.odoo/images
# Removes zodoo's local image/source cache so the next `odoo` command downloads a fresh copy.
```

### `rsync` errors

If you see `AttributeError: 'NoneType' object has no attribute 'groups'`
(from `rsync_progress_param`), install rsync inside WSL:

```bash
sudo apt install -y rsync
```

### Cannot connect to the Docker daemon

Docker Desktop → **Settings → Resources → WSL Integration** → confirm Ubuntu
integration is enabled, then restart Docker Desktop.

### Files not updating / changes ignored

Make sure your project lives under `~/...` (the WSL filesystem), not
`/mnt/c/...` — projects on the Windows drive suffer broken file-watching and
slow I/O.

### Line ending issues (CRLF)

If Odoo or Python complains about syntax errors right after cloning:

```bash
sudo apt install -y dos2unix
find . -type f \( -name "*.py" -o -name "*.xml" -o -name "*.csv" \) -exec dos2unix {} \;
```

For other issues (port conflicts, broken CSS/JS, Python version mismatches),
see the shared [Troubleshooting guide](./10-troubleshooting.md).

## Recap

After any change, the typical loop (always from your WSL terminal) is:

1. `odoo reload` — regenerate compose/settings.
2. `odoo build` — rebuild images if Dockerfiles or dependencies changed.
3. `odoo up -d` — (re)start containers.
4. `odoo update` — apply module changes.
5. `odoo status` — check the running URL and credentials.
