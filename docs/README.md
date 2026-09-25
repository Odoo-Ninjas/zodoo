# zodoo Documentation

| Doc                                                    | Description                                         |
| ------------------------------------------------------ | --------------------------------------------------- |
| [01-overview.md](01-overview.md)                     | What zodoo is, architecture, containers             |
| [02-installation.md](02-installation.md)             | Installing zodoo, upgrade, shell completion         |
| [03-quickstart.md](03-quickstart.md)                 | From zero to running Odoo in minutes                |
| [04-command-reference.md](06-command-reference.md)   | All `odoo` commands with options                    |
| [05-debug-mode.md](10-debug-mode.md)                 | Debug on production without affecting users         |
| [06-registry.md](09-registry.md)                     | Push/pull Docker images via registry                |
| [07-mac-setup.md](04-mac-setup.md)                   | macOS-specific setup guide                          |
| [08-settings-reference.md](07-settings-reference.md) | All settings explained                              |
| [09-manifest.md](08-manifest.md)                     | MANIFEST file format and fields                     |
| [10-troubleshooting.md](17-troubleshooting.md)       | Common problems and solutions                       |
| [11-offsite-backup.md](15-offsite-backup.md)         | Encrypted offsite backup with restic                |
| [12-pgbackrest.md](16-pgbackrest.md)                 | Database backup + point-in-time recovery            |
| [13-web-router.md](13-web-router.md)                 | nginx reverse proxy, vhosts.yml, vhost wizard       |
| [14-benchmarking.md](12-benchmarking.md)             | Finding slow fields with `odoo benchmark`           |
| [15-windows-wsl-setup.md](05-windows-wsl-setup.md)   | Windows (WSL2) setup guide                          |
| [16-robot-tests.md](11-robot-tests.md)               | Writing and running Robot Framework tests           |
| [17-filestore.md](14-filestore.md)                   | Shared attachment filestore, hardlinks vs. symlinks |

These files are the source of truth. (The former online copy at
docs.zebroo.de is gone; internal documentation now lives in Odoo Knowledge.)

## Editing

This `docs/` folder is the source of truth — edit the Markdown here. Images and
other media belong in `docs/img/`, referenced relatively (`![alt](./img/foo.png)`).
