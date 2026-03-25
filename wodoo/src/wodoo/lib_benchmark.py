import json
import re
import sys
import time
from urllib.parse import urlparse

import click
import requests
from tabulate import tabulate

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import odoorpc


class _SessionModel:
    """Minimal model proxy that uses an existing session cookie for RPC."""

    def __init__(self, base_url, session_id, model, timeout=300):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._session = requests.Session()
        self._session.cookies.set("session_id", session_id)
        self._rpc_id = 0

    def _rpc(self, method, args=None, kwargs=None):
        self._rpc_id += 1
        payload = {
            "id": self._rpc_id,
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": self._model,
                "method": method,
                "args": args or [],
                "kwargs": kwargs or {},
            },
        }
        url = f"{self._base_url}/web/dataset/call_kw/{self._model}/{method}"
        resp = self._session.post(url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            msg = (
                result["error"]
                .get("data", {})
                .get("message", str(result["error"]))
            )
            raise click.ClickException(f"Odoo RPC error: {msg}")
        return result.get("result")

    def fields_get(self):
        return self._rpc("fields_get", kwargs={"attributes": ["type"]})

    def search_count(self, domain):
        return self._rpc("search_count", args=[domain])

    def search_read(self, domain, fields=None, limit=None):
        kwargs = {}
        if fields is not None:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        return self._rpc("search_read", args=[domain], kwargs=kwargs)


class _SessionEnv:
    """Mimics odoorpc's odoo.env[model] interface using session cookies."""

    def __init__(self, base_url, session_id, timeout=300):
        self._base_url = base_url
        self._session_id = session_id
        self._timeout = timeout

    def __getitem__(self, model):
        return _SessionModel(
            self._base_url, self._session_id, model, self._timeout
        )


class _SessionOdoo:
    """Minimal odoorpc-compatible wrapper using an existing session cookie."""

    def __init__(self, base_url, session_id, timeout=300):
        self.env = _SessionEnv(base_url, session_id, timeout)


def _connect_odoo(config, host, user, password, db):
    db = db or config.DBNAME
    click.secho("Connecting to Odoo via RPC (timeout=300s)...", fg="blue")
    if host:
        import odoorpc as odoorpc_module

        protocol = (
            "jsonrpc+ssl" if not host.startswith("http://") else "jsonrpc"
        )
        host = host.replace("https://", "").replace("http://", "").rstrip("/")
        port = 443 if protocol == "jsonrpc+ssl" else 80
        odoo = odoorpc_module.ODOO(
            host, protocol=protocol, port=port, timeout=300
        )
        odoo.login(db, user or "admin", password or "admin")
    elif user and password:
        import odoorpc as odoorpc_module

        odoo = odoorpc_module.ODOO(
            "localhost", port=int(config.PROXY_PORT), timeout=300
        )
        odoo.login(db, user, password)
    else:
        odoo = odoorpc(config)
        odoo.config["timeout"] = 300
    click.secho(
        f"Connected as '{user or 'admin'}'. Database: {db}", fg="green"
    )
    return odoo


def _connect_session(base_url, session_id):
    click.secho(f"Using session cookie for {base_url}...", fg="blue")
    odoo = _SessionOdoo(base_url, session_id)
    return odoo


def _run_benchmark(odoo, model, field_names, target_seconds):
    click.secho(f"Fetching field definitions for '{model}'...", fg="blue")
    Model = odoo.env[model]
    fields_info = Model.fields_get()

    if field_names:
        missing = set(field_names) - set(fields_info.keys())
        if missing:
            click.secho(
                f"  Warning: fields not found on model: {', '.join(sorted(missing))}",
                fg="yellow",
            )
            field_names = [f for f in field_names if f in fields_info]
        all_fields = sorted(field_names)
    else:
        all_fields = sorted(fields_info.keys())

    click.secho(f"  {len(all_fields)} fields to benchmark", fg="green")

    total_records = Model.search_count([])
    click.secho(f"  {total_records} records in database\n", fg="green")

    def _search_read(fields, limit):
        t0 = time.time()
        Model.search_read([], fields=fields, limit=limit)
        return time.time() - t0

    limit = min(80, total_records) if total_records else 80
    click.secho(
        f"Phase 1: Calibrating record limit (target < {target_seconds}s)...",
        fg="blue",
        bold=True,
    )
    click.secho(
        f"  Requesting all {len(all_fields)} fields at once to gauge total cost.",
        fg="blue",
    )
    while limit >= 1:
        elapsed = _search_read(["id"] + all_fields, limit)
        status = "OK" if elapsed < target_seconds else "too slow"
        color = "green" if elapsed < target_seconds else "yellow"
        click.secho(
            f"  limit={limit:>5d}  -> {elapsed:.2f}s  [{status}]", fg=color
        )
        if elapsed < target_seconds:
            break
        old_limit = limit
        limit = max(1, limit // 2)
        click.secho(
            f"  Reducing limit from {old_limit} to {limit}...", fg="yellow"
        )
    else:
        click.secho(
            f"  Even limit=1 takes {elapsed:.2f}s - continuing anyway.",
            fg="yellow",
        )

    click.secho(
        f"\nPhase 2: Measuring baseline (only 'id' field, limit={limit})...",
        fg="blue",
        bold=True,
    )
    base_time = _search_read(["id"], limit)
    click.secho(f"  Baseline: {base_time:.3f}s\n", fg="green")

    click.secho(
        f"Phase 3: Benchmarking each field individually (limit={limit})...",
        fg="blue",
        bold=True,
    )
    click.secho(
        f"  Each request fetches ['id', <field>]. "
        f"Overhead = time - baseline ({base_time:.3f}s).\n",
        fg="blue",
    )
    results = []
    total = len(all_fields)
    width = len(str(total))
    for i, field in enumerate(all_fields, 1):
        ftype = fields_info[field].get("type", "?")
        elapsed = _search_read(["id", field], limit)
        overhead = elapsed - base_time
        results.append((field, ftype, elapsed, overhead))
        color = (
            "green" if overhead < 0.5 else "yellow" if overhead < 2 else "red"
        )
        click.secho(
            f"  [{i:>{width}}/{total}] "
            f"{field:<40s} ({ftype:<12s}) "
            f"{elapsed:.3f}s  (overhead {overhead:+.3f}s)",
            fg=color,
        )

    results.sort(key=lambda r: r[3], reverse=True)

    click.secho(f"\n{'=' * 70}", fg="blue")
    click.secho(
        f"Results for {model}  "
        f"(limit={limit}, records={total_records}, baseline={base_time:.3f}s)",
        fg="blue",
        bold=True,
    )
    click.secho(f"{'=' * 70}\n", fg="blue")

    table = [(f, ftype, f"{t:.3f}", f"{o:+.3f}") for f, ftype, t, o in results]
    click.secho(
        tabulate(
            table,
            headers=["Field", "Type", "Time (s)", "Overhead (s)"],
            tablefmt="fancy_grid",
        ),
        fg="yellow",
    )


def _parse_curl(curl_text):
    """Extract model, fields, URL, and session_id from a curl command."""
    # Extract URL
    url_match = re.search(r"curl\s+'([^']+)'", curl_text)
    if not url_match:
        url_match = re.search(r'curl\s+"([^"]+)"', curl_text)
    base_url = None
    session_id = None
    if url_match:
        parsed = urlparse(url_match.group(1))
        base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Extract session_id from -b / --cookie header
    cookie_match = re.search(
        r"""(?:-b|--cookie)\s+['"]([^'"]+)['"]""", curl_text
    )
    if cookie_match:
        cookie_str = cookie_match.group(1)
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith("session_id="):
                session_id = part.split("=", 1)[1]
                break

    # Find the JSON body: --data-raw '...' or --data-raw $'...' or -d '...'
    match = re.search(
        r"""(?:--data-raw|--data|-d)\s+\$?'(.*?)'(?:\s|$)""",
        curl_text,
        re.DOTALL,
    )
    if not match:
        match = re.search(
            r"""(?:--data-raw|--data|-d)\s+"(.*?)"(?:\s|$)""",
            curl_text,
            re.DOTALL,
        )
    if not match:
        raise click.ClickException(
            "Could not find JSON body (--data-raw / --data / -d) in the curl command."
        )

    body = json.loads(match.group(1))
    params = body.get("params", body)

    model = params.get("model")
    if not model:
        url_match2 = re.search(r"call_kw/([^/\s'\"]+)", curl_text)
        if url_match2:
            model = url_match2.group(1)
    if not model:
        raise click.ClickException(
            "Could not determine the model from the curl command."
        )

    kwargs = params.get("kwargs", {})
    specification = kwargs.get("specification")
    fields_list = kwargs.get("fields")
    if specification:
        field_names = sorted(specification.keys())
    elif fields_list and isinstance(fields_list, list):
        field_names = sorted(fields_list)
    else:
        raise click.ClickException(
            "Could not find 'specification' or 'fields' in the request kwargs."
        )

    return model, field_names, base_url, session_id


@cli.group(cls=AliasedGroup)
@pass_config
def benchmark(config):
    pass


@benchmark.command(name="fields")
@click.argument("model", required=True)
@click.option(
    "-t",
    "--target-seconds",
    default=20.0,
    type=float,
    help="Max seconds for the all-fields baseline; limit is reduced to stay below this.",
)
@click.option("-u", "--user", default=None, help="Odoo login username")
@click.option("-p", "--password", default=None, help="Odoo login password")
@click.option(
    "-H",
    "--host",
    default=None,
    help="Odoo host (e.g. stage18-odin.dinmedia.de)",
)
@click.option(
    "-d", "--db", default=None, help="Database name (default: from config)"
)
@pass_config
def benchmark_fields(config, model, target_seconds, user, password, host, db):
    """Benchmark each field of a model to find slow computed fields.

    Automatically adjusts the record limit so the total request stays
    under --target-seconds, then measures every field individually.
    """
    odoo = _connect_odoo(config, host, user, password, db)
    _run_benchmark(
        odoo, model, field_names=None, target_seconds=target_seconds
    )


@benchmark.command(name="curl")
@click.option(
    "-t",
    "--target-seconds",
    default=20.0,
    type=float,
    help="Max seconds for the all-fields baseline; limit is reduced to stay below this.",
)
@click.option("-u", "--user", default=None, help="Odoo login username")
@click.option("-p", "--password", default=None, help="Odoo login password")
@click.option(
    "-H",
    "--host",
    default=None,
    help="Odoo host (override URL from curl)",
)
@click.option(
    "-d", "--db", default=None, help="Database name (default: from config)"
)
@pass_config
def benchmark_curl(config, target_seconds, user, password, host, db):
    """Benchmark fields from a Chrome DevTools curl command.

    Copy a web_search_read request as cURL from Chrome DevTools, then run:

        odoo benchmark curl          # reads from clipboard (uses session from curl)
        pbpaste | odoo benchmark curl  # reads from stdin pipe

    Host and session cookie are auto-detected from the curl command.
    Use -u/-p to override with username/password auth instead.
    """
    if sys.stdin.isatty():
        import subprocess

        try:
            curl_text = subprocess.check_output(["pbpaste"], text=True).strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise click.ClickException(
                "Could not read from clipboard. "
                "Use: pbpaste | odoo benchmark curl"
            )
        if not curl_text:
            raise click.ClickException("Clipboard is empty.")
        click.secho("Read curl command from clipboard.", fg="blue")
    else:
        curl_text = sys.stdin.read().strip()
    if not curl_text:
        raise click.ClickException("No input received.")

    model, field_names, curl_url, curl_session = _parse_curl(curl_text)
    click.secho(f"Model: {model}", fg="green", bold=True)
    click.secho(
        f"Fields ({len(field_names)}): {', '.join(field_names)}\n", fg="green"
    )

    if user and password:
        odoo = _connect_odoo(config, host, user, password, db)
    elif curl_session and curl_url:
        base_url = host or curl_url
        if base_url and not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        odoo = _connect_session(base_url, curl_session)
    else:
        odoo = _connect_odoo(config, host, user, password, db)

    _run_benchmark(
        odoo, model, field_names=field_names, target_seconds=target_seconds
    )
