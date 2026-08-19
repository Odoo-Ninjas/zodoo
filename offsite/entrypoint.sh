#!/bin/bash
#
# Offsite-Backup mit BorgBackup.
#
# Verschluesselt wird hier, im Container, VOR dem Upload: `borg init` legt das
# Repository im Modus repokey-blake2 an, der Schluessel liegt (mit der
# Passphrase verschluesselt) im Repository selbst. Der Speicheranbieter sieht
# nur Chiffrat - er kann weder lesen noch unbemerkt manipulieren.
#
set -euo pipefail

SSH_KEY_SRC=/etc/offsite/id_ed25519
SSH_KEY=/tmp/offsite_key
KNOWN_HOSTS=/var/lib/borg/ssh_known_hosts

die() {
    echo "offsite: $*" >&2
    exit 1
}

require_config() {
    [ -n "${OFFSITE_REPO:-}" ] || die \
        "OFFSITE_REPO ist leer - kein Offsite-Ziel konfiguriert."
    [ -n "${OFFSITE_PASSPHRASE:-}" ] || die \
        "OFFSITE_PASSPHRASE ist leer. Ohne Passphrase kein verschluesseltes Repository."
    # Der Schluessel gehoert zum Transport, nicht zum Repository: ein lokales
    # Ziel (eingehaengte Platte) braucht keinen, und ihn dort zu verlangen
    # legte jedes Backup ohne entfernten Speicher lahm.
    if is_remote_repo; then
        [ -f "$SSH_KEY_SRC" ] || die \
            "Kein SSH-Key unter $SSH_KEY_SRC (Host: \$OFFSITE_SSH_DIR/id_ed25519)."
    fi
}

# Zwei Arten von Zielen:
#
#   ssh://user@host/pfad   ein entfernter Speicher (Storage Box o.ae.).
#                          Braucht einen Schluessel und borg auf der Gegenseite.
#   /pfad                  ein eingehaengtes Dateisystem (bei uns die
#                          NFS-Platte). Borg arbeitet dort direkt, ohne ssh --
#                          und ohne borg auf der Gegenseite, denn es gibt
#                          keine.
#
# Verschluesselt wird in beiden Faellen gleich, naemlich HIER, bevor etwas
# den Container verlaesst. Wo die Kiste danach steht, aendert daran nichts:
# der Speicher sieht Chiffrat, ob er nun per ssh oder per NFS angebunden ist.
is_remote_repo() {
    case "${OFFSITE_REPO:-}" in
        ssh://*) return 0 ;;
        *) return 1 ;;
    esac
}

setup_ssh() {
    if ! is_remote_repo; then
        # Lokales Ziel: kein Schluessel noetig. Stattdessen pruefen, ob das
        # Verzeichnis ueberhaupt da ist -- eine nicht eingehaengte NFS-Platte
        # sieht sonst aus wie ein leeres Repo, und borg legte munter ein neues
        # auf der lokalen Platte an. Das faellt erst auf, wenn man es braucht.
        local dir="${OFFSITE_REPO%/*}"
        [ -d "$dir" ] || die \
            "Offsite-Ziel $OFFSITE_REPO liegt nicht in einem vorhandenen Verzeichnis - ist die Platte eingehaengt?"
        return 0
    fi
    # Der Key kommt read-only von aussen und traegt womoeglich die Rechte des
    # Host-Users; ssh verweigert alles ausser 0600. Deshalb Kopie statt
    # chmod auf dem Original (das read-only gemountet ist).
    install -m 600 /dev/null "$SSH_KEY"
    cat "$SSH_KEY_SRC" > "$SSH_KEY"
    mkdir -p "$(dirname "$KNOWN_HOSTS")"
    touch "$KNOWN_HOSTS"
    # accept-new: der erste Kontakt pinnt den Hostkey (TOFU), jede spaetere
    # Aenderung bricht ab. Nicht "no" - das wuerde einen ausgetauschten
    # Serverschluessel stillschweigend akzeptieren.
    export BORG_RSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KNOWN_HOSTS -o BatchMode=yes"
}

# borg liest die Passphrase aus der Umgebung; sie steht damit zwar in der
# Prozessumgebung dieses Containers, aber nicht in der Kommandozeile (die
# jeder Prozess auf dem Host via /proc sehen koennte).
export BORG_PASSPHRASE="${OFFSITE_PASSPHRASE:-}"
export BORG_REPO="${OFFSITE_REPO:-}"

repo_exists() {
    borg info >/dev/null 2>&1
}

ensure_unlocked() {
    # Wird ein Lauf hart abgebrochen (Reboot, OOM-Killer, `docker stop`),
    # bleiben Sperren im Repository und im lokalen Cache liegen - jeder
    # weitere Lauf scheitert dann dauerhaft an "Failed to create/acquire the
    # lock", also genau so lange, bis jemand von Hand eingreift. Ein
    # Backup, das nach dem ersten Abbruch nie wieder laeuft, ist wertlos.
    #
    # Aufgebrochen wird nur bei einem echten Sperrfehler und nur hier, VOR dem
    # eigentlichen Lauf: das Repository gehoert genau einem Projekt, und
    # gleichzeitige Laeufe schliesst der feste Containername aus (siehe
    # lib_offsite.py). Ein "Repository existiert nicht" faellt nicht darunter.
    # Zwei verschiedene Sperren, und `borg break-lock` raeumt nur die eine:
    # die des Repositories. Die Sperre des LOKALEN Cache-Volumes bleibt liegen
    # und blockiert dann jeden weiteren Lauf - sie muss direkt entfernt werden.
    # Weil jeder Lauf in einem frischen Container startet und der Containername
    # parallele Laeufe ausschliesst, ist eine hier noch vorhandene Cache-Sperre
    # immer eine Leiche.
    local stale
    stale=$(find "${BORG_CACHE_DIR:-/var/lib/borg/cache}" -maxdepth 2 \
        \( -name 'lock.exclusive' -o -name 'lock.roster' \) 2>/dev/null || true)
    if [ -n "$stale" ]; then
        echo "offsite: entferne haengende Cache-Sperre eines abgebrochenen Laufs." >&2
        printf '%s\n' "$stale" | xargs -r rm -rf
    fi

    local out
    if out=$(borg info 2>&1); then
        return 0
    fi
    # Bleibt es bei einem Sperrfehler, haengt die Sperre auf der Gegenseite.
    if printf '%s' "$out" | grep -qi "lock"; then
        echo "offsite: haengende Sperre im Repository, breche sie auf:" >&2
        printf '%s\n' "$out" >&2
        borg break-lock || true
    fi
}

do_init() {
    if repo_exists; then
        echo "offsite: Repository existiert bereits."
        return 0
    fi
    echo "offsite: lege verschluesseltes Repository an (repokey-blake2) ..."
    # repokey-blake2: Schluessel im Repo, mit der Passphrase geschuetzt.
    # Damit reichen Repo-URL + Passphrase zur Wiederherstellung - es gibt
    # keine zusaetzliche Schluesseldatei, die man separat verlieren kann.
    borg init --encryption=repokey-blake2
}

do_backup() {
    do_init

    local archive limit_args=()
    # Archivname mit Zeitstempel; borg prune erkennt die Reihenfolge ueber die
    # Metadaten, der Name ist nur fuer Menschen.
    archive="${PROJECT_NAME:-zodoo}-$(date -u +%Y-%m-%dT%H:%M:%S)"

    if [ "${OFFSITE_UPLOAD_LIMIT:-0}" -gt 0 ] 2>/dev/null; then
        limit_args=(--upload-ratelimit "${OFFSITE_UPLOAD_LIMIT}")
    fi

    # Nur Quellen aufnehmen, die es auch gibt: ohne Barman ist /source/barman
    # leer - borg wuerde sonst mit "path does not exist" abbrechen und das
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

    # Ein Archiv ohne Datenbank ist kein Backup, sondern eine Falle: es sieht
    # aus wie eines, bis jemand wiederherstellen will.
    if [ "$have_db" != "1" ] && [ "${OFFSITE_ALLOW_WITHOUT_DB:-0}" != "1" ]; then
        die "Kein Datenbankstand im Backup - weder Barman (RUN_BARMAN=1) noch ein Dump.
Es wuerden nur die Dateien gesichert. Abhilfe: RUN_BARMAN=1 setzen (empfohlen,
bringt zusaetzlich Point-in-Time-Recovery) oder 'odoo offsite backup' benutzen,
das ohne Barman selbst einen Dump zieht. Wenn die Datenbank nachweislich
anderswo gesichert wird, schaltet OFFSITE_ALLOW_WITHOUT_DB=1 diese Pruefung ab."
    fi

    echo "offsite: sichere ${sources[*]} nach $BORG_REPO::$archive"
    borg create \
        --stats --compression "${OFFSITE_COMPRESSION:-zstd,3}" \
        "${limit_args[@]}" \
        "::$archive" "${sources[@]}"

    do_prune
}

do_prune() {
    echo "offsite: raeume alte Archive auf ..."
    borg prune --list \
        --keep-daily "${OFFSITE_KEEP_DAILY:-7}" \
        --keep-weekly "${OFFSITE_KEEP_WEEKLY:-4}" \
        --keep-monthly "${OFFSITE_KEEP_MONTHLY:-6}"
    # Erst compact gibt den Platz auf der Gegenseite wirklich frei.
    borg compact
}

require_config
setup_ssh
ensure_unlocked

case "${1:-backup}" in
    backup) do_backup ;;
    init)   do_init ;;
    prune)  do_prune ;;
    list)   shift; borg list "$@" ;;
    info)   shift; borg info "$@" ;;
    check)  shift; borg check --verify-data "$@" ;;
    borg)   shift; borg "$@" ;;
    *)      die "Unbekannter Befehl: $1" ;;
esac
