#!/bin/bash
#
# Write-only database backup: pgBackRest base backups + WAL segments.
#
# Same idea as the filestore path, and possible for the same reason - the
# source material is immutable:
#
#   * a WAL object is written once, never changed, and carries the segment name
#     (a strictly increasing hex sequence) in its file name
#   * a backup directory never changes once pgbackrest has written its
#     backup.manifest and recorded the label in backup.info
#
# So there is nothing to deduplicate, and therefore no need to read the target -
# which is what would force a decryptable key onto the machine. Here each object
# is encrypted to a PUBLIC key: this machine can neither read nor delete what it
# uploaded.
#
# Two things this buys beyond confidentiality:
#
#   * Completeness is checkable without any key. WAL names are sequential, and
#     the manifest declares which segments belong to which backup, so a gap is
#     visible from the outside.
#   * Retention is possible without any key. Whole generations can be dropped by
#     name.
#
# One object per WAL segment on purpose, rather than nightly bundles: the
# sequence stays visible in the object names, which is what makes the gap check
# work.
#
# Note what this is NOT: it is not pgbackrest's own repo-host topology. That one
# also keeps key and delete rights off this machine, but requires pgbackrest on
# the far side. This path uploads to a dumb receiver that only ever stores what
# it is given, which is why it can serve a target that knows nothing about
# postgres.
#
# Two modes, because they have very different rhythms:
#
#   wal   only WAL segments. Cheap, runs every minute (CRONJOB_OFFSITE_WAL), so
#         the window in which a machine loss costs transactions is a minute
#         rather than a night.
#   db    backups and WAL. Runs after the nightly pgbackrest base backup.
#
# Both take the same lock: a base backup can take longer than a minute, and two
# runs uploading the same object would have the second one rejected by the
# receiver (409, it never overwrites). A minutely cron must not produce a daily
# flood of errors, so a busy lock is a quiet, successful no-op.
#
set -euo pipefail

DB_STATE_DIR=${OFFSITE_STATE_DIR:-/var/lib/offsite-state}
WAL_LEDGER="$DB_STATE_DIR/wal.ledger"
BASE_LEDGER="$DB_STATE_DIR/base.ledger"
PGBR_SRC=/source/pgbackrest

db_die() {
    echo "offsite/db: $*" >&2
    exit 1
}

# Is the write-only database path configured?
wo_db_enabled() {
    [ -n "${OFFSITE_WO_URL:-}" ] && [ -n "${OFFSITE_WO_DB_RECIPIENT:-}" ]
}

db_require() {
    [ -n "${OFFSITE_WO_URL:-}" ] || db_die \
        "OFFSITE_WO_URL is empty - no write-only target configured."
    [ -n "${OFFSITE_WO_DB_RECIPIENT:-}" ] || db_die \
        "OFFSITE_WO_DB_RECIPIENT is empty. Without a public key this would
upload the database in plaintext. Generate a keypair with 'age-keygen', keep
the private key in 1Password and put the public key (age1…) here."
    [ -n "${OFFSITE_REST_USER:-}" ] || db_die "OFFSITE_REST_USER is empty."
    [ -n "${OFFSITE_REST_PASSWORD:-}" ] || db_die \
        "OFFSITE_REST_PASSWORD is empty."
    [ -d "$DB_STATE_DIR" ] || db_die \
        "State directory $DB_STATE_DIR is missing - it holds the ledger of what
has already been uploaded and must be writable and persistent."
}

# pgbackrest keeps one directory per stanza under backup/ and archive/; we run
# exactly one stanza per instance.
db_stanza() {
    local d
    for d in "$PGBR_SRC"/backup/*/; do
        [ -f "$d/backup.info" ] || continue
        basename "${d%/}"
        return 0
    done
    db_die "No pgbackrest repository under $PGBR_SRC. Is RUN_PGBACKREST=1 and
has a backup been taken yet? Without a database state this would upload nothing
but attachments - see the completeness check in entrypoint.sh."
}

# The archive directory for a stanza. pgbackrest nests it one level deeper by
# postgres version and system id (e.g. archive/<stanza>/17-1/), because a major
# upgrade starts a new history that must not mix with the old one.
db_archive_dirs() {
    local stanza="$1"
    find "$PGBR_SRC/archive/$stanza" -mindepth 1 -maxdepth 1 -type d 2>/dev/null
}

# Upload every archived WAL segment that is not in the ledger yet. Fills the
# global WAL_ENTRIES/NEW_WAL, so both modes can share it.
db_upload_wal() {
    local stanza="$1" base="$2" work="$3"
    local seg fname name r adir
    WAL_ENTRIES=()
    NEW_WAL=0
    KNOWN_WAL=0
    while read -r seg; do
        [ -n "$seg" ] || continue
        fname=$(basename "$seg")
        # pgbackrest names a segment <24 hex>-<sha1>[.compression]. The ledger
        # key is the bare segment name: it is what makes the sequence - and
        # therefore a gap - visible, and it stays stable if the repository is
        # ever reconfigured to a different compression.
        name=${fname%%-*}
        case "$name" in
            [0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]) ;;
            *) continue ;;
        esac
        grep -qxF "$name" "$WAL_LEDGER" && continue
        # NOT compressed again: pgbackrest already compressed the segment when
        # it archived it. Running gzip over a .zst would cost CPU and add size.
        age -r "$OFFSITE_WO_DB_RECIPIENT" -o "$work/w.age" "$seg"
        r=$(wo_put_file "$work/w.age" "wal-${fname}.age" "$base")
        if [ -z "$r" ]; then
            # Already there: record it locally, but do not count it as an
            # upload - otherwise a reset would report "13 segments uploaded"
            # when not a byte left the house.
            echo "$name" >> "$WAL_LEDGER"
            KNOWN_WAL=$((KNOWN_WAL + 1))
            rm -f "$work/w.age"
            continue
        fi
        WAL_ENTRIES+=("{\"segment\":\"$name\",\"object\":\"$(echo "$r" | cut -d' ' -f1)\",\"sha256\":\"$(echo "$r" | cut -d' ' -f2)\",\"size\":$(echo "$r" | cut -d' ' -f3)}")
        # Extended only after a successful upload: a crash costs a repeated
        # upload, never a segment believed safe that never arrived.
        echo "$name" >> "$WAL_LEDGER"
        NEW_WAL=$((NEW_WAL + 1))
        rm -f "$work/w.age"
    done < <(for adir in $(db_archive_dirs "$stanza"); do
                 find "$adir" -type f ! -name '*.history' ! -name 'archive.info*' 2>/dev/null
             done | LC_ALL=C sort)
}

# Runs $1 under the shared lock. A busy lock is not an error: with a minutely
# cron it is the normal state while a base backup is being uploaded, and an
# error every minute would drown the real ones.
db_with_lock() {
    local fn="$1"
    exec 9>"$DB_STATE_DIR/db-wo.lock"
    if ! flock -n 9; then
        echo "offsite/db: another run is in progress, skipping this one."
        return 0
    fi
    "$fn"
}

# Minutely mode: WAL only, no base backups.
do_db_wal() {
    db_require
    # Versatz gegen den Gleichtakt: ohne ihn laden 100 Instanzen in derselben
    # Sekunde hoch. Der Wert haengt am Projektnamen, ist also je Maschine fest.
    sleep "$(wo_stagger 45)"
    local stanza base work run_id
    stanza=$(db_stanza)
    WO_CACERT=()
    [ -f "$CA_CERT" ] && WO_CACERT=(--cacert "$CA_CERT")
    base="${OFFSITE_WO_URL%/}"
    run_id=$(date -u +%Y%m%dT%H%M%SZ)
    work=$(wo_workdir)
    # shellcheck disable=SC2064
    trap "rm -rf '$work'" EXIT

    touch "$WAL_LEDGER" "$BASE_LEDGER"
    db_upload_wal "$stanza" "$base" "$work"

    if [ "$NEW_WAL" -eq 0 ]; then
        # Silent on purpose: this runs 1440 times a day and is usually a no-op.
        return 0
    fi

    {
        printf '{\n  "run": "%s",\n  "kind": "db-wal",\n' "$run_id"
        printf '  "host": "%s",\n  "database": "%s",\n' \
            "${PROJECT_NAME:-zodoo}" "${DBNAME:-}"
        printf '  "stanza": "%s",\n' "$stanza"
        printf '  "bases": [],\n'
        printf '  "wal": [%s],\n' "$(IFS=,; echo "${WAL_ENTRIES[*]-}")"
        printf '  "wal_total": %s,\n' "$(wc -l < "$WAL_LEDGER")"
        printf '  "base_total": %s\n}\n' "$(wc -l < "$BASE_LEDGER")"
    } > "$work/manifest.json"
    wo_append_manifest "$base" "$(date -u +%Y%m%d)-db.jsonl" \
        "$(tr -d '\n' < "$work/manifest.json")"
    echo "offsite/db: $NEW_WAL WAL segment(s) uploaded"
}

do_db() {
    db_require
    local stanza
    stanza=$(db_stanza)

    WO_CACERT=()
    [ -f "$CA_CERT" ] && WO_CACERT=(--cacert "$CA_CERT")

    local base="${OFFSITE_WO_URL%/}"
    local run_id
    run_id=$(date -u +%Y%m%dT%H%M%SZ)
    local work
    work=$(wo_workdir)
    # shellcheck disable=SC2064  # expand now, not at trap time
    trap "rm -rf '$work'" EXIT

    touch "$WAL_LEDGER" "$BASE_LEDGER"

    # ---------------------------------------------------------------- base --
    # Only backups pgbackrest has recorded in backup.info. A directory on its
    # own is not enough: it exists while the backup is still being written, and
    # uploading that would record a state that cannot be restored. backup.info
    # is pgbackrest's own catalogue and the label appears there only when the
    # backup is complete and its WAL has been verified as archived.
    local base_entries=() new_bases=0
    local info_file="$PGBR_SRC/backup/$stanza/backup.info"
    [ -f "$info_file" ] || db_die "No backup.info for stanza '$stanza'."

    local label meta wal_start wal_stop btype
    while read -r label meta; do
        [ -n "$label" ] || continue
        grep -qxF "$label" "$BASE_LEDGER" && continue
        [ -d "$PGBR_SRC/backup/$stanza/$label" ] || continue

        echo "offsite/db: backup $label"
        # Streamed, not spooled: a base backup of a large database would
        # otherwise need its own compressed size in scratch space before the
        # first byte goes out. No gzip - the repository contents are already
        # compressed by pgbackrest.
        local res
        res=$(wo_put_stream "backup-${label}.tar.age" "$base" "$work" -- \
            bash -c "tar -C '$PGBR_SRC/backup/$stanza' -cf - '$label' | age -r '$OFFSITE_WO_DB_RECIPIENT'")
        # Empty means it was already there (a repeat after a reset): remember it
        # locally, but do not declare somebody else's ciphertext as ours.
        if [ -z "$res" ]; then
            echo "$label" >> "$BASE_LEDGER"
            continue
        fi
        # The WAL range travels in the manifest, in the clear: without it
        # nobody can tell which segments a backup needs, and the whole point is
        # that the check works without a key.
        wal_start=$(echo "$meta" | jq -r '."backup-archive-start" // ""')
        wal_stop=$(echo "$meta" | jq -r '."backup-archive-stop" // ""')
        btype=$(echo "$meta" | jq -r '."backup-type" // ""')
        base_entries+=("{\"label\":\"$label\",\"type\":\"$btype\",\"object\":\"$(echo "$res" | cut -d' ' -f1)\",\"sha256\":\"$(echo "$res" | cut -d' ' -f2)\",\"size\":$(echo "$res" | cut -d' ' -f3),\"wal_start\":\"$wal_start\",\"wal_stop\":\"$wal_stop\"}")
        echo "$label" >> "$BASE_LEDGER"
        new_bases=$((new_bases + 1))
    done < <(sed -n '/^\[backup:current\]$/,/^\[/p' "$info_file" \
                 | grep -E '^[0-9]{8}-[0-9]{6}[FDI]' \
                 | sed 's/=/ /')

    # ----------------------------------------------------------------- WAL --
    db_upload_wal "$stanza" "$base" "$work"

    if [ "$new_bases" -eq 0 ] && [ "$NEW_WAL" -eq 0 ]; then
        if [ "${KNOWN_WAL:-0}" -gt 0 ]; then
            echo "offsite/db: nothing to send - $KNOWN_WAL object(s) were" \
                 "already on the receiver, ledger brought up to date."
        else
            echo "offsite/db: nothing new (backups and WAL are up to date)."
        fi
        return 0
    fi

    # ------------------------------------------------------------ manifest --
    # Segment names in the clear, deliberately: they are what makes a gap
    # visible to a checker that cannot decrypt anything. Unlike filestore file
    # names - which are content hashes and would leak what is stored - a WAL
    # name says nothing beyond how much WAL there was.
    #
    # The backup type travels too: with full/diff/incr a label alone no longer
    # says whether a state is self-contained, and a checker that cannot decrypt
    # still has to be able to tell whether a restorable chain is present.
    {
        printf '{\n  "run": "%s",\n  "kind": "db",\n' "$run_id"
        printf '  "host": "%s",\n  "database": "%s",\n' \
            "${PROJECT_NAME:-zodoo}" "${DBNAME:-}"
        printf '  "stanza": "%s",\n' "$stanza"
        printf '  "bases": [%s],\n' "$(IFS=,; echo "${base_entries[*]-}")"
        printf '  "wal": [%s],\n' "$(IFS=,; echo "${WAL_ENTRIES[*]-}")"
        printf '  "wal_total": %s,\n' "$(wc -l < "$WAL_LEDGER")"
        printf '  "base_total": %s\n}\n' "$(wc -l < "$BASE_LEDGER")"
    } > "$work/manifest.json"

    wo_append_manifest "$base" "$(date -u +%Y%m%d)-db.jsonl" \
        "$(tr -d '\n' < "$work/manifest.json")"

    echo "offsite/db: done - $new_bases backup(s), $NEW_WAL WAL segment(s)" \
         "uploaded${KNOWN_WAL:+, $KNOWN_WAL already present}"
}
