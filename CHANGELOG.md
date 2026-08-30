# Changelog

## 10.3.0


- **Feature**: |


## 10.2.0


- **Feature**: |


## 10.1.0


- **Feature**: |


## 10.0.2


- |
- **Fix**: |


## 10.0.1


- **Internal**: |


## 10.0.0


- |
- |
- |
- **BREAKING**: Datenbanksicherung von barman auf pgBackRest umgestellt: WAL-Archivierung statt Streaming, Inkrementelle auf Page-Ebene, Aufraeumen als Teil jedes Backups, und ein Repo-Host-Modus, bei dem weder Schluessel noch Loeschrecht auf der Kundenmaschine liegen.
- |
- |
- |


## 9.4.4


- |


## 9.4.3


- **Fix**: 'Ein `odoo update`, das die Container vorher komplett heruntergenommen hat (cicd im Devmode killt das ganze Compose-Projekt) und danach frueh aussteigt (No module update required), liess die Instanz einfach aus: die drei Rollen-Starts liefen per docker exec in einen toten Container, der Fallback griff auf die laengst verschwundenen Compose-Services odoo_web/odoo_queuejobs/odoo_cronjobs zu, und das Update meldete trotzdem completed successfully - eine 3dm-Staging-Instanz stand so gut fuenf Stunden auf 502, bis es jemandem auffiel. Ist der Container weg, wird jetzt der echte Service `odoo` gestartet; sein Supervisor bringt web/queuejobs/cronjobs selbst hoch. Ausserdem im Supervisor: eine Rolle, deren Schalter aus ist (RUN_ODOO_CRONJOBS=0), wird nicht mehr endlos neu gestartet - `odoo update` startet am Ende alle drei Rollen, das Kind stieg sofort wieder aus (Cronjobs shall not run) und wurde etwa zweimal pro Sekunde neu gestartet, auf einer Staging-Instanz sieben Tage lang mit rund 50 Prozent CPU-Last; jeder dieser Starts schiesst per kill_odoo ausserdem auf die laufenden Web-Prozesse. Beim Hochfahren wird postgres mitgestartet (in den generierten Composes gibt es kein depends_on, der odoo-Container haengt sonst still in wait_postgres), und scheitert der Start, sagt das Update das jetzt deutlich statt Erfolg zu melden. Und: `supervisor.py` mit unbekanntem Argument (z.B. --help) fiel bisher in den Daemon-Modus und riss damit im laufenden Container die Web-Prozesse ab - unbekannte Argumente geben jetzt die Usage aus, und ein zweiter Daemon verweigert den Start, wenn der Kontroll-Socket schon antwortet.'


## 9.4.2


- |


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


- **Fix**: |


## 8.0.4


- **Fix**: |
- **Fix**: Der aus dem Verzeichnisnamen abgeleitete Projektname behaelt seine Unterstriche. _sanitize_project_name() hat sie bisher immer entfernt, auch wenn der Name die Laengengrenze gar nicht gerissen hat - aus dem Verzeichnis cicd_3dm_odoo_staging17 wurde so das Projekt cicd3dmodoostaging17. Dafuer gibt es kein ~/.odoo/run/<projekt>/settings, also lief jeder Aufruf ohne -p gegen ein unkonfiguriertes Projekt: Config.__getattribute__ findet keine settings-Datei und liefert None fuer jedes Setting. 'odoo filestore unshare' brach mit 'No filestore at None' ab, 'odoo psql' tat kommentarlos nichts - mit -p <verzeichnisname> lief dasselbe Kommando durch. Die Sanity-Pruefung in cli.py, die sonst bei abweichendem Verzeichnisnamen abbricht, hat den Fall ausdruecklich durchgewunken (name was auto-shortened from this directory), deshalb blieb es unbemerkt. Unterstriche sind in Docker-Compose-Projektnamen erlaubt; sie werden jetzt nur noch entfernt, wenn der Name sonst laenger als 50 Zeichen bliebe, und erst danach wird wie bisher aus der Mitte gekuerzt. Migration: wer ein solches Projekt bisher ohne -p benutzt hat, findet seinen Compose-Stand unter dem alten zusammengezogenen Namen in ~/.odoo/run/ und zieht ihn mit einem 'odoo reload' im Projektverzeichnis nach. Zum Testen: in einem Projektverzeichnis mit Unterstrichen im Namen 'odoo psql' bzw. 'odoo filestore unshare' ohne -p aufrufen - beides muss jetzt dasselbe tun wie mit -p <verzeichnisname>.


## 8.0.3


- **Fix**: >-


## 8.0.2


- **Fix**: `odoo init` legt wieder ein Projekt an. Der Befehl wurde von `offsite init` verdeckt, weil AliasedGroup Unterbefehle nach oben zieht und bei gleichem Namen nach Registrierungsreihenfolge entscheidet — der dokumentierte Schnellstart `odoo init ~/projects/my-odoo` brach mit \No such option '--ai'\ ab. `odoo offsite init` bleibt unverändert erreichbar.


## 8.0.1


- **Fix**: >-


## 8.0.0


- **Internal**: |
- **BREAKING**: | — |


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
