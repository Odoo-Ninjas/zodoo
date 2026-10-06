`odoo reload` now aborts with the traceback and a non-zero exit code when the
odoo image hook (`images/odoo/__after_compose.py`) fails. Before, it printed a
two-line warning, dropped the traceback and finished with exit code 0; the next
`odoo build` produced an image without the project's pip requirements and
without the odoo configuration. Hooks of the other services still only warn,
now with the traceback.
A missing dependency of a module that is only on the MANIFEST `uninstall` list
no longer breaks the dependency resolution; it is skipped with a warning.
Missing dependencies of `install` modules remain an error.
