# Local Odoo Development Setup on macOS

## Prerequisites

- Docker Desktop for Mac (installed and running)
- Homebrew
- Access to the Odoo project repository

## 1. Install zodoo

```bash
brew install git pipx rsync
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
```

By default this uses the Python that ships with Xcode. If your Odoo version
needs a newer Python (recommended for newer releases that drop 3.9 support),
reinstall pointing at a `pyenv`-managed interpreter instead:

```bash
pipx reinstall wodoo --python ~/.pyenv/versions/3.12.13/bin/python3
```

## 2. Clone the project repository

```bash
git clone <github-url> ~/projects/my-odoo
cd ~/projects/my-odoo
```

## 3. Configure for local development

```bash
odoo setting DEVMODE=1       # disables mail/cronjobs on restore, resets passwords
odoo setting ODOO_DEMO=1     # load demo data (optional)
odoo reload
odoo build
```

## 4. Initialize or restore database

**Fresh database with demo data:**

```bash
odoo -f db reset
```

**Restore a customer database:**

```bash
odoo -f restore odoo-db   # interactive file picker
odoo update               # update all modules after restore
```

## 5. Start

```bash
odoo up -d
odoo setup status         # shows URL and port
```

Open: `http://localhost:<PROXY_PORT>`

---

## Applying code changes

Whenever you modify module code (Python, XML views, security rules, data
files), the running Odoo instance won't reflect those changes until the
modules are reloaded into the database:

```bash
odoo update
# Installs/updates the modules listed under `install` in the project MANIFEST.
```

The module you're working on must be listed under `install` in the project's
`MANIFEST` — otherwise `odoo update` skips it and your changes won't show up.

Tips:

- `odoo update <module_name>` updates a single module faster than a full update.
- Pure Python changes are often picked up live by running in dev mode
  (`odoo dev`, which combines build + up + watch) without a full update, but
  **structural** changes (models, fields, views, security, data) always need
  `odoo update`.
- If a change still doesn't show up, hard-refresh the browser
  (⌘ + Shift + R) to bypass Odoo's asset cache.

---

## macOS-specific settings

On macOS, the postgres port is exposed on the host so you can connect from tools like TablePlus:

```bash
odoo setup next-port      # also sets HOST_DB_PORT
```

Connect to postgres:

- Host: `localhost`
- Port: `<HOST_DB_PORT>`
- User/DB: from `odoo setup status`

---

## Troubleshooting on macOS

### rsync errors

```bash
brew install rsync
```

### Python version issues

```bash
odoo setting ODOO_PYTHON_VERSION=3.12
odoo reload && odoo build
```

### Previous wodoo installation

If you had wodoo installed before:

```bash
rm -Rf ~/.odoo/images
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
```

### Port already in use

```bash
odoo setup next-port
odoo reload
odoo up -d
```

### Broken CSS/JS after update

```bash
odoo setup remove-web-assets
# then log in as admin to regenerate assets
```

### Docker Desktop not responding

Restart Docker Desktop. Then:

```bash
odoo down
odoo up -d
```
