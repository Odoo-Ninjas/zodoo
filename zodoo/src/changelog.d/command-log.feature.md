`odoo update` und `odoo restart` schreiben jeden Lauf als JSON-Zeile in `.odoo-commands.log` im Projektordner.

Festgehalten werden Startzeit, Dauer, Befehl mit Argumenten, Projekt, ob es im Container lief, Ergebnis (`ok`/`error`/`aborted`), Exit-Code und bei Fehlern nur der Fehlertyp. Umgebung, Settings, Benutzer- und Hostnamen landen nicht im Log; Optionswerte, die nach Passwort/Token/Key aussehen, und Zugangsdaten in URLs werden als `***` geschrieben. Anders als `update.log` wird die Datei nie geleert.

Die Datei ist lokale Laufzeit-Information: zodoo trägt `/.odoo-commands.log` vor dem ersten Schreiben in die `.gitignore` des Projekts ein. Neue Projekte bekommen die Regel – und `/update.log`, das bisher nur in der 17.0-Vorlage stand – direkt aus der Vorlage.

Zum Prüfen: in einem Projekt `odoo restart` ausführen, dann `tail -n 1 .odoo-commands.log` – dort steht der Lauf. `git status` darf die Datei nicht als neu zeigen.
