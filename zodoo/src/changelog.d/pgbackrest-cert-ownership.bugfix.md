pgBackRest mit Repo-Host lief nach der Anmeldung nicht: `pgbackrest check` brach mit Fehler 42 ab ("key file '/etc/pgbackrest/cert/client.key' must be owned by the 'pgbackrest' user or root") und das WAL-Archiv lief in den Zeitueberlauf. `odoo pgbackrest register` meldete dabei Erfolg -- die Sicherung waere in der Nacht still ausgefallen, und genau das faellt sonst erst am Tag der Wiederherstellung auf.

Ursache: die Zertifikate schreibt `register` als Betriebsbenutzer. Der darf den Besitz nicht auf den pgbackrest-Benutzer (uid 999) vergeben -- das kann nur root. Eine Kopie hilft nicht: der Schluessel ist 0600 und gehoert dem Betriebsbenutzer, ein Prozess als 999 kann ihn nicht einmal lesen.

Der entrypoint des pgbackrest-Containers laeuft als root und schreibt den Besitz jetzt um. Dafuer ist der Mount von `/etc/pgbackrest` nicht mehr `:ro`. Damit eine erneute Anmeldung die Dateien noch ersetzen kann, obwohl sie ihr dann nicht mehr gehoeren, loescht `register` sie vorher statt sie zu ueberschreiben.

Zum Testen: `odoo pgbackrest register`, dann `odoo reload && odoo up -d && odoo pgbackrest check` -- muss "completed successfully" melden. Danach `odoo pgbackrest backup --type full` und `odoo pgbackrest info`: dort muessen `cipher: aes-256-cbc` und eine Sicherung unter `repo1` stehen.
