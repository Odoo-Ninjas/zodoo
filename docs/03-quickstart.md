# Quickstart: New Odoo Project

## From zero to running Odoo

```bash
# 1. Create a new project (interactive: picks Odoo version)
odoo init ~/projects/my-odoo
cd ~/projects/my-odoo

# 2. Generate docker-compose from settings
odoo reload

# 3. Assign a free port
odoo setup next-port

# 4. Start containers (first run builds images — takes a few minutes)
odoo up -d

# 5. Initialize the database
odoo -f db reset

# 6. Open in browser
# http://localhost:<PROXY_PORT>
# Login: admin / admin
```

## From zero with a specific Odoo version

```bash
odoo init ~/projects/my-odoo17 17.0
```

## Clone an existing project and set up locally

```bash
# 1. Clone the project repo
git clone <github-url> ~/projects/my-odoo
cd ~/projects/my-odoo

# 2. If the project uses gimera (for odoo source):
gimera apply

# 3. Apply settings for local dev
odoo setting DEVMODE=1
odoo setting ODOO_DEMO=1

# 4. Reload and build
odoo reload
odoo build

# 5. Option A – fresh database with demo data:
odoo -f db reset

# 5. Option B – restore a customer database:
odoo -f restore odoo-db   # interactive file picker
odoo update               # update all modules

# 6. Start
odoo up -d
```

## Enterprise instance

Setting up an Odoo Enterprise instance needs one extra step between
`odoo init` and the rest of the quickstart flow: pulling in the Enterprise
addons via [gimera](https://github.com/geminicad/gimera) and pointing the
project at them. Requires access to the private
`git@github.com:odoo/enterprise` repo.

Add the enterprise repo to `gimera.yml`:

```yaml
- branch: ${VERSION}
  path: enterprise
  sha: <commit-sha-to-pin>
  type: integrated
  url: git@github.com:odoo/enterprise
```

Add `enterprise` to the project's `MANIFEST` addon paths:

```json
"addons_paths": [
    "odoo/odoo/addons",
    "odoo/addons",
    "enterprise",
    "addons_tools"
]
```

Then apply it and continue with the normal flow from `odoo setup next-port`
onward:

```bash
gimera apply
odoo setup setup-pyenv   # optional: local pyenv for debugging
odoo setup next-port
odoo up -d
odoo -f db reset
```

## Status check

```bash
odoo setup status
```

Shows project name, Odoo version, database connection, URL, and key settings.

## Stop / restart

```bash
odoo down       # stop and remove containers
odoo up -d      # start again

odoo restart    # restart without removing containers
```
