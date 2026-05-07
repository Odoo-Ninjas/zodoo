#!/usr/bin/env python3
"""Sample pg_stat_activity into a CSV; show stats from that CSV.

Designed to be invoked from the cronjobs container via a CRONJOB_*
env var. Reads DB connection details from the standard wodoo env
vars (DB_HOST, DB_PORT, DB_USER, DB_PWD).

Usage:
    diag_maxconn_sampler.py            # write one sample row (cron default)
    diag_maxconn_sampler.py sample     # same
    diag_maxconn_sampler.py show       # print latest + peaks from CSV
"""
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import psycopg2

def _default_out_path():
    project = os.environ.get("PROJECT_NAME", "")
    if not project:
        raise RuntimeError("PROJECT_NAME not set in environment")
    return Path.home() / ".odoo" / "run" / project / "diag" / "max_conn.csv"


OUT_PATH = Path(os.environ["DIAG_MAXCONN_SAMPLE_FILE"]) \
    if os.environ.get("DIAG_MAXCONN_SAMPLE_FILE") else _default_out_path()

QUERY = """
select
  current_setting('max_connections')::int as max_conn,
  current_setting('superuser_reserved_connections')::int as reserved,
  count(*) as total,
  count(*) filter (where state = 'active') as active,
  count(*) filter (where state = 'idle') as idle,
  count(*) filter (where state = 'idle in transaction') as idle_xact,
  count(*) filter (where state = 'idle in transaction (aborted)') as idle_xact_abort,
  count(*) filter (where datname = %s) as cicdadmin,
  count(*) filter (where datname = 'postgres') as pg_meta,
  count(*) filter (where wait_event_type is not null) as waiting
from pg_stat_activity;
"""

FIELDS = [
    "ts", "max_conn", "reserved", "total", "active", "idle",
    "idle_xact", "idle_xact_abort", "cicdadmin", "pg_meta", "waiting",
]


def _take_sample():
    cicdadmin = os.environ.get("DBNAME", "cicdadmin")
    conn_kwargs = dict(
        host=os.environ.get("DB_HOST", "postgres"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "odoo"),
        password=os.environ.get("DB_PWD", "odoo"),
        dbname="postgres",
        connect_timeout=5,
    )
    try:
        with psycopg2.connect(**conn_kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute(QUERY, (cicdadmin,))
                return cur.fetchone()
    except Exception as e:
        # Saturation itself produces "too many clients already" — record a
        # null row so the gap is visible in the CSV instead of skipped.
        sys.stderr.write(
            f"[diag_maxconn_sampler] connect failed: "
            f"{str(e).splitlines()[0][:200]}\n"
        )
        return (None,) * (len(FIELDS) - 1)


def _read_csv():
    if not OUT_PATH.exists():
        return []
    with OUT_PATH.open("r", newline="") as f:
        return list(csv.DictReader(f))


def _to_int(v):
    try:
        return int(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        ctx.invoke(sample)


@cli.command()
def sample():
    """Take one sample and append to the CSV."""
    row = _take_sample()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUT_PATH.exists()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with OUT_PATH.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(FIELDS)
        w.writerow([ts, *row])


@cli.command()
@click.option("-n", "--last", default=10, help="Show last N rows.")
def show(last):
    """Print latest sample, peaks, and the last N rows."""
    rows = _read_csv()
    if not rows:
        click.secho(f"No samples in {OUT_PATH}", fg="yellow")
        click.echo("Run a sample first or wait for the cron to fire.")
        return

    latest = rows[-1]
    counted = ("total", "active", "idle", "idle_xact", "cicdadmin", "waiting")
    peaks = {
        k: max(
            (_to_int(r[k]) for r in rows if _to_int(r[k]) is not None),
            default=0,
        )
        for k in counted
    }
    max_conn = _to_int(latest.get("max_conn"))
    reserved = _to_int(latest.get("reserved"))

    click.secho(f"file:    {OUT_PATH}", fg="cyan")
    click.secho(f"samples: {len(rows)}  ({rows[0]['ts']} → {latest['ts']})")
    click.echo()
    click.secho("postgres limits", fg="cyan")
    click.echo(f"  max_connections             {max_conn}")
    click.echo(f"  superuser_reserved          {reserved}")
    if max_conn and reserved is not None:
        click.echo(f"  available to non-superuser  {max_conn - reserved}")
    click.echo()
    click.secho("latest sample", fg="cyan")
    for k in counted:
        click.echo(f"  {k:<12} {latest[k]}")
    click.echo()
    click.secho("peak observed", fg="cyan")
    for k, v in peaks.items():
        marker = ""
        if max_conn and k == "total" and v >= max_conn - 5:
            marker = "  ← saturated"
        click.echo(f"  {k:<12} {v}{marker}")
    if last > 0:
        click.echo()
        click.secho(f"last {min(last, len(rows))} rows", fg="cyan")
        cols = ["ts", "total", "active", "idle", "idle_xact", "waiting"]
        click.echo("  " + "  ".join(f"{c:<20}" if c == "ts" else f"{c:<8}"
                                    for c in cols))
        for r in rows[-last:]:
            click.echo(
                "  "
                + "  ".join(
                    f"{r[c]:<20}" if c == "ts" else f"{(r[c] or '-'):<8}"
                    for c in cols
                )
            )


if __name__ == "__main__":
    cli()
