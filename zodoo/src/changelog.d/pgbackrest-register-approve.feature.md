`odoo pgbackrest register --approve` gibt die eigene Anfrage gleich auf der Konsole frei, gegen ein Anmeldegeheimnis, das nur wir kennen. Damit ist eine Instanz in einem Zug angebunden, statt zu warten, bis jemand die Freigabemaske im VPN oeffnet.

Zum Ausprobieren: `odoo pgbackrest register --approve` aufrufen, bei "Enrolment secret (Zebroo)" das Geheimnis eingeben (Eingabe bleibt unsichtbar). Kennt hosting.zebroo.de die Maschine, meldet der Befehl "Approved on the spot" samt Projekt, und derselbe Aufruf holt direkt danach Zertifikat und Passphrase ab -- danach wie gehabt `odoo reload && odoo up -d && odoo pgbackrest check`.

Was der Weg NICHT aushebelt: die Zugangsdaten gibt es weiterhin erst, wenn der Umschlag mit der Passphrase am Projekt in hosting.zebroo.de liegt. Laesst sich das Projekt nicht bestimmen, bleibt die Anfrage stehen und der Befehl sagt gelb, was auf dem Backup-Server noch fehlt. Eine Passphrase, die nur auf der gesicherten Maschine liegt, ist im Ernstfall wertlos -- deshalb ist das die eine Bedingung, die auch die Bequemlichkeit nicht ueberspringt.

zodoo ist oeffentlich, eine Anfrage kann also jeder stellen. Freigeben kann sie nur, wer das Geheimnis hat UND das Abhol-Token dieser Anfrage, das beim Anfragen auf dieser Maschine landet; fremde Anfragen lassen sich damit nicht durchwinken. Nach fuenf Fehlversuchen macht der Anmeldedienst fuer diese Adresse eine Viertelstunde zu.

Ohne `--approve` aendert sich nichts.
