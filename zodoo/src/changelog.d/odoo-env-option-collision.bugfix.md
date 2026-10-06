Odoo 19+: `RUN_ODOO_CRONJOBS=0` stops the cronjobs again. Since 19.0 Odoo
reads every config-file option also from `ODOO_<OPTION>` in the environment,
and the environment beats the config file - the container default
`ODOO_MAX_CRON_THREADS=2` made the web server, the queue job runner and the
debug instance start two cron threads each, ignoring the
`max_cron_threads = 0` zodoo writes into their config files. odoo-bin no
longer gets an `ODOO_<OPTION>` variable whose option is set in the role's
config file, so the config file wins as before Odoo 19. The startup log
names the variables held back and the effective `max_cron_threads`.
