`odoo pgbackrest verify` prüft jetzt auch, wie alt die zurückgespielte Sicherung ist. Bisher bestand die Rückspielprobe, sobald sich die jüngste Sicherung zurückspielen und lesen ließ – egal, ob sie von heute oder von letzter Woche war. Am 08.10.2026 ist so ein Bereich mit dem Stand vom Vortag als „passed“ durchgegangen.

Jetzt fällt die Probe durch, wenn die Sicherung mehr als 36 h vor dem Probelauf geendet hat (Fehlertext „… ist zu alt: N h“). Die Prüfung läuft vor dem Zurückspielen, eine zu alte Sicherung kostet also keine Restore-Zeit. Im Nachweis stehen zusätzlich `backup_stop` und `backup_age`.

Auf dem Prüfstand lässt sich die Schwelle je Bereich in der Konfiguration setzen: `"stanzas": {"<bereich>": {"max_backup_age": <sekunden>}}`.

Zum Testen: auf dem Prüfstand `odoo pgbackrest verify --bench-config /etc/pgbr-bench/config.json --stanza <bereich> --json` – im Ergebnis stehen `backup_age` und `backup_stop`. Mit `"max_backup_age": 60` für diesen Bereich muss die Probe mit „zu alt“ durchfallen.
