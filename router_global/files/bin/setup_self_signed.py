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

subprocess.check_output(
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
        "-addext",
        f"subjectAltName=DNS:{server_name}",
        "-keyout",
        str(key_file),
        "-out",
        str(cert_file),
    ],
    universal_newlines=True,
    encoding="utf-8",
)
key_file.chmod(0o600)
print(f"generated self-signed cert for {server_name} in {cert_dir}.")
