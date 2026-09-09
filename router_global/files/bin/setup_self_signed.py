#!/usr/bin/env python3
"""Generate (or keep) a self-signed certificate for an ssl_self_signed vhost.

Usage: setup_self_signed.py <server_name> <certificate_name>

Runs on the host (openssl is available there; the container image does not
depend on it). The router vhost template points nginx at
    custom_ssl/<certificate_name>/server.crt
    custom_ssl/<certificate_name>/server.key
(this maps to /etc/ssl/custom_ssl/... inside the container).

The certificate is only generated when it is missing, so a certificate that
was provided by hand is never overwritten - "provided always wins". Idempotent:
re-running for an existing pair does nothing and exits 0.
"""

import os
import subprocess
import sys
from pathlib import Path

server_name = sys.argv[1]
certificate_name = sys.argv[2]

# Same relative convention as setup_basic_auth.py: the caller runs this with
# the install dir as the working directory, so custom_ssl/ is the host dir that
# maps to /etc/ssl/custom_ssl inside the router container.
cert_dir = Path("custom_ssl") / certificate_name
cert_file = cert_dir / "server.crt"
key_file = cert_dir / "server.key"

if cert_file.exists() and key_file.exists():
    print(f"self-signed cert for {server_name} already present, keeping it.")
    sys.exit(0)

cert_dir.mkdir(parents=True, exist_ok=True)

# umask VOR openssl: der Schluessel entsteht sonst mit der Maske der Umgebung
# (ueblich 0644) und wird erst danach per chmod eingeschraenkt - ein kleines
# Fenster, in dem er fuer alle lesbar ist. Das chmod unten bleibt trotzdem,
# als ausdrueckliche Zusicherung statt als Verlass auf die Maske.
os.umask(0o077)

try:
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "3650",
            "-subj",
            f"/CN={server_name}",
            # SAN ist Pflicht: ohne subjectAltName lehnen die Browser das
            # Zertifikat ab, egal was im CN steht.
            "-addext",
            f"subjectAltName=DNS:{server_name}",
            "-keyout",
            str(key_file),
            "-out",
            str(cert_file),
        ],
        check=True,
        # stderr mitnehmen: openssl schreibt seine Fehler dorthin. Vorher lief
        # der Aufruf ueber check_output ohne stderr - ging etwas schief, stand
        # nur ein nackter Rueckgabewert da und man wusste nichts.
        capture_output=True,
        text=True,
    )
except FileNotFoundError:
    sys.exit(
        "openssl was not found. It is needed to generate the self-signed "
        "certificate for this vhost - install it on the host (Debian/Ubuntu: "
        "apt install openssl)."
    )
except subprocess.CalledProcessError as ex:
    ausgabe = ((ex.stdout or "") + (ex.stderr or "")).strip()
    # Halbe Paare wieder wegraeumen: nginx laedt eine angefangene Datei nicht,
    # und ein liegengebliebener Rest laesst den naechsten Lauf glauben, es sei
    # schon alles da.
    for rest in (cert_file, key_file):
        if rest.exists():
            rest.unlink()
    hinweis = ""
    if "unknown option" in ausgabe.lower() or "-addext" in ausgabe:
        hinweis = (
            "\nLooks like this openssl is too old: -addext (and therefore "
            "subjectAltName) needs OpenSSL 1.1.1 or newer."
        )
    sys.exit(
        f"openssl failed to generate the certificate for {server_name}:\n"
        f"{ausgabe}{hinweis}"
    )

key_file.chmod(0o600)
print(f"generated self-signed cert for {server_name} in {cert_dir}.")
