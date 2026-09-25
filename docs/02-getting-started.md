# Getting Started

This page takes you from nothing installed to Odoo open in a browser, and
explains what each step is doing so the commands are not just incantations.

For what zodoo is and how the pieces fit together, read
[Overview](01-overview.md) first. For installation detail, upgrades and shell
completion, see [Installation](03-installation.md).

## Before you start

- **Docker** — Docker Desktop on macOS, Docker Engine on Linux
- **git**
- **Python 3.10–3.14**
- **pipx**

On macOS:

```bash
brew install git pipx rsync
brew install --cask docker
```

On Ubuntu/Debian:

```bash
sudo apt-get install git pipx rsync docker.io docker-buildx docker-compose-v2
```

Do not skip `docker-buildx` on Ubuntu. Docker 29 enables BuildKit by default but
the `docker.io` package does not pull buildx in, and the resulting failure is
misleading — `odoo build` aborts, and the next command tries to pull a base
image that was never built, reporting `pull access denied` instead of the real
cause.

macOS and Windows have extra setup worth reading before you begin:
[Mac Setup](04-mac-setup.md), [Windows/WSL Setup](05-windows-wsl-setup.md).

## Install zodoo

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
```

This installs the `odoo` command through pipx and clones the zodoo images to
`~/.odoo/images`. Check it worked:

```bash
odoo --help
```

## A new project, from zero

```bash
odoo init ~/projects/my-odoo
cd ~/projects/my-odoo
```

`init` is interactive and asks which Odoo version you want. To skip the question,
name the version:

```bash
odoo init ~/projects/my-odoo17 17.0
```

Then, from inside the project directory:

```bash
odoo reload           # generate docker-compose from the project settings
odoo setup next-port  # claim a free port, so several projects can coexist
odoo up -d            # start the containers
odoo -f db reset      # create and initialise the database
```

What each one does:

- **`reload`** turns the project's settings and `MANIFEST` into a
  `docker-compose` configuration. Run it again whenever you change a setting or
  add a module — most "my change had no effect" moments are a missing `reload`.
- **`setup next-port`** assigns this project a free port. It is what lets you run
  several Odoo projects on one machine without them fighting over 8069.
- **`up -d`** starts the containers in the background. The first run builds the
  images and takes several minutes; later runs are quick.
- **`db reset`** drops and recreates the database. `-f` skips the confirmation
  prompt — which also means it will destroy an existing database without asking,
  so be careful once a project holds data you care about.

Find the URL:

```bash
odoo setup status
```

This prints the project name, Odoo version, database connection, URL and the
main settings. Open the URL and log in with **admin / admin**.

## An existing project

More often you are joining a project that already exists.

```bash
git clone <github-url> ~/projects/my-odoo
cd ~/projects/my-odoo
```

If the project uses [gimera](/docs/gimera) to assemble its Odoo source — most
Zebroo projects do — fetch that before anything else. The checkout on its own
does not contain Odoo:

```bash
gimera apply -r
```

Turn on the development conveniences:

```bash
odoo setting DEVMODE=1
odoo setting ODOO_DEMO=1
odoo reload
odoo build
```

Then pick a database. Either a fresh one with demo data:

```bash
odoo -f db reset
```

…or a copy of a real customer database:

```bash
odoo -f restore odoo-db   # opens an interactive file picker
odoo update               # bring all modules up to the code you just checked out
```

`odoo update` after a restore is not optional. A dump from production was made
against whatever code production runs; without an update, modules whose code has
moved on will misbehave in ways that are tedious to diagnose.

Start it:

```bash
odoo up -d
```

## Odoo Enterprise

Enterprise addons are not public. You need access to
`git@github.com:odoo/enterprise`, and one extra step between `odoo init` and the
rest of the flow.

Add the repository to `gimera.yml`:

```yaml
- branch: ${VERSION}
  path: enterprise
  sha: <commit-sha-to-pin>
  type: integrated
  url: git@github.com:odoo/enterprise
```

Add `enterprise` to the `addons_paths` in the project's `MANIFEST`:

```json
"addons_paths": [
    "odoo/odoo/addons",
    "odoo/addons",
    "enterprise",
    "addons_tools"
]
```

Then pull it in and carry on with the normal flow:

```bash
gimera apply
odoo setup setup-pyenv   # optional: a local pyenv, for step debugging
odoo setup next-port
odoo up -d
odoo -f db reset
```

## Everyday commands

| You want to | Command |
| --- | --- |
| Start the instance | `odoo up -d` |
| Stop it and remove the containers | `odoo down` |
| Restart without removing containers | `odoo restart` |
| See the URL, version and settings | `odoo setup status` |
| Rebuild after changing settings or modules | `odoo reload && odoo build` |
| Update modules after pulling code | `odoo update` |
| Run in the foreground, for debugging | `odoo dev` |

The full set is in the [Command Reference](06-command-reference.md).

## When it goes wrong

**`odoo build` fails on Ubuntu with a BuildKit error, or a later command reports
`pull access denied`.** `docker-buildx` is missing — see
[Before you start](#before-you-start).

**A code or settings change has no effect.** Run `odoo reload`, then `odoo build`
if you changed anything the image contains.

**Permission denied writing `update.log`.**

```bash
sudo chmod u+rwx update.log
```

**Two projects fight over a port.** Each project needs its own:
`odoo setup next-port`.

**Odoo starts but modules behave oddly after a restore.** Run `odoo update`.

More in [Troubleshooting](17-troubleshooting.md).

## Next

- [Command Reference](06-command-reference.md) — every command and option
- [Settings Reference](07-settings-reference.md) — every setting explained
- [Manifest](08-manifest.md) — the `MANIFEST` format, including `addons_paths`
- [Debug Mode](10-debug-mode.md) — stepping through Python code
