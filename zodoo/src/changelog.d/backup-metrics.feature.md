Neuer Befehl `odoo backup-metrics`: schreibt Kennzahlen zur Sicherung fuer den textfile-Collector des node_exporter, damit ein Ausfall der Sicherung in der Ueberwachung auffaellt. Laeuft alle fuenf Minuten aus den Cronjobs (`CRONJOB_BACKUP_METRICS`), der node_exporter bekommt dafuer `--collector.textfile.directory`.

Warum: eine Instanz, deren Sicherung nicht laeuft, sieht von aussen aus wie jede andere -- sie antwortet, die Kurven sind gruen, und der Unterschied faellt genau einmal auf: an dem Tag, an dem jemand wiederherstellen will.

Ausgegeben werden `zodoo_backup_enabled{art}`, `zodoo_backup_query_success{art}`, `zodoo_backup_count{art}`, `zodoo_backup_last_success_timestamp_seconds{art}` und `zodoo_backup_last_full_timestamp_seconds{art}`.

Bewusst wird der ZEITPUNKT ausgegeben und nicht das Alter: das Alter bildet man mit `time() - <wert>`, und so altert es auch dann weiter, wenn der Schreiber selbst nicht mehr laeuft. Eine vorberechnete Alterszahl stuende in dem Fall fuer immer still auf ihrem letzten Wert und saehe gesund aus. Dagegen steht ausserdem `zodoo_backup_metrics_written_timestamp_seconds` -- altert der, ist alles andere in der Datei nur noch Erinnerung.

Gibt es gar keine Sicherung, fehlt die Zeitpunkt-Zeile, statt auf 0 zu stehen: eine 0 hiesse "1970 gesichert" und liesse sich von einer echten alten Sicherung nicht unterscheiden. In PromQL greift dafuer `absent()`.

Fuer offsite steht nur `zodoo_backup_enabled{art="offsite"}` drin. Einen Zeitpunkt gibt es dort nicht -- `offsite list` liefert Text fuers Auge, und die Zustandsdatei ist leer. Eine Null waere schlimmer als die Luecke: sie saehe aus wie eine Messung.

Zum Testen: `odoo backup-metrics --stdout` zeigt, was die Ueberwachung ueber diese Instanz erfaehrt, ohne etwas zu schreiben. Danach im Grafana der Instanz `time() - zodoo_backup_last_success_timestamp_seconds` abfragen.
