"""Leere Changelog-Eintraege aus den Patchnote-Fragmenten der Historie holen.

Einmalwerkzeug, aber aufgehoben: es dokumentiert, WIE die 36 Eintraege vom
06.09.2026 wiederhergestellt wurden, und taugt als Vorlage, falls die
Verarbeitung noch einmal etwas verschluckt.

Jeder Release-Commit LOESCHT die Fragmente, die er verarbeitet hat. Sie stehen
also im Eltern-Commit noch da - genau dort holt das Skript sie und laesst sie
durch scripts/collect_patchnotes.py laufen.

    python3 scripts/rebuild_changelog_from_history.py              # Vorschau
    python3 scripts/rebuild_changelog_from_history.py --schreiben  # wirklich

Sicherheitsnetz: ein Abschnitt wird nur ersetzt, wenn JEDER vorhandene
nicht-leere Eintrag im neu erzeugten Text wiederzufinden ist. Sonst waere
handgeschriebener Text still verloren - und genau darum geht es hier ja.
"""

import json, re, subprocess, sys, tempfile, os, shutil
from pathlib import Path

SCHREIBEN = "--schreiben" in sys.argv

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True).stdout

def erzeuge(fragmente_inhalt):
    d = tempfile.mkdtemp()
    try:
        for name, inhalt in fragmente_inhalt:
            (Path(d) / Path(name).name).write_text(inhalt)
        r = subprocess.run([sys.executable, "scripts/collect_patchnotes.py", d],
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONSAFEPATH": "1"})
        if r.returncode:
            return None, r.stderr.strip()
        return json.loads(r.stdout)["entries"], None
    finally:
        shutil.rmtree(d)

release = {}
for z in git("log", "--all", "--pretty=%H %s").splitlines():
    sha, _, b = z.partition(" ")
    m = re.match(r"release v(\d+\.\d+\.\d+)$", b.strip())
    if m and m.group(1) not in release:
        release[m.group(1)] = sha

pfad = Path("CHANGELOG.md")
s = pfad.read_text()
# Auch die Form "- **BREAKING**: | — |" ist leer: dort war zusaetzlich die
# breaking_description ein Block-Skalar und wurde ebenso verschluckt.
LEER = re.compile(r"^- (\*\*[A-Za-z]+\*\*: )?\|( — \|)?$", re.M)

# Abschnitte finden: "## <ver>\n" bis zum naechsten "## "
teile = re.split(r"(?m)^(## .+)$", s)
kopf, rest = teile[0], teile[1:]
neu_teile = [kopf]
ersetzt, uebersprungen = [], []

for i in range(0, len(rest), 2):
    titel, koerper = rest[i], rest[i + 1]
    ver = titel[3:].strip()
    if not LEER.search(koerper):
        neu_teile += [titel, koerper]; continue

    sha = release.get(ver)
    frag = [z.split("\t")[-1] for z in git("show", "--name-status", "--format=", sha).splitlines()
            if z.startswith("D\t") and ".patchnotes/" in z and z.endswith(".yml")] if sha else []
    inhalte = [(f, git("show", f"{sha}^:{f}")) for f in frag]
    inhalte = [(n, c) for n, c in inhalte if c.strip()]
    if not inhalte:
        uebersprungen.append((ver, "keine Fragmente lesbar")); neu_teile += [titel, koerper]; continue

    eintraege, fehler = erzeuge(inhalte)
    if fehler:
        uebersprungen.append((ver, fehler[:60])); neu_teile += [titel, koerper]; continue

    # Sicherheitsnetz: nichts Vorhandenes verlieren
    vorhanden = [z for z in koerper.split("\n") if z.startswith("- ") and not LEER.match(z)]
    verloren = [v for v in vorhanden if v.strip() not in "\n".join(eintraege)]
    if verloren:
        uebersprungen.append((ver, f"{len(verloren)} vorhandene Eintraege waeren weg")); neu_teile += [titel, koerper]; continue

    neu_koerper = "\n\n" + "\n".join(eintraege) + "\n\n\n"
    neu_teile += [titel, neu_koerper]
    ersetzt.append((ver, len(eintraege)))

print("ersetzt:")
for v, n in ersetzt: print("   %-10s %d Eintraege" % (v, n))
print("uebersprungen:")
for v, g in uebersprungen: print("   %-10s %s" % (v, g))
print()
if SCHREIBEN:
    pfad.write_text("".join(neu_teile))
    print("CHANGELOG.md geschrieben")
else:
    Path("/tmp/CHANGELOG.neu").write_text("".join(neu_teile))
    print("Vorschau in /tmp/CHANGELOG.neu - nichts geaendert")
