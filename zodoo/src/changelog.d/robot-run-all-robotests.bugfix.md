`odoo robot run-all` now honours the MANIFEST key `robotests`. With glob
patterns there (relative to the project root, e.g.
`"robotests": ["addons/*/tests/robot/*.robot"]`) only the matching suites
run; `--list` shows the selection. Before, the key was never read and
run-all started every `.robot` file of the project, including the self
tests of vendored robot libraries and suites of foreign repos. Projects
without the key behave as before; `odoo robot run <file>` still runs any
single file.
