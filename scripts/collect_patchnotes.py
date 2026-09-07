#!/usr/bin/env python3
"""Patchnote-Fragmente einsammeln: Changelog-Text und Versionssprung.

Warum ein Skript und kein grep: die Release-Automatik las die Beschreibung mit

    grep '^description:' | sed 's/description: *//'

Bei der YAML-Blockschreibweise `description: |` liefert das genau ein
Pipe-Zeichen - der eigentliche Text steht ja in den eingerueckten Zeilen
darunter. Jede MEHRZEILIGE Patchnote landete damit als "- **Fix**: |" im
Changelog, und das ist niemandem aufgefallen, weil ein Changelog niemand
gegenliest. Am 06.09.2026 waren 36 der 308 Eintraege auf diese Weise leer.

Also: richtig parsen. Ausgabe ist JSON auf stdout:

    {"entries": ["- **Fix**: ...", ...], "bump": "major|minor|patch"}
"""
import argparse
import json
import pathlib
import re
import sys

import yaml

# Der Typ bestimmt die Ueberschrift im Changelog und ob die Version springt.
BESCHRIFTUNG = {
    "feature": "Feature",
    "fix": "Fix",
    "docs": "Docs",
    "internal": "Internal",
    "breaking": "BREAKING",
}


def lies(pfad):
    try:
        daten = yaml.safe_load(pfad.read_text()) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"{pfad}: kein gueltiges YAML - {exc}")
    if not isinstance(daten, dict):
        raise SystemExit(f"{pfad}: erwartet wurde ein YAML-Objekt")
    return daten


# Zeilen, die eine Aufzaehlung beginnen: "- ", "* " oder "1. ".
AUFZAEHLUNG = re.compile(r"^\s*([-*]|\d+\.)\s+")


def text(wert):
    """Mehrzeiliges umbrechen - aber Aufzaehlungen bleiben Aufzaehlungen.

    Der Changelog ist eine Liste; ein Fragment darf trotzdem ausfuehrlich sein.
    Leerzeilen trennen Absaetze, und innerhalb eines Absatzes werden Zeilen
    zusammengezogen, sonst zerfaellt der Eintrag in der Darstellung.

    NICHT zusammengezogen werden Aufzaehlungen. Beim ersten Anlauf am
    06.09.2026 fiel genau das auf die Nase: die fuenf Spiegelstriche einer
    Patchnote landeten als ein einziger Absatz im CHANGELOG, hintereinander
    weg. Eine Zeile, die eine Aufzaehlung beginnt, faengt deshalb eine neue
    Ausgabezeile an; eingerueckte Fortsetzungen haengen sich an ihren
    Spiegelstrich.
    """
    if wert is None:
        return ""
    absaetze = []
    for roh in str(wert).strip().split("\n\n"):
        zeilen = []
        for z in roh.strip().split("\n"):
            if not z.strip():
                continue
            if AUFZAEHLUNG.match(z) or not zeilen:
                zeilen.append(z.strip())
            else:
                zeilen[-1] += " " + z.strip()
        if zeilen:
            absaetze.append("\n  ".join(zeilen))
    return "\n\n  ".join(absaetze)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("verzeichnis", nargs="?", default=".patchnotes")
    args = p.parse_args()

    wurzel = pathlib.Path(args.verzeichnis)
    # Rekursiv: Fragmente liegen auch in Unterordnern (.patchnotes/fix/*.yml).
    dateien = sorted(f for f in wurzel.rglob("*.yml") if not f.name.endswith(".template"))

    eintraege = []
    hat_breaking = False
    hat_feature = False

    for f in dateien:
        d = lies(f)
        beschreibung = text(d.get("description"))
        if not beschreibung:
            raise SystemExit(f"{f}: 'description' fehlt oder ist leer")

        typ = str(d.get("type", "")).strip().lower()
        breaking = d.get("breaking") is True or typ == "breaking"

        if breaking:
            hat_breaking = True
            zeile = f"- **BREAKING**: {beschreibung}"
            zusatz = text(d.get("breaking_description"))
            if zusatz:
                zeile += f"\n\n  {zusatz}"
        else:
            if typ == "feature":
                hat_feature = True
            kopf = BESCHRIFTUNG.get(typ)
            zeile = f"- **{kopf}**: {beschreibung}" if kopf else f"- {beschreibung}"
        eintraege.append(zeile)

    bump = "major" if hat_breaking else ("minor" if hat_feature else "patch")
    json.dump({"entries": eintraege, "bump": bump}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
