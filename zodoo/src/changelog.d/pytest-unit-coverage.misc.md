Added pytest unit-test coverage for `lib_control`, `lib_backup` and
`lib_docker_registry` (94 new tests, combined ~67% line coverage).
Heavy end-to-end tests are marked `@slow`, share a session-scoped
`odoo_project_19` fixture (which symlinks the host's
`~/.odoo/images` into the test HOME so `odoo src init` finds its
templates), and are opt-in via `pytest -m slow` or
`ZODOO_RUN_SLOW=1`. The bake-flow E2E test no longer needs the custom
`bake` marker and now runs via the same `@slow` mechanism.
