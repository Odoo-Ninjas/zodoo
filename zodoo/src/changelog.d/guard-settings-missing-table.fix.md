Guard `dev-env update-setting` and `dev-env remove-settings` against a
missing `ir_config_parameter` table. When restore finalization runs
against an instance postgres whose `odoo` DB has not been populated
yet, both commands now log a yellow warning and return instead of
raising `psycopg2.errors.UndefinedTable`.
