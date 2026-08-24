#!/bin/bash
#
# Shared plumbing for the write-only paths (filestore and database).
#
# Two ways to upload, and the difference matters for large customers:
#
#   wo_put_file    the object is already a file, so size and checksum are known
#                  up front. Used for small things: WAL segments, manifests.
#   wo_put_stream  the object is produced by a pipeline and streamed, so nothing
#                  is written to disk first. Used for base backups and the
#                  initial filestore bundle - the only two that can be huge.
#
# Why streaming needs the server to return the checksum: `age` is deliberately
# not reproducible (it picks a fresh ephemeral X25519 key per encryption), so the
# source cannot know the ciphertext's hash before sending it. Hashing the same
# pipeline twice would produce two different answers. So the source hashes what
# it streams, the receiver hashes what it got, and the two are compared - an
# end-to-end check that costs no disk.
#
# The alternative, spooling to a file first, is what this avoids: a base backup
# of a 600 GB database would need ~170 GB of scratch space before the first byte
# goes out, and it would land on the container's writable layer, i.e. the system
# disk.

# Scratch space, when a file really is needed. Deliberately inside the state
# directory: that is a host mount next to the data, not the container's
# writable layer on the system disk.
wo_workdir() {
    local base="${OFFSITE_STATE_DIR:-/var/lib/offsite-state}/spool"
    mkdir -p "$base"
    mktemp -d "$base/run-XXXXXX"
}

wo_curl() {
    curl --fail-with-body --silent --show-error \
        --user "${OFFSITE_REST_USER}:${OFFSITE_REST_PASSWORD}" \
        ${WO_CACERT[@]+"${WO_CACERT[@]}"} "$@"
}

# Is this object already on the receiver? Asked before uploading, so a lost
# ledger costs one small request per object instead of re-sending everything.
# The answer says only whether the NAME is taken - there is still no way to read
# an object.
wo_exists() {
    local name="$1" base="$2"
    local code
    code=$(curl --silent --output /dev/null --write-out '%{http_code}' \
        --head --user "${OFFSITE_REST_USER}:${OFFSITE_REST_PASSWORD}" \
        ${WO_CACERT[@]+"${WO_CACERT[@]}"} "$base/objects/$name")
    [ "$code" = "200" ]
}

# Read the sha256 out of the receiver's JSON answer, without needing jq.
wo_answer_sum() {
    grep -o '"sha256"[[:space:]]*:[[:space:]]*"[0-9a-f]\{64\}"' "$1" \
        | head -1 | grep -o '[0-9a-f]\{64\}'
}

# Both upload helpers echo "<name> <sha256> <size>" on a fresh upload and
# NOTHING when the object was already there. That distinction matters: age
# encrypts differently every time, so the ciphertext stored earlier has a
# different checksum than what we would compute now. Declaring our value for
# somebody else's bytes would make the completeness check report a mismatch that
# is not one. An object already on the receiver was declared by the run that
# uploaded it, and manifests are read cumulatively - so it stays declared.
#
# wo_put_file <file> <object-name> <base-url>  ->  "<name> <sha256> <size>" | ""
wo_put_file() {
    local file="$1" name="$2" base="$3"
    local sum size
    sum=$(sha256sum "$file" | cut -d' ' -f1)
    size=$(stat -c %s "$file")
    # Already there? Then this is a repeat - after a reset, or after a crash
    # between upload and ledger write. Not an error: the object is immutable, so
    # "already present" is exactly the desired end state.
    if wo_exists "$name" "$base"; then
        return 0
    fi
    # The receiver never overwrites, so a retried run cannot damage what is
    # already there, and it rejects a truncated upload by comparing the
    # checksum - without decrypting anything.
    wo_curl --upload-file "$file" \
        --header "X-Content-Sha256: $sum" \
        "$base/objects/$name" > /dev/null
    echo "$name $sum $size"
}

# wo_put_stream <object-name> <base-url> <workdir> -- <command...>
#
# Streams the command's stdout straight to the receiver. Echoes
# "<name> <sha256> <size>" on success, fails when the two checksums disagree.
wo_put_stream() {
    local name="$1" base="$2" work="$3"
    shift 3
    [ "${1:-}" = "--" ] && shift

    # Ask first. The receiver answers 409 BEFORE reading the body, so without
    # this a repeated base backup would be pushed over the wire in full only to
    # be refused at the end - and the broken pipe would look like a failure.
    if wo_exists "$name" "$base"; then
        echo "offsite: $name is already on the receiver, skipping" >&2
        return 0
    fi

    local sumfile="$work/.sum" respfile="$work/.resp"
    rm -f "$sumfile" "$respfile"

    # tee into a subshell that hashes, while the other copy goes out over the
    # wire. No temporary copy of the object itself anywhere.
    "$@" \
        | tee >(sha256sum | cut -d' ' -f1 > "$sumfile") \
        | wo_curl --header "Transfer-Encoding: chunked" \
            --upload-file - "$base/objects/$name" > "$respfile"

    # The hashing subshell is not part of the pipeline's exit status, so wait
    # for its result to appear rather than reading a half-written file.
    local waited=0
    while [ ! -s "$sumfile" ] && [ "$waited" -lt 60 ]; do
        sleep 0.5
        waited=$((waited + 1))
    done
    [ -s "$sumfile" ] || {
        echo "offsite: could not compute the local checksum of $name" >&2
        return 1
    }

    local mine theirs size
    mine=$(cat "$sumfile")
    theirs=$(wo_answer_sum "$respfile")
    size=$(grep -o '"size"[[:space:]]*:[[:space:]]*[0-9]*' "$respfile" \
        | head -1 | grep -o '[0-9]*$')

    if [ -z "$theirs" ] || [ "$mine" != "$theirs" ]; then
        # The object stays on the server as an orphan - we cannot delete, by
        # design. It is not written into any manifest, so the completeness
        # check ignores it and it can be cleaned up later. What must not happen
        # is declaring it as good.
        echo "offsite: checksum mismatch for $name - sent $mine, the receiver
computed ${theirs:-nothing}. The object is NOT being declared; it stays behind
as an orphan and the run fails." >&2
        return 1
    fi
    echo "$name $mine ${size:-0}"
}

# wo_reset [filestore|db|all]
#
# "Tabula rasa": das lokale Verzeichnis beiseite schieben, damit der naechste
# Lauf alles noch einmal anbietet. Auf dem Empfaenger wird NICHTS geloescht -
# das kann diese Maschine nicht und soll sie nicht.
#
# Billig geworden ist das erst durch die Vorabfrage: was schon da ist, wird per
# HEAD erkannt und nicht erneut hochgeladen, sondern nur ins Verzeichnis
# nachgetragen. Ein Reset kostet also Anfragen, keine Uebertragung - ausser fuer
# das, was wirklich fehlt.
#
# Die alten Verzeichnisse werden umbenannt, nicht geloescht: sie sind der
# einzige Nachweis dessen, was diese Maschine je gemeldet hat.
wo_reset() {
    local what="${1:-all}" ts
    ts=$(date -u +%Y%m%dT%H%M%SZ)
    local dir="${OFFSITE_STATE_DIR:-/var/lib/offsite-state}"
    local moved=0 f

    for f in $(
        case "$what" in
            filestore) echo "filestore.ledger" ;;
            db)        echo "wal.ledger base.ledger" ;;
            all)       echo "filestore.ledger wal.ledger base.ledger" ;;
            *)         echo "" ;;
        esac
    ); do
        if [ -s "$dir/$f" ]; then
            mv "$dir/$f" "$dir/$f.reset-$ts"
            echo "offsite: $f -> $f.reset-$ts ($(wc -l < "$dir/$f.reset-$ts") Eintraege)"
            moved=$((moved + 1))
        fi
    done

    [ "$moved" -gt 0 ] || echo "offsite: nothing to reset."
    echo "offsite: the next run will offer everything again; whatever is
already on the receiver is recognised and not re-sent."
}

# Eine Zeile an das Tagesmanifest anhaengen (JSON Lines).
#
# Ein Manifest je Lauf waere bei einem minuetlichen WAL-Job hunderte Dateien am
# Tag und Bereich - und wo-check liest die Manifeste ALLER Bereiche. Bei 100
# Instanzen sind das ueber ein Jahr Millionen kleiner Dateien. Ein Manifest je
# Tag macht daraus 365 je Bereich.
#
# Angehaengt, nicht ersetzt: frueher geschriebene Zeilen bleiben unantastbar,
# also gilt die Monotonie-Pruefung weiter.
wo_append_manifest() {
    local base="$1" name="$2" line="$3"
    printf '%s' "$line" | wo_curl --request POST \
        --header "Content-Type: application/json" \
        --data-binary @- "$base/manifests/$name" > /dev/null
}

# Ein STABILER Versatz in Sekunden, aus dem Projektnamen. Ohne das feuern 100
# Instanzen mit "* * * * *" alle in derselben Sekunde. Stabil statt zufaellig,
# damit jede Maschine ihre eigene Sekunde behaelt und die Laeufe sich nicht
# gegenseitig ueberholen.
wo_stagger() {
    local max="${1:-45}" key h
    key="${PROJECT_NAME:-zodoo}"
    h=$(printf '%s' "$key" | cksum | cut -d' ' -f1)
    echo $(( h % max ))
}
