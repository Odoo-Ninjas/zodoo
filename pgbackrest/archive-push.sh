#!/bin/bash
#
# archive_command mit einer einzigen Selbstheilung: fehlende Stanza.
#
# Warum ueberhaupt eine Huelle statt `pgbackrest archive-push` direkt:
#
# postgres archiviert ab seiner ersten Sekunde, die Stanza legt aber der
# Sidecar an. Fehlt sie - Sidecar noch nicht da, abgestuerzt, oder postgres
# allein gestartet - scheitert jeder Push mit
#
#     FileMissingError: unable to open missing file
#     '/var/lib/pgbackrest/archive/<stanza>/archive.info' for read
#
# und zwar dauerhaft. postgres bedient weiter, das WAL staut sich, und die
# Sicherung, die alle fuer vorhanden halten, gibt es nicht.
#
# Was sie ebenfalls nicht tut: ein HALB zerstoertes Repository flicken. Fehlt
# nur archive.info, waehrend backup.info dasteht, verweigert pgbackrest die
# Neuanlage ("[055]: backup.info exists but archive.info is missing") - und das
# ist richtig so. Ein archive.info neben bestehende Sicherungen zu setzen wuerde
# einen Bestand als brauchbar ausweisen, der es womoeglich nicht ist. Solche
# Faelle gehoeren vor menschliche Augen, nicht in eine Automatik. Die Huelle
# scheitert dann weiter, laut, mit dem Rueckgabewert von archive-push.
#
# Was diese Huelle NICHT tut: Fehler verschlucken. Ein archive_command, das
# bei Problemen Erfolg meldet, wirft WAL-Segmente weg, und die Luecke faellt
# beim Wiederherstellen auf - dem teuersten denkbaren Zeitpunkt. Deshalb wird
# GENAU eine Ursache behandelt und jede andere unveraendert durchgereicht.
set -uo pipefail

STANZA="${1:?stanza fehlt}"
WAL="${2:?WAL-Pfad fehlt}"

push() { pgbackrest --stanza="$STANZA" archive-push "$WAL" 2>&1; }

out=$(push)
rc=$?
if [ "$rc" -eq 0 ]; then
    printf '%s\n' "$out"
    exit 0
fi

# Nur diese eine Ursache. Die Meldung nennt archive.info bzw. archive.info.copy
# - das ist die Datei, die stanza-create anlegt.
if ! printf '%s' "$out" | grep -q 'archive\.info'; then
    printf '%s\n' "$out" >&2
    exit "$rc"
fi

echo "archive-push: Stanza '$STANZA' fehlt, lege sie an und versuche erneut." >&2
create=$(pgbackrest --stanza="$STANZA" stanza-create 2>&1)
crc=$?
if [ "$crc" -ne 0 ]; then
    # Ein paralleler stanza-create (etwa vom Sidecar) ist kein Fehler - dann
    # existiert sie jetzt, und der zweite Versuch unten klaert es.
    printf '%s\n' "$create" >&2
fi

out=$(push)
rc=$?
if [ "$rc" -eq 0 ]; then
    printf '%s\n' "$out"
    exit 0
fi

printf '%s\n' "$out" >&2
exit "$rc"
