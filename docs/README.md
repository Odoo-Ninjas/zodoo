# zodoo

zodoo runs Odoo in Docker. It gives you a single `odoo` command that creates a
project, builds the containers, manages the database, and starts and stops the
instance — on a laptop, on a server, and in CI, from the same configuration.

## Where to go next

| If you want to… | Read |
| --- | --- |
| Install zodoo and get Odoo running | [Getting Started](02-getting-started.md) |
| Understand what zodoo is and how it fits together | [Overview](01-overview.md) |
| See the installation details and upgrade path | [Installation](03-installation.md) |
| Set up on macOS | [Mac Setup](04-mac-setup.md) |
| Set up on Windows (WSL2) | [Windows/WSL Setup](05-windows-wsl-setup.md) |

New to zodoo? Start with [Getting Started](02-getting-started.md) — it takes you
from nothing installed to Odoo open in a browser.

## Reference

| Topic | Page |
| --- | --- |
| Every `odoo` command and its options | [Command Reference](06-command-reference.md) |
| Every setting explained | [Settings Reference](07-settings-reference.md) |
| The `MANIFEST` file format | [Manifest](08-manifest.md) |
| Pushing and pulling images via a registry | [Registry](09-registry.md) |
| Debugging on production without affecting users | [Debug Mode](10-debug-mode.md) |
| Writing and running Robot Framework tests | [Robot Tests](11-robot-tests.md) |
| Finding slow fields with `odoo benchmark` | [Benchmarking](12-benchmarking.md) |
| The nginx reverse proxy and `vhosts.yml` | [Web Router](13-web-router.md) |
| The shared attachment filestore | [Filestore](14-filestore.md) |
| Encrypted offsite backups with restic | [Offsite Backup](15-offsite-backup.md) |
| Database backup and point-in-time recovery | [pgBackRest](16-pgbackrest.md) |
| Common problems and their fixes | [Troubleshooting](17-troubleshooting.md) |

## Related tools

| Tool | Role |
| --- | --- |
| [gimera](/docs/gimera) | Assembles the Odoo source tree a zodoo project runs |
| [zCICD](/docs/zCICD) | Tests and releases changes before they reach an instance |
| [zCloud](/docs/zCloud) | Provisions hosted machines that run Odoo this same way |
| [zSYNC](/docs/zSYNC) | Integration pipelines running inside Odoo |

## Editing

This `docs/` folder is the source of truth — edit the Markdown here. Images and
other media belong in `docs/img/`, referenced relatively
(`![alt](./img/foo.png)`). The numeric filename prefixes set the order pages
appear in on the documentation site and are stripped from the published URLs, so
renumbering a page does not change its address.
