#!/bin/bash
#
# Write-only database backup: barman base backups + WAL segments.
#
# Same idea as the filestore path, and possible for the same reason - the
# source material is immutable:
#
#   * a WAL segment is written once, never changed, and its name is a strictly
#     increasing hex sequence
#   * a base backup directory never changes once barman marks it DONE
#
# So there is nothing to deduplicate, and therefore no need to read the target -
# which is what forces a decryptable key onto the machine in the restic path.
# Here each object is encrypted to a PUBLIC key: this machine can neither read
# nor delete what it uploaded.
#
# Two things this buys beyond confidentiality:
#
#   * Completeness is checkable without any key. WAL names are sequential, and
#     the manifest declares which segments belong to which base backup, so a
#     gap is visible from the outside. In a restic repository the file names are
#     encrypted, so only a key holder could ever notice a broken chain.
#   * Retention is possible without any key. Whole generations can be dropped by
#     name - which is why this path can be pruned at all, while an append-only
#     restic repository cannot be (forget/prune needs the repo key).
#
# One object per WAL segment on purpose, rather than nightly bundles: the
# sequence stays visible in the object names, which is what makes the gap check
# work.
#
# Two modes, because they have very different rhythms:
#
#   wal   only WAL segments. Cheap, runs every minute (CRONJOB_OFFSITE_WAL), so
#         the window in which a machine loss costs transactions is a minute
#         rather than a night.
#   db    base backups and WAL. Runs after the nightly barman base backup.
#
# Both take the same lock: a base backup can take longer than a minute, and two
# runs uploading the same segment would have the second one rejected by the
# receiver (409, it never overwrites). A minutely cron must not produce a daily
# flood of errors, so a busy lock is a quiet, successful no-op.
#
set -euo pipefail

DB_STATE_DIR=${OFFSITE_STATE_DIR:-/var/lib/offsite-state}
WAL_LEDGER="$DB_STATE_DIR/wal.ledger"
BASE_LEDGER="$DB_STATE_DIR/base.ledger"
BARMAN_SRC=/source/barman

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

# barman keeps one directory per server; we run exactly one.
db_server_dir() {
    local d
    for d in "$BARMAN_SRC"/*/; do
        [ -d "$d/wals" ] || continue
        echo "${d%/}"
        return 0
    done
    db_die "No barman catalogue under $BARMAN_SRC. Is RUN_BARMAN=1 and has
barman taken a base backup yet? Without a database state this would upload
nothing but attachments - see the completeness check in entrypoint.sh."
}

db_curl() {
    curl --fail-with-body --silent --show-error \
        --user "${OFFSITE_REST_USER}:${OFFSITE_REST_PASSWORD}" \
        ${WO_CACERT[@]+"${WO_CACERT[@]}"} "$@"
}

# Upload one already-prepared file and echo "<name> <sha256> <size>".
db_put_object() {
    local file="$1" name="$2" base="$3"
    local sum size
    sum=$(sha256sum "$file" | cut -d' ' -f1)
    size=$(stat -c %s "$file")
    # The receiver refuses to overwrite, so a retried run cannot damage what is
    # already there; the checksum lets it reject a truncated upload without
    # decrypting anything.
    db_curl --upload-file "$file" \
        --header "X-Content-Sha256: $sum" \
        "$base/objects/$name" > /dev/null
    echo "$name $sum $size"
}

# Upload every archived WAL segment that is not in the ledger yet. Fills the
# global WAL_ENTRIES/NEW_WAL, so both modes can share it.
db_upload_wal() {
    local srv="$1" base="$2" work="$3"
    local seg name r
    WAL_ENTRIES=()
    NEW_WAL=0
    # Only from wals/. streaming/ holds the segment currently being written as
    # *.partial - incomplete by definition, and uploading it would put a
    # half-written segment under a name that must mean "complete". The name
    # filter is belt and braces on top of the directory choice.
    while read -r seg; do
        [ -n "$seg" ] || continue
        case "$seg" in *.partial) continue ;; esac
        name=$(basename "$seg")
        grep -qxF "$name" "$WAL_LEDGER" && continue
        gzip -nc "$seg" | age -r "$OFFSITE_WO_DB_RECIPIENT" -o "$work/w.age"
        r=$(db_put_object "$work/w.age" "wal-${name}.gz.age" "$base")
        WAL_ENTRIES+=("{\"segment\":\"$name\",\"object\":\"$(echo "$r" | cut -d' ' -f1)\",\"sha256\":\"$(echo "$r" | cut -d' ' -f2)\",\"size\":$(echo "$r" | cut -d' ' -f3)}")
        # Extended only after a successful upload: a crash costs a repeated
        # upload, never a segment believed safe that never arrived.
        echo "$name" >> "$WAL_LEDGER"
        NEW_WAL=$((NEW_WAL + 1))
        rm -f "$work/w.age"
    done < <(find "$srv/wals" -type f -name '0*' 2>/dev/null | LC_ALL=C sort)
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
    local srv base work run_id
    srv=$(db_server_dir)
    WO_CACERT=()
    [ -f "$CA_CERT" ] && WO_CACERT=(--cacert "$CA_CERT")
    base="${OFFSITE_WO_URL%/}"
    run_id=$(date -u +%Y%m%dT%H%M%SZ)
    work=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$work'" EXIT

    touch "$WAL_LEDGER" "$BASE_LEDGER"
    db_upload_wal "$srv" "$base" "$work"

    if [ "$NEW_WAL" -eq 0 ]; then
        # Silent on purpose: this runs 1440 times a day and is usually a no-op.
        return 0
    fi

    {
        printf '{\n  "run": "%s",\n  "kind": "db-wal",\n' "$run_id"
        printf '  "host": "%s",\n  "database": "%s",\n' \
            "${PROJECT_NAME:-zodoo}" "${DBNAME:-}"
        printf '  "bases": [],\n'
        printf '  "wal": [%s],\n' "$(IFS=,; echo "${WAL_ENTRIES[*]-}")"
        printf '  "wal_total": %s,\n' "$(wc -l < "$WAL_LEDGER")"
        printf '  "base_total": %s\n}\n' "$(wc -l < "$BASE_LEDGER")"
    } > "$work/manifest.json"
    db_curl --upload-file "$work/manifest.json" \
        --header "Content-Type: application/json" \
        "$base/manifests/${run_id}-db-wal.json" > /dev/null
    echo "offsite/db: $NEW_WAL WAL segment(s) uploaded"
}

do_db() {
    db_require
    local srv
    srv=$(db_server_dir)

    WO_CACERT=()
    [ -f "$CA_CERT" ] && WO_CACERT=(--cacert "$CA_CERT")

    local base="${OFFSITE_WO_URL%/}"
    local run_id
    run_id=$(date -u +%Y%m%dT%H%M%SZ)
    local work
    work=$(mktemp -d)
    # shellcheck disable=SC2064  # expand now, not at trap time
    trap "rm -rf '$work'" EXIT

    touch "$WAL_LEDGER" "$BASE_LEDGER"

    # ---------------------------------------------------------------- base --
    # Only backups barman marked DONE. A base backup in WAITING_FOR_WALS is not
    # yet usable: its own WAL has not been archived, and uploading it would
    # record a state that cannot be restored.
    local base_entries=() new_bases=0
    local info id
    for info in "$srv"/meta/*-backup.info; do
        [ -f "$info" ] || continue
        grep -q "^status=DONE$" "$info" || continue
        id=$(basename "$info")
        id=${id%-backup.info}
        grep -qxF "$id" "$BASE_LEDGER" && continue
        [ -d "$srv/base/$id" ] || continue

        echo "offsite/db: packing base backup $id"
        tar -C "$srv/base" -cf - "$id" \
            | gzip -n \
            | age -r "$OFFSITE_WO_DB_RECIPIENT" -o "$work/base.age"
        local res
        res=$(db_put_object "$work/base.age" "base-${id}.tar.gz.age" "$base")
        # begin_wal/end_wal/timeline travel in the manifest, in the clear:
        # without them nobody can tell which WAL a base backup needs, and the
        # whole point is that the check works without a key.
        local begin end tl
        begin=$(sed -n 's/^begin_wal=//p' "$info")
        end=$(sed -n 's/^end_wal=//p' "$info")
        tl=$(sed -n 's/^timeline=//p' "$info")
        base_entries+=("{\"id\":\"$id\",\"object\":\"$(echo "$res" | cut -d' ' -f1)\",\"sha256\":\"$(echo "$res" | cut -d' ' -f2)\",\"size\":$(echo "$res" | cut -d' ' -f3),\"begin_wal\":\"$begin\",\"end_wal\":\"$end\",\"timeline\":\"$tl\"}")
        echo "$id" >> "$BASE_LEDGER"
        new_bases=$((new_bases + 1))
        rm -f "$work/base.age"
    done

    # ----------------------------------------------------------------- WAL --
    db_upload_wal "$srv" "$base" "$work"

    if [ "$new_bases" -eq 0 ] && [ "$NEW_WAL" -eq 0 ]; then
        echo "offsite/db: nothing new (base backups and WAL are up to date)."
        return 0
    fi

    # ------------------------------------------------------------ manifest --
    # Segment names in the clear, deliberately: they are what makes a gap
    # visible to a checker that cannot decrypt anything. Unlike filestore file
    # names - which are content hashes and would leak what is stored - a WAL
    # name says nothing beyond how much WAL there was.
    {
        printf '{\n  "run": "%s",\n  "kind": "db",\n' "$run_id"
        printf '  "host": "%s",\n  "database": "%s",\n' \
            "${PROJECT_NAME:-zodoo}" "${DBNAME:-}"
        printf '  "bases": [%s],\n' "$(IFS=,; echo "${base_entries[*]-}")"
        printf '  "wal": [%s],\n' "$(IFS=,; echo "${WAL_ENTRIES[*]-}")"
        printf '  "wal_total": %s,\n' "$(wc -l < "$WAL_LEDGER")"
        printf '  "base_total": %s\n}\n' "$(wc -l < "$BASE_LEDGER")"
    } > "$work/manifest.json"

    db_curl --upload-file "$work/manifest.json" \
        --header "Content-Type: application/json" \
        "$base/manifests/${run_id}-db.json" > /dev/null

    echo "offsite/db: done - $new_bases base backup(s), $NEW_WAL WAL segment(s)"
}
