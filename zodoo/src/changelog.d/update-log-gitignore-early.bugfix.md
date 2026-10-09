`odoo update` trägt `/update.log` jetzt in die `.gitignore` ein, bevor die Datei zum ersten Mal geschrieben wird. Bisher kam die Regel erst nach einem erfolgreichen Update dazu (mit `--no-progress` gar nicht) – brach der erste Lauf ab, lag `update.log` ungeschützt im Projekt. Steht schon `update.log` oder `/update.log` drin, bleibt die Datei unverändert.

Zum Prüfen: in einem Projekt ohne Regel `odoo update` starten und gleich abbrechen – `git status` zeigt `update.log` nicht.
