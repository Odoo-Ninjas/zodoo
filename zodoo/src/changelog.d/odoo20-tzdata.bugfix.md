Odoo 20: Das Image bringt jetzt die Zeitzonendaten des Systems mit.

Ab 20.0 baut Odoo die Zeitzonenauswahl aus `zoneinfo.available_timezones()`
statt aus `pytz`. Odoos `requirements.txt` zieht das pip-Paket `tzdata` nur
unter Windows und setzt sonst `/usr/share/zoneinfo` vom Betriebssystem voraus.
Unser Image nutzt ein vorgebautes Python auf einem nackten Ubuntu, dort fehlte
das Paket. Die Liste war leer, die Demodaten von `base` scheiterten an der
ersten Zeitzone, und weil Odoo Demodaten nur lädt, wenn alle Abhängigkeiten
welche haben, bekam kein Modul mehr Demodaten. Auch im Benutzerformular ließ
sich keine Zeitzone wählen.

`tzdata` steht jetzt in der Paketliste von `odoo/config/20/Dockerfile` und
`Dockerfile.base`. Nach `odoo reload` und `odoo build odoo` neu angelegte
Datenbanken haben wieder Demodaten; bestehende müssen dafür neu angelegt
werden.
