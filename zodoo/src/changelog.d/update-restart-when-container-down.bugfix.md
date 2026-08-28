`odoo update` no longer leaves an instance switched off. When the whole
compose project was taken down before the update (cicd devmode does a
brutal kill) and the update then exited early ("No module update
required"), every role start ran `docker exec` against a dead container,
the fallback reached for the long-gone `odoo_web` / `odoo_queuejobs` /
`odoo_cronjobs` compose services, and the update still reported
"completed successfully" — the instance stayed on HTTP 502 until someone
noticed (5 h on a staging instance). If the container is gone, the real
`odoo` service is started instead; its supervisor spawns web, queuejobs
and cronjobs by itself.
Postgres is started first (nothing declares `depends_on: postgres`, so
the odoo container would otherwise wait for a database that never comes),
and if the container cannot be started the update says so loudly instead
of reporting success.
