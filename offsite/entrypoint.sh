#!/bin/bash
#
# Offsite-Backup mit restic.
#
# Verschluesselt wird hier, im Container, VOR dem Upload: `restic init` legt das
# Repository an, der Schluessel (OFFSITE_PASSPHRASE) steht mit ihm verschluesselt
# im Repository selbst. Der Speicherort sieht nur Chiffrat - er kann weder lesen
# noch unbemerkt manipulieren.
#
# Ziel ist im Regelfall unser eigener Backup-Server (rest-server im Modus
# --append-only): dieser Container darf dort schreiben, aber NICHTS loeschen.
# Eine uebernommene Odoo-Maschine kann die Sicherungen damit nicht zerstoeren.
# Die Aufbewahrung (forget/prune) laeuft deshalb auf dem Backup-Server, nicht
# hier - siehe do_prune().
#
set -euo pipefail

SSH_KEY_SRC=/etc/offsite/id_ed25519
SSH_KEY=/tmp/offsite_key
CA_CERT=/etc/offsite/rest-server.crt
KNOWN_HOSTS=/var/lib/restic/ssh_known_hosts

die() {
    echo "offsite: $*" >&2
    exit 1
}

# Drei Arten von Zielen:
#
#   rest:https://host:8000/bereich/   unser Backup-Server (rest-server). Der
#                                     Regelfall. Append-only, ein Bereich je
#                                     Kunde.
#   sftp:user@host:/pfad              entfernter Speicher (Hetzner Storage Box).
#   /pfad                             eingehaengtes Dateisystem.
#
# Verschluesselt wird in allen Faellen gleich, naemlich HIER, bevor etwas den
# Container verlaesst.
repo_kind() {
    case "${OFFSITE_REPO:-}" in
        rest:*) echo rest ;;
        sftp:*) echo sftp ;;
        s3:*)   echo s3 ;;
        *)      echo local ;;
    esac
}

require_config() {
    [ -n "${OFFSITE_REPO:-}" ] || die \
        "OFFSITE_REPO ist leer - kein Offsite-Ziel konfiguriert."
    [ -n "${OFFSITE_PASSPHRASE:-}" ] || die \
        "OFFSITE_PASSPHRASE ist leer. Ohne Passphrase kein verschluesseltes Repository."
    case "$(repo_kind)" in
        rest)
            # Zugangsdaten des Bereichs. Sie regeln, WER schreiben darf - nicht,
            # wer lesen kann. Das macht die Passphrase.
            [ -n "${OFFSITE_REST_USER:-}" ] || die \
                "OFFSITE_REST_USER ist leer - der Bereich auf dem Backup-Server braucht einen Benutzer.
Mit 'odoo offsite register' wird ein Bereich angefragt und alles Noetige hinterlegt."
            [ -n "${OFFSITE_REST_PASSWORD:-}" ] || die \
                "OFFSITE_REST_PASSWORD ist leer - siehe 'odoo offsite register'."
            ;;
        sftp)
            [ -f "$SSH_KEY_SRC" ] || die \
                "Kein SSH-Key unter $SSH_KEY_SRC (Host: \$HOST_RUN_DIR/offsite/id_ed25519)."
            ;;
    esac
}

setup_transport() {
    case "$(repo_kind)" in
        rest)
            # Benutzer/Passwort gehoeren in die URL, nicht in die Kommandozeile:
            # restic liest das Repository aus RESTIC_REPOSITORY, und die
            # Prozessumgebung sieht - anders als die Kommandozeile - nicht jeder
            # Prozess auf dem Host via /proc.
            local rest="${OFFSITE_REPO#rest:}"
            local scheme="${rest%%://*}"
            local host="${rest#*://}"
            export RESTIC_REPOSITORY="rest:${scheme}://${OFFSITE_REST_USER}:${OFFSITE_REST_PASSWORD}@${host}"
            # Unser Backup-Server hat ein selbst ausgestelltes Zertifikat; das
            # oeffentliche Zertifikat kommt per 'odoo offsite register' auf die
            # Maschine. Ohne es wuerde restic die Verbindung ablehnen - zu Recht.
            if [ -f "$CA_CERT" ]; then
                RESTIC_ARGS+=(--cacert "$CA_CERT")
            else
                echo "offsite: kein Serverzertifikat unter $CA_CERT - restic wird die Verbindung ablehnen. 'odoo offsite register' erneut laufen lassen." >&2
            fi
            ;;
        sftp)
            # Der Key kommt read-only von aussen und traegt womoeglich die Rechte
            # des Host-Users; ssh verweigert alles ausser 0600. Deshalb Kopie
            # statt chmod auf dem Original.
            install -m 600 /dev/null "$SSH_KEY"
            cat "$SSH_KEY_SRC" > "$SSH_KEY"
            mkdir -p "$(dirname "$KNOWN_HOSTS")"
            touch "$KNOWN_HOSTS"
            # accept-new: der erste Kontakt pinnt den Hostkey (TOFU), jede
            # spaetere Aenderung bricht ab. Nicht "no" - das wuerde einen
            # ausgetauschten Serverschluessel stillschweigend akzeptieren.
            RESTIC_ARGS+=(-o "sftp.args=-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KNOWN_HOSTS -o BatchMode=yes")
            export RESTIC_REPOSITORY="$OFFSITE_REPO"
            ;;
        local)
            # Eine nicht eingehaengte Platte sieht aus wie ein leeres Repo, und
            # restic legte munter ein neues auf der lokalen Platte an. Das faellt
            # erst auf, wenn man es braucht.
            local dir="${OFFSITE_REPO%/*}"
            [ -d "$dir" ] || die \
                "Offsite-Ziel $OFFSITE_REPO liegt nicht in einem vorhandenen Verzeichnis - ist die Platte eingehaengt?"
            export RESTIC_REPOSITORY="$OFFSITE_REPO"
            ;;
        *)
            export RESTIC_REPOSITORY="$OFFSITE_REPO"
            ;;
    esac
}

# restic liest die Passphrase aus der Umgebung; sie steht damit zwar in der
# Prozessumgebung dieses Containers, aber nicht in der Kommandozeile.
export RESTIC_PASSWORD="${OFFSITE_PASSPHRASE:-}"
RESTIC_ARGS=()

restic_() {
    restic "${RESTIC_ARGS[@]}" "$@"
}

repo_exists() {
    restic_ cat config >/dev/null 2>&1
}

ensure_unlocked() {
    # Wird ein Lauf hart abgebrochen (Reboot, OOM-Killer, `docker stop`), bleibt
    # eine Sperre im Repository liegen und jeder weitere Lauf scheitert daran -
    # also genau so lange, bis jemand von Hand eingreift. Ein Backup, das nach
    # dem ersten Abbruch nie wieder laeuft, ist wertlos.
    #
    # Aufgebrochen wird nur bei einem echten Sperrfehler und nur hier, VOR dem
    # eigentlichen Lauf: das Repository gehoert genau einem Projekt, und
    # gleichzeitige Laeufe schliesst der feste Containername aus (siehe
    # lib_offsite.py). Ein "Repository existiert nicht" faellt nicht darunter.
    #
    # rest-server erlaubt das Entfernen von Sperren auch im append-only-Modus -
    # genau dafuer ist die Ausnahme dort vorgesehen.
    local out
    if out=$(restic_ cat config 2>&1); then
        return 0
    fi
    if printf '%s' "$out" | grep -qiE "locked|lock"; then
        echo "offsite: haengende Sperre im Repository, breche sie auf:" >&2
        printf '%s\n' "$out" >&2
        restic_ unlock --remove-all || restic_ unlock || true
    fi
}

do_init() {
    if repo_exists; then
        echo "offsite: Repository existiert bereits."
        return 0
    fi
    echo "offsite: lege verschluesseltes Repository an ..."
    # Der Schluessel liegt (mit der Passphrase verschluesselt) im Repository.
    # Damit reichen Repo-Adresse + Passphrase zur Wiederherstellung - es gibt
    # keine zusaetzliche Schluesseldatei, die man separat verlieren kann.
    restic_ init
}

do_backup() {
    do_init

    local limit_args=()
    if [ "${OFFSITE_UPLOAD_LIMIT:-0}" -gt 0 ] 2>/dev/null; then
        limit_args=(--limit-upload "${OFFSITE_UPLOAD_LIMIT}")
    fi

    # Nur Quellen aufnehmen, die es auch gibt: ohne Barman ist /source/barman
    # leer - restic wuerde sonst mit "path does not exist" abbrechen und das
    # gesamte Backup verlieren.
    #
    # have_db haelt fest, ob ueberhaupt ein Datenbankstand im Archiv landet.
    # Das ist der Kern: Filestore gibt es immer, die Datenbank nicht. Ohne
    # diese Buchhaltung lief ein Backup ohne Barman und ohne Dump klaglos
    # durch und sicherte nur die Dateien - der Fehler faellt dann genau dann
    # auf, wenn man das Backup braucht.
    local sources=() have_db=0

    # -d allein genuegt nicht: das barman_data-Volume ist auch bei RUN_BARMAN=0
    # deklariert (siehe docker-compose.yml) und dann ein leeres Verzeichnis.
    if [ -d /source/barman ] && [ -n "$(ls -A /source/barman 2>/dev/null)" ]; then
        sources+=(/source/barman)
        have_db=1
    fi

    # ODOO_FILES ist ein HOST-weiter Pool mit einem Unterordner je Datenbank
    # (filestore/<db>) - auf einem Rechner mit mehreren Instanzen liegen darin
    # auch die Anhaenge fremder Datenbanken. Gesichert wird deshalb gezielt der
    # Ordner dieser Datenbank; nur wenn der (noch) nicht existiert, faellt es
    # auf den ganzen Pool zurueck.
    if [ -n "${DBNAME:-}" ] && [ -d "/source/filestore/filestore/$DBNAME" ]; then
        sources+=("/source/filestore/filestore/$DBNAME")
    elif [ -d /source/filestore ]; then
        echo "offsite: kein filestore/${DBNAME:-?} gefunden - sichere den gesamten Filestore-Pool." >&2
        sources+=(/source/filestore)
    fi

    # Die Dumps sind per Default NICHT dabei: mit Barman ist die Datenbank
    # ueber WAL + Basisbackup bereits abgedeckt, und /host/dumps sammelt oft
    # etliche alte Staende - die jede Nacht mitzuschleppen kostet Platz und
    # Zeit ohne zusaetzliche Sicherheit.
    if [ "${OFFSITE_INCLUDE_DUMPS:-0}" = "1" ] && [ -d /source/dumps ]; then
        sources+=(/source/dumps)
        have_db=1
    elif [ -n "${OFFSITE_DB_DUMP:-}" ]; then
        # Laeuft kein Barman, legt `odoo offsite backup` unmittelbar vor
        # diesem Lauf einen frischen Dump unter diesem Namen ab und reicht
        # ihn hier durch (siehe lib_offsite.py). Fehlt er trotz Ankuendigung,
        # ist beim Dumpen etwas schiefgegangen - dann lieber abbrechen als
        # ein Archiv ohne Datenbank anzulegen, das man fuer vollstaendig haelt.
        if [ -f "/source/dumps/$OFFSITE_DB_DUMP" ]; then
            sources+=("/source/dumps/$OFFSITE_DB_DUMP")
            have_db=1
        else
            die "Der angekuendigte Datenbank-Dump /source/dumps/$OFFSITE_DB_DUMP fehlt."
        fi
    fi

    [ ${#sources[@]} -gt 0 ] || die "Keine Backup-Quellen vorhanden."

    # Ein Snapshot ohne Datenbank ist kein Backup, sondern eine Falle: er sieht
    # aus wie eines, bis jemand wiederherstellen will.
    if [ "$have_db" != "1" ] && [ "${OFFSITE_ALLOW_WITHOUT_DB:-0}" != "1" ]; then
        die "Kein Datenbankstand im Backup - weder Barman (RUN_BARMAN=1) noch ein Dump.
Es wuerden nur die Dateien gesichert. Abhilfe: RUN_BARMAN=1 setzen (empfohlen,
bringt zusaetzlich Point-in-Time-Recovery) oder 'odoo offsite backup' benutzen,
das ohne Barman selbst einen Dump zieht. Wenn die Datenbank nachweislich
anderswo gesichert wird, schaltet OFFSITE_ALLOW_WITHOUT_DB=1 diese Pruefung ab."
    fi

    echo "offsite: sichere ${sources[*]} nach ${OFFSITE_REPO}"
    # --host: der Snapshot traegt den Projektnamen, nicht den zufaelligen
    # Containernamen - sonst sieht die Snapshot-Liste jede Nacht anders aus.
    # --tag: erlaubt 'restic snapshots --tag zodoo' auf dem Backup-Server.
    restic_ backup \
        --host "${PROJECT_NAME:-zodoo}" \
        --tag zodoo \
        --compression "${OFFSITE_COMPRESSION:-auto}" \
        "${limit_args[@]}" \
        "${sources[@]}"

    # Bei append-only-Zielen raeumt der Backup-Server auf, nicht wir - dann hier
    # auch keine Meldung darueber jede Nacht.
    if [ "$(repo_kind)" != "rest" ]; then
        do_prune
    fi
}

do_prune() {
    # Der Regelfall ist ein append-only-Ziel: dieser Container darf dort
    # schreiben, aber nichts loeschen. Das ist der ganze Sinn der Uebung - eine
    # uebernommene Maschine soll die Historie nicht zerstoeren koennen. Also
    # laeuft die Aufbewahrung serverseitig, und zwar dort auch wirklich: sonst
    # waechst das Repository unbegrenzt.
    if [ "$(repo_kind)" = "rest" ]; then
        cat >&2 <<'EOF'
offsite: Dieses Ziel ist append-only - Aufraeumen ist von hier aus nicht
moeglich und auch nicht gewollt. Die Aufbewahrung laeuft auf dem Backup-Server
(Wartungsfenster mit dem dortigen Wartungszugang). Die Settings
OFFSITE_KEEP_DAILY/_WEEKLY/_MONTHLY beschreiben, was dort gelten soll.
EOF
        return 0
    fi
    echo "offsite: raeume alte Snapshots auf ..."
    restic_ forget --prune \
        --keep-daily "${OFFSITE_KEEP_DAILY:-7}" \
        --keep-weekly "${OFFSITE_KEEP_WEEKLY:-4}" \
        --keep-monthly "${OFFSITE_KEEP_MONTHLY:-6}"
}

require_config
setup_transport
ensure_unlocked

case "${1:-backup}" in
    backup) do_backup ;;
    init)   do_init ;;
    prune)  do_prune ;;
    list)   shift; restic_ snapshots "$@" ;;
    info)   shift; restic_ stats "$@" ;;
    check)  shift; restic_ check --read-data "$@" ;;
    restic) shift; restic_ "$@" ;;
    *)      die "Unbekannter Befehl: $1" ;;
esac
