# zodoo

zodoo runs Odoo in Docker. It gives you a single `odoo` command that creates a
project, builds the containers, manages the database, and starts and stops the
instance — on a laptop, on a server, and in CI, from the same configuration.

## Where to go next

| If you want to… | Read |
| --- | --- |
| Install zodoo and get Odoo running | [Getting Started](020-getting-started.md) |
| Understand what zodoo is and how it fits together | [Overview](010-overview.md) |
| See the installation details and upgrade path | [Installation](030-installation.md) |
| Set up on macOS | [Mac Setup](040-mac-setup.md) |
| Set up on Windows (WSL2) | [Windows/WSL Setup](050-windows-wsl-setup.md) |

New to zodoo? Start with [Getting Started](020-getting-started.md) — it takes you
from nothing installed to Odoo open in a browser.

## Reference

| Topic | Page |
| --- | --- |
| Every `odoo` command and its options | [Command Reference](060-command-reference.md) |
| Every setting explained | [Settings Reference](070-settings-reference.md) |
| The `MANIFEST` file format | [Manifest](080-manifest.md) |
| Pushing and pulling images via a registry | [Registry](090-registry.md) |
| Debugging on production without affecting users | [Debug Mode](100-debug-mode.md) |
| Writing and running Robot Framework tests | [Robot Tests](110-robot-tests.md) |
| Finding slow fields with `odoo benchmark` | [Benchmarking](120-benchmarking.md) |
| The nginx reverse proxy and `vhosts.yml` | [Web Router](130-web-router.md) |
| The shared attachment filestore | [Filestore](140-filestore.md) |
| Encrypted offsite backups with restic | [Offsite Backup](150-offsite-backup.md) |
| Database backup and point-in-time recovery | [pgBackRest](160-pgbackrest.md) |
| Common problems and their fixes | [Troubleshooting](170-troubleshooting.md) |

## Related tools

| Tool | Role |
| --- | --- |
| [gimera](/docs/gimera) | Assembles the Odoo source tree a zodoo project runs |
| [zCICD](/docs/zCICD) | Tests and releases changes before they reach an instance |
| zCloud | Provisions hosted machines that run Odoo this same way (documentation not published yet) |
| [zSYNC](/docs/zSYNC) | Integration pipelines running inside Odoo |
