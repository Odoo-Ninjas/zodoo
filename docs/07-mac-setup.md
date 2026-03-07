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

## 2. Clone the project repository

```bash
git clone <github-url> ~/projects/my-odoo
cd ~/projects/my-odoo
```

## 3. Configure for local development

```bash
odoo setting DEVMODE 1       # disables mail/cronjobs on restore, resets passwords
odoo setting ODOO_DEMO 1     # load demo data (optional)
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
odoo setting ODOO_PYTHON_VERSION 3.12
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
