#!/bin/bash
#
# Write-only filestore backup.
#
# Unlike the restic path, this machine cannot read what it has uploaded and
# cannot delete it. That is possible here because the filestore has two
# properties restic has to work hard for:
#
#   * Odoo names every attachment after the SHA-1 of its content
#     (filestore/<db>/05/055ffc5c…), so a file is written once and never
#     changes, and "same content" is already "same name" - the deduplication is
#     in the naming. No chunking, no repository index, no key needed to decide
#     what is new.
#   * Therefore "what is missing at the far end?" is a pure name comparison,
#     and we can answer it from a LOCAL ledger instead of by reading the
#     target.
#
# Consequences, both deliberate:
#
#   * Each run encrypts to a PUBLIC key (OFFSITE_WO_RECIPIENT). This machine
#     has no private key, so it cannot read even its own uploads. Restoring
#     needs the private key from 1Password.
#   * If the local ledger is lost (volume wiped, machine rebuilt), the next run
#     uploads everything again. That is the price of never asking the target
#     what it has. It is recoverable and it costs traffic, not data.
#
# New files go up as one bundle per run rather than one object per file: an
# instance with a million attachments would otherwise mean a million HTTP
# requests. The manifest deliberately lists only bundles and their checksums,
# never file names - a file name is the hash of its content, so a name list at
# the target would let someone confirm whether a known document is in the
# backup.
#
set -euo pipefail

STATE_DIR=${OFFSITE_STATE_DIR:-/var/lib/offsite-state}
LEDGER="$STATE_DIR/filestore.ledger"

wo_die() {
    echo "offsite/filestore: $*" >&2
    exit 1
}

wo_require() {
    [ -n "${OFFSITE_WO_URL:-}" ] || wo_die \
        "OFFSITE_WO_URL is empty - no write-only target configured."
    [ -n "${OFFSITE_WO_RECIPIENT:-}" ] || wo_die \
        "OFFSITE_WO_RECIPIENT is empty. Without a public key this would upload
plaintext. Generate a keypair with 'age-keygen', keep the private key in
1Password and put the public key (age1…) here."
    [ -n "${OFFSITE_REST_USER:-}" ] || wo_die \
        "OFFSITE_REST_USER is empty - see 'odoo offsite register'."
    [ -n "${OFFSITE_REST_PASSWORD:-}" ] || wo_die \
        "OFFSITE_REST_PASSWORD is empty - see 'odoo offsite register'."
    [ -d "$STATE_DIR" ] || wo_die \
        "State directory $STATE_DIR is missing. It holds the ledger of what has
already been uploaded and must be writable and persistent."
}

# The filestore of THIS database, not the host-wide pool: on a machine with
# several instances the pool holds other customers' attachments.
wo_filestore_root() {
    local root="/source/filestore/filestore/${DBNAME:-}"
    [ -n "${DBNAME:-}" ] || wo_die "DBNAME is not set."
    [ -d "$root" ] || wo_die \
        "No filestore at $root. Check how ODOO_FILES is mounted and whether
DBNAME is correct - an empty or missing filestore is what an unmounted volume
looks like."
    echo "$root"
}

do_filestore() {
    wo_require
    local root
    root=$(wo_filestore_root)

    WO_CACERT=()
    [ -f "$CA_CERT" ] && WO_CACERT=(--cacert "$CA_CERT")

    local base="${OFFSITE_WO_URL%/}"
    local run_id
    run_id=$(date -u +%Y%m%dT%H%M%SZ)
    local work
    work=$(wo_workdir)
    # shellcheck disable=SC2064  # expand $work now, not at trap time
    trap "rm -rf '$work'" EXIT

    touch "$LEDGER"

    # Paths relative to the filestore root, so the bundle can be unpacked
    # straight into a restored filestore.
    find "$root" -type f -printf '%P\n' | LC_ALL=C sort > "$work/current"
    LC_ALL=C sort -u "$LEDGER" > "$work/known"
    LC_ALL=C comm -23 "$work/current" "$work/known" > "$work/new"

    local total added
    total=$(wc -l < "$work/current")
    added=$(wc -l < "$work/new")

    if [ "$added" -eq 0 ]; then
        echo "offsite/filestore: nothing new ($total files already uploaded)."
        return 0
    fi

    echo "offsite/filestore: $added new of $total files - streaming"
    # Streamed, not spooled: the first run of an instance with a large
    # filestore would otherwise need its own compressed size in scratch space.
    # The name can no longer contain the checksum (it is only known once the
    # stream is through), so the run id identifies the bundle - and the
    # manifest carries the checksum.
    #
    # -T reads the file list; --no-recursion because the list is already
    # complete and we do not want a re-listed directory to drag in files that
    # are not in it.
    local name sum size res
    name="filestore-${run_id}.tar.gz.age"
    res=$(wo_put_stream "$name" "$base" "$work" -- \
        bash -c "tar -C '$root' -cf - --no-recursion -T '$work/new' | gzip -n | age -r '$OFFSITE_WO_RECIPIENT'")
    if [ -z "$res" ]; then
        # Already there - a repeat within the same second after a reset. The
        # files are on the receiver, so record them and leave the declaring to
        # the run that actually uploaded them.
        cat "$work/new" >> "$LEDGER"
        echo "offsite/filestore: $name was already present, ledger updated."
        return 0
    fi
    sum=$(echo "$res" | cut -d' ' -f2)
    size=$(echo "$res" | cut -d' ' -f3)
    echo "offsite/filestore: uploaded $name ($size bytes)"

    # Only now is the ledger extended: a crash between upload and this line
    # costs a repeated upload of those files in the next bundle, never a file
    # that is believed to be safe but never arrived.
    cat "$work/new" >> "$LEDGER"

    # The manifest names bundles, not files. It is the far end's only way to
    # notice a missing bundle, and it must not leak content hashes.
    local ledger_sum
    ledger_sum=$(LC_ALL=C sort -u "$LEDGER" | sha256sum | cut -d' ' -f1)
    cat > "$work/manifest.json" <<EOF
{
  "run": "$run_id",
  "kind": "filestore",
  "host": "${PROJECT_NAME:-zodoo}",
  "database": "${DBNAME:-}",
  "bundle": "$name",
  "sha256": "$sum",
  "size": $size,
  "files_added": $added,
  "files_total": $total,
  "ledger_sha256": "$ledger_sum"
}
EOF
    wo_curl --upload-file "$work/manifest.json" \
        --header "Content-Type: application/json" \
        "$base/manifests/$run_id.json" > /dev/null

    echo "offsite/filestore: done - $added files in $name, $total files total"
}
