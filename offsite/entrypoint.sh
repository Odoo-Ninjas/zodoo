#!/bin/bash
#
# Offsite backup with restic.
#
# Encryption happens HERE, inside the container, BEFORE anything is uploaded:
# `restic init` creates the repository, and the key (OFFSITE_PASSPHRASE) is
# stored inside that repository, encrypted with the passphrase. The storage side
# only ever sees ciphertext - it can neither read the backup nor tamper with it
# unnoticed.
#
# The normal target is our own backup server (rest-server running with
# --append-only): this container may write there but may NOT delete anything, so
# a compromised Odoo machine cannot destroy the backups. Retention
# (forget/prune) therefore runs on the backup server, not here - see do_prune().
#
# A run writes TWO separate repositories under the same area:
#
#   <area>/db/     database state (pgbackrest repository or dump)
#   <area>/files/  the filestore of this database
#
# The reason is monitoring, not tidiness: with both in one repository, an
# arriving filestore hides a database dump that stopped coming - the age of the
# area looks fresh while the database state is missing. Split, each stream has
# its own visible age (the backup server alarms per stream). Both live in the
# same area and therefore share access credentials and passphrase - it stays one
# secret per project.
#
# OFFSITE_LAYOUT=flat switches back to the old behaviour (one repository for
# everything). That exists only for legacy installations that should not be
# moved.
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

# Three kinds of target:
#
#   rest:https://host:8000/area/   our backup server (rest-server). The normal
#                                  case. Append-only, one area per customer.
#   sftp:user@host:/path           remote storage (Hetzner Storage Box).
#   /path                          a mounted filesystem.
#
# Encryption is identical in all three cases, namely HERE, before anything
# leaves the container.
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
        "OFFSITE_REPO is empty - no offsite target configured."
    [ -n "${OFFSITE_PASSPHRASE:-}" ] || die \
        "OFFSITE_PASSPHRASE is empty. No encrypted repository without a passphrase."
    case "$(repo_kind)" in
        rest)
            # Credentials for the area. They govern WHO may write - not who can
            # read. Reading is governed by the passphrase.
            [ -n "${OFFSITE_REST_USER:-}" ] || die \
                "OFFSITE_REST_USER is empty - the area on the backup server needs a user.
'odoo offsite register' requests an area and stores everything needed."
            [ -n "${OFFSITE_REST_PASSWORD:-}" ] || die \
                "OFFSITE_REST_PASSWORD is empty - see 'odoo offsite register'."
            ;;
        sftp)
            [ -f "$SSH_KEY_SRC" ] || die \
                "No SSH key at $SSH_KEY_SRC (host: \$HOST_RUN_DIR/offsite/id_ed25519)."
            ;;
    esac
}

setup_transport() {
    case "$(repo_kind)" in
        rest)
            # User and password belong in the URL, not on the command line:
            # restic reads the repository from RESTIC_REPOSITORY, and unlike the
            # command line, a process environment is not readable by every
            # process on the host via /proc.
            local rest="${OFFSITE_REPO#rest:}"
            local scheme="${rest%%://*}"
            local host="${rest#*://}"
            REPO_BASE="rest:${scheme}://${OFFSITE_REST_USER}:${OFFSITE_REST_PASSWORD}@${host}"
            # Our backup server uses a self-issued certificate; the public
            # certificate reaches the machine via 'odoo offsite register'.
            # Without it restic refuses the connection - rightly so.
            if [ -f "$CA_CERT" ]; then
                RESTIC_ARGS+=(--cacert "$CA_CERT")
            else
                echo "offsite: no server certificate at $CA_CERT - restic will refuse the connection. Run 'odoo offsite register' again." >&2
            fi
            ;;
        sftp)
            # The key arrives read-only from outside and may carry the host
            # user's permissions; ssh rejects anything but 0600. Hence a copy
            # rather than chmod on the original.
            install -m 600 /dev/null "$SSH_KEY"
            cat "$SSH_KEY_SRC" > "$SSH_KEY"
            mkdir -p "$(dirname "$KNOWN_HOSTS")"
            touch "$KNOWN_HOSTS"
            # accept-new: first contact pins the host key (TOFU), any later
            # change aborts. Not "no" - that would silently accept a swapped
            # server key.
            RESTIC_ARGS+=(-o "sftp.args=-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KNOWN_HOSTS -o BatchMode=yes")
            REPO_BASE="$OFFSITE_REPO"
            ;;
        local)
            # An unmounted disk looks exactly like an empty repo, and restic
            # would happily create a fresh one on the local disk. That is only
            # discovered when the backup is needed.
            local dir="${OFFSITE_REPO%/*}"
            [ -d "$dir" ] || die \
                "Offsite target $OFFSITE_REPO is not inside an existing directory - is the disk mounted?"
            REPO_BASE="$OFFSITE_REPO"
            ;;
        *)
            REPO_BASE="$OFFSITE_REPO"
            ;;
    esac
}

# restic reads the passphrase from the environment; it is therefore in this
# container's process environment, but not on the command line.
export RESTIC_PASSWORD="${OFFSITE_PASSPHRASE:-}"
RESTIC_ARGS=()
LAYOUT="${OFFSITE_LAYOUT:-split}"

# Every restic call runs against the currently selected stream. REPO_BASE is set
# by setup_transport (credentials included in the URL); use_stream appends the
# sub-path.
use_stream() {
    if [ "$LAYOUT" = flat ] || [ -z "${1:-}" ]; then
        export RESTIC_REPOSITORY="$REPO_BASE"
    else
        export RESTIC_REPOSITORY="${REPO_BASE%/}/$1"
    fi
}

# Which streams do commands like list/info/check iterate over? With flat it is
# the single unnamed one.
all_streams() {
    if [ "$LAYOUT" = flat ]; then echo ""; else echo "db files"; fi
}

stream_label() {
    case "${1:-}" in
        db)    echo "database" ;;
        files) echo "filestore" ;;
        *)     echo "repository" ;;
    esac
}

restic_() {
    restic "${RESTIC_ARGS[@]}" "$@"
}

# Write-only filestore backup (no restic, no key on this machine). Sourced
# rather than exec'd so it can use die()/CA_CERT and be dispatched like the
# other commands.
# shellcheck source=wo-common.sh
. /wo-common.sh
# shellcheck source=filestore-wo.sh
. /filestore-wo.sh
# shellcheck source=db-wo.sh
. /db-wo.sh

# Is the write-only path configured? When it is, it replaces the restic
# filestore stream instead of running next to it - two copies of the same
# attachments in two places is cost without redundancy, and it would make
# "which one do I restore from?" a question nobody wants during an incident.
wo_files_enabled() {
    [ -n "${OFFSITE_WO_URL:-}" ] && [ -n "${OFFSITE_WO_RECIPIENT:-}" ]
}

repo_exists() {
    restic_ cat config >/dev/null 2>&1
}

ensure_unlocked() {
    # When a run is killed hard (reboot, OOM killer, `docker stop`), a lock is
    # left behind in the repository and every later run fails on it - that is,
    # until somebody intervenes by hand. A backup that never runs again after
    # the first abort is worthless.
    #
    # The lock is only broken on an actual lock error, and only here, BEFORE the
    # run itself: the repository belongs to exactly one project, and concurrent
    # runs are ruled out by the fixed container name (see lib_offsite.py). A
    # "repository does not exist" error does not qualify.
    #
    # rest-server permits removing locks even in append-only mode - that is
    # precisely what the exception there is for.
    local out
    if out=$(restic_ cat config 2>&1); then
        return 0
    fi
    if printf '%s' "$out" | grep -qiE "locked|lock"; then
        echo "offsite: stale lock in the repository, breaking it:" >&2
        printf '%s\n' "$out" >&2
        restic_ unlock --remove-all || restic_ unlock || true
    fi
}

do_init() {
    if repo_exists; then
        echo "offsite: repository already exists."
        return 0
    fi
    echo "offsite: creating encrypted repository ..."
    # The key lives inside the repository, encrypted with the passphrase. So
    # repository address plus passphrase are enough to restore - there is no
    # extra key file that can be lost separately.
    #
    # Both streams of an area get the same passphrase. That is deliberate: they
    # belong to one project and are restored together, and two passphrases would
    # be two things to lose without either protecting anything the other does
    # not.
    restic_ init
}

# One stream: create the repository if needed, break a stale lock, back up.
# Reports failure through the return value so that one broken stream does not
# swallow the other (see do_backup).
backup_stream() {
    local stream="$1" tags="$2"
    shift 2
    local sources=("$@")

    [ ${#sources[@]} -gt 0 ] || return 0

    use_stream "$stream"
    ensure_unlocked
    do_init || return 1

    echo "offsite: [$(stream_label "$stream")] backing up ${sources[*]} to ${RESTIC_REPOSITORY##*@}"
    # --host: the snapshot carries the project name rather than the random
    # container name - otherwise the snapshot list looks different every night.
    # --tag: allows 'restic snapshots --tag db' on the backup server.
    restic_ backup \
        --host "${PROJECT_NAME:-zodoo}" \
        --tag "$tags" \
        --compression "${OFFSITE_COMPRESSION:-auto}" \
        ${LIMIT_ARGS[@]+"${LIMIT_ARGS[@]}"} \
        "${sources[@]}" || return 1

    # For append-only targets the backup server cleans up, not us - and then no
    # message about it here every night either.
    if [ "$(repo_kind)" != "rest" ]; then
        do_prune
    fi
}

do_backup() {
    LIMIT_ARGS=()
    if [ "${OFFSITE_UPLOAD_LIMIT:-0}" -gt 0 ] 2>/dev/null; then
        LIMIT_ARGS=(--limit-upload "${OFFSITE_UPLOAD_LIMIT}")
    fi

    # Only include sources that actually exist: without pgbackrest
    # /source/pgbackrest is empty, and restic would abort with "path does not
    # exist" and lose the entire backup.
    #
    # have_db/have_files record whether any database state, respectively any
    # filestore, ends up in the archive at all. That is the crux: neither part
    # is guaranteed to be there, and each without the other is only half the
    # truth. Without this bookkeeping a backup with neither pgbackrest nor a
    # dump ran through without complaint and saved only the files - a mistake
    # that surfaces exactly when the backup is needed.
    local db_sources=() files_sources=() have_db=0 have_files=0

    # -d alone is not enough: the pgbackrest_data volume is declared even with
    # RUN_PGBACKREST=0 (see docker-compose.yml) and is then an empty directory.
    if [ -d /source/pgbackrest ] && [ -n "$(ls -A /source/pgbackrest 2>/dev/null)" ]; then
        db_sources+=(/source/pgbackrest)
        have_db=1
    fi

    # ODOO_FILES is a HOST-wide pool with one subdirectory per database
    # (filestore/<db>) - on a machine with several instances it also holds other
    # databases' attachments. So this database's directory is backed up
    # specifically; only if that does not exist (yet) do we fall back to the
    # whole pool.
    #
    # An EMPTY filestore directory does not count as a filestore: that is
    # exactly what a mount that is not there looks like.
    if [ -n "${DBNAME:-}" ] && [ -d "/source/filestore/filestore/$DBNAME" ]; then
        files_sources+=("/source/filestore/filestore/$DBNAME")
        [ -n "$(ls -A "/source/filestore/filestore/$DBNAME" 2>/dev/null)" ] && have_files=1
    elif [ -d /source/filestore ] && [ -n "$(ls -A /source/filestore 2>/dev/null)" ]; then
        echo "offsite: no filestore/${DBNAME:-?} found - backing up the whole filestore pool." >&2
        files_sources+=(/source/filestore)
        have_files=1
    fi

    # Dumps are NOT included by default: with pgbackrest the database is already
    # covered by WAL plus base backup, and /host/dumps often accumulates many
    # old states - dragging those along every night costs space and time without
    # adding safety.
    if [ "${OFFSITE_INCLUDE_DUMPS:-0}" = "1" ] && [ -d /source/dumps ]; then
        db_sources+=(/source/dumps)
        have_db=1
    elif [ -n "${OFFSITE_DB_DUMP:-}" ]; then
        # With pgbackrest off, `odoo offsite backup` writes a fresh dump under this
        # name immediately before this run and passes it in (see
        # lib_offsite.py). If it is missing despite being announced, something
        # went wrong while dumping - and then it is better to abort than to
        # create an archive without a database that everyone believes to be
        # complete.
        if [ -f "/source/dumps/$OFFSITE_DB_DUMP" ]; then
            db_sources+=("/source/dumps/$OFFSITE_DB_DUMP")
            have_db=1
        else
            die "The announced database dump /source/dumps/$OFFSITE_DB_DUMP is missing."
        fi
    fi

    [ $((${#db_sources[@]} + ${#files_sources[@]})) -gt 0 ] || die "No backup sources present."

    # A snapshot without the database is not a backup but a trap: it looks like
    # one until somebody wants to restore.
    if [ "$have_db" != "1" ] && [ "${OFFSITE_ALLOW_WITHOUT_DB:-0}" != "1" ]; then
        die "No database state in the backup - neither pgbackrest
(RUN_PGBACKREST=1) nor a dump. Only the files would be saved. Remedy: set
RUN_PGBACKREST=1 (recommended, it also brings point-in-time recovery) or use
'odoo offsite backup', which pulls a dump itself when pgbackrest is off. If the
database is provably backed up elsewhere, OFFSITE_ALLOW_WITHOUT_DB=1 switches
this check off."
    fi

    # And the other direction, for the same reason: a database without its
    # attachments is restorable but incomplete - invoice PDFs, images and
    # documents are missing, and in Odoo that only shows up when somebody clicks
    # one. An empty or missing filestore directory is the normal case for a
    # volume that was not mounted, not for an empty instance.
    if [ "$have_files" != "1" ] && [ "${OFFSITE_ALLOW_WITHOUT_FILES:-0}" != "1" ]; then
        die "No filestore in the backup - /source/filestore/filestore/${DBNAME:-?} is
missing or empty. The database would be saved and the attachments not; that only
shows up on restore. Check how ODOO_FILES is mounted (docker-compose of the
offsite service) and whether DBNAME is correct. For an instance that really has
no attachments yet, OFFSITE_ALLOW_WITHOUT_FILES=1 switches this check off."
    fi

    if [ "$LAYOUT" = flat ]; then
        # Legacy: one repository for everything.
        backup_stream "" zodoo \
            ${db_sources[@]+"${db_sources[@]}"} \
            ${files_sources[@]+"${files_sources[@]}"}
        return
    fi

    # Both streams are attempted even when one fails: otherwise an error in the
    # first one hides that the second did not run either - and one alarm arrives
    # where two belonged.
    local failed=()
    if wo_db_enabled; then
        db_with_lock do_db || failed+=("database (write-only)")
    else
        backup_stream db "zodoo,db" ${db_sources[@]+"${db_sources[@]}"} \
            || failed+=("database")
    fi
    if wo_files_enabled; then
        do_filestore || failed+=("filestore (write-only)")
    else
        backup_stream files "zodoo,files" ${files_sources[@]+"${files_sources[@]}"} \
            || failed+=("filestore")
    fi

    [ ${#failed[@]} -eq 0 ] || die "Backup failed: ${failed[*]}"
}

do_prune() {
    # The normal case is an append-only target: this container may write there
    # but may not delete. That is the whole point of the exercise - a
    # compromised machine must not be able to destroy the history. So retention
    # runs server-side, and it has to actually run there: otherwise the
    # repository grows without bound.
    if [ "$(repo_kind)" = "rest" ]; then
        cat >&2 <<'EOF'
offsite: This target is append-only - cleaning up from here is neither possible
nor intended. Retention runs on the backup server (in a maintenance window,
using the maintenance access there). The settings
OFFSITE_KEEP_DAILY/_WEEKLY/_MONTHLY describe what should apply there.
EOF
        return 0
    fi
    echo "offsite: pruning old snapshots ..."
    restic_ forget --prune \
        --keep-daily "${OFFSITE_KEEP_DAILY:-7}" \
        --keep-weekly "${OFFSITE_KEEP_WEEKLY:-4}" \
        --keep-monthly "${OFFSITE_KEEP_MONTHLY:-6}"
}

# Read-only commands run over both streams and state which one is being
# reported - a snapshot list without that would be impossible to interpret.
for_each_stream() {
    local stream rc=0
    for stream in $(all_streams); do
        use_stream "$stream"
        if [ "$LAYOUT" != flat ]; then
            echo
            echo "=== $(stream_label "$stream") ($stream) ==="
        fi
        "$@" || rc=$?
    done
    return $rc
}

# The write-only filestore path needs no restic configuration at all - no
# repository, no passphrase. Handle it before require_config so it also works
# on a machine that has nothing but a write-only target.
case "${1:-}" in
    filestore) do_filestore; exit 0 ;;
    db)        db_with_lock do_db; exit 0 ;;
    wal)       db_with_lock do_db_wal; exit 0 ;;
    reset)     shift; wo_reset "${1:-all}"; exit 0 ;;
esac

# Gehen BEIDE Stroeme write-only, wird restic ueberhaupt nicht mehr benutzt -
# dann darf ein Lauf auch keine Repo-Adresse und keine Passphrase verlangen. Das
# ist der Zustand, auf den wir zugehen: die Passphrase ist das teuerste Geheimnis
# im Aufbau, und wer sie nicht braucht, soll sie nicht haben muessen.
if [ "${1:-backup}" = "backup" ] && wo_files_enabled && wo_db_enabled; then
    failed=()
    db_with_lock do_db || failed+=("database (write-only)")
    do_filestore      || failed+=("filestore (write-only)")
    [ ${#failed[@]} -eq 0 ] || die "Backup failed: ${failed[*]}"
    exit 0
fi

require_config
setup_transport

case "${1:-backup}" in
    backup) do_backup ;;
    init)   for_each_stream do_init ;;
    # With append-only the explanation is needed once, not per stream.
    prune)  if [ "$(repo_kind)" = rest ]; then do_prune; else for_each_stream do_prune; fi ;;
    list)   shift; for_each_stream restic_ snapshots "$@" ;;
    info)   shift; for_each_stream restic_ stats "$@" ;;
    check)  shift; for_each_stream restic_ check --read-data "$@" ;;
    # Escape hatch for everything else. Which stream is meant comes from
    # OFFSITE_STREAM (db|files); without it the database stream, because that is
    # the one that matters in an emergency.
    restic) shift
            use_stream "${OFFSITE_STREAM:-db}"
            ensure_unlocked
            restic_ "$@" ;;
    *)      die "Unknown command: $1" ;;
esac
