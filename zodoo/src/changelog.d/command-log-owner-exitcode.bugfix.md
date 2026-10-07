`.odoo-commands.log`: `exit_code` ist jetzt der Wert, den die Shell sieht (`$?`) – ein `sys.exit(-1)` steht als `255` im Log statt `-1`.

Legt zodoo dabei (oder beim Schreiben von `update.log`) die `.gitignore` des Projekts erst an – etwa als root im Container –, gehört sie anschließend dem Projektbenutzer (`OWNER_UID`), wie die Logdateien selbst. Eine schon vorhandene `.gitignore` behält ihren Besitzer.
