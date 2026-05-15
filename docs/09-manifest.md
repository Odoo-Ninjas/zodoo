# MANIFEST File

The `MANIFEST` file lives at the **project root** and controls which Odoo modules are installed and which addon paths are active. It is a Python dict literal (not JSON — comments and trailing commas are allowed).

## Example

```python
{
    "version": 17.0,

    # Modules loaded server-wide (available without database)
    "server-wide-modules": ["web"],

    # Python version for the Odoo container
    "python_version": "3.12",

    # Modules to install
    "install": [
        "sale",
        "purchase",
        "account",
        "stock",
        "my_custom_module",
    ],

    # Modules to uninstall (if present)
    "uninstall": [
        "web_tree_many2one_clickable",
    ],

    # Modules to uninstall only in DEVMODE
    "devmode_uninstall": [
        "password_security",
    ],

    # Modules to run tests for
    "tests": ["my_custom_module"],

    # Run these update steps before the main update
    "before-odoo-update": [
        ["update", "base"],
    ],

    # Where Odoo looks for modules
    "addons_paths": [
        "odoo/odoo/addons",
        "odoo/addons",
        "enterprise",          # Odoo Enterprise (if available)
        "addons_tools",        # zodoo helper modules
        # "addons_OCA/sale-workflow",
        # "addons_OCA/account-invoicing",
    ],
}
```

## Fields

| Field                 | Description                                                 |
| --------------------- | ----------------------------------------------------------- |
| `version`             | Odoo version as float: `17.0`, `16.0`, etc.                 |
| `server-wide-modules` | Loaded without a database. Always include `"web"`.          |
| `python_version`      | Python version for the Odoo Docker image.                   |
| `install`             | Modules to install/keep installed.                          |
| `uninstall`           | Modules to force-uninstall.                                 |
| `devmode_uninstall`   | Modules to uninstall when `DEVMODE=1`.                      |
| `tests`               | Modules to run tests for (used by `odoo module run-tests`). |
| `before-odoo-update`  | Module update steps to run before main update.              |
| `addons_paths`        | Directories where Odoo searches for modules. Order matters. |
| `odoo_dir`            | Where the Odoo source is cloned (default: `odoo`).          |
| `upgrade_path`        | Path to upgrade-utils for OpenUpgrade migrations.           |

## OCA addons

OCA modules are managed via gimera. Add the desired OCA repo to `addons_paths` (uncomment in template), then run:

```bash
gimera apply
odoo reload
```
