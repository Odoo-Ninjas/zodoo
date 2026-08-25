Die Datenbanksicherung laeuft jetzt ueber pgBackRest statt barman.

Zu testen unter `odoo pgbackrest`: `backup --type full|diff|incr`, `info` (zeigt
Sicherungen, Groessen und den WAL-Bereich), `check` (prueft, ob die Archivierung
wirklich funktioniert) und `restore` (mit interaktivem Auswahldialog fuer
Zeitpunkt, Alter oder benannten Wiederherstellungspunkt).

Was sich im Betrieb aendert:

* Voreinstellung ist ein **woechentliches Vollbackup mit taeglichen
  Differenzsicherungen**, nicht mehr jede Nacht ein volles. Bei einer 45-GiB-
  Datenbank spart das rund 5 TiB im Jahr.
* Das **Aufraeumen laeuft als letzter Schritt jedes Backups** und kann nicht
  mehr vergessen werden.
* `restore` arbeitet mit `--delta`, holt also nur abweichende Dateien. Dafuer
  gibt es keine automatische Ruecksprungkopie mehr wie beim barman-Weg --
  `--keep-previous` legt sie an, kostet aber eine zweite Vollkopie.
* Mit `PGBACKREST_REPO_HOST` liegt das Repository auf dem Backup-Server; die
  Instanz haelt dann weder Passwort noch Loeschrecht.

Umstellung: `RUN_BARMAN=0`, `RUN_PGBACKREST=1`, `odoo reload && odoo up -d`.
Der barman-Katalog wird nicht uebernommen -- das alte Volume erst wegwerfen,
wenn `odoo pgbackrest check` nach dem ersten Vollbackup sauber durchlaeuft.
