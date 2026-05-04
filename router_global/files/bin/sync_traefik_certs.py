#!/usr/bin/env python3
"""Extract certificates from a Traefik acme.json into custom_ssl/.

Usage:
    sync_traefik_certs.py <acme.json> <custom_ssl_dir>

Reads every cert/key pair from the acme.json ACME storage file and writes:
    <custom_ssl_dir>/<domain>.crt
    <custom_ssl_dir>/<domain>.key

Existing files are only overwritten when the certificate actually changed.
Returns exit code 0 (no reload needed) or 10 (at least one cert updated).
"""
import base64
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <acme.json> <custom_ssl_dir>", file=sys.stderr)
        sys.exit(1)

    acme_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])

    if not acme_path.exists():
        print(f"acme.json not found: {acme_path}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(acme_path.read_bytes())

    updated = 0
    for resolver, content in data.items():
        for entry in content.get("Certificates", []):
            domain = entry["domain"]["main"]
            cert_pem = base64.b64decode(entry["certificate"])
            key_pem = base64.b64decode(entry["key"])

            cert_file = out_dir / f"{domain}.crt"
            key_file = out_dir / f"{domain}.key"

            if not cert_file.exists() or cert_file.read_bytes() != cert_pem:
                cert_file.write_bytes(cert_pem)
                key_file.write_bytes(key_pem)
                key_file.chmod(0o600)
                print(f"Updated cert for {domain}")
                updated += 1
            else:
                print(f"Cert for {domain} unchanged")

    sys.exit(10 if updated else 0)


if __name__ == "__main__":
    main()
