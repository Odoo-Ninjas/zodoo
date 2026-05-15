Consolidated odoo, odoo_cronjobs, odoo_queuejobs and odoo_update into a
single `odoo` container managed by an in-container supervisor
(`/odoolib/supervisor.py`, PID 1). `odoo_debug` stays as a `manual`-profile
service on the same image for ad-hoc debugging.

Breaking: `odoo restart odoo` now restarts the whole container (web +
cronjobs + queuejobs all at once). For per-role restarts use the legacy
aliases `odoo restart odoo_cronjobs` / `odoo restart odoo_queuejobs` —
these now drive the in-container supervisor instead of touching compose.
`UPDATE_ON_STARTUP=1` is still honoured and runs before any role starts.

Deprecated: `ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER` and
`ODOO_CRON_IN_ONE_CONTAINER` are ignored (with a warning) — toggle
`RUN_ODOO_WEB` / `RUN_ODOO_CRONJOBS` / `RUN_ODOO_QUEUEJOBS` instead.
