cadvisor laeuft jetzt einmal je Maschine statt einmal je Instanz.

cadvisor misst Container, und zwar immer ALLE, die auf der Maschine laufen -- er haengt am Docker-Daemon und an /sys, nicht an einem Projekt. Definiert war er trotzdem im Stapel jeder Instanz. Auf einer CICD-Maschine mit 99 Containern und fuenf Instanzen haben also fuenf Prozesse im Halbminutentakt dieselben 99 Container abgefragt: dieselbe Arbeit, fuenfmal, rund um die Uhr. Gemessen 30 Prozent eines Kerns je Behaelter, also rund 1,5 Kerne fuer eine Messung, die einer haette machen koennen -- und zwar auf overlay2, ganz ohne ZFS.

Neu laeuft genau einer: Behaelter `zodoo_cadvisor` im Netz `zodoo_monitoring`, beides ausserhalb der Projekt-Stapel. zodoo legt ihn beim `up` an, wenn RUN_DASHBOARD=1 ist; laeuft er schon, passiert nichts. Der Prometheus jeder Instanz haengt zusaetzlich in diesem Netz und fragt ihn unter seinem Namen ab.

Was sich dadurch im Alltag aendert:

- `odoo down` einer Instanz nimmt den anderen die Container-Messwerte nicht mehr weg -- der cadvisor gehoert der Maschine und bleibt stehen.
- Jede Instanz behaelt nur noch die eigenen Container (Filter ueber den Projektnamen in ihrer prometheus.yml). Vorher legte jede Instanz die Messreihen aller Container der Maschine ab, also dieselben Daten so oft, wie es Instanzen gibt.
- Zum Nachsehen gibt es `odoo host-cadvisor status`, `odoo host-cadvisor restart` und `odoo host-cadvisor remove`.

Zum Pruefen nach dem Update: `odoo up -d`, dann `docker ps | grep cadvisor` -- es darf nur noch `zodoo_cadvisor` dastehen, nicht mehr einer je Projekt. Im Grafana der Instanz unter /system muessen die Tafeln "Container CPU" und "Container Memory" weiter gefuellt sein, und zwar nur mit den Containern dieser Instanz. `docker stats --no-stream zodoo_cadvisor` zeigt die Last der Maschine an einer Stelle statt verteilt.

Wichtig fuer Maschinen, die laenger nicht neu geladen wurden: die Aenderung sitzt in der Vorlage, die erzeugte docker-compose.yml einer Instanz entsteht erst beim naechsten `odoo reload`. Bis dahin laeuft die alte, instanz-eigene Variante weiter.
