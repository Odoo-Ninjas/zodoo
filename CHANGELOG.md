# Changelog

## 11.4.2

- Der globale Router laesst sich wieder deployen, wenn mindestens ein vhost mit `allowed_ips` konfiguriert ist. Vorher brach jeder Deploy-Versuch ab mit

  nginx: [emerg] duplicate location "/.well-known/acme-challenge/"

  und rollte zurueck - damit war KEINE vhost-Aenderung mehr moeglich, auch nicht an voellig unbeteiligten Hosts.

  Ursache: fuer vhosts mit Allowlist gibt `_ip_allowlist.inc` eine ACME-Location aus (damit certbot trotz Allowlist durchkommt), das `upstream`-Template gibt am Ende eine zweite aus. Das fiel jahrelang nicht auf, weil die zweite `accme-challenge` hiess - der Tippfehler hat die Kollision zufaellig verhindert. Mit dessen Korrektur kollidierten beide.

  Die Location im `upstream`-Template entfaellt jetzt fuer vhosts mit Allowlist; dort gilt die `^~`-Variante aus dem Include, die ohnehin Vorrang braucht.

  Zum Testen: auf einem Router mit einem `allowed_ips`-vhost `odoo router apply-vhosts --global` laufen lassen - es muss "Reloaded." kommen statt der emerg-Meldung. Danach in der gerenderten Datei dieses vhosts pruefen, dass `/.well-known/acme-challenge/` nur noch einmal vorkommt, und dass eine Zertifikatserneuerung dort weiterhin durchgeht.


## 11.4.1

- **Fix**: Der Web-Router prueft eine neue Konfiguration jetzt, bevor sie in Kraft tritt - und nimmt sie zurueck, wenn nginx sie ablehnt.

  Bisher hat "odoo router apply-vhosts" die erzeugten Dateien direkt nach sites-enabled kopiert und dann nginx neu geladen. Lehnt nginx die Konfiguration ab, laeuft er mit der alten weiter - man sieht eine Fehlermeldung, aber alles funktioniert weiter, und der Fehler wirkt harmlos. Er ist es nicht: in sites-enabled liegt jetzt die kaputte Fassung, und beim naechsten Neustart des Router-Containers kommt nginx nicht mehr hoch. Dann sind nicht nur der geaenderte vHost, sondern ALLE Domains hinter dem Router offline - und zwar Stunden nach der Aenderung, die es ausgeloest hat.

  Jetzt wird vor dem Ausrollen eine Kopie der betroffenen Verzeichnisse angelegt, danach "nginx -t" im Container ausgefuehrt. Lehnt nginx ab, wird die Kopie zurueckgeschrieben und der Aufruf bricht mit der Meldung von nginx ab - der Router laeuft unveraendert weiter, so als waere nichts passiert. Geprueft wird bewusst erst zum Schluss, nach dem Setzen von Basic Auth, weil das noch in dieselben Dateien schreibt: geprueft werden muss der Stand, der nachher wirklich geladen wird.

  Laeuft kein Router-Container (etwa beim ersten Einrichten), kann nicht geprueft werden. Dann wird wie bisher ausgerollt und ein Hinweis ausgegeben, statt den Vorgang zu blockieren.

  Zum Nachschauen: in der vhosts.yml bei einem vHost mit eigenem Zertifikat den certificate_name auf ein Verzeichnis zeigen lassen, das es nicht gibt, und "odoo router apply-vhosts" aufrufen. Es muss die nginx-Meldung ("cannot load certificate") kommen, der Aufruf abbrechen, und "odoo router vhost list" sowie die Seiten der anderen Domains muessen unveraendert weiterlaufen. Vorher lief das durch und der Router waere beim naechsten Neustart nicht mehr hochgekommen.


## 11.4.0

- **Feature**: Router: self-signed TLS vhosts (ssl_self_signed) for protected LANs where Let's Encrypt/ACME cannot verify; generate a self-signed cert on the host, listen on 443 plus an 80->https redirect. Also fixes the accme-challenge typo in the ACME location.


## 11.3.6

- **Fix**: `odoo reload` brach fuer Odoo 12 und 13 ab, bevor ueberhaupt gebaut wurde:

  Exception: None value not allowed for: ODOO_PYTHON_VERSION

  Die Zuordnung Odoo-Fassung -> Python-Fassung fiel fuer 11, 12 und 13 auf `pass` durch, `None` landete in den Einstellungen, und der Fehler kam erst beim Schreiben der Datei - mit einer Meldung, die nicht sagt, was zu tun ist. Fuer 12 und 13 ist jetzt 3.8.20 hinterlegt (beide Abbilder wenden `patches/python_3.8.email.patch` an, die 3.8er Reihe ist also gesetzt).

  Fuer Odoo 11 bleibt bewusst nichts hinterlegt - es baut auf buster und wird nirgends mehr neu gebaut. Statt `None` kommt dort jetzt aber eine klare Ansage: "Fuer Odoo 11 ist keine Python-Fassung hinterlegt. Bitte selbst waehlen: odoo setting ODOO_PYTHON_VERSION=3.x.y". Eine selbst gesetzte Fassung wird wie bisher nie ueberschrieben.

  Zum Nachvollziehen: ein Projekt auf Odoo 12 oder 13 anlegen und `odoo reload` aufrufen - das lief vorher in den obigen Abbruch.


## 11.3.5

- **Internal**: Die automatischen Tests laufen jetzt bei jeder Aenderung, nicht nur bei bestimmten Verzeichnissen.

  Die Unit-Tests waren auf Aenderungen unter zodoo/src beschraenkt. Das klingt vernuenftig, hatte aber eine Luecke: die Tests liegen zwar dort, pruefen von dort aus aber auch Dateien ausserhalb - test_cronjobs_run laedt cronjobs/bin/run.py, test_router_vhost_wizard laedt router_global/render_configs.py. Wer genau die Datei aenderte, die ein Test prueft, bekam diesen Test also nicht zu sehen. Insgesamt liefen bei Aenderungen an cronjobs, router_global, common_snippets, proxy, console, install.sh und einem guten Dutzend weiterer Verzeichnisse gar keine Tests.

  Dramatisch war das nie, weil nach dem Zusammenfuehren auf main ohnehin alles laeuft - nur eben zu spaet: der Fehler faellt dann erst danach auf und blockiert die Auslieferung, statt vorher im Vorschlag aufzutauchen.

  Der Filter der Unit-Tests ist deshalb ersatzlos weg; die Suite braucht keine Minute. Beim schweren Docker-Durchlauf, der eine Viertelstunde dauert, bleibt ein Filter sinnvoll - er umfasst jetzt zusaetzlich common_snippets und cronjobs, weil beides direkt in die Abbilder geht (common_snippets/zodoo baut das venv jedes Containers, cronjobs stellt den Cron-Daemon der Instanz).

  Zum Nachschauen: einen Vorschlag aufmachen, der nur eine Datei ausserhalb von zodoo/src aendert (etwa in docs/ oder router_global/) - unter den Pruefungen muessen jetzt die unit-Eintraege fuer alle Python-Versionen auftauchen.
- **Fix**: Der Log-Level stand faktisch auf debug, obwohl in der odoo.conf "info" stand. run.py setzte den Kommandozeilenschalter mit dem Default "debug", und der ueberschreibt die Konfigurationsdatei. Wer nachsah, las dort "info" oder sogar "error" und wunderte sich; sichtbar war es nur in der Prozessliste. Zum Pruefen: nach dem Update auf einer Instanz die Odoo-Logs ansehen -- es sollten deutlich weniger Zeilen kommen und keine mehr mit DEBUG-Praefix. Wer weiterhin debug braucht, setzt ODOO_LOG_LEVEL=debug in den Settings; das hat weiterhin Vorrang. Auf hosting.zebroo.de waren es vorher rund 4000 Logzeilen pro Minute, nach der Umstellung 180 -- die alloy/Loki-Ablage hat das alles mitgesammelt.


## 11.3.4

- **Fix**: Die Abbilder fuer Odoo 12 und 13 bauen auf Debian bullseye und liefen in dasselbe Loch wie der apt-Zwischenspeicher: bullseye ist EOL, die Sicherheitspakete verschwinden von den Spiegeln und liegen noch nicht im Archiv, `apt-get install` bricht dadurch sporadisch mit 404 ab. Beide holen ihre Pakete jetzt von einem Debian-Schnappschuss - ueber den neuen Schnipsel `common_snippets/debian_snapshot`, einmal je Build-Stufe.

  Dabei kamen zwei Fehler mit heraus, die beide Abbilder unabhaengig davon unbaubar gemacht haben:

  - `odoo/config/12` und `odoo/config/14` schrieben die Schnipsel-Marke `DEB_REQUIERMENTS` statt `DEB_REQUIREMENTS`. Eine unbekannte Marke wird nicht ersetzt; die Ersetzungsschleife laeuft 100 Runden leer und bricht dann mit "Not resolved or endless loop" ab - eine Meldung, die auf eine Endlosschleife deutet statt auf den Tippfehler. Ein neuer Test prueft jetzt fuer alle Dockerfiles, dass jede Marke eine Datei hat.
  - `odoo/config/12` installierte `python-dev`. Das ist das Python-2-Uebergangspaket, und Python 2 ist mit bullseye aus Debian entfernt worden - das Paket gibt es dort also gar nicht. Jetzt `python3-dev`. In derselben Zeile stand `apt-get update; apt-get install` mit Semikolon, womit die Installation auch nach einem gescheiterten Update mit veralteter Paketliste weitergelaufen waere; jetzt `&&`.

  Zum Nachvollziehen: eine Odoo-12- bzw. -13-Instanz bauen (`odoo build`). Vorher brach das mit "Not resolved or endless loop" ab.


## 11.3.3

- **Fix**: Das Abbild des apt-Zwischenspeichers (`apt_cacher`) liess sich sporadisch nicht mehr bauen: `apt-get install squid-deb-proxy` brach mit einer Reihe von 404 ab. Ursache ist nicht unser Dockerfile, sondern Debian 11: bullseye ist seit Ende August 2026 EOL, die Sicherheitspakete verschwinden von den Spiegeln und liegen noch nicht auf archive.debian.org. Waehrend dieses Uebergangs nennt der Paketindex Versionen, deren .deb schon weg ist - und je nach CDN-Knoten mal so, mal so. Am 07.09.2026 hat das den Release-Lauf von v11.3.1 gerissen.

  Das Abbild baut jetzt gegen einen Debian-Schnappschuss (`snapshot.debian.org`, Datum im Build-Argument `SNAPSHOT_DATE`), der Index und Pool aus demselben Moment liefert. Ein Wechsel auf ein neueres Debian hilft hier nicht: `squid-deb-proxy` ist aus Debian entfernt und existiert weder in bookworm noch in trixie.

  Zum Nachvollziehen: `docker build apt_cacher` muss durchlaufen und der Container auf Port 8000 als Proxy antworten. Wer die Sicherheitslage des Abbilds nachziehen will, hebt `SNAPSHOT_DATE`.

  Ausserdem: schlaegt der Start des apt- oder pypi-Zwischenspeichers fehl, bricht `odoo build` nicht mehr ab, sondern warnt und baut ohne ihn weiter - beide sparen nur Bauzeit. Vorher landete der Fehlschlag in einem Future, das niemand abfragte: der Build lief ohne Beschleuniger weiter, ohne dass irgendwo stand, warum.
- **Fix**: zodoo wartet jetzt zuverlaessig, wenn postgres gerade nicht bedient - vorher brach es sofort ab.

  Anlass war ein Fehlschlag beim automatischen Testlauf: "odoo db reset" starb mit "FATAL: the database system is shutting down". Der Datenbankserver fuhr in dem Moment gerade herunter, was beim Zuruecksetzen normal ist - zodoo haette einfach kurz warten muessen.

  Zwei Stellen waren schuld. Die erste ist die Vorabpruefung in tools._execute_sql: dort stand zwar eine Wiederholungslogik, die zugehoerige Funktion hat ihren Fehler aber selbst abgefangen und nur rot ausgegeben. Damit bekam die Wiederholung nie einen Fehler zu sehen und hat NIE wiederholt - der Schutz war seit immer wirkungslos.

  Die zweite ist der Verbindungsaufbau selbst: der hat nur auf "database system is starting up" gewartet, ein herunterfahrender Server flog sofort durch. Ausserdem war die Warteschleife dort endlos - bei einem Server, der dauerhaft im Zustand "starting up" haengt, wartete zodoo unbegrenzt.

  Jetzt gibt es eine gemeinsame Erkennung fuer Zustaende, die von allein vergehen (herunterfahren, hochfahren, Wiederherstellung, Verbindung abgewiesen, Verbindung vom Server geschlossen, Verbindung durch den Administrator beendet). Nur die werden ausgesessen, und nur bis zu einer Frist (60 Sekunden, ueber PSYCOPG_CONNECT_RETRY_SECONDS aenderbar). Ein falsches Passwort oder eine fehlende Tabelle fuehrt weiterhin sofort zum Abbruch - darauf zu warten hilft ja nicht.

  Wichtig: wiederholt wird nur der Verbindungsaufbau, nicht die Ausfuehrung einer Anweisung. Ein Wiederholen von Schreibvorgaengen koennte Daten doppelt anlegen.

  Zum Nachschauen: "odoo -f db reset" mehrfach hintereinander laufen lassen - es darf nicht mehr mit "the database system is shutting down" abbrechen. Waehrend eines Neustarts von postgres ("odoo restart postgres") sollte ein paralleles "odoo psql" ein paar Sekunden warten und dann durchkommen statt sofort zu scheitern.
- **Docs**: Richtigstellung zu einem Hinweis von heute Vormittag: in der Installationsanleitung stand, unter Python 3.10 sei der Schutz des Cron-Daemons gegen beschattete Standardmodule unwirksam. Das ist so zu pauschal und verunsichert ohne Grund.

  Richtig ist: PYTHONSAFEPATH gibt es tatsaechlich erst ab Python 3.11, und aeltere Interpreter ignorieren die Variable stillschweigend - deshalb wird der zugehoerige Test unter 3.10 uebersprungen. Die Cronjobs laufen davon aber unberuehrt, denn der Cronjob-Container baut sein eigenes venv mit python3.11 und ruft odoo daraus auf. Welches Python auf dem Host installiert ist, spielt dafuer keine Rolle.

  Ausserdem steht jetzt dabei, warum es den Schutz ueberhaupt braucht: der Aufruf im Container ist "python3 -m zodoo", und bei "-m" landet das aktuelle Verzeichnis in sys.path. Zusammen mit dem "cd /opt/src" des Cron-Daemons wuerde eine Datei im Projektverzeichnis, die wie ein Standardmodul heisst (inspect.py, grp.py, ...), das echte Modul verdecken und jeden Cronjob der Instanz lahmlegen.

  Zum Nachschauen: docs/02-installation.md, Abschnitt Prerequisites. Die Begruendung des uebersprungenen Tests in test_cronjobs_run.py sagt jetzt dasselbe, damit niemand aus dem "skipped" auf eine Luecke im Betrieb schliesst.


## 11.3.2

- **Fix**: Abfragen im Terminal pruefen die Eingabe jetzt wirklich, und die Testlaeufe auf GitHub decken zusaetzlich Python 3.10 ab.

  Bei den Rueckfragen, die zodoo im Terminal stellt, wurde eine falsche Eingabe bisher teilweise einfach angenommen. Der Grund ist eine Tuecke der verwendeten Bibliothek: sie betrachtet jeden Rueckgabewert der Pruefung als "in Ordnung", solange er nicht leer ist. Die naheliegende Schreibweise "pruefung ... oder 'Muss eine Zahl sein'" liefert bei falscher Eingabe aber genau diesen Text zurueck - und der gilt damit als Zustimmung. Betroffen waren die beiden Portabfragen beim Einrichten des APT-/PyPI-Zwischenspeichers ("odoo setup apt-proxy"): dort war jede Eingabe erlaubt, auch "abc" oder "70000", und die Begruendung wurde nie angezeigt.

  Es gibt jetzt drei gemeinsame Pruefungen in tools.py (Pflichtfeld, Port, sowie die Hilfsfunktion, die eine Eingabe mit Begruendung ablehnt). Der Router-Assistent nutzt sie ebenfalls, statt eigene mitzuschleppen.

  Zum Nachschauen: "odoo setup apt-proxy" aufrufen und bei der Portabfrage "abc" eingeben - das muss jetzt mit "Must be a port between 1 and 65535" abgelehnt werden, statt die Eingabe zu uebernehmen. Ein Test haelt die Tuecke ausserdem fest, damit die Pruefungen nicht wieder zu Einzeilern zusammengefasst werden.

  Ausserdem laufen die Tests auf GitHub jetzt gegen Python 3.10 bis 3.14 (vorher 3.11 bis 3.14). 3.10 ist dabei, weil Ubuntu 22.04 das noch mitbringt; vorab gemessen: die Suite ist dort gruen.

  Beim Aufnehmen von 3.10 in die Testlaeufe ist dabei ein Test aufgefallen, der nicht das geprueft hat, was er prueft: Der Nachweis, dass PYTHONSAFEPATH das Beschatten von Standardmodulen verhindert, rief "python3" aus dem Suchpfad auf statt den Interpreter, unter dem zodoo laeuft. Auf einer Maschine mit Python 3.10 und einem neueren python3 daneben waere er gruen geworden, obwohl der Schutz gar nicht greift - denn PYTHONSAFEPATH gibt es erst ab 3.11, aeltere Versionen ignorieren die Variable stillschweigend. Der Test nimmt jetzt sys.executable und wird unter 3.10 uebersprungen.

  Das heisst zugleich: **unter Python 3.10 schuetzt der Cron-Daemon nicht davor, dass eine Datei mit dem Namen eines Standardmoduls im Projektverzeichnis (inspect.py, grp.py, ...) alle Cronjobs lahmlegt.** Auf Maschinen mit Cronjobs also besser 3.11 oder neuer. Steht so auch in der Installationsanleitung.
- **Fix**: `odoo pgbackrest policy` holt die Aufbewahrungs-Vorgabe vom Backup-Server und legt sie als `PGBR_RETENTION_FULL_EFFECTIVE` in den Einstellungen ab. Der Befehl brach dabei bisher mit `NameError: name 'update_setting' is not defined` ab - der Helfer, der schreibt, hatte den Import nicht (in dieser Datei wird `update_setting` in jeder Funktion einzeln importiert).

  Zum Nachvollziehen: auf einer registrierten Instanz `odoo pgbackrest policy` aufrufen. Erwartet wird die Meldung mit den vorgegebenen Tagen; danach steht in `~/.odoo/settings.<projekt>` ein `PGBR_RETENTION_FULL_EFFECTIVE`, und nach `odoo reload` taucht der Wert als `repo1-retention-full` in der erzeugten `pgbackrest.conf` auf.


## 11.3.1

- **Internal**: Die Testlaeufe auf GitHub laufen jetzt gegen Python 3.11, 3.12, 3.13 und 3.14 statt nur gegen 3.11 - und ein Release kommt nur heraus, wenn alle vier gruen sind.

  Bisher lief die Testsuite in beiden Workflows (Pytest und Release on merge) fest unter 3.11. Ob zodoo mit einem neueren Python zurechtkommt, hat also niemand gemessen - was unangenehm ist, seit die aktuellen Systeme 3.13 bzw. 3.14 mitbringen (Ubuntu 26.04 hat gar kein aelteres Paket mehr).

  Der Release haengt unveraendert an "needs: [test, bake]". Weil sich das bei einer Matrix auf alle Varianten bezieht, blockiert eine einzige rote Version den Release. "fail-fast" ist bewusst aus: schlaegt eine Version fehl, laufen die anderen weiter, damit man sieht, ob es an der einen Version haengt oder an allen.

  Zum Nachschauen: in einem Pull Request stehen unter den Checks jetzt vier Eintraege "unit (3.11)" bis "unit (3.14)" statt einem. In der Installationsanleitung stand ausserdem noch "Python 3.13 not yet supported" - das ist mit den Laeufen widerlegt und korrigiert.


## 11.3.0

- **Feature**: Die Aufbewahrung bestimmt ab jetzt der Backup-Server. `PGBR_RETENTION_FULL` ist nur noch ein Wunsch.

  Ausgefuehrt wird sie weiter auf der Instanz - nur die kann `backup.info` entschluesseln. WAS gilt, sagt der Server, dem die Platte gehoert. Reihenfolge beim Rendern:

  1. `PGBR_RETENTION_FULL_EFFECTIVE` - was der Server geliefert hat
  2. `PGBR_RETENTION_FULL` - der eigene Wunsch
  3. die dokumentierte Vorgabe von 14 Tagen

  Absichtlich in dieser Reihenfolge und NICHT als groesserer der beiden Werte: sonst koennte eine Instanz mit einem hohen Wunsch die Vorgabe ueberbieten, und der Server waere wieder nicht die entscheidende Seite.

  **Nicht umbenannt.** Eine Umbenennung haette jedes Projekt gebrochen, das die Einstellung gesetzt hat - fuer eine Wirkung, die die Serverantwort ohnehin ueberschreibt.

  Neu:

  - `odoo pgbackrest policy` holt die geltende Vorgabe und legt sie ab. Sagt ausserdem, wenn der eigene Wunsch abweicht und deshalb nicht gilt.
  - `register` bringt Vorgabe und Token gleich mit. Der Token berechtigt zum Erfragen der EIGENEN Vorgabe und zu nichts weiter.
  - `CRONJOB_PGBACKREST_POLICY` fragt woechentlich nach.

  Worauf beim Testen zu achten ist: `odoo pgbackrest policy` aufrufen, dann in `~/.odoo/run/<projekt>/pgbackrest/pgbackrest.conf` nachsehen - nach `odoo reload` muss dort der Wert des Servers stehen, nicht der eigene. Der Kommentar ueber den Retention-Zeilen sagt, welcher der beiden gerade gilt.

  Zwei Grenzen ausdruecklich:

  - Der Cronjob macht die Vorgabe NICHT wirksam. Der geholte Wert wird erst beim naechsten `odoo reload` gerendert; ein reload aus dem Container bricht absichtlich ab (siehe 11.0.1). Die Luecke deckt die Ueberwachung auf dem Backup-Server ab (`backup.retention.tooshort`).
  - Eine clientseitige Konfiguration ist keine Kontrolle: root auf der Instanz kann sie aendern. Durchgesetzt wird die Historie vom unveraenderlichen Zweitbestand, nicht von dieser Einstellung.

  Bereiche, die vor dem 07.09.2026 angemeldet wurden, haben keinen Token. Der Befehl sagt das, und der Cron-Eintrag wird geleert statt jede Woche zu scheitern.
- **Feature**: Neuer Assistent "odoo router vhost new" legt einen Virtual Host im Dialog an, und ein fehlendes Feld in der vhosts.yml fliegt jetzt auf, statt eine kaputte nginx-Konfiguration zu erzeugen.

  Bisher liess sich ein vHost nur aus einer fertigen Datei einlesen ("odoo router vhost add <datei>") - man musste also wissen, welche Felder das jeweilige Template braucht, und die stehen nur in den Templates selbst. Der Assistent fragt der Reihe nach ab: Art des vHosts, Domain, Backend-Adresse und -Port, Zeitlimit, Let's-Encrypt-Zertifikat, IP-Freigabeliste und Basic Auth. Er prueft die Eingaben, zeigt den fertigen vHost als YAML und schreibt ihn auf Wunsch in die vhosts.yml und rollt ihn aus.

  Mit "--dry-run" gibt er den vHost nur aus und aendert nichts - dafuer braucht es auch keinen installierten Router. Das ist der schnellste Weg, sich ein korrektes Schnipsel fuer die vhosts.yml zu erzeugen.

  Zwei Eingaben werden geprueft, weil sie erfahrungsgemaess schiefgehen: der Upstream-Name darf nur Buchstaben, Ziffern und Unterstriche enthalten (er wird zu einem nginx-Variablennamen, mit Punkt oder Bindestrich laedt nginx die Konfiguration nicht - und das merkt man erst beim Reload), und die Ports muessen echte Ports sein.

  Ausserdem gerendert wird jetzt mit StrictUndefined. Das war zwar schon importiert, aber nie gesetzt - ein fehlendes Feld wurde deshalb still zu einem leeren Text, und heraus kam eine kaputte Konfiguration mit Zeilen wie "server :;" und "proxy_pass http://$var_;", ohne jede Meldung. Fehlt ein Feld, nennt das Rendern nun den vHost und das Feld und bricht ab. ACHTUNG beim Aktualisieren: wer bisher eine unvollstaendige vhosts.yml hatte, bekommt bei "odoo router apply-vhosts" jetzt einen Fehler statt eines stillen Teilergebnisses. Der betroffene vHost hat vorher nicht funktioniert - die Zeile muss ergaenzt werden.

  Zum Nachschauen: "odoo router vhost new --dry-run" durchklicken, dabei als Upstream-Namen bewusst "meine.domain.de" eingeben - das muss abgelehnt werden. Am Ende steht der vHost als YAML auf dem Bildschirm und in der vhosts.yml steht unveraendert das Alte. Danach ohne --dry-run anlegen, "odoo router vhost list" zeigt ihn, und die Datei unter sites-enabled enthaelt Backend-Adresse und -Port an den richtigen Stellen.

  Neu dazu: eine vollstaendig kommentierte Beispielkonfiguration (router_global/vhosts.example.yml) und die Doku docs/13-web-router.md - fuer den Router gab es bisher gar keine.

  Dazu gibt es "odoo router config": ein gefuehrtes Menue, das man mit den Pfeiltasten bedient. Darin kann man vHosts anlegen, bearbeiten, loeschen und anzeigen, die Konfiguration ausrollen und Zertifikate holen. Es bleibt offen, bis man "Quit" waehlt, und wenn dann noch nicht ausgerollte Aenderungen offen sind, fragt es danach.

  Die Liste zeigt zu jedem vHost, wohin er zeigt, und markiert unvollstaendige ("incomplete: upstream_server, timeout") - so sieht man die kaputten Eintraege aus der Zeit vor der Pruefung sofort. Beim Bearbeiten steht der aktuelle Wert als Vorgabe drin; noch nicht gesetzte Felder werden mit "+" und einer kurzen Erklaerung angeboten. Leert man ein optionales Feld, wird es entfernt und nicht als leerer Wert gespeichert.

  Beim Neuanlegen macht der Assistent Vorschlaege: die Backend-Adresse aus dem, worauf die anderen vHosts zeigen, den Port eine Nummer ueber dem hoechsten bereits benutzten, und den Upstream-Namen aus der Domain.

  Nebenbei korrigiert: die Eingabepruefungen haben nicht geprueft. inquirer betrachtet jeden Rueckgabewert von "validate" als gueltig, solange er nicht leer ist - der uebliche Einzeiler "... or 'Must be a valid port'" liefert bei falscher Eingabe also einen Text zurueck, und der gilt als "in Ordnung". Die Pruefungen im Router-Assistenten loesen jetzt einen Fehler aus, damit die Eingabe wirklich abgelehnt und die Begruendung angezeigt wird.


## 11.2.9

- **Fix**: "odoo build" sagt jetzt selbst, wenn ein Docker-Plugin fehlt - mit dem Befehl zum Nachinstallieren.

  Anlass war eine frische Ubuntu 26.04: dort bringt das Paket docker.io (Docker 29) kein buildx mit. Docker fährt BuildKit aber als Standard, also bricht der Build sofort mit "BuildKit is enabled but the buildx component is missing or broken" ab. Bitter wird es danach: weil das Basis-Image dadurch nie entsteht, versucht der nächste Schritt es aus der Registry zu ziehen, und man sieht nur noch "pull access denied ... odoo_base_17_..." - man sucht dann bei den Registry-Zugangsdaten, obwohl bloß ein Paket fehlt.

  Jetzt prüft "odoo build" vor dem Start, ob "docker compose" und "docker buildx" da sind. Fehlt compose, bricht es sofort ab (ohne compose läuft gar nichts). Fehlt buildx, kommt eine gelbe Warnung samt Hinweis, dass der Rückfallweg auf aktuellem Docker ebenfalls nicht baut. Und wenn der Build doch an der buildx-Meldung stirbt, endet er mit dem Klartext-Hinweis statt mit dem irreführenden Folgefehler. In der Meldung stehen beide Paketnamen, weil sie sich je nach Docker-Quelle unterscheiden: docker-buildx / docker-compose-v2 (Distributions-Docker) bzw. docker-buildx-plugin / docker-compose-plugin (Docker-eigenes Repo).

  Zum Nachschauen: auf einer Maschine mit Docker, aber ohne buildx (z.B. Ubuntu 26.04 nach "apt install docker.io"), im Projekt "odoo build" aufrufen. Es muss gleich am Anfang die gelbe Meldung mit dem apt-install-Befehl kommen, nicht erst nach Minuten ein Fehler über eine Registry. Nach "apt install docker-buildx" ist die Meldung weg und der Build läuft normal durch. In der Installationsanleitung stehen die Pakete inzwischen ebenfalls.


## 11.2.8

- **Docs**: Dokumentiert, warum die Odoo-Basisabbilder auf alten Distributionen stehen - und warum bullseye JETZT nicht umgestellt werden darf.

  Jede Odoo-Generation hat eine Basis ihrer Epoche: 11 auf buster, 12 bis 14 auf bullseye, 15 bis 19 auf Ubuntu 22.04. Das ist Absicht, altes Odoo braucht altes Python. 12 bis 14 auf bookworm zu heben ist keine Haertung, sondern ein Bruch: bookworm liefert Python 3.11, und Odoo 12 von 2018 laeuft darauf nicht.

  Kaputt geht nicht der laufende Container, sondern der BAU - sobald Debian eine Fassung von deb.debian.org ins Archiv verschiebt. Bei buster ist das schon passiert; odoo/config/11 ueberlebt es, weil es seine Quellen vorher umschreibt. Das Rezept steht jetzt in der Doku, samt dem Teil, den man vergisst: `Acquire::Check-Valid-Until "false"`, weil die Release-Dateien im Archiv per Definition abgelaufen sind.

  Fuer bullseye gilt am 07.09.2026 gemessen:

  - deb.debian.org bedient bullseye UND bullseye-security vollstaendig
  - archive.debian.org hat bullseye und bullseye-updates
  - archive.debian.org hat bullseye-security NICHT (404)

  Wer jetzt umstellt, macht den Bau kaputt statt ihn zu retten: `apt-get update` endet mit 100, weil der Security-Zweig wegfaellt. Nachgestellt, nicht vermutet. Umstellen also erst, wenn deb.debian.org bullseye nicht mehr fuehrt - und den Security-Zweig dann getrennt pruefen.

  Ausserdem eine wirkungslose Zeile in odoo/config/11 entfernt: sie legte eine apt-Quelle als sources.list.d/dmtx ab, OHNE .list-Endung, und apt liest dort nur *.list. Die Zeile hat nie gewirkt. Nachgemessen: ohne Endung erwaehnt apt die URL null mal und endet mit 0, mit Endung dreimal und endet mit 100. libdmtx0b kommt aus buster main und laesst sich ohne die Quelle installieren (geprueft).

  Worauf beim Testen zu achten ist: `odoo build` fuer ein Odoo-11-Projekt muss unveraendert durchlaufen.
- **Fix**: Der Installer installiert gimera jetzt mit, und "odoo bisect" stolpert nicht mehr ueber eine Warnung von Python 3.14.

  Das "pipx inject zodoo gimera" gab es bisher nur in "odoo setup reinstall". Wer eine Maschine frisch mit install.sh aufgesetzt hat, hatte deshalb gar kein gimera - "gimera apply" ging erst, nachdem man einmal reinstall aufgerufen hatte. Auf einer neu aufgesetzten Ubuntu 26.04 nachgestellt.

  In lib_bisect.py stand ein "break" in einem finally-Block. Python 3.14 warnt darueber, und eine spaetere Version macht daraus einen Fehler, weil so ein Sprung eine noch anstehende Exception verschluckt. Die Schleife merkt sich den Abbruch jetzt in einer Variablen und bricht nach dem finally ab.

  Zum Nachschauen: nach dem Installer muss "gimera --version" direkt funktionieren, ohne vorher "odoo setup reinstall" aufzurufen. "odoo bisect" verhaelt sich unveraendert - inklusive Abbruch nach dem ersten Fehler, wenn "stop_after_first_error" gesetzt ist.

  In der Installationsanleitung stehen fuer Ubuntu jetzt zusaetzlich docker-buildx und docker-compose-v2. Ohne buildx bricht "odoo build" auf Ubuntu 26.04 ab ("BuildKit is enabled but the buildx component is missing"), und weil das Basis-Image dadurch nie entsteht, kommt der Folgefehler als irrefuehrendes "pull access denied ... odoo_base_..." an.


## 11.2.7

- **Docs**: Die 36 leeren Changelog-Eintraege sind wiederhergestellt. Der Changelog reicht damit erstmals lueckenlos bis 8.0.0 zurueck.

  Bis zur Korrektur in 11.2.3 hat die Release-Automatik jede mehrzeilige Patchnote verschluckt und "- **Fix**: |" hinterlassen. Betroffen waren 36 Eintraege in 25 Fassungen.

  Wiederherstellbar war das, weil jeder Release-Commit die Fragmente LOESCHT, die er verarbeitet hat - im Eltern-Commit stehen sie also noch. Das neue Werkzeug `scripts/rebuild_changelog_from_history.py` holt sie dort und laesst sie durch denselben Sammler laufen, der heute die Releases baut.

  Zwei Vorkehrungen, damit dabei nichts verloren geht:

  - Ein Abschnitt wird nur ersetzt, wenn JEDER vorhandene nicht-leere Eintrag im neu erzeugten Text wiederzufinden ist. Bei 8.0.0 hat das zunaechst angeschlagen - dort war ein zweiter Eintrag ebenfalls leer, nur in der Form "- **BREAKING**: | — |", die das Muster erst nicht erfasste.
  - Das Werkzeug ist wiederholbar: ein zweiter Lauf findet nichts mehr und erzeugt denselben Stand.

  Gegengeprueft: 131 Fassungs-Ueberschriften vorher wie nachher, die Fassungen ab 11.2.3 bitgleich, 0 leere Eintraege uebrig.

  Worauf beim Testen zu achten ist: `CHANGELOG.md` von unten nach oben durchblaettern - vor 11.2.3 stand dort ueberwiegend nichts, jetzt steht ueberall der Text, der damals geschrieben wurde.


## 11.2.6

- **Fix**: Aufzaehlungen in Patchnotes bleiben im Changelog Aufzaehlungen.

  Der neue Sammler zieht Zeilen innerhalb eines Absatzes zusammen, damit ein Eintrag nicht in Einzelzeilen zerfaellt. Bei einer Liste ist das genau falsch: in v11.2.5 landeten die fuenf Spiegelstriche einer Patchnote als ein einziger Absatz hintereinander weg.

  Jetzt beginnt eine Zeile mit "- ", "* " oder "1. " eine neue Ausgabezeile; eingerueckte Fortsetzungen haengen sich an ihren eigenen Punkt. Fliesstext wird weiterhin zusammengezogen.

  Diese Patchnote pruft es gleich selbst:

  - erster Punkt
  - zweiter Punkt, der absichtlich ueber zwei Zeilen geht und hier weiterlaeuft
  - dritter Punkt

  Stehen die drei nach dem Release untereinander, stimmt es; stehen sie in einer Zeile, nicht.


## 11.2.5

- **Fix**: `odoo setting KEY VALUE` schreibt nichts - die Doku und die Hilfe des Befehls lehrten trotzdem genau diese Form.

  `_parse_settings` teilt an `=`. Ein Argument ohne Gleichheitszeichen landet im LESE-Modus, `odoo setting DEVMODE 1` liest also die zwei Einstellungen "DEVMODE" und "1" und schreibt nichts. Ohne Fehlermeldung: der Befehl endet mit 0 und gibt nichts aus, weil ungesetzte Schluessel eben leer sind.

  Nachgemessen am 06.09.2026 mit einem bedeutungslosen Schluessel: `odoo setting ZZTESTKEY 7` hinterlaesst 0 Zeilen in der Einstellungsdatei, `odoo setting ZZTESTKEY=7` hinterlaesst `ZZTESTKEY=7`.

  Korrigiert an 18 Stellen in der Doku und in der Hilfe des Befehls selbst - die fuehrte beide Formen als gleichwertige Beispiele auf und stand damit im Widerspruch zum eigenen Rumpf.

  Beim Durchsehen der uebrigen Doku (01 bis 10) ausserdem:

  - `odoo odoo-shell` gibt es nicht. So heisst der Befehl nur in zodoos interner Registry (`Commands.register(shell, "odoo-shell")`); tippen muss man `odoo shell`. Die CLI weist die dokumentierte Form ab. - Der Odoo-Container heisst `<projekt>_odoo`, nicht `<projekt>_odoo_1`. - `ODOO_INSTALL_LIBPOSTAL` ist wirkungslos - nichts liest die Einstellung mehr, sie wird aus settings.txt aber weiter in jedes Projekt geschrieben. Als wirkungslos markiert statt stillschweigend entfernt. - Der Registry-Abschnitt erklaerte, warum `docker login` nichts beweist, aber nicht die haertere Folge: der klassische docker-Client bekommt auf `/v2/` eine 200, schickt daraufhin die ganze Sitzung OHNE Zugangsdaten und scheitert erst am Manifest mit 401. Dafuer gibt es `registry-push.zebroo.de` (derselbe Server, verlangt ueberall Anmeldung). Beide Namen am 06.09.2026 nachgeprueft: 200 gegen 401. - `docs.zebroo.de` war als "blockiert" gefuehrt; die Seite gibt es gar nicht mehr.

  Worauf beim Testen zu achten ist: `odoo setting --help` nennt jetzt nur noch die Form mit Gleichheitszeichen und sagt ausdruecklich, was ohne passiert.
- **Docs**: Die pgBackRest- und Offsite-Doku sagt jetzt, was der Code tut. An drei Stellen sagte sie das Gegenteil.

  Aufbewahrung: Doku und der in jede Instanz-Konfiguration gerenderte Kommentar behaupteten "Retention lives on the backup server" und "PGBR_RETENTION_* are therefore ignored in this mode" - und direkt darunter standen die Retention-Zeilen. Richtig ist: `expire` muss `backup.info` LESEN, und die ist clientseitig verschluesselt. Bei `BACKUP_FROM=here` (gepusht) hat nur die Instanz die Passphrase, also gehoert die Aufbewahrung dorthin; nur bei `BACKUP_FROM=repo-host` (gezogen) haelt der Backup-Server sie und kann selbst aufraeumen. Bis 31.08.2026 stand sie nirgends, und expire lief entsprechend nirgends.

  Dazu ausgeraeumt: die Lesart, die Instanz koenne ihre Historie nicht loeschen. Sie kann - mit ihrem eigenen Zertifikat und ihrer Passphrase, ausprobiert. Was schuetzt, ist der unveraenderliche Zweitbestand, nicht eine fehlende Konfigurationszeile.

  Offsite: der GEMISCHTE Fall fehlte ganz - Datenbank ueber pgBackRest, nur der Filestore write-only. Das ist unser Normalaufbau und war zugleich der, der nichts sicherte. Jetzt steht da, welcher Strom wann laeuft und welche zwei Faelle seit 05.09.2026 absichtlich laut sind.

  Beim Durchsehen aufgefallen und ergaenzt:

  - `PGBR_ARCHIVE_PUSH_QUEUE_MAX` stand in keiner Doku. Das ist die Einstellung, bei deren Ueberschreiten pgbackrest die GANZE WAL-Warteschlange wegwirft und postgres Erfolg meldet - der einzige Ausfall im System, der die Punkt-genau-Wiederherstellung still zerstoert. Mit dem Hinweis, dass man ihn pro Maschine an den echten freien Platz von pg_wal setzt. - Sechs Befehle fehlten in der Liste, darunter `verify` und `repo-verify` - also ausgerechnet die beiden, die pruefen, ob die Sicherung etwas taugt. Mit den zwei Fallen von `repo-verify`: es endet auch bei Maengeln mit 0, und ein heiler Bestand erzeugt gar keine Statuszeile.

  Worauf beim Testen zu achten ist: `odoo reload` auf einer Instanz mit Repo-Host erzeugen und in der gerenderten `pgbackrest.conf` nachsehen - der Kommentarblock ueber den `repo1-retention-*`-Zeilen muss jetzt zu ihnen passen.


## 11.2.4

- **Fix**: Cronjobs auf den Instanzen melden jetzt, wenn sie scheitern - und eine Datei im Projektverzeichnis kann den zodoo-Start nicht mehr verhindern.

  Was passiert war: In einem Projektverzeichnis lag ein odoo-shell-Schnipsel namens `inspect.py`. Der Cron-Daemon ruft seine Jobs als `cd /opt/src; odoo -p <projekt> ...` auf; damit steht das Projektverzeichnis vorn in sys.path, und Pythons `import inspect` erwischte den Schnipsel statt der Standardbibliothek. zodoo starb beim Start mit "NameError: name 'env' is not defined", Rueckgabewert 1.

  Betroffen war damit JEDER Job dieser Instanz: keine pgBackRest-Sicherung, kein check, kein Offsite-Lauf, keine naechtlichen Dumps - zwei Naechte lang. Aufgefallen ist es nur, weil beim Nachsehen einer ganz anderen Sache auffiel, dass im Repository seit zwei Tagen keine Sicherung mehr lag.

  Warum es niemand merkte: der Daemon rief `os.system()` auf und warf den Rueckgabewert weg. Im Protokoll stand deshalb dieselbe Zeile wie bei Erfolg - "Execution took 0.04 seconds".

  Zwei Aenderungen:

  - Der Aufruf setzt `PYTHONSAFEPATH=1`. Das Projektverzeichnis kommt damit nicht mehr auf sys.path; welches Projekt gemeint ist, sagt ohnehin `-p`. - Rueckgabewerte werden ausgewertet und ein gescheiterter Job als FEHLER protokolliert, mit Job-Name, Rueckgabewert und Befehl.

  Worauf beim Testen zu achten ist: eine Datei mit dem Namen eines Standardmoduls (`inspect.py`, `grp.py`, `types.py`, ...) im Projektverzeichnis darf die Cronjobs nicht mehr stoeren. Und ein absichtlich fehlschlagender Job muss im Container-Protokoll als ERROR auftauchen statt als stiller Erfolg.


## 11.2.3

- **Fix**: Mehrzeilige Patchnotes landen wieder im Changelog. Bisher wurden sie stillschweigend weggeworfen.

  Die Release-Automatik las die Beschreibung mit `grep '^description:' | sed 's/description: *//'`. Bei der YAML-Blockschreibweise `description: |` steht in dieser Zeile aber nur ein Pipe-Zeichen - der eigentliche Text folgt eingerueckt darunter. Ergebnis war ein Changelog-Eintrag "- **Fix**: |", und zwar bei JEDER mehrzeilig geschriebenen Patchnote. Am 06.09.2026 waren 36 der 308 Eintraege so leer.

  Aufgefallen ist es nur zufaellig, weil beim Nachsehen einer Version die Changelog-Ausgabe angeschaut wurde. Ein Changelog liest im Alltag niemand gegen, deshalb konnte das lange laufen.

  Jetzt liest `scripts/collect_patchnotes.py` die Fragmente mit einem YAML-Parser, zieht Absaetze sauber zusammen und bricht ab, wenn eine Beschreibung fehlt oder leer ist - lieber ein roter Release-Lauf als ein leerer Eintrag.

  Worauf beim Testen zu achten ist: Dieser Eintrag hier ist selbst mehrzeilig. Steht er nach dem naechsten Release vollstaendig im CHANGELOG.md, hat die Korrektur funktioniert; steht dort "- **Fix**: |", nicht.

  Die 36 alten Eintraege bleiben vorerst leer. Ihre Fragmente liegen noch in der Git-Historie (jeweils im Eltern-Commit des Release-Commits), sie liessen sich also nachtraeglich rekonstruieren - das ist ein eigenes Vorhaben.


## 11.2.2

- **Fix**: `odoo offsite backup` sichert jetzt auch dann, wenn nur EIN Strom write-only konfiguriert ist. Bisher hat es in dem Fall gar nichts gesichert und trotzdem Erfolg gemeldet.

  Hintergrund: die Weiche verlangte `wo_files && wo_db` - also dass BEIDE Stroeme (Filestore und Datenbank) ein write-only Ziel haben. Unser Normalaufbau ist aber ein anderer: die Datenbank geht ueber pgBackRest, nur der Filestore geht offsite. `OFFSITE_WO_DB_RECIPIENT` ist dann absichtlich leer. Damit fiel der Lauf durch auf die Pruefung von `OFFSITE_REPO`, die im write-only Aufbau ebenfalls leer ist - und stieg mit einer Meldung auf stdout und Rueckgabewert 0 aus.

  Der naechtliche Cronjob (`CRONJOB_OFFSITE_BACKUP`, 04:00) hat das jede Nacht getan und jedes Mal Erfolg gemeldet. Aufgefallen ist es nur daran, dass die angemeldeten Bereiche auf dem Backup-Server nach Tagen noch 0 Dateien hatten - beide Instanzen, seit dem 01. bzw. 02.09.2026, kein einziger PUT beim Empfaenger. Der Filestore war die ganze Zeit vollstaendig konfiguriert; er wurde nur nie angefasst.

  Neu:

  - Ist nur der Filestore write-only und die Datenbank liegt bei pgBackRest (`RUN_PGBACKREST=1`), laeuft der Filestore-Strom. Kein restic, keine Passphrase noetig.
  - Ist nur der Filestore write-only und die Datenbank ist durch NICHTS gedeckt, bricht der Lauf ab. Die Anhaenge allein hochzuladen sieht aus wie ein Backup und ist keins.
  - `RUN_OFFSITE=1` ohne jedes Ziel ist jetzt ein FEHLER statt eines stillen Erfolgs. Wer ein Offsite-Backup anfordert und keins bekommt, soll das merken. Der leise Fall bleibt `RUN_OFFSITE=0` - der steigt weiter wortlos aus, damit Projekte ohne Offsite-Ziel nicht jede Nacht einen Cron-Fehler melden.

  Worauf beim Testen zu achten ist: auf einer Instanz mit pgBackRest und angemeldetem Filestore-Ziel `odoo offsite backup` von Hand starten. Danach muessen im Bereich auf dem Backup-Server Objekte liegen (vorher 0 Dateien). Wer ein `RUN_OFFSITE=1` ohne Ziel stehen hat, bekommt ab jetzt jede Nacht einen Cron-Fehler - das ist beabsichtigt und weist auf eine unfertige Anmeldung hin.


## 11.2.1

- **Fix**: Die postgres-Abbilder stehen jetzt auf Debian 12 "bookworm" statt auf "bullseye".

  Grund: **Debian 11 bullseye hat am 31.08.2026 sein Lebensende erreicht.** Seit September gibt es keine Sicherheitsaktualisierungen mehr, und der Paketbestand wird abgeraeumt. Der Index wird noch ausgeliefert, die Pakete dahinter nicht - `apt-get install` scheitert mit

  E: Failed to fetch .../debian-security/pool/.../libperl5.32_...deb  404

  und zwar je nach Paket mal so und mal so. Jeder Neubau war damit ein Gluecksspiel.

  Betrifft alle sechs Fassungen (11, 12, 13, 14, 16, 17). Vorher geprueft: fuer jede gibt es ein `postgres:<n>-bookworm`, und pgdg liefert dort alle benoetigten Pakete - `pgbackrest=2.59.1-1.pgdg12+1`, postgis, pgvector und server-dev. Die alten Postgres-Fassungen bekommen aeltere postgis- und pgvector-Staende (11 etwa postgis 3.3 statt 3.6); das ist die Folge davon, dass diese Postgres-Fassungen selbst am Ende sind, und kein Rueckschritt gegenueber bullseye.

  Nachgestellt und bestaetigt: auf `postgres:17-bookworm` installieren sich alle Pakete, und pgbackrest UEBERLEBT den Aufraeum-Block aus purge und autoremove. Damit ist auch klar, was pgbackrest vorher hat verschwinden lassen - nicht das Aufraeumen, sondern die gescheiterte Installation, deren Fehler das Semikolon vor `rm -rf` verschluckt hat. Der Nachweis-Schritt aus dem vorigen Patch faengt genau diesen Fall.

  Worauf beim Testen zu achten ist: `odoo build` muss durchlaufen, und in der Ausgabe steht am Ende die pgbackrest-Version. Die Abbilder werden dabei neu gebaut, das dauert laenger als sonst.


## 11.2.0

- **Feature**: Router: Redirect-vHosts koennen jetzt auf eine bestimmte Seite zeigen, nicht nur auf eine andere Domain.

  Bisher hat das `redirect`-Template den Pfad des Aufrufs immer an das Ziel angehaengt (`$request_uri`). Fuer "Domain A zeigt auf Domain B" ist das richtig, fuer "Domain A zeigt auf genau diese Seite" nicht: aus `redirect_to: zebroo.de/zebroo-experience` wurde beim Aufruf von `/` die Adresse `zebroo.de/zebroo-experience/` und beim Aufruf von `/irgendwas` entsprechend `zebroo.de/zebroo-experience/irgendwas` - beides Adressen, die es beim Ziel so nicht gibt.

  Steht im `Redirect To` ein Pfad (also ein `/` im Wert), wird `$request_uri` jetzt weggelassen und alles landet genau auf der angegebenen Seite. Ohne Pfad bleibt es beim alten Verhalten.

  Zum Nachschauen: hosting.zebroo.de -> Web Router -> Virtual Hosts, ein vHost mit Template "Redirect". Bei `Redirect To` einen Pfad mitgeben, z.B. `zebroo.de/zebroo-experience`, deployen, dann die Domain aufrufen - der Browser muss direkt auf der Zielseite stehen (eine Weiterleitung, kein angehaengter Pfad, kein 404). Bestehende Redirects ohne Pfad im Ziel erzeugen unveraenderte nginx-Dateien.
- **Fix**: Das postgres-Abbild wird jetzt beim BAUEN darauf geprueft, dass pgbackrest wirklich drin ist.

  Hintergrund: der Installations- und Aufraeumblock in `postgres/Dockerfile.*` endet mit `find ... 2>/dev/null;` - einem SEMIKOLON. Der Rueckgabewert des ganzen RUN ist damit der des abschliessenden `rm -rf`, und der gelingt praktisch immer. Scheitert weiter oben etwas - etwa `apt-get install pgbackrest=<version>-*`, weil der Debian-Spiegel diese Version nicht mehr fuehrt - dann baut das Abbild trotzdem durch, nur ohne pgbackrest.

  Was man dann sieht, ist nicht der Bau, sondern der Betrieb: das archive_command stirbt mit `pgbackrest: command not found` (exit 127), und in den Protokollen steht "WAL segment was not archived before the 60000ms timeout". Das sieht nach einem Zeitproblem aus und ist keins - wer darauf den `archive-timeout` hochsetzt, meldet denselben Ausfall nur spaeter.

  Am 04.09.2026 hat genau das die pgBackRest-e2e-Tests gekippt, auf `main` und auf einem Zweig, im selben Commit einmal rot und einmal gruen - und vorher eine echte Instanz getroffen, deren Archivierung nach dem Bauen nie lief.

  Worauf beim Testen zu achten ist: der Bau bricht jetzt mit `command -v pgbackrest` ab, wenn die Binaerdatei fehlt. In der Bauausgabe steht danach die pgbackrest-Version - taucht sie nicht auf, ist das Abbild nicht brauchbar. Betrifft alle sechs Postgres-Fassungen (11 bis 17).

  Ausserdem: `postgres/**` fehlte in den Pfadfiltern des Bake-Tests. Eine Aenderung an den postgres-Dockerfiles - also genau an den Abbildern, die dieser Test baut - hat den Test bisher NICHT ausgeloest. Aufgefallen daran, dass dieser PR zuerst ohne Bake durchlief.
- **Internal**: Die deutschen Funktionsnamen im pgBackRest-Teil heissen jetzt englisch.

  Rein mechanisch, kein Verhalten geaendert - aber es betrifft Namen, die in Tracebacks und Logzeilen auftauchen, deshalb hier vermerkt:

  _aus_umschlag                        -> _from_envelope _bench_umgebung                      -> _bench_environment _bestandsname                        -> _store_name _check_ablegen                       -> _record_check _luecken                             -> _wal_gaps _nach_verwurf_vollsicherung           -> _full_backup_after_drop _verify_ausgabe_lesen                -> _read_verify_output neuester_umschlag                    -> newest_envelope umschlag_bereiche                    -> envelope_areas umschlag_oeffnen                     -> open_envelope _spool_und_verworfen                 -> _spool_and_dropped _passphrase_aus_umgebungen_entfernen -> _strip_passphrase_from_environments _passphrase_injizieren               -> _inject_passphrase

  Eine Aenderung ist mehr als ein Name: das Ergebnisfeld `wal_luecken` heisst jetzt **`wal_gaps`**. Es steht in den Ergebnisdateien von `odoo pgbackrest repo-verify`. Geprueft, dass es auf dem Pruefstand niemand ausliest (die Auswertung dort nimmt `result` und `kind`) - wer eigene Auswertungen darauf gebaut hat, muss nachziehen.

  Deutsche PROSA in Kommentaren und in den HELP-Texten der Kennzahlen bleibt absichtlich stehen. Das sind Begruendungen fuer uns, keine Bezeichner, und die HELP-Texte liest ein Mensch in Grafana - sie zu uebersetzen haette Erklaerungen gekostet, ohne etwas zu verbessern.


## 11.1.1

- **Fix**: WAL-Verwurf: die Grenze war zu eng, der Kommentar daneben falsch, und nach einem Verwurf passierte nichts.

  Hintergrund. `archive-push-queue-max` ist keine Bremse, sondern ein Verlustmechanismus. pgBackRest sagt es selbst:

  "pgBackRest will notify PostgreSQL that the WAL was successfully archived, then DROP IT. [...] In asynchronous mode the entire queue will be dropped."

  Wird der Spool groesser als die Grenze, wird also die GANZE Warteschlange weggeworfen und postgres bekommt Erfolg gemeldet. Es fehlt danach nicht eine Datei, sondern ein Stueck Kette - und ab da ist keine Wiederherstellung auf einen Zeitpunkt mehr moeglich, bis eine neue Basissicherung existiert.

  Drei Aenderungen:

  1. `PGBR_ARCHIVE_PUSH_QUEUE_MAX` steht jetzt auf 16GB statt 1GB. Die Grenze soll die Platte schuetzen; bei 1GB griff sie, waehrend noch Dutzende Gigabyte frei waren. Ein Netzproblem von einer Stunde auf einer belebten Instanz reichte, um die Kette zu reissen. Der Wert gehoert pro Maschine an den ECHTEN freien Platz von pg_wal angepasst - 16GB ist ein Kompromiss, keine Wahrheit.

  2. Neu: `PGBR_ARCHIVE_PUSH_BATCH_SIZE` (256MB). Die Grenze wird nur zu BEGINN eines Laufs geprueft; mit pgBackRests Vorgabe von 16GiB je Lauf kann die Warteschlange weit darueber hinauswachsen, bevor jemand wieder nachsieht. Ein kleinerer Stapel laesst den Prozess enden und neu starten, und damit erneut pruefen.

  3. Nach einem Verwurf stoesst der stuendliche `odoo pgbackrest check --record` eine Vollsicherung an - die Kette ist ohnehin gerissen, und je frueher die neue Basis steht, desto kleiner das Loch. Zwei Bedingungen verhindern, dass das schadet: es zaehlt der ANSTIEG des Zaehlers (sonst liefe jede Stunde eine Vollsicherung, solange er ueber Null steht), und der Spool muss LEER sein (sonst verlaengert die Vollsicherung die Warteschlange und provoziert den naechsten Verwurf; dann wartet sie auf den naechsten Lauf).

  Worauf beim Testen zu achten ist: in der erzeugten `pgbackrest.conf` der Instanz muessen jetzt beide Zeilen stehen, `archive-push-queue-max` und `archive-push-batch-size`. Der Zustand des Verwurf-Zaehlers liegt in `<run>/pgbackrest-verwurf.json`; beim ersten Lauf wird er nur gemerkt, damit ein Altbestand im Logfile nicht als frischer Anstieg gilt.

  Ausserdem korrigiert: der Kommentar in `pgbackrest.conf.template` behauptete, die Grenze lasse `archive-push` "laut scheitern" - das Gegenteil trifft zu. Wer danach den Wert einstellte, hielt den gefaehrlichsten Zustand der Anlage fuer einen lauten Fehler.

  Dazu ein Riegel in `_render_conf()`: die Vorlage wird mit `safe_substitute` gefuellt, und ein Platzhalter ohne Wert bleibt dort WOERTLICH stehen. In der erzeugten Datei steht dann z.B. `archive-push-batch-size=${PGBR_ARCHIVE_PUSH_BATCH_SIZE}`, pgbackrest verwirft die Zeile als ungueltige Groesse, und JEDER archive-push scheitert - sichtbar erst als "WAL segment was not archived before the timeout", weit weg von der Ursache. Genau so ist diese Option beim ersten Anlauf in die Vorlage geraten, ohne dass sie im Wertepaar-Verzeichnis stand. Bleibt jetzt ein Platzhalter uebrig, scheitert `odoo reload` laut und nennt den Namen, statt eine Instanz mit kaputter Archivierung hochzufahren.


## 11.1.0

- cadvisor verbrennt auf Hosts mit Docker-zfs-Storage-Driver nicht mehr dauerhaft einen ganzen CPU-Kern pro Instanz.

  Hintergrund: fuer die Dateisystem-Metriken pro Container fragt cadvisor ZFS ab und iteriert dabei ueber tausende Layer-Datasets. Neben dem cadvisor-Prozess selbst haengen zwei zfs-Prozesse mit je 100 Prozent CPU daran, und zwar rund um die Uhr. Gemessen auf hy-odooprod: 7 Tage 14 h CPU-Zeit in 13 Tagen Laufzeit. Mit zwei Instanzen mit Dashboard-Stack lag die Maschine bei Load 14 statt der ueblichen 2,5, und SSH-Verbindungen brachen zeitweise weg. Aufgefallen ist es erst nach 13 Tagen - solange nichts ausfaellt, sieht niemand auf die Last.

  Der cadvisor-Container bekommt deshalb vier Argumente mit:

  --disable_metrics=disk,diskIO     container_fs_* und container_blkio_* raus --housekeeping_interval=30s       Default war 1s --docker_only=true                keine fremden cgroups scannen --store_container_labels=false    weniger Kardinalitaet

  Zum Nachsehen, auf einem Host mit Dashboard-Stack:

  docker stats --no-stream <projekt>_cadvisor pgrep -c zfs

  Erwartet werden 0,8 bis 3 Prozent CPU statt der bisherigen 100+ Prozent, und keine dauerhaften zfs-Prozesse mehr. Wer es genauer will, vergleicht die CPU-Zeit ueber einige Minuten:

  ps -o etime=,time= -p $(docker inspect <projekt>_cadvisor -f '{{.State.Pid}}')

  Worauf zu achten ist: in zodoo-overview.json bleiben die beiden Panels leer, die container_fs_reads_bytes_total und container_fs_writes_bytes_total abfragen. Die uebrigen vier Panels (CPU, Speicher, Netz rein/raus) haben weiter Daten, das Prometheus-Target bleibt up.

  Das ist bewusst so: den Pool-Fuellstand und die ZFS-Statistik liefert der node_exporter ohnehin, mit node_filesystem_* und 266 node_zfs_*-Metriken - und das ist die Ebene, auf der Kapazitaet entschieden wird. Der Verbrauch pro Container-Layer ist dafuer redundant und war der teuerste Teil der Messung.

  Wer die beiden Panels wirklich braucht, kann disk/diskIO fuer eine einzelne Instanz wieder zulassen und nur das Housekeeping-Intervall stehen lassen - dann bleibt die ZFS-Iteration aber grundsaetzlich bestehen.
- **Feature**: Neuer Befehl `odoo pgbackrest envelope`: oeffnet einen age-Umschlag und gibt ein Feld aus - der Weg, eine Passphrase zurueckzubekommen.

  Hintergrund: `umschlag_oeffnen()` gab es schon, aber nur als Funktion, die der Pruefstand benutzt. Um von Hand an eine Passphrase zu kommen, musste man Python schreiben. Deshalb hat niemand den Umschlag als Ablageort betrachtet - und deshalb wurde die Passphrase zusaetzlich im Klartext gehalten, unter anderem in einem Odoo-Feld.

  Zum Ausprobieren, auf dem Pruefstand:

  odoo pgbackrest envelope --area <bereich> \ --bench-config /etc/pgbr-pruefstand/config.json

  gibt die Passphrase roh auf stdout aus, damit sie sich weiterverwenden laesst. `--field` waehlt ein anderes Feld, `--list-fields` zeigt die NAMEN ohne Werte.

  Worauf zu achten ist - der eigentliche Entwurfspunkt: der Befehl geht auch OHNE Pruefstand.

  odoo pgbackrest envelope --file <umschlag.age> --age-key <schluessel>

  Im Ernstfall ist der Pruefstand vielleicht genau das, was fehlt. Dann hat man den Schluessel aus dem Tresor und den Umschlag von irgendwo - aus dem Anhang am Projekt in hosting.zebroo.de, von der Backup-Maschine, aus dem Zweitbestand - und braucht sonst nichts.

  Fehlt der Schluessel, sagt der Befehl, wo er liegt (Pruefstand bzw. 1Password-Item). Fehlt ein Feld, nennt er die vorhandenen NAMEN - nie die Werte. Es wird nichts protokolliert: ein Geheimnis gehoert in kein Logfile.
- Einstellungsdateien mit der pgBackRest-Passphrase werden jetzt auch wirklich auf 0600 verengt.

  Hintergrund: zodoo verengt Einstellungsdateien, sobald ein Geheimnis darin steht - erkannt an Hinweiswoertern im Schluesselnamen (PASSPHRASE, PASSWORD, SECRET, TOKEN, PRIVATE_KEY). `PGBR_CIPHER_PASS` heisst weder ...PASSPHRASE noch ...PASSWORD und fiel deshalb durch dieses Raster - ausgerechnet die Passphrase, die den ganzen Datenbankbestand eines Kunden aufschliesst. Auf einer produktiven Instanz lag die Datei damit weiter auf 0664, gruppenschreibbar und fuer alle lesbar, gerettet allein von den Rechten des Home-Verzeichnisses.

  Zum Nachsehen: `ls -l ~/.odoo/settings.<projekt>` nach dem naechsten Schreibvorgang (etwa `odoo pgbackrest register` oder `odoo setting PGBR_CIPHER_PASS=...`). Vorhandene Dateien werden erst beim naechsten Schreiben verengt, nicht rueckwirkend - bei Bedarf einmal von Hand `chmod 600`.

  Zweite Aenderung im selben Zug: geprueft wird jetzt der WERT, nicht nur der Schluesselname. In jeder Projektdatei stehen `PGBR_CIPHER_PASS` und `DEFAULT_DEV_PASSWORD` auch dann, wenn sie leer sind - eine leere Passphrase ist kein Geheimnis. Vorher haette der bloss vorhandene Name genuegt.

  Worauf zu achten ist: das Hinweiswort ist "CIPHER_PASS" und nicht "CIPHER". Letzteres trifft auch `PGBR_CIPHER_TYPE`, und der hat IMMER einen Wert - damit waere jede Einstellungsdatei verengt worden, auch ohne Geheimnis darin. Der Bake-Lauf ist daran gescheitert.
- Die Passphrase steht nicht mehr in der gemounteten `pgbackrest.conf`, sondern nur noch in der Umgebung der zwei Dienste, die sie brauchen: `postgres` (dort laeuft das archive_command) und der pgbackrest-Sidecar.

  Hintergrund: die Datei wird nach `/etc/pgbackrest` der Container gemountet und muss fuer den Container-Benutzer lesbar bleiben, also 0644. Das Verzeichnis enger zu ziehen hilft nicht - dann kaeme der Container selbst nicht mehr hin. Ein Geheimnis gehoert also nicht in diese Datei.

  pgBackRest liest jede Option auch aus der Umgebung (`PGBACKREST_<OPTION>`). Nachgewiesen am 02.09.2026 mit einem echten `info` gegen ein verschluesseltes Repository, das allein mit `PGBACKREST_REPO1_CIPHER_PASS` geoeffnet wurde - ohne die Zeile in der conf.

  `repo1-cipher-type` bleibt in der Datei und in `[global]`: dort gehoert es laut pgBackRest-Handbuch hin, damit `info` jede Stanza lesen kann, und es ist kein Geheimnis.

  Zum Nachsehen nach `odoo reload`: `grep -c cipher-pass <run-dir>/pgbackrest/pgbackrest.conf` ergibt 0, und `grep -c PGBACKREST_REPO1_CIPHER_PASS <run-dir>/docker-compose.yml` ergibt 2.

  Worauf zu achten ist: gesetzt wird erst NACH den Ausstiegen der Funktion. Ist pgBackRest abgeschaltet, wandert die Passphrase in keine einzige Umgebung - auch nicht in die von postgres.


## 11.0.2

- Die Backup-Passphrase steht nicht mehr in der Umgebung jedes Dienstes.

  Hintergrund: zodoo haengt jedem Dienst die Einstellungsdatei als `env_file` an, und `docker compose config` loest sie auf. Damit stand `PGBR_CIPHER_PASS` in der erzeugten `docker-compose.yml` einmal pro Dienst - auf einer produktiven Instanz 18 Mal - und in der Umgebung von Grafana, Proxy, Konsole, Cronjobs und allem anderen, das sie nie braucht. Die Datei liegt mit 0644 auf der Platte.

  Gebraucht wird sie dort NIRGENDS: gelesen wird sie beim Erzeugen der Konfiguration aus den Einstellungen, und getragen wird sie von der `pgbackrest.conf`, die nur dorthin gemountet wird, wo sie hingehoert.

  Zum Nachsehen: `grep -c PGBR_CIPHER_PASS <run-dir>/docker-compose.yml`. Vorher die Zahl der Dienste, nachher 0.

  Worauf zu achten ist: das Entfernen laeuft auch bei RUN_PGBACKREST=0. Sonst bliebe die leere Variable ueberall stehen und waere wieder da, sobald jemand die Funktion einschaltet.

  Zwei Stellen bleiben offen und gehoeren nicht hierher: die Einstellungsdatei selbst (auf odooprod 0664, gerettet nur vom Home mit 0750) und die gemountete `pgbackrest.conf`, die fuer den Container-Benutzer lesbar bleiben muss - enger ziehen laesst sie sich nur ueber das Verzeichnis, und das ist Sache des zodoo-Kerns.


## 11.0.1

- Der Code-/VSCode-Container einer Instanz startet wieder. Bisher ist er reproduzierbar mit Exit-Code 1 gestorben, im Log stand nur

  chown: invalid user: 'coder:coder'

  Ursache: das entrypoint-Skript legt einen unprivilegierten Benutzer `coder` mit der UID des Host-Eigentuemers an (`OWNER_UID`, in der Praxis fast immer 1000, weil das der erste Benutzer der Maschine ist). Das Basis-Image `gitpod/openvscode-server` bringt aber schon `openvscode-server` mit genau dieser UID mit, und `useradd -u` verweigert eine doppelte UID. Der Fehler wurde verschluckt (`2>/dev/null || true`), also existierte `coder` nie und das folgende `chown coder:coder` brach ab.

  Jetzt uebernimmt das Skript den Benutzer, der die UID bereits haelt, und legt `coder` nur an, wenn die UID frei ist. Die Gruppe wird ueber `id -gn` ermittelt statt gleich dem Benutzernamen angenommen.

  Zum Testen: an einer Instanz im CICD auf "Code" klicken. Der Container `<projekt>_coding` muss laufen bleiben (`docker ps`) und `/code/` die VSCode-Oberflaeche zeigen, statt in eine Fehlerseite zu laufen.
- **Fix**: Die docker-compose.yml wird nicht mehr aus einem Container heraus neu geschrieben, dessen Home vom Host-Home abweicht. Bind-Mount-Quellen loest der Docker-Daemon auf dem Host auf; zodoo schrieb aber die Pfade, die es im Container sah - ein 'odoo reload' aus dem robot-Image (Home /opt/robot) machte aus jeder Quelle ein /opt/robot/.odoo/..., das es auf dem Host nicht gibt. Die Container starteten danach ohne ihren Code und starben mit 'ModuleNotFoundError: No module named zodoo'; sichtbar war nur, dass die Instanz nicht mehr antwortet. Das Schreiben bricht jetzt mit einer Meldung ab, die beide Pfade nennt. Zum Pruefen: 'odoo reload' auf dem Host laeuft unveraendert durch; aus einem Robot-/Console-Container heraus kommt der Abbruch mit Erklaerung. Befehle, die nur mit einer laufenden Instanz sprechen (odoo shell, psql, robot run), sind nicht betroffen, und ZODOO_ALLOW_CONTAINER_RECONFIG=1 hebt die Pruefung auf.


## 11.0.0

- **BREAKING**: Die Aufbewahrung wird jetzt auch dann in die pgbackrest.conf der Instanz geschrieben, wenn gegen einen Repo-Host gesichert wird (BACKUP_FROM=here). Vorher blieb sie dort weg - und lief damit NIRGENDS.

  Hintergrund: die Begruendung war, die Aufbewahrung gehoere der Maschine, der die Platte gehoert, und der Backup-Server fahre seinen eigenen `expire`. Das klingt richtig und funktioniert bei einem VERSCHLUeSSELTEN Repository nicht: `expire` muss `backup.info` lesen, und die ist clientseitig verschluesselt. Auf dem Repo-Host endet der Versuch mit `FormatError: key/value found outside of section at line 1: Salted__...` - genauso wie `verify`. Dass er die Datei nicht oeffnen kann, ist der Sinn des Aufbaus und kein Mangel.

  Folge bis 2026-08-31: kein einziger `expire` lief, der Bestand wuchs unbegrenzt, und die Dokumentation versprach 14 Tage. Genau der Fehler, vor dem der Kommentar in `_retention_lines` seit jeher warnt - eine Aufraeumung, die eingerichtet, aber nie wirksam war.

  ACHTUNG, das ist der breaking-Teil: nach `odoo reload && odoo up -d` beginnt die Instanz, Sicherungen aelter als `PGBR_RETENTION_FULL` (Vorgabe 14 Tage) zu entfernen - beim naechsten Sicherungslauf, denn pgBackRest laesst `expire` ohnehin mitlaufen. Wer laenger vorhalten will, setzt die Zahl VORHER. Empfehlung: einmal `odoo pgbackrest info` ansehen und pruefen, was wegfaellt.

  Neue Loeschbefugnis entsteht dadurch nicht: `odoo pgbackrest expire` gibt es auf der Instanz laengst, und der unveraenderliche Zweitbestand nimmt an einem `expire` ohnehin nicht teil - dort wird nichts geloescht.

  Bei `BACKUP_FROM=repo-host` (der Server zieht) bleibt die Aufbewahrung weiterhin drueben; dort weist der Reload jetzt darauf hin, dass sie mit einem verschluesselten Repository nicht durchsetzbar ist.


## 10.9.1

- `odoo pgbackrest repo-verify` hielt beim ersten echten Lauf JEDEN gesunden Bestand fuer kaputt. Behoben - und dabei kam heraus, wonach eigentlich zu suchen ist.

  Die Annahme war, `pgbackrest verify` gebe je Bereich ein Urteil ("status: ok" bzw. "status: error") aus. Das tut es nur, wenn etwas nicht stimmt. Bei heilem Bestand protokolliert es die gefundenen WAL-Bereiche und endet - ohne Statuszeile. Wer auf "ok" wartet, meldet also jeden gesunden Bestand als Fehlschlag, und ein Waechter, der grundlos schreit, wird nach der dritten Meldung abgeschaltet.

  Gelesen wird jetzt auf PROBLEME statt auf ein Urteil. Ein Lauf ohne "verify command end" gilt weiterhin als Fehlschlag: kein Ende heisst, wir wissen nichts - nicht "heil".

  Neu und eigentlich der Gewinn: das Ergebnis fuehrt die zusammenhaengenden WAL-Abschnitte (`wal_bereiche`) und ihre Zahl (`wal_luecken`). Steht dort mehr als ein Abschnitt je archiveId, FEHLEN WAL-Segmente dazwischen, und zwischen zwei Abschnitten laesst sich auf keinen Zeitpunkt wiederherstellen. Dafuer laeuft verify jetzt mit `--log-level-console=detail` - auf INFO stehen die Bereiche gar nicht im Log.

  Beim ersten Lauf auf dem Pruefstand hat genau das zugeschlagen und im Testbereich drei Abschnitte statt einem gefunden.

  Worauf zu achten ist: eine Luecke ist KEIN Fehlschlag. Vor der ersten Sicherung ist sie normal, und pgBackRest nennt sie ebenfalls nicht Fehler. Sie wird gezaehlt und gemeldet (gelbe Zeile mit den Abschnitten), damit jemand hinsieht - nicht, damit ein Alarm losgeht.


## 10.9.0

- **Feature**: Die Instanz meldet jetzt auch den Zustand der WAL-ARCHIVIERUNG, nicht nur den ihrer Sicherungen - und prueft stuendlich selbst, ob der Weg zum Repository ueberhaupt funktioniert.

  Hintergrund: bisher sagten die Kennzahlen, WANN zuletzt gesichert wurde. Eine Instanz kann aber taeglich sichern und trotzdem seit Tagen kein WAL mehr loswerden - dann gibt es Basisstaende, aber keinen lueckenlosen Weg dazwischen, und Wiederherstellung auf einen Zeitpunkt ist nicht mehr moeglich. Auf dem Backup-Server faellt ein stehengebliebener Archivierer erst nach Stunden auf, in der Instanz selbst bisher gar nicht.

  Neu in `odoo backup-metrics`: `zodoo_wal_archived_total`, `zodoo_wal_failed_total`, `zodoo_wal_last_archived_timestamp_seconds`, `zodoo_wal_last_failed_timestamp_seconds` (aus `pg_stat_archiver`), `zodoo_wal_spool_files` (wartende Segmente), `zodoo_wal_dropped_total` und `zodoo_backup_check_success` / `zodoo_backup_check_timestamp_seconds`.

  `zodoo_wal_dropped_total` ist die wichtigste davon: sie zaehlt, wie oft pgBackRest WAL WEGGEWORFEN hat, weil `archive-push-queue-max` ueberschritten war. In dem Fall meldet pgBackRest postgres ERFOLG, postgres gibt das Segment frei, danach laeuft alles weiter und sieht frisch aus - die Luecke faellt erst beim Wiederherstellen auf. Der Kompromiss ist bewusst so gewaehlt (sonst laeuft die Instanzplatte voll), aber jeder Anstieg dieses Zaehlers ist ein Zwischenfall.

  Zum Ausprobieren: `odoo backup-metrics --stdout` zeigt die Datei, ohne sie zu schreiben. Der neue Zeitplan `CRONJOB_PGBACKREST_CHECK` laeuft stuendlich (`odoo pgbackrest check --record`) und legt sein Ergebnis unter `<run>/pgbackrest-check.json` ab; von Hand geht das mit demselben Befehl.

  Worauf zu achten ist: laesst sich ein Wert nicht lesen, wird die Zeile WEGGELASSEN statt auf 0 gesetzt. Eine 0 bei "fehlgeschlagen" saehe aus wie "alles gut" - und das ist genau der Zustand, den diese Kennzahlen aufdecken sollen.


## 10.8.0

- **Feature**: Neuer Befehl `odoo pgbackrest repo-verify --bench-config <datei>`: prueft die abgelegten Bytes selbst - Luecken im WAL, beschaedigte Bloecke in aelteren Sicherungen.

  Hintergrund: die Rueckspielprobe (`verify`) faehrt die NEUESTE Sicherung hoch und spielt kein WAL nach. Sie beweist "die juengste Sicherung laeuft an" - nicht "PITR ueber die Aufbewahrungszeit funktioniert" und nicht "die aelteren Sicherungen sind heil". Genau dafuer gibt es `pgbackrest verify`, und es lief bei uns bisher nirgends.

  Zum Ausprobieren: auf dem Pruefstand `odoo pgbackrest repo-verify --bench-config /etc/pgbr-pruefstand/config.json`. Laeuft ueber alle Bereiche, die sich aus den Umschlaegen ergeben, und legt mit `--report-to` je Bereich und Bestand einen Nachweis ab.

  Worauf zu achten ist - zweierlei:

  Erstens laeuft das NUR im Pruefstandsbetrieb, nicht auf dem Repo-Host. Der hat die Passphrase bewusst nicht, und `verify` muss die Dateien lesen, um ihre Pruefsummen nachzurechnen. Dort aufgerufen meldet es nur "No usable backup.info file" - was aussieht wie ein kaputtes Repository, aber nur heisst, dass der Host tut, was er soll.

  Zweitens meldet `pgbackrest verify` ein `status: error` und beendet sich trotzdem mit 0 ("completed successfully"). Das Urteil wird deshalb aus der AUSGABE gelesen, nicht aus dem Rueckgabewert. Wer das andersherum baut, bekommt fuer ein kaputtes Repository ein gruenes Ergebnis - der stillste denkbare Fehlschlag. Eine Ausgabe ohne erkennbares Urteil gilt als Fehlschlag, nicht als heil.


## 10.7.2


- **Internal**: 'Der prebuild-Ablauf schiebt die Images jetzt ueber registry-push.zebroo.de statt ueber registry.zebroo.de. Der Pull-Weg bedient /v2/ und die zodoo-Abbilder bewusst anonym, damit eine frische Maschine ohne Zugangsdaten ziehen kann -- der klassische docker-Client schliesst daraus zu Beginn einer Push-Sitzung, dass keine Anmeldung noetig ist, und schickt danach gar keine Zugangsdaten mehr; das abschliessende Ablegen des Manifests scheitert mit 401. Nur Clients mit containerd-Bildspeicher sind davon nicht betroffen, was lange verschleiert hat, worum es geht. Der neue Name zeigt auf denselben Registry-Server, verlangt aber ueberall Anmeldung; gezogen wird weiter ueber den alten Namen, es ist derselbe Bestand. Ausserdem wird die Postgres-Fassung jetzt ausdruecklich gesetzt statt der Voreinstellung ueberlassen: die haengt an ~/.odoo/settings der bauenden Maschine, und auf einem anderen Rechner entstanden so Images fuer Postgres 14, die zu keiner Kundenmaschine passen. Steuerbar ueber die Repository-Variablen ZODOO_REGISTRY_PUSH_URL und ZODOO_PREBUILD_POSTGRES.'


## 10.7.1


- **Fix**: 'pgBackRest mit Repo-Host lief nach der Anmeldung nicht: die TLS-Schluessel gehoerten dem Betriebsbenutzer, pgBackRest verlangt aber einen Schluessel, der ihm selbst oder root gehoert (Fehler 42, ''key file ... must be owned by the pgbackrest user or root''), und das WAL-Archiv lief in den Zeitueberlauf (Fehler 82/103). Die Anmeldung meldete dabei Erfolg -- die Sicherung waere nachts still ausgefallen, und das faellt sonst erst am Tag der Wiederherstellung auf. Ursache: geschrieben werden die Dateien vom Betriebsbenutzer, der den Besitz gar nicht auf den pgbackrest-Benutzer vergeben DARF; das kann nur root. Kopieren ist kein Ausweg, weil der Schluessel 0600 ist und ein fremder Prozess ihn nicht einmal lesen kann. Der entrypoint laeuft als root und schreibt den Besitz jetzt um; dafuer ist der Mount von /etc/pgbackrest nicht mehr read-only. Damit eine erneute Anmeldung die Dateien noch ersetzen kann, loescht register sie vorher statt sie zu ueberschreiben. Zum Testen: nach der Anmeldung ein ''odoo reload && odoo up -d && odoo pgbackrest check'' -- muss ''completed successfully'' melden; danach zeigt ''odoo pgbackrest info'' cipher aes-256-cbc und eine Sicherung unter repo1.'


## 10.7.0

- **Feature**: Jeder Nachweis einer Rueckspielprobe sagt jetzt, aus WELCHEM Bestand er stammt - im Ergebnis (Feld `store`) und im Dateinamen (`<bereich>-<bestand>-<zeitstempel>.json`).

  Hintergrund: seit der Pruefstand beide Bestaende prueft (Repo-Host und gespiegelten Objektspeicher), entstehen je Bereich zwei Nachweise - und die sahen gleich aus. Die Ueberwachung nimmt je Bereich den juengsten BESTANDENEN; ein durchgefallener Zweitbestand verschwand damit hinter dem bestandenen Erstbestand. Ausgerechnet die Probe, die eine Vermutung durch einen Nachweis ersetzen soll, haette also wieder eine Vermutung gedeckt.

  Zum Ausprobieren: in der Pruefstand-Konfiguration `"store": "zweitbestand"` setzen (frei benennbar - `s3` unterscheidet zwei Objektspeicher nicht, sobald es zwei gibt) und einen Lauf mit `--report-to` machen. Im Ablageordner liegen danach zwei Dateien nebeneinander, deren Namen auseinanderhalten, was frueher uebereinander lag. Ohne Angabe bleibt die Art (`s3` bzw. `tls`), im Projektbetrieb steht `projekt`.

  Worauf zu achten ist: auch der FEHLERFALL traegt den Bestand. "Gescheitert" ohne die Angabe wo ist keine brauchbare Nachricht - und frueher war es genau der Pfad, der gar kein `store` gesetzt hat.


## 10.6.4


- **Internal**: 'Der prebuild-Ablauf misst jetzt zwei Dinge, um den unauthorized-Fehlschlag einzukreisen: einen direkten docker push unmittelbar nach der Anmeldung (trennt docker/Registry von unterwegs verloren) und einen zweiten Blick in ~/.docker/config.json nach dem Fehlschlag (zeigt, ob der Zugang zwischendurch ueberschrieben wurde).'


## 10.6.3


- **Internal**: Die Diagnosezeile im prebuild-Ablauf zeigt jetzt auch, ob der gespeicherte docker-Zugang einen gefuellten auth-Wert traegt (nie den Wert selbst). Ohne das war nicht zu unterscheiden, ob docker gar keinen Eintrag hat oder einen leeren -- ein leerer entsteht, wenn docker login gegen eine anonym bediente /v2/ laeuft und deshalb nie etwas beweisen musste.
- **Internal**: Die Diagnosezeile im prebuild-Ablauf war selbst fehlerhaft (doppelte Anfuehrungszeichen in einem doppelt gequoteten f-String) und riss den Schritt wegen set -e ab, bevor ueberhaupt gepusht wurde. Neu geschrieben ohne f-String und vor dem Committen ausprobiert.


## 10.6.2


- **Internal**: Der prebuild-Ablauf meldet Docker jetzt selbst am Registry an, statt sich darauf zu verlassen, dass zodoo es tut. Am 31.08.2026 meldete zodoo Stored registry credentials und der Push scheiterte trotzdem mit unauthorized; im Apache-Protokoll war zu sehen, dass die CI den 401 nie mit Zugangsdaten wiederholte, waehrend derselbe Push auf einem gewoehnlichen Linux mit denselben Daten durchging. Dazu gibt der Ablauf aus, was docker gespeichert hat (nur die Schluessel, nie die Werte), damit ein naechster Fehlschlag nicht wieder blind ist.


## 10.6.1

- **Fix**: Das Vorbauen der Images war gruen, aber in der Registry kam nichts an.

  "odoo build" laedt nicht selbst hoch: enqueue_registry_uploads benennt das Image lokal um, legt einen Auftrag in ${run}/jobqueue/ und startet einen ABGEKOPPELTEN Arbeiter. Auf einem GitHub-Runner endet der Job unmittelbar nach dem Bauen, der Arbeiter stirbt mit ihm -- und der docker push passiert nie.

  Nachweisbar am 28.08.2026: der Lauf lief durch, die Tag-Liste der Registry war danach unveraendert, und eine frisch aufgesetzte Kundenmaschine suchte weiterhin genau die Tags, die die CI selbst als "not in zodoo registry" gemeldet und gebaut hatte (postgres 17-20b751e7, cronjobs 17-ec190864, offsite e8e79952). Die Tags stimmen also ueberein -- es lud nur niemand hoch.

  Der eigentliche Grund lag noch eine Ebene tiefer: _get_push_credentials liest ZODOO_REGISTRY_SUGGESTED ausschliesslich aus ~/.odoo/settings (_read_user_setting). Der Ablauf setzte es mit "odoo setting" im Projekt -- also in ./.odoo/settings. Ist der Schluessel in der Benutzerdatei leer und haengt kein Terminal dran, steigt die Funktion stillschweigend aus: kein Push, keine Meldung, gruener Lauf.

  Der Ablauf schreibt die Registry-Einstellungen jetzt in ~/.odoo/settings und ruft am Ende zusaetzlich "odoo run-crontab", damit auch die in die Warteschlange gelegten Uploads noch im Vordergrund abgearbeitet werden, bevor der Runner abgeraeumt wird.


## 10.6.0


- **Feature**: 'Neuer Befehl `odoo backup-metrics`: schreibt Kennzahlen zur Sicherung fuer den textfile-Collector des node_exporter, damit ein Ausfall der Sicherung in der Ueberwachung auffaellt (alle fuenf Minuten aus den Cronjobs, CRONJOB_BACKUP_METRICS). Eine Instanz, deren Sicherung nicht laeuft, sieht von aussen aus wie jede andere -- sie antwortet, die Kurven sind gruen, und der Unterschied faellt genau einmal auf: an dem Tag, an dem jemand wiederherstellen will. Ausgegeben werden zodoo_backup_enabled{art}, zodoo_backup_query_success{art}, zodoo_backup_count{art}, zodoo_backup_last_success_timestamp_seconds{art} und zodoo_backup_last_full_timestamp_seconds{art}. Bewusst der ZEITPUNKT und nicht das Alter: das Alter bildet man mit time() - <wert> und es altert damit auch dann weiter, wenn der Schreiber selbst nicht mehr laeuft -- eine vorberechnete Alterszahl stuende dann fuer immer still auf ihrem letzten Wert und saehe gesund aus. Dagegen steht ausserdem zodoo_backup_metrics_written_timestamp_seconds. Gibt es gar keine Sicherung, fehlt die Zeitpunkt-Zeile statt auf 0 zu stehen (eine 0 hiesse 1970 gesichert); in PromQL greift dafuer absent(). Fuer offsite steht nur enabled drin, einen verlaesslichen Zeitpunkt gibt es dort nicht. Zum Testen: `odoo backup-metrics --stdout` zeigt ohne zu schreiben, was die Ueberwachung ueber die Instanz erfaehrt.'


## 10.5.0

- **Feature**: Der Pruefstand kann jetzt auch Bestaende in einem OBJEKTSPEICHER pruefen (S3 / MinIO), nicht nur ueber einen pgBackRest-Repo-Host.

  Hintergrund: der unveraenderliche Zweitbestand liegt auf einem MinIO mit Object Lock. Ohne diese Erweiterung haetten wir eine Kopie, von der niemand laufend nachweist, dass sich daraus zurueckspielen laesst - genau der Zustand, den wir beim ersten Bestand gerade behoben haben.

  Zum Ausprobieren: in der Pruefstand-Konfiguration `"repo_type": "s3"` setzen und `s3_endpoint`, `s3_bucket`, `s3_key`, `s3_key_secret` angeben, dazu optional `s3_path` (Praefix im Bucket) und `storage_ca_file`. Ein Client-Zertifikat entfaellt - ein Objektspeicher weist ueber ein Schluesselpaar aus.

  Worauf zu achten ist: `s3_uri_style` steht auf `path`, weil MinIO Buckets ueber den Pfad adressiert. Bei einem Anbieter mit eigenem DNS je Bucket waere `host` richtig. Und die Verschluesselung bleibt bei uns: der Speicher sieht Chiffrat, egal ob eigener MinIO oder fremder Anbieter.


## 10.4.0


- **Feature**: 'Der Prometheus einer Instanz kann jetzt eine Kopie seiner Messwerte an eine zentrale Ablage schicken (remote_write) -- gedacht fuer den Betrieb mehrerer Maschinen, die bisher zwar jede fuer sich alles gemessen haben, aber ohne Stelle, an der das zusammenlaeuft. Der lokale Prometheus bleibt unveraendert die Detailsicht vor Ort. Einschalten mit DASHBOARD_REMOTE_WRITE_URL (leer = aus, dann aendert sich nichts), dazu _USER/_PASSWORD fuer den Zugang und _INSTANZ fuer den Namen, unter dem die Maschine in der Ablage erscheint (Label instanz). _INSTANZ ist Pflicht, sobald eine URL steht, und faellt bewusst NICHT auf $PROJECT_NAME zurueck -- der heisst auf vielen Installationen ueberall gleich, und die Messwerte der ganzen Flotte laegen dann uebereinander, ohne dass es auffiele; fehlt der Name, bleibt remote_write aus und sagt warum. Auf DEVMODE-Maschinen ist es aus (DASHBOARD_REMOTE_FORCE_IN_DEVMODE=1 schaltet es zum Testen ein). Technisch wird prometheus.yml dafuer je Projekt nach $HOST_RUN_DIR/dashboard/prometheus.yml gerendert und der Mount darauf umgebogen; bisher hing fuer alle Projekte dieselbe Datei aus dem Images-Verzeichnis im Container, und die kann keine Werte je Maschine tragen. Ohne die Einstellung passiert das nicht und der bisherige Mount bleibt. Zum Testen: URL und _INSTANZ setzen, odoo reload, dann $HOST_RUN_DIR/dashboard/prometheus.yml ansehen -- remote_write und external_labels muessen drinstehen -- und in der Ablage pruefen, ob Messwerte mit dem eigenen instanz-Label ankommen; ohne _INSTANZ muss odoo reload rot melden und nichts schicken.'


## 10.3.0

- **Feature**: Der Pruefstand kann jetzt die age-Umschlaege des Anmeldedienstes oeffnen — und braucht dadurch KEIN eigenes Zertifikat mehr.

  Beim Freigeben eines Bereichs legt der Anmeldedienst einen verschluesselten Umschlag ab. Darin steht nicht nur die Passphrase, sondern auch das Client-Zertifikat des Kunden. Das ist der eigentliche Gewinn: der Pruefstand nimmt je Bereich das Zertifikat des KUNDEN, statt eines Sammelzertifikats, das auf alle Bereiche berechtigt waere. pgBackRest kennt kein Nur-Lese-Zertifikat — ein Sammelzertifikat duerfte ueberall auch schreiben.

  Zum Ausprobieren: in der Pruefstand-Konfiguration `age_identity` (privater Schluessel) und `envelope_dir` (Ordner mit den Umschlaegen) setzen; die Bereichsliste und `cert_dir` koennen dann entfallen. Ein Lauf ohne weitere Angaben prueft alle Bereiche, zu denen ein Umschlag liegt:

  odoo pgbackrest verify --bench-config /etc/pgbr-pruefstand/config.json

  Worauf zu achten ist: neue Kunden muessen NICHT nachgetragen werden — was nachgetragen werden muss, wird irgendwann vergessen, und ein Bereich, den niemand prueft, faellt nicht auf. Liegen mehrere Umschlaege eines Bereichs, gilt der juengste. Einzelne Werte lassen sich weiter von Hand uebersteuern.

  Der private Schluessel wird NICHT in einen Container eingehaengt: geoeffnet wird auf der Maschine, hinein geht nur das Ergebnis.


## 10.2.0

- **Feature**: `odoo pgbackrest verify` bekommt `--bench-config` — damit prueft ein eigener Pruefstand FREMDE Bereiche mit derselben Probe.

  Bisher konnte die Rueckspielprobe nur die Sicherungen des Projekts pruefen, in dem sie aufgerufen wird. Die Maschine, die stellvertretend fuer alle Kunden prueft, hat aber gar kein Projekt - sie haette also eine zweite Umsetzung derselben Sache gebraucht. Zwei Umsetzungen laufen frueher oder spaeter auseinander, und dann prueft der Pruefstand etwas anderes als das, was getestet wurde.

  Zum Ausprobieren: `odoo pgbackrest verify --bench-config <datei.json>`. Die Datei sagt, WOHER Repository, Zertifikat und Bereiche kommen; getan wird danach genau dasselbe wie im Projekt. Ohne Bereichsangabe werden alle Bereiche der Datei nacheinander geprueft, mit `--stanza` nur einer.

  { "repo_host": "db.backup.zebroo.de", "repo_port": 443, "cert_dir": "/etc/pgbr-pruefstand/cert", "pgbackrest_image": "pgbr-pruefstand:2.59.1", "run_user": "999:999", "stanzas": {"kunde-a": {"cipher_pass": "..."}} }

  Worauf zu achten ist: die Passphrase steht je Bereich, nicht global — jeder Kunde hat eine eigene. Die abgelegte Konfiguration bleibt 0600 und gehoert dem Benutzer, unter dem der Container laeuft; sie enthaelt Geheimnisse.

  Fuer bestehende Aufrufe aendert sich nichts. Ohne `--bench-config` laeuft alles wie zuvor.


## 10.1.0

- **Feature**: Neu: `odoo pgbackrest verify` — die Rueckspielprobe.

  Bisher pruefte an den Sicherungen alles nur, ob die Bytes daliegen, die wir hingelegt haben: Groessen, Zeitstempel, Lueckenlosigkeit der WAL-Kette. Keine dieser Pruefungen sagt etwas darueber, ob sich aus dem Bestand je wieder ein Postgres starten laesst. Das sagt nur diese hier.

  Zum Ausprobieren: im Projektverzeichnis `odoo pgbackrest verify` aufrufen. Die neueste Sicherung wird in ein Wegwerf-Volume zurueckgespielt, ein Postgres darauf gestartet und aus der groessten Nutztabelle der groessten Datenbank gelesen. Am Ende steht eine Zeile wie

  Rueckspielprobe bestanden: Sicherung 20260825-212040F laeuft, 70000 Zeilen aus public.res_partner gelesen (15s).

  Worauf zu achten ist: die LAUFENDE Instanz bleibt dabei unberuehrt - sie muss waehrend und nach der Probe unveraendert weiterlaufen. Das ist keine Sorgfaltsfrage, sondern eingebaut: das Datenvolume des Projekts wird gar nicht erst eingehaengt, und das Repository nur lesend. Was nicht eingehaengt ist, kann auch ein Fehler in diesem Code nicht ueberschreiben.

  `--json` fuer die maschinenlesbare Form, `--report-to <ordner>` legt das Ergebnis als `<stanza>-<zeitstempel>.json` ab (das liest die Ueberwachung), `--stanza` prueft einen fremden Bereich - dafuer gibt es den Pruefstand.

  Ein Fehlschlag ist ein Ergebnis, kein Absturz: es wird trotzdem eine Datei geschrieben. "Probe gescheitert" und "keine Probe gelaufen" sind sehr verschiedene Nachrichten, und die Ueberwachung muss sie unterscheiden koennen.


## 10.0.2

- Das archive_command holt eine fehlende Stanza jetzt selbst nach, statt dauerhaft zu scheitern. Betroffen war jede Lage, in der postgres ohne den Sidecar laeuft - und es fiel nicht auf, weil postgres normal weiterbediente, waehrend sich das WAL staute.

  Genau EINE Ursache wird geheilt (die vollstaendig fehlende Stanza), jeder andere Fehler geht unveraendert durch: ein archive_command, das Probleme verschluckt, wirft WAL weg, und die Luecke faellt erst beim Wiederherstellen auf.

  Ein HALB zerstoertes Repository wird bewusst NICHT geflickt - fehlt nur archive.info, waehrend backup.info dasteht, scheitert es weiter und laut. Das gehoert vor menschliche Augen.

  Abgedeckt von einem End-zu-Ende-Test im Bake-Lauf: Stanza im laufenden Projekt entfernen, WAL-Wechsel ausloesen, und pruefen, dass sie zurueckkommt, dass die Meldung im Log steht und dass danach wieder archiviert wird.

  Von Hand nachvollziehbar mit `rm -rf /var/lib/pgbackrest/archive` im postgres-Container und `select pg_switch_wal()`.
- **Fix**: Das Vorbauen der Images lief seit dem 24.08.2026 in jedem Lauf auf einen Fehler: "could not find any target matching 'pgbackrest'". Das Wegwerf- Projekt, in dem gebaut wird, hatte RUN_PGBACKREST nicht gesetzt -- damit schreibt "odoo reload" den Dienst gar nicht erst in die Compose-Datei, und der Bau bricht ab, bevor irgendetwas hochgeladen wird.

  Die Folge war auf jeder Kundenmaschine zu sehen: postgres, cronjobs, cronjobshell, offsite und odoo_metrics_exporter meldete zodoo als "not in zodoo registry" und baute sie einzeln nach. Gemessen an einer frisch aufgesetzten Instanz sind das rund neun Minuten pro Aufsetzen statt anderthalb.

  RUN_PGBACKREST, RUN_OFFSITE und RUN_DASHBOARD sind jetzt im Wegwerf-Projekt gesetzt. Das hat dort keine Nebenwirkung -- gestartet wird nichts, gebraucht wird nur die richtige Berechnung der Tags.

  Ausserdem stehen cronjobshell, offsite und odoo_metrics_exporter jetzt mit in der Bauliste. Sie laufen auf jeder Kundenmaschine, fehlten aber.


## 10.0.1

- **Internal**: Auch die VSCode-Erweiterung ist vom Privataccount marcwimmer nach Odoo-Ninjas umgezogen. Der Download-Link in `lib_composer.py` zeigt jetzt direkt dorthin statt ueber GitHubs Weiterleitung.

  Damit verweist zodoo nur noch an einer einzigen Stelle auf den Privataccount: in einem Kommentar in `module_tools.py`, der die Syntax fuer direkte Git-URLs am Beispiel eines pymssql-Forks zeigt. Der hat keine Funktion.


## 10.0.0

- Der Anmeldedienst laeuft jetzt oeffentlich unter enroll.backup.zebroo.de (443) statt auf Port 8445 im VPN. Damit entfaellt der Schritt, bei dem beim ersten Kontakt ein CA-Fingerabdruck angezeigt und bestaetigt werden musste - das Zertifikat ist oeffentlich ausgestellt.

  Zum Testen: `odoo pgbackrest register` auf einer Instanz ohne VPN-Zugang zum Backup-Server aufrufen. Erwartet: die Anfrage geht durch. Die Freigabemaske ist von aussen NICHT erreichbar (404) - nur aus VPN und LAN.
- Das Repository ist jetzt oeffentlich unter db.backup.zebroo.de auf Port 443 erreichbar - eine Instanz braucht fuer die Sicherung keine VPN-Mitgliedschaft mehr. PGBR_REPO_HOST_PORT steht deshalb auf 443.

  Zum Testen: auf einer Instanz ohne VPN-Zugang zum Backup-Server `odoo pgbackrest check` aufrufen. Erwartet: die Pruefung laeuft durch und archiviert ein WAL-Segment.
- Neu: `odoo pgbackrest register` meldet eine Instanz beim Backup-Server an. Der erste Aufruf stellt eine Anfrage, ein Admin gibt sie in der Maske des Anmeldedienstes frei, der zweite Aufruf holt Stanza, Client-Zertifikat und Passphrase ab und traegt alles in die Settings ein. Danach nur noch `odoo reload && odoo up -d && odoo pgbackrest check`.

  Zum Testen: auf einer Instanz mit VPN-Zugang zum Backup-Server `odoo pgbackrest register` aufrufen. Beim ersten Kontakt wird der Fingerabdruck der CA angezeigt - der gehoert einmal gegen den Server geprueft. Erwartet: die Zugangsdaten werden genau EINMAL herausgegeben, ein zweiter Abholversuch liefert "delivered" und nichts weiter.

  Eine Freigabe deckt beide Stroeme ab: Datenbank (pgBackRest) und Filestore (write-only Empfaenger). Liefert der Server keinen oeffentlichen age-Schluessel, bleibt der Filestore-Strom absichtlich AUS - sonst gingen Anhaenge im Klartext raus.
- **BREAKING**: Datenbanksicherung von barman auf pgBackRest umgestellt: WAL-Archivierung statt Streaming, Inkrementelle auf Page-Ebene, Aufraeumen als Teil jedes Backups, und ein Repo-Host-Modus, bei dem weder Schluessel noch Loeschrecht auf der Kundenmaschine liegen.
- Der vhost-Router kann jetzt Backends anbinden, die selbst TLS sprechen (`upstream_scheme=https`), und kennt zwei Einstellungen fuer grosse Uploads: `client_max_body_size` (z.B. "0" ohne Grenze) und `proxy_request_buffering` (aus = durchreichen statt erst auf Platte puffern).

  Zum Testen: einen bestehenden vhost anschauen - er muss unveraendert rendern (http, 1024M, Pufferung an). Nur ein vhost, der die neuen Felder ausdruecklich setzt, bekommt anderes Verhalten.
- Postgres zieht den pgBackRest-Sidecar beim Start mit hoch. Ohne das scheiterte die WAL-Archivierung dauerhaft, wenn jemand postgres allein startete (`docker compose up -d postgres`, ein Teil-Neustart, `odoo db reset`) - die Stanza legt naemlich der Sidecar an. Gemeldet hat sich dabei nichts: postgres lief weiter, das WAL staute sich, und die Sicherung, die alle fuer vorhanden hielten, gab es nicht.

  Zum Testen: `odoo up -d postgres` auf einem Projekt mit RUN_PGBACKREST=1 - es muss der Sidecar mit hochkommen. Danach `odoo pgbackrest check`: die WAL-Archivierung muss durchlaufen.
- Eingeschaltetes pgBackRest hat auf Linux die Verbindung zu postgres gekappt: `odoo psql`, `odoo db reset` und alles, was von aussen an die Datenbank will, scheiterten mit "No such file or directory" auf dem Socket. Ursache war ein Docker-Volume auf /var/run/postgresql, das den Host-Bind-Mount ueberdeckte, durch den zodoo selbst spricht.

  Zum Testen auf einem Linux-Host: RUN_PGBACKREST=1 setzen, `odoo reload`, `odoo up -d`, dann `odoo psql`. Muss eine Sitzung oeffnen. Danach `odoo pgbackrest check` - der Sidecar muss postgres weiterhin erreichen.


## 9.4.4

- Der vhost-Router kann jetzt je Absender-IP begrenzen: `rate_limit` (nginx-Syntax, z.B. "10r/s") und `rate_limit_burst`. Wer darueber liegt, bekommt 429.

  Zum Testen: einen vhost ohne die Felder anschauen - er muss unveraendert rendern, ohne jede limit_req-Zeile. Nur ein vhost, der `rate_limit` setzt, bekommt Zone und Begrenzung.


## 9.4.3


- **Fix**: 'Ein `odoo update`, das die Container vorher komplett heruntergenommen hat (cicd im Devmode killt das ganze Compose-Projekt) und danach frueh aussteigt (No module update required), liess die Instanz einfach aus: die drei Rollen-Starts liefen per docker exec in einen toten Container, der Fallback griff auf die laengst verschwundenen Compose-Services odoo_web/odoo_queuejobs/odoo_cronjobs zu, und das Update meldete trotzdem completed successfully - eine 3dm-Staging-Instanz stand so gut fuenf Stunden auf 502, bis es jemandem auffiel. Ist der Container weg, wird jetzt der echte Service `odoo` gestartet; sein Supervisor bringt web/queuejobs/cronjobs selbst hoch. Ausserdem im Supervisor: eine Rolle, deren Schalter aus ist (RUN_ODOO_CRONJOBS=0), wird nicht mehr endlos neu gestartet - `odoo update` startet am Ende alle drei Rollen, das Kind stieg sofort wieder aus (Cronjobs shall not run) und wurde etwa zweimal pro Sekunde neu gestartet, auf einer Staging-Instanz sieben Tage lang mit rund 50 Prozent CPU-Last; jeder dieser Starts schiesst per kill_odoo ausserdem auf die laufenden Web-Prozesse. Beim Hochfahren wird postgres mitgestartet (in den generierten Composes gibt es kein depends_on, der odoo-Container haengt sonst still in wait_postgres), und scheitert der Start, sagt das Update das jetzt deutlich statt Erfolg zu melden. Und: `supervisor.py` mit unbekanntem Argument (z.B. --help) fiel bisher in den Daemon-Modus und riss damit im laufenden Container die Web-Prozesse ab - unbekannte Argumente geben jetzt die Usage aus, und ein zweiter Daemon verweigert den Start, wenn der Kontroll-Socket schon antwortet.'


## 9.4.2

- Der vhost-Router kann jetzt Backends anbinden, die selbst TLS sprechen (`upstream_scheme=https`), und kennt zwei Einstellungen fuer grosse Uploads: `client_max_body_size` (z.B. "0" ohne Grenze) und `proxy_request_buffering` (aus = durchreichen statt erst auf Platte puffern).

  Zum Testen: einen bestehenden vhost anschauen - er muss unveraendert rendern (http, 1024M, Pufferung an). Nur ein vhost, der die neuen Felder ausdruecklich setzt, bekommt anderes Verhalten.


## 9.4.1


- **Fix**: Der minuetliche WAL-Job war auf JEDER Instanz definiert, auch ohne write-only Ziel. Er bricht dann sofort ab, startet aber die CLI - gemessen 0,44 s je Start, also rund 10 Minuten CPU pro Tag und Instanz fuer nichts, bei 100 Instanzen etwa 18 CPU-Stunden taeglich. Ohne konfiguriertes Ziel wird der Job jetzt weggelassen statt leer zu laufen.


## 9.4.0


- **Feature**: Gehen beide Stroeme write-only, wird restic gar nicht mehr benutzt - dann verlangt ein Offsite-Lauf auch keine Repo-Adresse und keine Passphrase mehr, und der Anmeldedienst erzeugt gar keinen Repo-Key mehr. Eine so eingerichtete Maschine haelt damit KEIN Geheimnis, mit dem sie ihre eigene Sicherung lesen koennte: sie bekommt einen Upload-Zugang und zwei OEFFENTLICHE age-Schluessel. Das Zugangspasswort ist ersetzbar (restic-area passwd); unersetzlich sind nur die privaten age-Schluessel, und die entstehen nicht auf dem Server, sondern liegen im Vault. Ein aelterer Backup-Server, der noch Repo-Keys ausgibt, funktioniert unveraendert weiter. Auf dem Server legt 'restic-area retire <bereich>' die alten Repos still (verschieben, nicht loeschen) - sonst feuert der 48-Stunden-Alarm je Strom ab dem naechsten Tag dauerhaft.


## 9.3.0


- **Feature**: Der Datenbankstrom kann write-only: Basisbackups und WAL werden gegen einen oeffentlichen age-Schluessel (OFFSITE_WO_DB_RECIPIENT) verschluesselt hochgeladen, die Maschine kann ihre Sicherungen weder lesen noch loeschen. WAL geht minuetlich (OFFSITE_WAL_CRON), das laufende *.partial nie. Grosse Objekte werden gestreamt statt zwischengespeichert - ein Basisbackup einer 600-GB-Datenbank braucht so keine 170 GB Zwischenplatz. Vor dem Upload wird per HEAD gefragt, ob das Objekt schon da ist; damit ist 'odoo offsite reset' billig (Verzeichnis vergessen, nur Fehlendes senden). Basisbackups werden jetzt mit zstd komprimiert (gemessen Faktor 2,8) und barman haelt lokal nur noch 2 Tage, weil die Historie offsite liegt: statt ueber 4 TB nur noch ein paar hundert GB bei einer 600-GB-Datenbank. Das barman-Image bringt zstd und lz4 mit - ohne die Binaries scheitert ein komprimiertes Basisbackup komplett.


## 9.2.2


- **Internal**: Der write-only Filestore-Weg hat jetzt einen Ende-zu-Ende-Test im Bake-Lauf. Er prueft genau das, was den Weg ausmacht und was ein Unit-Test nicht sehen kann: der zweite Lauf laedt nichts hoch, der dritte genau die eine Datei, die dazwischen entstanden ist. Das Paket wird danach im Container mit dem privaten Schluessel geoeffnet und muss genau diese Datei enthalten.


## 9.2.1


- **Fix**: Nach 'odoo barman recover' lief der WAL-Empfang nicht von allein weiter: die Zeitlinie wechselt, pg_receivewal haelt aber noch eine .partial der alten, der Replikations-Slot bleibt uninitialisiert und es wird stillschweigend kein WAL mehr archiviert - das naechste Basisbackup scheitert dann mit 'Impossible to start the backup'. Der Recover setzt den Empfaenger jetzt selbst zurueck; dafuer gibt es auch den neuen Befehl 'odoo barman receive-wal-reset'. Ausserdem prueft ein neuer Ende-zu-Ende-Test im Bake-Lauf den Update-Guard vollstaendig: gescheitertes Update, Rueckrollen auf den vom Guard selbst gesetzten Safepoint, und dass der WAL-Empfang danach wieder laeuft.


## 9.2.0


- **Feature**: Neuer Weg fuer das Filestore-Backup, bei dem die Odoo-Maschine ihre eigenen Sicherungen NICHT mehr lesen kann. Moeglich, weil Odoo Anhaenge nach dem SHA-1 ihres Inhalts benennt: eine Datei wird einmal geschrieben und nie geaendert, 'was ist neu' ist ein reiner Namensvergleich gegen ein lokales Verzeichnis, und es braucht keinen Repo-Index und keinen Schluessel. Verschluesselt wird gegen einen oeffentlichen age-Schluessel (OFFSITE_WO_RECIPIENT), hochgeladen per PUT an OFFSITE_WO_URL. Neuer Befehl 'odoo offsite filestore'; sind beide Settings gesetzt, ersetzt der Weg den restic-Strom 'files' statt danebenzulaufen.
- **Fix**: Barman auf einer bestehenden Instanz einschalten fuehrte zu stummem Stillstand: der pg_hba-Eintrag fuer Replikationsverbindungen wurde nur beim Initialisieren einer neuen Datenbank angelegt, also nie bei einem schon vorhandenen Cluster. wal_level passte, der barman-Container lief, aber Streaming und Basisbackup scheiterten - sichtbar nur ueber 'barman check'. Der Eintrag wird jetzt bei jedem Start des Postgres-Containers idempotent sichergestellt.


## 9.1.1


- **Internal**: The offsite files were the only corner of the repo written in German (94 German vs 13 English comment lines, while barman/postgres/cronjobs and the CLI are English throughout). Comments, docstrings, CLI help texts and operator messages of the offsite service are now English, so external contributors can read the reasoning behind the design. No behaviour change.


## 9.1.0


- **Feature**: Offsite-Backup schreibt je Kunde zwei getrennte Repositories (<bereich>/db und <bereich>/files), damit ein ausgefallener Datenbank-Dump nicht mehr hinter einem weiterhin ankommenden Filestore verschwindet; der Lauf bricht jetzt auch ab, wenn der Filestore fehlt oder leer ist (Notausgang OFFSITE_ALLOW_WITHOUT_FILES=1), und Settings-Dateien mit Geheimnissen sind nur noch fuer den Besitzer lesbar. OFFSITE_LAYOUT=flat behaelt das alte Verhalten mit einem Repository.


## 9.0.1


- **Docs**: zodoo-Doku zum Offsite-Backup auf restic aktualisiert: neue Seite 11-offsite-backup.md, Settings-Referenz und Overview


## 9.0.0


- **BREAKING**: Offsite-Backup laeuft auf restic statt BorgBackup; neuer Befehl 'odoo offsite register' meldet die Instanz am Backup-Server an


## 8.0.6


- **Fix**: Offsite-Backup: die Datenbank ist jetzt garantiert im Archiv - vorher konnte sie lautlos fehlen. Der Borg-Lauf nahm mit, was er vorfand: /source/barman (nur wenn RUN_BARMAN=1) und den Filestore. RUN_BARMAN steht per Default auf 0, also sicherte eine normale Maschine mit RUN_OFFSITE=1 ausschliesslich die Anhaenge und meldete Erfolg. Das faellt erst auf, wenn man wiederherstellen will. Jetzt zieht 'odoo offsite backup' ohne Barman vorab selbst einen frischen Dump (fester Name offsite-db.dump in DUMPS_PATH, wird jeden Lauf ueberschrieben, unkomprimiert damit borg dagegen deduplizieren kann) und reicht ihn dem Container durch; findet der Container weder einen Barman-Stand noch einen Dump, bricht er mit Erklaerung ab, statt ein unvollstaendiges Archiv anzulegen. OFFSITE_ALLOW_WITHOUT_DB=1 schaltet die Pruefung ab, wenn die Datenbank nachweislich woanders gesichert wird. Ausserdem verlangte require_config bisher immer einen SSH-Key, auch bei einem lokalen Repository-Pfad - damit scheiterte jedes Backup auf eine eingehaengte Platte, obwohl setup_ssh dort gar keinen Key benutzt; der Key wird jetzt nur noch fuer ssh://-Ziele gefordert. Zum Testen: auf einer Maschine mit RUN_BARMAN=0 und RUN_OFFSITE=1 'odoo offsite backup' laufen lassen und mit 'odoo offsite list' bzw. 'odoo offsite borg list ::<archiv>' pruefen, dass offsite-db.dump und der Filestore im Archiv stehen.


## 8.0.5

- **Fix**: `odoo down --cleanup-files` löscht den Filestore der Datenbank jetzt wirklich. Zum Nachstellen: Projekt mit `odoo down --cleanup-files` abräumen und danach in `<data_dir>/filestore/` schauen - vorher blieb dort der Ordner der Datenbank liegen und im Log stand `Failed to remove path ...: not allowed`, jetzt ist er weg. Auf Build-/CI-Rechnern, die pro Lauf eine neue Test-Datenbank anlegen, liefen dadurch die Platten voll.


## 8.0.4

- **Fix**: Ein veralteter requirements.hash fuehrt nicht mehr stillschweigend dazu, dass Maschinen weiter das alte Image ziehen.

  Hintergrund: der Image-Tag wird aus requirements.hash und requirements.txt.all berechnet - beide sind generierte Dateien. Wer requirements.static (oder eine Modul-Abhaengigkeit) aendert und kein "odoo reload" laufen laesst, behaelt denselben Tag, obwohl eine neue Bibliothek gefordert ist. Es kam keine Meldung, und die neue Lib fehlte in jedem Image.

  Was sich fuer den Tester aendert:
  - "odoo build" prueft das jetzt selbst und regeneriert die Dateien bei Bedarf (per "odoo reload --no-gimera-apply", also ohne Submodule anzufassen).
  - Neues Kommando "odoo requirements-check" zum Pruefen ohne Build; mit "--fix" wird direkt regeneriert. Exit-Code 1, wenn veraltet - damit auch in CI oder pre-commit nutzbar.
  - Sind die generierten Dateien nach dem Regenerieren nicht committed, kommt eine Warnung: sonst rechnen alle anderen Maschinen weiter mit dem alten Tag.

  Zum Nachstellen: in einem Projekt eine Zeile in requirements.static ergaenzen, "odoo requirements-check" aufrufen - es muss die Abweichung mit altem und erwartetem Hash melden. Nach "odoo reload" ist die Meldung weg.
- **Fix**: Der aus dem Verzeichnisnamen abgeleitete Projektname behaelt seine Unterstriche. _sanitize_project_name() hat sie bisher immer entfernt, auch wenn der Name die Laengengrenze gar nicht gerissen hat - aus dem Verzeichnis cicd_3dm_odoo_staging17 wurde so das Projekt cicd3dmodoostaging17. Dafuer gibt es kein ~/.odoo/run/<projekt>/settings, also lief jeder Aufruf ohne -p gegen ein unkonfiguriertes Projekt: Config.__getattribute__ findet keine settings-Datei und liefert None fuer jedes Setting. 'odoo filestore unshare' brach mit 'No filestore at None' ab, 'odoo psql' tat kommentarlos nichts - mit -p <verzeichnisname> lief dasselbe Kommando durch. Die Sanity-Pruefung in cli.py, die sonst bei abweichendem Verzeichnisnamen abbricht, hat den Fall ausdruecklich durchgewunken (name was auto-shortened from this directory), deshalb blieb es unbemerkt. Unterstriche sind in Docker-Compose-Projektnamen erlaubt; sie werden jetzt nur noch entfernt, wenn der Name sonst laenger als 50 Zeichen bliebe, und erst danach wird wie bisher aus der Mitte gekuerzt. Migration: wer ein solches Projekt bisher ohne -p benutzt hat, findet seinen Compose-Stand unter dem alten zusammengezogenen Namen in ~/.odoo/run/ und zieht ihn mit einem 'odoo reload' im Projektverzeichnis nach. Zum Testen: in einem Projektverzeichnis mit Unterstrichen im Namen 'odoo psql' bzw. 'odoo filestore unshare' ohne -p aufrufen - beides muss jetzt dasselbe tun wie mit -p <verzeichnisname>.


## 8.0.3


- **Fix**: >-


## 8.0.2


- **Fix**: `odoo init` legt wieder ein Projekt an. Der Befehl wurde von `offsite init` verdeckt, weil AliasedGroup Unterbefehle nach oben zieht und bei gleichem Namen nach Registrierungsreihenfolge entscheidet — der dokumentierte Schnellstart `odoo init ~/projects/my-odoo` brach mit \No such option '--ai'\ ab. `odoo offsite init` bleibt unverändert erreichbar.


## 8.0.1


- **Fix**: >-


## 8.0.0

- **Internal**: gimera, odoo-anonymize und odoo-cleardb sind vom Privataccount marcwimmer nach Odoo-Ninjas umgezogen. Die Verweise in zodoo zeigen jetzt direkt dorthin.

  Betroffen sind der gimera-Pin in `zodoo/src/gimera.yml`, die beiden URLs in `lib_db.py` und die `gimera.yml` der Projektvorlagen fuer alle acht Odoo-Versionen (11.0 bis 19.0). Letztere sind der eigentliche Grund fuer die Aenderung: die Vorlage wird beim Anlegen eines Projekts kopiert und trug die Adresse des Privataccounts damit dauerhaft in jedes Kundenrepository.

  Bestehende Projekte muessen nichts tun. GitHub leitet die alten Adressen weiter, vorhandene Pins und Klone funktionieren unveraendert weiter; sie ziehen die neue Adresse erst beim naechsten Anfassen der jeweiligen gimera.yml.
- **BREAKING**: Drei Verweise auf Repositories entfernt, die es nicht gibt.

  - `odoo reload` hatte eine Option `--images-url`, deren Hilfetext auf github.com/marcwimmer/odoo verwies. Das Repository existiert nicht, und die Option wurde auch nie ausgewertet: der Wert kam in der Signatur an und wurde dort nie wieder angefasst. Option entfernt.
  - Die URL in `zodoo/src/setup.cfg` zeigte auf marcwimmer/zodoo. Das Projekt liegt unter Odoo-Ninjas/zodoo.
  - `robot/.artefacts` beschrieb den Download von Chromedriver und Chrome von github.com/marcwimmer/chromedrivers. Das Repository existiert nicht mehr, die Links liefern 404. Sechs Minuten nach dem Anlegen der Datei wurden die beiden Dateien 2022 direkt nach `robot/artefacts/` eingecheckt und werden seitdem von dort genommen; die Beschreibung las ohnehin niemand mehr. Datei entfernt.
  - `lib_robot.py` zeigte auf marcwimmer/odoo-robot_utils. Das Repository ist laengst nach Odoo-Ninjas/odoo-robot_utils umgezogen; der Verweis funktionierte nur noch ueber GitHubs Weiterleitung. Auf das echte Ziel gesetzt.

  `odoo reload --images-url <url>` bricht jetzt mit einem Fehler ab, statt das Argument stillschweigend zu verwerfen. Wer die Option in einem Skript stehen hat, muss sie streichen - eine Wirkung hatte sie nie.


## 7.8.3


- **Internal**: >-


## 7.8.2


- **Internal**: >-


## 7.8.1


- **Fix**: Das in zodoo mitgelieferte gimera ist von 0.12.0 auf 0.13.0 angehoben. Zwei Dinge kommen damit an: Erstens legt gimera den Golden Cache unter ~/.cache/gimera nicht mehr doppelt an. Bisher lag jedes Repository dort zweimal - einmal als das bare Repository, das tatsaechlich benutzt wird, und noch einmal als Tarball genau desselben Standes, der bei jedem Update neu geschrieben und nur gelesen wurde, um das Repository daneben wiederherzustellen. Bei odoo/odoo waren das zweistellige GB ohne Gegenwert. Ein Tarball, den eine aeltere Version hinterlassen hat, wird beim naechsten gimera-Lauf entfernt, und es wird gemeldet, wieviel Platz dadurch frei geworden ist - sonst laege er fuer immer da, ohne dass man die Herkunft zuordnen koennte. Zweitens werden liegengebliebene Sperrdateien wieder erkannt: wurde ein gimera-Lauf hart abgeschossen, blockierte der naechste Lauf auf demselben Repository bislang eine volle Stunde und brach dann mit 'Timeout occured.' ab, weil die Aufraeumlogik nach einem Dateinamen suchte, den nie jemand anlegt. Zum Testen: 'du -sh ~/.cache/gimera' vor und nach dem naechsten 'odoo update' bzw. 'gimera apply' vergleichen - der Ordner sollte deutlich kleiner werden, und in der Ausgabe steht ein Hinweis auf den entfernten Alt-Tarball. Ansonsten aendert sich am Verhalten nichts; die Option --clear-zip-cache gibt es weiterhin, sie tut aber nichts mehr und weist darauf hin.


## 7.8.0


- **Feature**: odoo warnt jetzt, wenn es aus einer Shell heraus benutzt wird, der das Projektverzeichnis gar nicht gehoert - der typische Fall ist eine Root-Shell in /home/odoo/odoo. Alles, was der Befehl dann anlegt, gehoert anschliessend root, und der eigentliche Benutzer kann es nicht mehr aendern. Das faellt erst viel spaeter auf und sieht dann nach etwas ganz anderem aus: ein Build bricht mit 'permission denied' ab, ein git-Checkout schlaegt fehl, ein Container startet nicht, weil er seine Settings-Datei nicht lesen kann - und zu dem Zeitpunkt denkt niemand mehr an den einen Befehl, der als falscher Benutzer lief. Die Meldung nennt beide Benutzer und sagt bei Root auch, was zu tun ist: 'su - <benutzer>' und ausdruecklich nicht 'sudo -iu <benutzer>', weil letzteres SUDO_USER=root stehen laesst und damit in die naechste Falle fuehrt (OWNER_UID=0, an dem der Container gar nicht erst startet). Es ist bewusst nur eine Warnung und kein Abbruch, denn es gibt legitime Gruende, als anderer Benutzer zu arbeiten. Geprueft wird nur innerhalb eines echten Projektbaums, damit ein 'odoo --help' in einem beliebigen fremden Verzeichnis nicht grundlos meckert; im Container wird gar nicht geprueft, weil der Entrypoint die UIDs dort absichtlich umschreibt. Zum Testen: in einem Projektverzeichnis 'sudo odoo version' aufrufen - es muss eine rote Warnung erscheinen, die den Verzeichnisbesitzer und root nennt. Als normaler Benutzer darf im selben Verzeichnis nichts kommen.


## 7.7.0


- **Feature**: Das mitgelieferte gimera ist von 0.7.118 auf 0.12.0 angehoben worden - der bisherige Stand lag 65 Commits und vier Minor-Versionen zurueck, sodass dort laengst geloeste Probleme bei uns weiterbestanden. Das wichtigste davon betrifft den Plattenplatz: gimera legt fuer grosse Repositories einen gemeinsamen Zwischenspeicher an, und der wurde bisher als vollstaendige Kopie samt aller alten Dateistaende gezogen. Bei odoo/odoo waren das rund 17 GB, auf einem Server mit 75 GB Platte also ein erheblicher Anteil. Ab 0.12.0 werden nur noch die Historie und die tatsaechlich benoetigten Dateistaende geholt, gemessen 1,4 GB statt 17 GB. Bereits vorhandene Zwischenspeicher bleiben unangetastet - wer den Platz zurueckhaben will, loescht den Ordner unter ~/.cache/gimera einmal von Hand, danach wird er in der schlanken Form neu aufgebaut. Ebenfalls neu ist, dass sich einzelne Repositories per Konfiguration vom Zwischenspeichern ausnehmen lassen. Zum Testen: 'odoo reload' und 'odoo build' auf einem bestehenden Projekt durchlaufen lassen - beides muss sich unveraendert verhalten. Wer den Effekt sehen will, loescht vorher ~/.cache/gimera und vergleicht die Groesse danach. Nebenwirkung des neuen gimera: es traegt beim ersten Lauf '.gimera' in die .gitignore neben der gimera.yml ein, das ist die Konfigurationsdatei fuer die Cache-Ausnahmen.


## 7.6.0


- **Feature**: Neues Setting ODOO_DBFILTER, mit dem sich einstellen laesst, welche Datenbanken eine Instanz bedient (odoo.conf dbfilter). Bisher gab es dafuer gar keinen Schalter: unsere Templates setzen db_name, aber keinen dbfilter, und Odoo nimmt dann db_name als Allowlist. Mit ODOO_ENABLE_DB_MANAGER=1 fuehrt das zu einem halb funktionsfaehigen DB-Manager - neu angelegte Datenbanken entstehen in Postgres, tauchen in der Liste aber nicht auf, sind per HTTP nicht erreichbar und lassen sich auch nicht mehr loeschen, weil beim Loeschen gegen dieselbe Liste geprueft wird. Der Default ist leer, damit sich ohne Zutun nichts aendert; wer den DB-Manager wirklich benutzen will, setzt ODOO_DBFILTER=.*. Beim 'odoo reload' weist eine Meldung darauf hin, wenn der Manager an ist, der dbfilter aber nur die Projekt-DB durchlaesst - automatisch aufmachen waere falsch, das wuerde aus einem Debug-Schalter still eine Instanz machen, die auf jeden DB-Namen antwortet. Das Setting wirkt in beiden Wegen, im gebauten Image (Versionen 12 bis 19) und im Pfad mit dem offiziellen Odoo-Image. Zum Testen: ODOO_ENABLE_DB_MANAGER=1 und ODOO_DBFILTER=.* setzen, 'odoo reload && odoo up -d', dann im DB-Manager eine zweite Datenbank anlegen - sie muss danach in der Liste stehen und wieder loeschbar sein.
- **Feature**: Die zodoo-Registry wird jetzt standardmaessig zum Lesen genutzt, ohne dass man vorher etwas einrichten muss. Bisher fragte der erste 'odoo build' auf einer frischen Maschine 'Do you want to use the zodoo registry?' und wollte gleich danach einen Account anlegen - also eine Identitaet, bevor ueberhaupt feststand, ob eine gebraucht wird. Wer die Frage wegklickte oder in einer Umgebung ohne Terminal baute, bekam kein vorgebautes CPython aus der Registry und compilierte es selbst, was rund 12 Minuten dauert. Neu ist die Trennung von Lesen und Schreiben: Pullen laeuft ohne Konto (registry.zebroo.de liefert das Image zodoo/python anonym aus, alles andere bleibt hinter der Anmeldung, insbesondere die Repository-Liste), und nach einem Account gefragt wird erst, wenn tatsaechlich ein gebautes Image hochgeladen werden soll. Wer die Registry gar nicht will, setzt weiterhin ZODOO_REGISTRY_SUGGESTED=0. Ausserdem ist der Vorschlag fuer den Benutzernamen brauchbarer geworden: hiess der Systembenutzer 'odoo' oder 'root', wurde genau das vorgeschlagen - ein Name, den es auf der Registry laengst gibt, sodass die Anlage mit 'existiert bereits' zurueckkam. Jetzt wird in so einem Fall der Name der Maschine herangezogen, aus odoo.3dm.de wird also '3dm'. Weil fuer den anonymen Pull auch der Versions-Endpunkt der Registry offen sein muss, meldet 'docker login' dort jetzt selbst bei falschem Passwort Erfolg - es prueft nur, ob ueberhaupt eine Anmeldung verlangt wird. Damit ein Vertipper nicht erst beim Push auffliegt, prueft zodoo die Zugangsdaten selbst gegen einen weiterhin geschuetzten Endpunkt und sagt sofort Bescheid, wenn sie abgelehnt werden; ist die Registry nicht erreichbar, wird das als solches gemeldet und nicht als falsches Passwort. Zum Testen: auf einem Rechner ohne Registry-Zugangsdaten (ZODOO_REGISTRY_USERNAME/PASSWORD leer) 'odoo build' starten - es darf keine Frage nach der Registry mehr kommen, und im Log muss zodoo/python aus der Registry gezogen statt gebaut werden. Erst wenn hinterher gepusht wird, taucht die Frage nach dem Konto auf. Fuer den zweiten Teil bewusst ein falsches Passwort in ~/.odoo/settings eintragen - es muss eine rote Meldung kommen, bevor irgendetwas hochgeladen wird.
- **Fix**: ~/.odoo/odoo.config und odoo.config.<projekt> wirken wieder. Der Inhalt reist als eine Zeile in der Umgebungsvariablen ADDITIONAL_ODOO_CONFIG in den Container (Zeilenumbrueche gehen dort nicht), wurde dort aber nie wieder aufgetrennt, sondern so an configparser gegeben. Der liest '[options]___|||___dbfilter = .*' als Section-Header und wirft den Rest der Zeile weg - ohne Fehler und ohne Warnung. Damit war jede Option aus diesen Dateien wirkungslos, und weil die Config-Templates per ADD im Image liegen, gab es gar keinen Weg mehr, eine odoo.conf-Option ohne Rebuild zu setzen. Zum Testen: 'printf \[options]\ndbfilter = .*\n\ > ~/.odoo/odoo.config.$PROJECT', dann 'odoo reload && odoo up -d' und 'docker exec ${PROJECT}_odoo grep dbfilter /etc/odoo/config/config_webserver' - die Zeile muss jetzt drinstehen. Kommt trotz gesetzter Variable keine Option an, sagt der Container das beim Start rot heraus, statt es zu verschlucken.
- **Fix**: OWNER_UID landet nicht mehr auf 0, und wenn doch, sagt zodoo warum. Wer aus einer Root-Shell mit 'sudo -iu odoo' in den Projektordner ging, bekam OWNER_UID=0 in die Settings geschrieben: sudo laesst SUDO_USER=root stehen, und whoami() hat SUDO_USER bedingungslos dem tatsaechlichen Benutzer vorgezogen. Der odoo-Container startet damit nicht - sein Entrypoint benennt den User mit dieser UID um, das ist root, und root gehoert PID 1. usermod verweigert das, der Container endet mit Exit 1 und der Meldung 'user root is currently used by process 1', in der OWNER_UID nicht vorkommt. Jetzt zaehlen SUDO_USER/SUDO_UID nur noch, wenn wir wirklich root sind ('sudo -u <anderer>' laesst die effektive UID gewinnen), 'odoo reload' bricht bei OWNER_UID=0 mit Hinweis auf 'su - <user>' ab, und reuid.py verweigert die Umbenennung des Users, dem PID 1 gehoert, mit Nennung der Ursache. Beim offiziellen Odoo-Image (ODOO_STANDARD_IMAGE=1) bleibt eine 0 erlaubt, weil dort unser Entrypoint gar nicht laeuft. Zum Testen: 'sudo -iu <user>' in ein Projekt, 'odoo reload' - muss jetzt mit klarer Meldung abbrechen statt einen Container zu bauen, der beim Start stirbt.
- Der rsync-Container wird nicht mehr mitgestartet. Er stand ohne eigenes Profil in der compose-Datei und landete damit im Profil 'auto', das 'odoo up -d' hochfaehrt. Da das Image als Einstiegspunkt 'rsync' ohne Argumente aufruft, gab es seine Hilfe aus und endete mit Exit 1. Seit 7.2.0 wertet der Watchdog alles ausser 0, 130 und 143 als Absturz - auf Instanzen mit DEVMODE=0 und RUN_RSYNC=1 hat er den Container also im Minutentakt neu gestartet, ohne dass das je klappen konnte. Auf Entwicklungsmaschinen faellt es nicht auf, weil DEVMODE=1 den Watchdog ueberspringt; sichtbar war nur ein dauerhaftes 'Exited (1)' in 'docker ps -a'. Der Container einfach ins vorhandene Profil 'manual' zu schieben waere die naheliegende Loesung gewesen, haette aber das Image nicht mehr gebaut, weil 'odoo build' mit Profil 'auto' laeuft - und ein fehlendes rsync-Image faellt erst auf, wenn jemand einen Snapshot zurueckspielt, weil es dort per 'docker run' gebraucht wird. Deshalb gibt es jetzt das Profil 'build_only': der Build zieht es mit, 'odoo up' nicht. Zum Testen: 'odoo build' laufen lassen und pruefen, dass es das Image '<projekt>-rsync:latest' danach gibt ('docker images | grep rsync'); dann 'odoo up -d' und pruefen, dass in 'docker ps -a' kein rsync-Container mehr auftaucht. Anschliessend einen Snapshot anlegen und zurueckspielen - das muss unveraendert funktionieren. Der pgtools-Container bleibt bewusst wie er ist: er wird tatsaechlich als compose-Service verwendet und endet sauber mit 0.


## 7.5.3


- **Docs**: Medienordner der Doku von docs/.document360/assets/ nach docs/img/ umbenannt. Bilder gehoeren jetzt dorthin und werden relativ referenziert (![alt](./img/foo.png)) - das passt zu der Docusaurus-Site, die docs/ nach docs.zebroo.de spiegelt. Der alte Name kam noch von Document360.
- **Fix**: router_global: certbot und seine Plugins kommen jetzt komplett aus pip statt gemischt aus apt und pip. Vorher wurde das apt-certbot 1.21 durch certbot-dns-ionos (pip) auf 5.x hochgezogen, waehrend nginx- und rfc2136-Plugin bei 1.21 blieben. Das faellt nicht beim Build auf, sondern erst beim Ausstellen eines Zertifikats: 'certbot.errors.Error: Unsupported RSA key length: 1024', weil das alte nginx-Plugin fuer einen frischen 443-Block einen 1024-Bit-Platzhalter anlegt, den die neue cryptography-Version ablehnt. Effekt war ein geholtes, aber nicht eingebautes Zertifikat - der vhost blieb ohne TLS. Zum Testen: Router-Image neu bauen und 'certbot --nginx' fuer eine neue Domain laufen lassen, der 443-Block muss danach mit Zertifikat stehen. Ausserdem ist curl im Image, um sowas von innen pruefen zu koennen.


## 7.5.2


- **Docs**: docs/README.md: die Beschreibung des Doku-Workflows auf das Wesentliche gekuerzt (Markdown hier pflegen, Medien in docs/.document360/assets/). Die Aussage, dass die Doku-Site bei jedem Push automatisch nachzieht, ist raus - darauf sollte sich niemand verlassen.
- **Docs**: Prep docs/ for Document360's GitHub extension: add required docs/.document360/assets/ media folder and document that docs/ is now the synced source of truth for the hosted docs site.
- **Fix**: Registry: the default credentials admin/zebroo are gone. That account has not been valid on registry.zebroo.de for a long time (the registry answers 401), but every project got the pair written into its settings via lib_composer._set_defaults. That made every host look as if it had registry credentials — odoo build ran a docker login that could not succeed, and anyone reading the settings believed those were the credentials to use. There are no shared credentials any more: ZODOO_REGISTRY_USERNAME/PASSWORD come from ~/.odoo/settings only, odoo build asks for them once (and offers to request an account), and the username prompt now defaults to the OS user instead of admin. The URL default (registry.zebroo.de) stays. Docs updated in docs/06-registry.md.
- **Fix**: odoo build: the pre-flight check for the prebuilt Python image no longer rebuilds an image that is already there. On a host that was never logged in to the registry three things went wrong: zodoo has ZODOO_REGISTRY_USERNAME/PASSWORD in the settings but never handed them to docker, so the registry answered every query with a 401; a 401 was counted as 'image not in registry' just like a real miss; and nobody looked into the local docker store, although a FROM resolves against it. Result was a ~12 minute rebuild of an image that was sitting on the machine. Now a failed registry query is classified: 'the registry says no' (rebuild, as before) versus 'we could not ask' (401, DNS, TLS, refused connection). In the second case zodoo logs in with the credentials from the settings and asks again, and if it still cannot ask, a local copy of the image is used instead of rebuilding — checked against the architecture docker reports, and skipped for 'odoo build --pull', where BuildKit re-resolves every FROM against the registry anyway. An unclear error message counts as 'could not ask' and is printed in red with a hint to the credentials, instead of quietly costing a rebuild. A local image is never pushed: the tag carries no content hash, so an old local copy must not end up in the shared registry — a real miss is rebuilt from current sources as before.
- **Fix**: release workflow: the GitHub release is created again. The 'Create GitHub Release' step pasted the collected changelog entries straight into the shell script via ${{ }} interpolation. Patchnote descriptions are free prose, so their backticks were evaluated as command substitution and placeholders like <domain> parsed as redirects — the step aborted with a pile of 'command not found' and 'syntax error near unexpected token' messages, leaving tag and commit pushed but no release. This stayed invisible for as long as the step was being skipped. Tag and notes now travel through the step env and are written to a file for 'gh release create --notes-file', so no patchnote text is ever interpreted by the shell. The v7.2.0 release was created by hand after the fact.
- **Fix**: odoo setup upgrade: local changes in ~/.odoo/images no longer look lost. Before pulling, the upgrade stashes local changes and pops them afterwards. If the upgrade touched the same file, the pop aborts — and that failure was swallowed, so a locally patched Dockerfile fragment or config seemed to be gone. The upgrade now prints git's message plus the commands to get the change back (git stash list / show -p / pop / drop) and the hint that permanent local changes belong upstream instead.


## 7.5.1


- **Fix**: Zwei Dev-Fixes: (1) der SHA-Check im Odoo-Container bricht nicht mehr hart ab, wenn keine CUSTOMS_SHA injiziert wurde (z.B. SHA_IN_DOCKER=0 oder Base-Split-Dev-Builds) - es wird n/a nach /sha geschrieben statt exit -3. (2) Der Robot-Container chownt jetzt auch das echte Home von robot (/opt/robot laut useradd -d), nicht nur /home/robot - sonst konnte der Test-Harness nach dem usermod die robo_params.json bzw. seine temporaeren Suites nicht schreiben. Zum Pruefen: odoo robot run <suite> laeuft wieder durch, und ein Build ohne SHA startet ohne Abbruch.


## 7.5.0


- **Feature**: Neuer Modus ODOO_STANDARD_IMAGE=1: der odoo-Container laeuft dann mit dem offiziellen odoo:<version>-Image von Docker Hub statt mit unserem gebauten Image. Der restliche Stack (Proxy, Postgres, Barman, Monitoring) bleibt unveraendert. Zum Testen: ODOO_STANDARD_IMAGE=1 setzen, odoo reload + odoo up -d - Odoo muss normal hochkommen; update und db reset laufen ueber das mitgelieferte Odoo-CLI. Befehle, die zwingend /odoolib brauchen (shell, debug, lang, Tests), melden sich mit einer verstaendlichen Meldung ab.


## 7.4.0


- **Feature**: `odoo status` now also prints the monitoring URLs: the Grafana dashboard under `<url>/system` and the log view under `<url>/logs`, both on the proxy port. Only shown when RUN_DASHBOARD=1; the dashboard password is printed as well when one is set. To check: run `odoo status` in a project and open the monitoring line in the browser.


## 7.3.1


- **Fix**: Ein MANIFEST, das gerade von einem anderen Prozess (rsync aus dem geteilten CI-Cache, git checkout, gimera) neu geschrieben wird, liest sich kurzzeitig leer — und brach damit bisher nach ~1 Sekunde den ganzen Befehl ab. Die Meldung war 'Could not parse ' ohne Inhalt, und der Abbruch tauchte danach als voelig anderer Fehler wieder auf (z.B. 'somehow dbname is missing' beim restore), was in CI-Logs praktisch nicht diagnostizierbar war. Ein leer/unvollstaendig gelesenes MANIFEST wird jetzt mit exponentiellem Backoff bis zu 15 Sekunden erneut gelesen (ueber ZODOO_MANIFEST_READ_TIMEOUT einstellbar); ein gar nicht vorhandenes MANIFEST kehrt sofort zurueck, statt das Budget zu verbrauchen, und ein MANIFEST ohne 'addons_paths' behaelt seine kurze Wartezeit (der Lesepfad laeuft bei jedem Zugriff, darf also nicht langsamer werden). Gibt zodoo doch auf, nennt die Meldung nun Pfad, Dateigroesse, Wartezeit und den tatsaechlich gesehenen Inhalt. Zusaetzlich raeumt 'robot run' den Selenium-Container jetzt best-effort ab: ein Fehler beim Herunterfahren kann das Testergebnis nicht mehr ueberschreiben — bisher wurde ein Lauf, dessen Tests alle bestanden hatten, dadurch als fehlgeschlagen gemeldet.


## 7.3.0


- **Feature**: >


## 7.2.0


- **Feature**: Optional barman service for PostgreSQL backups with point-in-time-recovery: continuous WAL streaming (no SSH) + daily full backup via cronjobs, plus `odoo barman backup/list/status/check/recover` CLI. Opt-in via RUN_BARMAN=1, off by default and on DEVMODE.
- **Feature**: Add per-instance monitoring dashboard service (Grafana + Prometheus + Loki + Alloy + exporters), reachable via proxy under /system
- **Feature**: `backup files` now backs up the filestore incrementally: a timestamp marker (<dump>.marker) records the start of the last successful run and only source files newer than it are copied (find -newer | rsync --files-from), avoiding the full destination scan that took ~45-65 min over a network share on large filestores. The filestore is content-addressed/immutable, so --ignore-existing is a safe net and --delete is never used (additive). restore files now also accepts the rsync-directory format (legacy tar.gz still supported).
- **Fix**: robot: wait for proxy warmup sentinel before starting tests, ROBOT_URL_PREFIX setting, pass uppercase run-parameters as robot variables; composer: build services that define both image and build, glob-based __after_settings.py discovery; use shutil.copyfile for set_docker_group.sh
- **Feature**: Router-vhosts können jetzt auf IP-Bereiche eingeschränkt werden: Feld `allowed_ips` in vhosts.yml (kommagetrennte IPs/CIDRs) rendert `allow …; deny all;` in den server-Block, alle anderen bekommen 403. Zum Prüfen: `odoo router vhost show <domain>` bzw. die gerenderte Datei in `<install_dir>/sites-enabled/<domain>` — der Block steht direkt unter `client_max_body_size`. Die ACME-Location (`/.well-known/acme-challenge/`) bleibt bewusst für alle offen, damit certbot die Zertifikate weiter erneuern kann. Ohne `allowed_ips` ändert sich nichts (vhost bleibt öffentlich).
- **Feature**: 'New top-level `odoo set-ribbon <text>` command: fetches the version-matched OCA web_environment_ribbon module, wires its path into the MANIFEST addons_paths, installs it if missing and sets the ribbon text (upsert). Handy to mark neutralized/staging databases. `-Q/--quick` only sets the text.'
- **Fix**: backup: 'odoo backup all' works on hosts without the zip package. It shelled out to the external zip binary and aborted with FileNotFoundError: 'zip' wherever that is not installed (backup odoo-db and backup files were unaffected, so only the combined odoo-sh archive failed). The archive is now built with Python's zipfile: no external dependency, and no temporary zipped.zip written into the filestore folder itself. Same layout as before, dump.sql plus filestore/ at the archive root. The restore side had the same problem twice: the dump-type detector probed the archive with 'unzip -l' and swallowed the error, so without the unzip package an odoo-sh archive was silently misdetected as a plain pg_dump and handed to pg_restore — which aborts only after the target database has been dropped — and the odoo-sh restore path itself shelled out to 'unzip'. Both now use zipfile as well, so 'odoo backup all' and 'odoo restore odoo-db <file>.zip' work as a round trip on hosts without zip/unzip installed.
- **Fix**: barman recover: datadir swap runs inside a one-off postgres container instead of writing to the volume's host mountpoint — works on Docker Desktop/Colima/remote daemons (PITR e2e test passes on macOS now)
- **Fix**: base_dockerfile_path resolves against the project's images dir (honors ODOO_IMAGES) instead of hardcoded ~/.odoo/images; remove duplicated _locate_odoo_config_dockerfile
- **Fix**: Proxy serves the construction/maintenance page with HTTP 503 instead of 200, so monitoring and crawlers no longer mistake a down/updating Odoo for a healthy one. Covers all three paths: the standalone construction server, the in-proxy odoo_update gate (now served inline via lua to bypass proxy_intercept_errors), and the @fallback for backend 502/503/504 (now forced to =503). Adds Retry-After: 30 to the construction page.
- **Fix**: robot: wait for odoo healthcheck before tests; settings: follow symlinks via bashfind; composer: match odoo service by name
- **Fix**: Base image build no longer fails when Odoo's upstream requirements.txt pins a version that was later yanked from PyPI (e.g. cbor2==5.4.2). Known-yanked name==version pins are rewritten to a safe release (cbor2 5.4.2 -> 5.4.6) via a small _YANKED_PIN_OVERRIDES table in lib_base_image, so the base rebuilds without bumping the whole Odoo submodule pin.
- **Fix**: postgres: hard abort when user-pinned max_connections cannot be parsed; supervisor: raise on unknown action
- **Fix**: Odoo 16: der Queuejob-Worker bekommt einen eigenen gevent_port (8073) - vorher kollidierte er mit dem Webserver auf 8072 (Address already in use) und eine der beiden Rollen lief in einen Crashloop
- **Fix**: Odoo 19: translate_modules und email_from aus der 19er Config entfernt - Odoo 19 kennt beide Optionen so nicht mehr und schrieb bei jedem Start Warnungen ins Log (auch ins update.log)
- **Fix**: pg17-Image: python3 bleibt im Runtime-Image erhalten - vorher entfernte autoremove es und der Container lief in einen Crashloop (python3: command not found in run.sh)
- **Fix**: Allow PROJECT_NAME pinned in a settings file to differ from the source directory name (e.g. dir 'ipe' with PROJECT_NAME=odoo_prod) — the directory-name sanity check now treats a settings-defined PROJECT_NAME like an explicit -p override and no longer aborts.
- **Fix**: ZODOO_REGISTRY_URL mit Schema (https://) wird frueh mit klarer Meldung abgelehnt statt spaeter als kryptisches 'invalid reference format' beim Image-Build
- **Fix**: release workflow: releases are no longer silently blocked, and patchnotes in subfolders reach the CHANGELOG. Three defects, all of which hid each other: (1) the push used 'git push origin main --tags', which is not atomic — when branch protection rejected main the tag was still pushed, leaving a tag whose release commit never landed on main; that is how v7.1.0 became an orphan while main stayed on 7.0.0. Now pushed with --atomic, so main and tag land together or not at all. (2) Every later run then recomputed the same version from the unchanged VERSION plus the still-present patchnotes, found the existing tag and did 'exit 0' — the job reported success, 'Create GitHub Release' was skipped, and no release was cut for weeks behind a green check. The step now only skips quietly when the tag is an ancestor of main (a genuine re-run) and fails loudly with an explanation otherwise. (3) The changelog loop globbed '.patchnotes/*.yml' (top level only) while the cleanup deleted with 'find .patchnotes -name *.yml -delete' (recursive), so notes in subfolders such as .patchnotes/fix/ were deleted without ever appearing in the CHANGELOG. Collection is recursive now. main has been reconciled with the v7.1.0 tag and the two notes lost that way have been restored.
- **Fix**: odoo reload: rsync source syncs no longer print progress info (log noise); snapshot volume copies keep their progress
- **Fix**: postgres: respect user-set superuser_reserved_connections, last-wins for duplicate max_connections in postgres.conf; CLI: odoo bar prefix resolves again, restart warns on unconfirmed supervisor role; routing + warning paths now tested
- **Fix**: Review follow-ups: keep DB_MAXCONN in sync with a user-pinned postgres max_connections, never leave it unset on malformed input, drop the non-existent ODOO_QUEUEJOB_CHANNELS (singular) read, ensure the base image on `odoo up --build`, broaden the graceful pg shutdown fallback, surface unconfirmed update-blocking-role stops, and harden run_root_cmd input/stdin handling.
- **Fix**: queue_job: only the dedicated queuejobs container runs the job runner. The web and cronjob containers had no [queue_job] channels entry, so the runner fell back to its root:1 default and started there too — up to three runners competed for the same queue_job rows, which showed up as 'SerializationFailure: could not serialize access due to concurrent update' on otherwise healthy jobs and left jobs stranded in state 'enqueued' (a stranded job blocks a capacity-1 channel and stalls the whole queue). After updating and restarting, check the web and cronjob container logs: 'queue job runner ready for db' must appear only in the queuejobs container, and the 'unknown channel <name>, using root channel' warnings are gone. Requires the queuejobs role to be active, which the supervisor spawns whenever queue_job is installed in the project DB.
- **Fix**: Unit-Test: der Stub fuer lib_control_with_docker.shell nimmt jetzt die debug/debug_port-kwargs an - der Test war seit der Einfuehrung von odoo shell --debug rot und hat alle offenen PRs blockiert
- **Fix**: odoo status now shows project info; odoo barman-status added as top-level shortcut for barman status
- **Fix**: ODOO_FILES_COMMON=1 now shares the attachment filestore via hardlinks instead of replacing each filestore/<db> by a symlink to filestore/_common. The symlink also shared Odoo's GC checklist, so one database's nightly autovacuum deleted the freshly written attachments of every other instance on the host (missing images, HTTP 500 on /web/assets/... bundles, therefore no login). New commands: `odoo filestore unshare` migrates legacy symlinks without extra disk space, `odoo filestore dedup` re-links per-database filestores into the pool.
- **Fix**: remove_webassets (odoo setup remove-web-assets, and the restore step unless NO_REMOVE_WEB_ASSETS_AFTER_RESTORE=1) no longer runs `delete from ir_asset` on Odoo >= 17. Since Odoo 15 the bundles are built purely from ir.asset records, which are created from the modules' manifest at install/update time and are not recreated by a restart or an admin login - so the purge left the instance with empty bundles and HTTP 500 on /web/assets/... until `odoo update` ran. Instead the generated bundle attachments are deleted by their url. Plus: `odoo filestore unshare` now skips databases whose postgres cannot be reached instead of aborting the sweep.
- **Fix**: restart_unhealthy_containers: also detect crash-looping containers (via RestartCount episode tracking across cron ticks), stuck-in-'starting' containers and crashed 'exited' containers (non-clean exit code / OOM-killed), not only health=unhealthy. Plus: per-job lock in cronjobs run.py, anchored docker name filters (script + lib_robot), committed pytest coverage for the script.
- **Fix**: restart_unhealthy_containers: drop crash-loop episode state of stopped containers so a stale episode can't fire prematurely when the container returns


## 7.1.0

- **Feature**: Odoo 19: check for missing fonttools and offer to add it to requirements.static on reload
- **Feature**: odoo build --repair-zodoo-registry: rebuild locally and overwrite a corrupt/stale image in the zodoo (fast-build helper) registry; bundles --no-zodoo-pull + --force-zodoo-registry-push (-ZPf), asks interactively about --no-cache
- **Feature**: odoo setup upgrade warns (and asks to wait) when CI pipelines are currently running on main, i.e. a new release is on the way; skipped in ZODOO_DEVMODE/ZODOO_ALPHA and never blocks on network errors
- **Fix**: release workflow: skip tag creation if version tag already exists (idempotent)

## 7.0.0

- **BREAKING**: project Dockerfile reordered (zodoo-CLI install runs before volatile ODOO_PROJECT_REQUIREMENTS) so adding one new pip dep no longer triggers a 130s rebuild; ODOO_REQUIREMENTS → ODOO_PROJECT_REQUIREMENTS rename clarifies framework vs project — Build args renamed: ODOO_REQUIREMENTS → ODOO_PROJECT_REQUIREMENTS, ODOO_DEB_REQUIREMENTS → ODOO_PROJECT_DEB_REQUIREMENTS (plus \_CLEARTEXT variants). External tools or CI scripts that set these env vars directly must be updated. Existing projects need one `odoo reload` after updating to pick up the regenerated Dockerfile.project.template with the new MARKER COMMON_STATIC layout.
- **Internal**: CI: pytest.yml triggert jetzt auch bei direct-push auf main (nicht nur bei PR) — bisher gab's keinen Test-Run bei push-to-main, Feedback kam erst über den Release-Workflow
- **BREAKING**: RUN_REDIS default auf 0 — Redis-Container startet nicht mehr automatisch. Projekte, die Redis explizit brauchen (z.B. session-store, custom caching), müssen RUN_REDIS=1 in ihren settings setzen — Bestehende Projekte, die implizit auf den default-Redis-Container gesetzt haben, müssen RUN_REDIS=1 in ~/.odoo/settings.<project> oder ./.odoo/settings nachtragen. Odoo selbst nutzt Redis nicht — das betrifft nur Custom-Setups.
- **Docs**: README.md: CRONJOB_DADDY_CLEANUP-Tabellenzelle in inline-code gewrappt — vorher hat Markdown den * in der Cron-Expression als Formatierung interpretiert und 'CRONJOB*DADDY_CLEANUP' gerendert
- **Feature**: nginx proxy holds API requests and serves a maintenance page to browsers while Odoo is warming up, so external clients never hit a cold worker
- **Fix**: odoo restart/kill/up akzeptieren odoo_web, odoo-web und odoo.web als equivalente Schreibweisen (analog für cronjobs/queuejobs); Tab-Completion schlägt alle drei Separator-Varianten vor; queue_job-jobrunner Log-Spam (~12 master-election-lost-DEBUG-Zeilen pro Minute) durch log_handler-INFO unterdrückt

## 6.0.0

- **Feature**: Introduce ZODOO_ALPHA=1 setting + `alpha` branch as the staging channel for unstable features. `odoo setup upgrade` now tracks the alpha branch when the flag is set.
- **Fix**: Supervisor now watches the cronjobs and queuejobs roles for DB-connection-loss patterns (server closed connection, psycopg2.InterfaceError, ...) and respawns just that role instead of recycling the whole container. Drops the docker-level healthcheck and the healthcheck_cronjobs/healthcheck_queuejobs scripts — a stuck cron no longer takes the web UI down with it. A user-initiated `odoo kill odoo_cronjobs` is honoured (want_running=False overrides the watchdog).
- **BREAKING**: Decouple zodoo CLI source from container images — source bind-mounted at runtime, only zodoo deps remain in image. Source-only zodoo updates no longer require image rebuilds. Bakery mode (self-contained k8s deploys) opt-in via ZODOO_EMBED=1.
- **Feature**: Split monolithic Odoo image into a shared per-version base image + thin project layer. Etappe 1: hash/tag library and Dockerfile.base for Odoo 18 (no composer wiring yet).
- **Internal**: Unify privilege escalation: every helper that needed sudo (btrfs snapshots, chown/chgrp on dumps + filestore + fix-permissions) now goes through `run_root_cmd` with a three-tier chain — direct → privileged Docker helper → sudo.
- **Fix**: `odoo update -i` (--installed-modules) was short-circuited by the stored SHA-revision: when the DB sha matched HEAD, \_perform_install returned with 'No module update required' before the -i path could run. The SHA shortcut is now skipped when -i is set, so installed modules are always updated.
- **Internal**: Reorder odoo image cleanup to run BEFORE the venv/share tars and consolidate the 5 cleanup RUNs into one — strips **pycache** from /opt/venv + /opt/zodoo_pipx before they are tarred, shrinking venv.tar.zst and the final flattened image.

## 5.1.1

- **Fix**: `odoo update -i` (--installed-modules) was short-circuited by the stored SHA-revision: when the DB sha matched HEAD, \_perform_install returned with 'No module update required' before the -i path could run. The SHA shortcut is now skipped when -i is set, so installed modules are always updated.

## 5.1.0

- **Feature**: Restore the pre-supervisor split-container layout for legacy Odoo v11/v13 images: odoo, odoo*cronjobs, odoo_queuejobs and odoo_update are real compose services again (those versions run Debian Buster with Python 3.7 and predate the in-container supervisor). run.py runs the full prepare (prepare_run_shared + prepare_run_role) so each role container renders its own config*\*. importlib.metadata import is made py3.7-safe in run.py / update_modules.py. lib_control_with_docker only forwards 'odoo restart odoo_cronjobs' etc. to the in-container supervisor on v14+. lib_composer's walrus-operator usage in \_export_container_buildsettings is rewritten so the module parses under Python 3.7 when zodoo is bind-mounted into a legacy container.

## 5.0.0

- **Feature**: Introduce ZODOO_ALPHA=1 setting + `alpha` branch as the staging channel for unstable features. `odoo setup upgrade` now tracks the alpha branch when the flag is set.
- **BREAKING**: Decouple zodoo CLI source from container images — source bind-mounted at runtime, only zodoo deps remain in image. Source-only zodoo updates no longer require image rebuilds. Bakery mode (self-contained k8s deploys) opt-in via ZODOO_EMBED=1.
- **Feature**: Split monolithic Odoo image into a shared per-version base image + thin project layer. Etappe 1: hash/tag library and Dockerfile.base for Odoo 18 (no composer wiring yet).
- **Internal**: Unify privilege escalation: every helper that needed sudo (btrfs snapshots, chown/chgrp on dumps + filestore + fix-permissions) now goes through `run_root_cmd` with a three-tier chain — direct → privileged Docker helper → sudo.
- **Fix**: Stabilize test_run_root_cmd_capture_returns_stdout on Linux CI: stub \_docker_root_helper_available so the patched subprocess.run doesn't reach \_is_real_docker (str/bytes mismatch)
- **Fix**: Sync test_lib_backup with main: backup_files now rsyncs to a directory and \_\_apply_dump_permissions uses chown -R. Restores CI green on main.
- **Internal**: Reorder odoo image cleanup to run BEFORE the venv/share tars and consolidate the 5 cleanup RUNs into one — strips **pycache** from /opt/venv + /opt/zodoo_pipx before they are tarred, shrinking venv.tar.zst and the final flattened image.

## 4.0.0

- **BREAKING**: odoo down -v / --postgres-volume now requires --force; on production also a hostname confirmation. Plain odoo down (no volume removal) works without force everywhere. — Plain `odoo down` no longer requires --force on production. Volume-removing forms (`-v`, `--postgres-volume`) now uniformly require --force; before --force was only required on production for the non-volume case, and additionally for --postgres-volume.

## 3.2.3

- **Fix**: Run slow (bake) tests before releasing — release job now waits for bake-test to pass
- **Fix**: Fix duplicate --profile flag passed to docker compose up
- **Fix**: Create postgres.logs as directory on Linux before docker compose up to prevent bind-mount file conflict
- **Fix**: Create postgres.socket as directory on Linux before docker compose up
- **Fix**: Add missing profile parameter to up mock in test_up_command_dispatches_and_runs_after_up

## 3.2.2

- **Fix**: Always set DB_MAXCONN even when user overrides postgres max_connections. Previously, a user-defined max_connections in ~/.odoo/postgres.conf or POSTGRES_CONFIG made **after_settings.py return early without writing DB_MAXCONN, leaving the **DB_MAXCONN\_\_ placeholder unsubstituted in the odoo config and crashing odoo at CLI parse time.

## 3.2.1

- **Fix**: Always set DB_MAXCONN even when user overrides postgres max_connections. Previously, a user-defined max_connections in ~/.odoo/postgres.conf or POSTGRES_CONFIG made **after_settings.py return early without writing DB_MAXCONN, leaving the **DB_MAXCONN\_\_ placeholder unsubstituted in the odoo config and crashing odoo at CLI parse time.

## 3.2.0

- **Feature**: Add generation field to registry_tag.yml to allow manual hash invalidation (force re-pull from zebroo registry)

## 3.1.0

- **Feature**: Add generation field to registry_tag.yml to allow manual hash invalidation (force re-pull from zebroo registry)

## 3.0.3

- **Fix**: Remove Deadsnakes PPA dependency by explicitly installing Python 3.10/3.11 from Ubuntu standard repos
- **Fix**: Switch v11/v13 Dockerfile CMD from run.py to supervisor.py so odoo kill/up odoo_cronjobs works
- **Fix**: Add missing dirs[images] to test fixtures after buildx allow-opts change
- **Fix**: Add missing project_name and HOST_RUN_DIR attributes to test fixtures for \_build_with_network_retry and test_build_passes_targetarch_as_build_arg

## 3.0.2

- **Fix**: Prevent MANIFEST read failures caused by non-atomic writes from rsync/git checkout during CI

## 3.0.1

- **Fix**: odoo setup upgrade now always installs the latest gimera (pipx inject --force)

## 3.0.0

- **Internal**: Bump bake-test long_timeout from 30 to 60 min to survive cold-cache builds on busy machines (e.g. Python prebuilt compile when registry image hasn't been pushed yet).
- **Feature**: debug: --one-action flag, frozen_modules fix, unit test logfile
- **Feature**: Use docker buildx bake when buildx is available, fall back to docker compose build otherwise
- **Feature**: Per-image registry tags: each image gets its own content-based tag instead of a global one, reducing unnecessary rebuilds
- **Feature**: Pull compiled Python from the zodoo registry (multi-arch) instead of compiling from source in every Odoo build. Adds python_prebuilt/ builder image + build.sh script. Odoo v19 Dockerfile switches its python_builder stage to FROM ${ZODOO_REGISTRY_URL}/zodoo/python:${ODOO_PYTHON_VERSION}-${TARGETARCH}. Cross-arch builds via qemu no longer need to compile Python (which segfaults under qemu-aarch64). Also normalizes the --platform argument (was producing linux/linux/arm64).
- **Feature**: tests: unit tests for sudo_odoo_cmd + bake-test regression guard for permission + double-sudo startup bugs
- **Feature**: Add --verify/-v option to `odoo backup odoo-db` to validate the produced dump with `pg_restore -l`
- **Feature**: Automatically compute superuser_reserved_connections (~10% of max_connections) for PostgreSQL
- **Fix**: Default `_backup_pgdump(verify=False)` so the existing pytest suite still runs after the verify-option feature; add positive/negative tests for the --verify pass-through.
- **Fix**: Restore parallel BuildKit progress output during odoo build by using a PTY when stdout is a terminal
- **Fix**: Stop setting COMPOSE_BAKE=true on regular odoo build (compose-bake mode is unrelated to the bakery feature and breaks multi-service builds)
- **Fix**: Make `test_e2e_cronjob_driven_backup` robust against session-fixture state from prior backup/restore tests: wait for postgres health, kill stale cronjobs container before reload, dump container logs on failure, raise poll deadline 3 → 5 min.
- **Fix**: Prevent MANIFEST read failures caused by non-atomic writes from rsync/git checkout during CI
- **Fix**: MyConfigParser: add **contains** and **iter** so `key in settings` no longer crashes with `KeyError: 'Key N doesn't exist'`
- **Fix**: Fix postgres connection leaks in `get_conn` (odoo_config), `wait_postgres` (odoo/bin/tools.py) and `DBSizeOutputter` / `execute` (cronjobs/bin/postgres.py). Without `contextlib.closing` around `psycopg2.connect()` the `with` block only ends the transaction, leaking the connection — heavy reset_db / update flows hit `FATAL: sorry, too many clients already`. Also fix test_zodoo basetest defaults (disable queue_job server-wide so tests don't import a missing OCA module).
- **Fix**: Raise computed postgres max_connections — old formula (1.2 conns/process + 10 buffer) yielded 22 for default 6+2+2 process counts and exhausted instantly during `odoo update`. New: 3 conns/process + 30 buffer + 100 floor.
- **Fix**: Pass ZODOO_REGISTRY_URL via env to python_prebuilt/build.sh so it doesn't fail with `exit 2` when ~/.odoo/settings doesn't exist (CI runners). Script also reads from env first, falls back to settings file.
- **Fix**: \_ensure_prebuilt_python_image only attempts `--push` when ~/.docker/config.json has auth credentials for the target registry. Without this guard, CI runners (no creds) failed the hook with a 401 even though a local-only build would have been enough for the subsequent docker compose build.
- **Fix**: Auto-build prebuilt-Python hook now finds Dockerfile when config.odoo_version is a float (19.0) but the on-disk dir is named '19'; fixes silent no-op that allowed bake/builds to fail with the original `not found` error.
- **Fix**: `odoo psql` / `pg_dump` / `pg_restore` now route through the `pgtools` compose service whenever it is available, instead of always falling back to a `docker run --network=host postgres:17` container. The host-networked fallback cannot resolve compose-internal host names (e.g. `postgres`), so it broke on CI runners where the postgres container's port is not published on the host.
- **Fix**: Fix odoo build hanging after Docker build completes on macOS (PTY empty-read loop)
- **Fix**: Fix `_queue_job_installed` exception catch on psycopg2 builds where the `psycopg2.errors` submodule isn't auto-imported (CI runner). Replace specific subclasses with bare `except Exception` — the probe is fail-soft anyway.
- **Fix**: Skip zodoo-registry-setup prompt in non-interactive shells (CI, cron) instead of aborting the build
- **Fix**: Resolve `odoo reload` clash with `odoo router reload` (registration-order tiebreak in AliasedGroup)
- **Fix**: dev-env remove-settings: skip gracefully when ir_config_parameter table does not exist yet
- **Fix**: Fix 8 failing unit tests: \_FakeProc context manager + buildx --set assertions
- **Fix**: Isolate E2E tests from global DEVMODE=1 setting to prevent docker compose kill failures
- **BREAKING**: Consolidate odoo / odoo_cronjobs / odoo_queuejobs / odoo_update into a single container managed by an internal supervisor. odoo_debug stays as a manual-profile service on the same image. — `odoo restart odoo` now restarts the entire odoo container (web + cronjobs + queuejobs). Use `odoo restart odoo_cronjobs` / `odoo restart odoo_queuejobs` (backwards-compat — they now drive the in-container supervisor) or `docker exec <proj>_odoo /opt/venv/bin/python /odoolib/supervisor.py restart <role>` for per-role restarts. `UPDATE_ON_STARTUP=1` is still honoured and now handled by supervisor.py before any role is spawned. Obsolete settings ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER / ODOO_CRON_IN_ONE_CONTAINER are ignored with a warning — toggle RUN_ODOO_CRONJOBS / RUN_ODOO_QUEUEJOBS / RUN_ODOO_WEB to disable individual roles instead.
- **Feature**: add ncdu to robot, selenium_customized, vscode images
- **Fix**: sudoers env_keep whitelist in common.docker so ENV vars set for root (k8s pod spec / docker -e) reach the odoo user under `sudo -u odoo`

## 2.0.8

- **Fix**: Isolate E2E tests from global DEVMODE=1 setting to prevent docker compose kill failures

## 2.0.7

- **Fix**: `odoo psql` / `pg_dump` / `pg_restore` now route through the `pgtools` compose service whenever it is available, instead of always falling back to a `docker run --network=host postgres:17` container. The host-networked fallback cannot resolve compose-internal host names (e.g. `postgres`), so it broke on CI runners where the postgres container's port is not published on the host.

## 2.0.6

- **Fix**: `odoo psql` / `pg_dump` / `pg_restore` now route through the `pgtools` compose service whenever it is available, instead of always falling back to a `docker run --network=host postgres:17` container. The host-networked fallback cannot resolve compose-internal host names (e.g. `postgres`), so it broke on CI runners where the postgres container's port is not published on the host.

## 2.0.5

- **Fix**: Skip zodoo-registry-setup prompt in non-interactive shells (CI, cron) instead of aborting the build

## 2.0.4

- **Fix**: Pass ZODOO_REGISTRY_URL via env to python_prebuilt/build.sh so it doesn't fail with `exit 2` when ~/.odoo/settings doesn't exist (CI runners). Script also reads from env first, falls back to settings file.

## 2.0.3

- **Fix**: Pass TARGETARCH explicitly as --build-arg so prebuilt Python image resolves under docker buildx bake

## 2.0.2

- **Fix**: MyConfigParser: add **contains** and **iter** so `key in settings` no longer crashes with `KeyError: 'Key N doesn't exist'`

## 2.0.1

- **Fix**: \_ensure_prebuilt_python_image only attempts `--push` when ~/.docker/config.json has auth credentials for the target registry. Without this guard, CI runners (no creds) failed the hook with a 401 even though a local-only build would have been enough for the subsequent docker compose build.

## 2.0.0

- **BREAKING**: queue_job is now auto-detected from the project DB (`ir_module_module` probe). RUN_ODOO_QUEUEJOBS toggle is removed — the queuejobs role is spawned iff queue_job is installed. Server-wide-modules list follows the same probe. Mandatory ODOO_QUEUEJOBS_CHANNELS / QUEUEJOB_CHANNELS_FILE fail-loud at container start when missing. — RUN_ODOO_QUEUEJOBS / ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER / ODOO_CRON_IN_WEB_CONTAINER / ENABLE_QUEUEJOBS env vars are ignored. Set ODOO_QUEUEJOBS_CHANNELS=root:1 (or higher) when you have queue_job installed.
- **Fix**: Fix `_queue_job_installed` exception catch on psycopg2 builds where the `psycopg2.errors` submodule isn't auto-imported (CI runner). Replace specific subclasses with bare `except Exception` — the probe is fail-soft anyway.

## 1.3.4

- **Fix**: Raise computed postgres max_connections — old formula (1.2 conns/process + 10 buffer) yielded 22 for default 6+2+2 process counts and exhausted instantly during `odoo update`. New: 3 conns/process + 30 buffer + 100 floor.
- **Fix**: Resolve `odoo reload` clash with `odoo router reload` (registration-order tiebreak in AliasedGroup)

## 1.3.3

- **Fix**: Fix postgres connection leaks in `get_conn` (odoo_config), `wait_postgres` (odoo/bin/tools.py) and `DBSizeOutputter` / `execute` (cronjobs/bin/postgres.py). Without `contextlib.closing` around `psycopg2.connect()` the `with` block only ends the transaction, leaking the connection — heavy reset_db / update flows hit `FATAL: sorry, too many clients already`. Also fix test_zodoo basetest defaults (disable queue_job server-wide so tests don't import a missing OCA module).

## 1.3.2

- **Fix**: Make `test_e2e_cronjob_driven_backup` robust against session-fixture state from prior backup/restore tests: wait for postgres health, kill stale cronjobs container before reload, dump container logs on failure, raise poll deadline 3 → 5 min.

## 1.3.1

- **Internal**: Bump bake-test long_timeout from 30 to 60 min to survive cold-cache builds on busy machines (e.g. Python prebuilt compile when registry image hasn't been pushed yet).

## 1.3.0

- **Feature**: `odoo build` retries once with `--no-cache` when the failure looks like a transient Launchpad / DNS hiccup (`ServerNotFoundError`, `api.launchpad.net`, `Could not resolve host`) — refreshes the apt layer that often poisons the cache.

## 1.2.1

- **Fix**: Auto-build prebuilt-Python hook now finds Dockerfile when config.odoo_version is a float (19.0) but the on-disk dir is named '19'; fixes silent no-op that allowed bake/builds to fail with the original `not found` error.

## 1.2.0

- **Feature**: `odoo build` now auto-builds & pushes the prebuilt Python image (registry/zodoo/python:<ver>-<arch>) on registry miss instead of failing with a cryptic Docker `not found` error.

## 1.1.0

- **Feature**: Add --verify/-v option to `odoo backup odoo-db` to validate the produced dump with `pg_restore -l`
- **Fix**: Default `_backup_pgdump(verify=False)` so the existing pytest suite still runs after the verify-option feature; add positive/negative tests for the --verify pass-through.

## 1.0.2

- **Fix**: Stream docker push output live so users see per-layer registry push progress instead of a silent wait

## 1.0.1

- **Fix**: Install gimera from PyPI in coding container; old GitHub repo Odoo-Ninjas/gimera no longer exists

## 1.0.0

- **Feature**: Pull compiled Python from the zodoo registry (multi-arch) instead of compiling from source in every Odoo build. Adds python_prebuilt/ builder image + build.sh script. Odoo v19 Dockerfile switches its python_builder stage to FROM ${ZODOO_REGISTRY_URL}/zodoo/python:${ODOO_PYTHON_VERSION}-${TARGETARCH}. Cross-arch builds via qemu no longer need to compile Python (which segfaults under qemu-aarch64). Also normalizes the --platform argument (was producing linux/linux/arm64).
- **BREAKING**: Consolidate odoo / odoo_cronjobs / odoo_queuejobs / odoo_update into a single container managed by an internal supervisor. odoo_debug stays as a manual-profile service on the same image. — `odoo restart odoo` now restarts the entire odoo container (web + cronjobs + queuejobs). Use `odoo restart odoo_cronjobs` / `odoo restart odoo_queuejobs` (backwards-compat — they now drive the in-container supervisor) or `docker exec <proj>_odoo /opt/venv/bin/python /odoolib/supervisor.py restart <role>` for per-role restarts. `UPDATE_ON_STARTUP=1` is still honoured and now handled by supervisor.py before any role is spawned. Obsolete settings ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER / ODOO_CRON_IN_ONE_CONTAINER are ignored with a warning — toggle RUN_ODOO_CRONJOBS / RUN_ODOO_QUEUEJOBS / RUN_ODOO_WEB to disable individual roles instead.

## Unreleased

- **Feature**: EXTERNAL_DOMAIN accepts a comma-separated list of URLs (e.g. `http://10.8.99.1,http://127.0.0.1`). `odoo status` prints each URL on its own line (with `:PROXY_PORT`) so they stay cmd+clickable in the terminal.

## 0.19.1

- **Fix**: MANIFEST writer aborts instead of overwriting a populated MANIFEST with a near-empty one (would drop install/addons_paths/server-wide-modules). Protects against accidental truncation seen in the wild.

## 0.19.0

- **Feature**: odoo setup upgrade pins to the latest semver tag by default; release workflow now runs pytest before tagging. Set ZODOO_DEVMODE=1 to keep tracking main on dev hosts.
- **Fix**: CI test steps resolve pipx venv path via `pipx environment --value PIPX_LOCAL_VENVS` instead of hardcoding $HOME/.local/pipx — GitHub's ubuntu-latest runner stores pipx venvs under /opt/pipx.
- **Fix**: CI pytest.yml + release.yml pipx inject step now runs from /tmp so pipx no longer treats the package name 'zodoo' as a path (the repo has a ./zodoo/ directory). Broke silently — pytest.yml had been failing on every push for weeks.

## 0.18.1

- **Fix**: odoo status: omit :PROXY_PORT when EXTERNAL_DOMAIN is a hostname (not an IP)

## 0.18.0

- **Feature**: odoo setup upgrade: early-return when git pull has nothing to fetch — no reinstall, no gimera update, no permission fix

## 0.17.0

- **Feature**: perf: cache bashfind + negative-cache NotInAddonsPath in Module.get_by_name — `odoo reload` ~1.4x faster on projects with many uninstalled modules (bvodin-mig18 17.6s → 12.5s), immune to cold-cache pathologies from per-miss `find .` subprocesses

## 0.16.4

- **Fix**: sudo_odoo_cmd: skip sudo prefix when already running as odoo user — fixes 'odoo is not in the sudoers file' when update_on_startup.py + exec_odoo double-wrap in sudo

## 0.16.3

- **Fix**: prepare_run: chown -R writable dirs so files inside (created by root on first invocation) can be overwritten on re-invocation as the odoo user

## 0.16.2

- **Fix**: prepare_run: chown -R writable dirs so files inside (created by root on first invocation) can be overwritten on re-invocation as the odoo user

## 0.16.1

- **Fix**: fix PermissionError on /etc/odoo/config when update_modules.py runs as odoo user

## 0.16.0

- **Feature**: Print zodoo version at startup in run.py and odoo update

## 0.15.1

- **Fix**: fix PermissionError on /etc/odoo/config when update_modules.py runs as odoo user

## 0.15.0

- **Feature**: postgres: add observability (pg_stat_statements tracking, slow-query log, I/O timing), tune autovacuum, disable JIT, lower max_connections to sane default

## 0.14.4

- **Fix**: E2E test fixtures: start postgres before db reset, remove redundant reload from bake test

## 0.14.3

- **Fix**: bake test symlinks gimera cache into isolated HOME to avoid multi-GB re-clone

## 0.14.2

- **Fix**: Config now falls back to os.environ when no settings file exists (fixes DBNAME lookup in k8s containers that only have ENV vars)

## 0.14.1

- **Fix**: `update_on_startup.py` now runs `odoo update` as the odoo user (via shared `sudo_odoo_cmd` helper), fixing missing DBNAME and root-owned file issues in k8s

## 0.14.0

- **Feature**: `odoo setup zodoo-tests` command to run the unit-test suite (--slow for E2E tests)

## 0.13.3

- **Fix**: graceful fallback when docker CLI is not installed (e.g. inside a Kubernetes container)

## 0.13.2

- **Fix**: sudoers env_keep whitelist in common.docker so ENV vars set for root (k8s pod spec / docker -e) reach the odoo user under `sudo -u odoo`

## 0.13.1

- **Internal**: Release workflow: checkout with RELEASE_PAT secret so the release commit + tag can be pushed past the `main` branch protection (default GITHUB_TOKEN is not in the bypass list)

## 0.13.0

- **Feature**: Add 'backup show-dumps' command to list dumps with size and age (default: newest 5)
- **Feature**: Changelog system with patchnotes, automated versioning and GitHub releases
- **Feature**: Add expanded Claude Code permissions (edit, read, git, tmp) with dynamic home paths
- **Fix**: Remove unused wodoo dependency from cronjobs requirements
- **Fix**: Set http_interface=0.0.0.0 in Odoo configs 15-19 so proxy can reach Odoo inside Docker; also always update outdated modules during odoo update
- **Fix**: Sanitize project name: replace special characters to avoid Docker errors
- **Fix**: Skip registry fallback images with wrong architecture instead of pulling arm64 on amd64 hosts
- **Fix**: Add trailing newline to generated requirements.txt and requirements.txt.all
- **Fix**: Preserve /\_custom/ SCSS attachments (website theme fonts/colors) when running remove-web-assets
- **Feature**: Show changelog since last version after `odoo upgrade`

All notable changes to this project will be documented in this file.

## 0.12.2 — April 2026

### Fixes

- Registry push: skip pushing to the shared zodoo registry when `SRC_EXTRA` is unset/0 (i.e. customer source is baked into the image, e.g. `odoo bake` or default builds that include source) — uploading would publish the customer's code under a tag other customers may pull
- Update at startup: if the stored git SHA is not in the current history (typical for baked images that strip `.git`, or after a rebase/squash), fall back to MANIFEST-mode update with a yellow warning instead of crashing with `subprocess.CalledProcessError`

## 0.12.1 — April 2026

### Fixes

- Import `_is_in_container` in `Config.project_name` setter; fixed `NameError` on `odoo` invocation inside baked containers

### Internal

- Registry: cross-architecture builds run as fully detached subprocess instead of waiting threads, so `odoo bake`/push returns immediately while the other-arch build continues in background (log written to `~/.odoo/log/cross_build_<service>_<arch>.log`)
- Add end-to-end pytest (`pytest -m bake`) and GitHub workflow `bake-test` covering `odoo init` → `reload` → `db reset` → `bake`; runs on PR (relevant paths), `workflow_dispatch` (with version input), and weekly schedule
- Release workflow: target `zodoo/src/setup.cfg` and `zodoo/src/zodoo/version.txt` instead of legacy `wodoo/*` paths (the wodoo→zodoo rename had left the version-bump step writing to a non-existent file, breaking every release since)

## 0.12.0 — April 2026

### Features

- Auto-assign free ports (`odoo next`) during `odoo reload` when DEVMODE is active
- Add `--no-zodoo-push` flag to `odoo build` to skip pushing images to zodoo registry
- Add docs link to zodoo registry setup prompt
- Friendly error message on unauthorized registry push (instead of raw traceback) with hints to configure `ZODOO_REGISTRY_*` settings or use a custom registry

### Fixes

- Fix macOS Docker auth: bypass osxkeychain credential helper in non-interactive sessions (SSH, CI)
- Read DEVMODE from project/user/system settings directly during reload (combined settings file gets deleted)
- Handle unauthorized errors on all push paths (main, arch-specific, background cross-platform)
- Remove leftover `pudb` debugger in zodoo-push command

## 0.11.0 — March 2026

### Features

- Changelog system with patchnotes, automated versioning and GitHub releases
- Zodoo registry: automatic account request when credentials are missing
- `--suppress-other-platform-build` flag to skip QEMU cross-build
- Symmetric cross-build support (ARM <-> AMD64) with buildx
- Integrate gimera as source dependency
- Shared filesystem / common filestore option
- `fix_permissions` command to fix directory ownership via Docker container
- Global file lock for `odoo reload` to prevent concurrent runs
- `backup list` command to show available backup files with age and size
- Slim Docker image builds

### Fixes

- Fix pull of architecture-specific images from zodoo registry
- Fix proxy_exchange dir permissions for nginx worker
- Fix 405 error on registry account request (use HTTPS, explicit POST)
- Fix `odoo console`: export DB vars so `odoo update` works via SSH
- Fix `KeyError` in `list_installed_modules`
- Fix docker build during restore to avoid missing postgres image
- Fix race condition in `start_container` when container name already in use
- Fix `fix_permissions`: fallback to `os.getuid()`, remove debug breakpoint
- Fix requirements newline handling
- Add `@retry` to rsync functions, replace `shutil.copytree` with rsync
- Fix volume removal: call `fix_permissions` on mountpoint when `docker volume rm` fails
- Multiple bugfixes across `lib_src.py`, `module_tools.py`, `lib_control.py`
- Exclude `.pyc` and `__pycache__` from zodoo_src sync in cronjobs

## 0.10.0 — February 2026

### Features

- Global settings switch: user-wide and system-wide settings support
- Settings stored in file (settings_in_file)
- Remove zodoo_src container (faster builds)
- Better warmup strategy
- Delegator configuration support
- Profiles as set
- Improved update strategy

### Fixes

- Fix settings evaluation at reload
- Fix typo in reload
- Fix deb cacher
- Fix directory handling
- Safer uninstall process
- More robust uninstall
- Fix SSH cleanup
- Fix purges

## 0.9.0 — January 2026

### Features

- Odoo 19.0 support (templates, demo data, encryption)
- New wkhtml library for v19
- Sort and order improvements for fields

### Fixes

- Fix robo odoo port configuration
- Fix host directory creation
- Fix postgres config evaluation

## 0.8.0 — December 2025

### Features

- `--enable-queuejobs` flag

### Fixes

- Fix pipx installation in `install.sh`
- Fix entrypoint for Odoo 13
- Odoo 13 compatibility improvements

## 0.7.0

- Initial versioned release
