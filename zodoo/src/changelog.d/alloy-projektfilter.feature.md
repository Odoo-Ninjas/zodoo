Jede Instanz schreibt nur noch ihre eigenen Container-Logs mit.

alloy sieht ueber die docker.sock jeden Container der Maschine, nicht nur die des eigenen Projekts -- und hat sie bisher auch alle mitgeschrieben. Auf cicd-3dm heisst das: sechs alloy lesen dieselben 123 Container und legen sie in sechs Lokis ab. Gemessen rund 9 GB ueber sechs Loki-Volumes, im Wesentlichen dieselben Zeilen, dazu sechsmal dasselbe Lesen und Schreiben auf derselben Platte.

Das hatte noch eine zweite Seite: wer an das Grafana einer Instanz kam (/logs2), konnte dort die Logs aller Projekte der Maschine lesen. Auf einer Maschine mit mehreren Kunden ist das keine Kleinigkeit.

Neu filtert alloy auf das eigene Compose-Projekt. Den Namen setzt zodoo beim Erzeugen der Compose-Datei an den Dienst; es ist derselbe, der als Label `com.docker.compose.project` an jedem Container haengt.

Soll eine Instanz weiterhin alles mitschreiben, was auf der Maschine laeuft -- etwa auf einer eigenen Kiste, auf der auch Nicht-zodoo-Container laufen --, dann `DASHBOARD_LOGS_ALL_CONTAINERS=1` setzen und `odoo reload && odoo up -d`.

Zum Pruefen nach dem Update: im Grafana der Instanz unter /logs2 eine Suche ueber alle Logs (`{job="docker"}`) -- dort duerfen nur noch Container dieser Instanz auftauchen. `du -sh /var/lib/docker/volumes/*loki*/_data` zeigt ueber die naechsten Tage, wie die Ablage zurueckgeht; die alten Zeilen verschwinden mit der Aufbewahrungsfrist (DASHBOARD_LOKI_RETENTION, Standard 168h).

Wichtig: die Filterregel liegt in der gemeinsamen alloy-Konfiguration und ist nach dem Update sofort da, der Projektname kommt aber aus der erzeugten Compose-Datei. Bis zum naechsten `odoo reload` einer Instanz fehlt er -- dann bleibt es bewusst beim alten Verhalten (alle Container), statt dass die Logs lautlos verschwinden.
