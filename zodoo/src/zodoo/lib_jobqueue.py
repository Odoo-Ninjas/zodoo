"""
File-based job queue for host-side background work (e.g. registry uploads).

Used to decouple slow operations (large `docker push`) from interactive
commands. Jobs are written to ``${run}/jobqueue/`` as JSON files. A worker
process is kicked off detached at enqueue time for low latency, and the
``odoo run-crontab`` command processes any leftovers as a safety net for
crashed workers or reboots.

State machine per job file:
  <job_id>.json                  pending
  <job_id>.json.processing.<pid> claimed (atomic rename)
  (deleted)                      success
  <job_id>.json.failed.<n>       failed n times

Atomic claim via ``os.rename`` (POSIX guarantee on the same filesystem).
Stale ``.processing.*`` files (mtime older than STALE_AFTER_SEC and the
PID is gone) are reclaimed back to ``.json`` on the next sweep.
"""

import json
import os
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from .cli import cli, pass_config

QUEUE_SUBDIR = "jobqueue"
LOG_SUBDIR = "log"
STALE_AFTER_SEC = 30 * 60


def _queue_dir(config):
    run_dir = config.dirs.get("run")
    if not run_dir:
        return None
    return run_dir / QUEUE_SUBDIR


def _log_dir(config):
    qdir = _queue_dir(config)
    if not qdir:
        return None
    d = qdir / LOG_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def enqueue(config, job_type, payload):
    """Write a job file and return its absolute path.

    Caller is responsible for setting up any side state (e.g. retagging
    docker images) BEFORE calling this — the worker will run later and
    must find the world in the state the job assumes.
    """
    qdir = _queue_dir(config)
    if not qdir:
        raise RuntimeError("No project run-dir configured; cannot enqueue.")
    qdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"{ts}_{job_type}_{secrets.token_hex(4)}"
    body = {
        "id": job_id,
        "type": job_type,
        "payload": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = qdir / f".{job_id}.json.tmp"
    final = qdir / f"{job_id}.json"
    tmp.write_text(json.dumps(body, indent=2))
    os.rename(tmp, final)
    click.secho(f"Queued job {job_id} ({job_type})", fg="cyan")
    return final


def spawn_worker(config):
    """Kick off a detached ``odoo run-crontab`` for this project.

    Best-effort: if Popen fails the cron entry is the safety net.
    """
    if not config.WORKING_DIR:
        return
    log_file = _log_dir(config) / f"worker_{int(time.time())}.log"
    try:
        with open(log_file, "a") as fh:
            subprocess.Popen(
                ["odoo", "run-crontab"],
                cwd=str(config.WORKING_DIR),
                stdout=fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        click.secho(f"Spawned background worker (log: {log_file})", fg="cyan")
    except OSError as e:
        click.secho(
            f"Could not spawn background worker ({e}); "
            "rely on `odoo run-crontab` cron entry instead.",
            fg="yellow",
        )


def _claim(job_path):
    """Atomically rename ``<job>.json`` to ``<job>.json.processing.<pid>``.

    Returns the new path on success, ``None`` if another worker won the race.
    """
    target = job_path.with_suffix(
        job_path.suffix + f".processing.{os.getpid()}"
    )
    try:
        os.rename(job_path, target)
        return target
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _release_failed(processing_path):
    """Rename ``.processing.<pid>`` to ``.failed.<n>`` (or increment n)."""
    name = processing_path.name
    base = name.split(".processing.", 1)[0]
    parent = processing_path.parent
    n = 1
    while (parent / f"{base}.failed.{n}").exists():
        n += 1
    target = parent / f"{base}.failed.{n}"
    os.rename(processing_path, target)
    return target


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def _reclaim_stale(qdir):
    """Rename stale ``.processing.<pid>`` files back to ``.json`` so they
    can be retried. Considered stale when the worker PID is gone OR the
    file is older than STALE_AFTER_SEC.
    """
    now = time.time()
    for p in qdir.glob("*.json.processing.*"):
        try:
            pid_str = p.suffix.lstrip(".")
            pid = int(pid_str)
        except ValueError:
            continue
        try:
            mtime = p.stat().st_mtime
        except FileNotFoundError:
            continue
        if _pid_alive(pid):
            if now - mtime < STALE_AFTER_SEC:
                continue
        # Strip the trailing ".processing.<pid>" to get back to .json
        # p.stem here is e.g. "<id>.json.processing" — use string manipulation.
        original = Path(str(p).rsplit(".processing.", 1)[0])
        try:
            os.rename(p, original)
            click.secho(f"Reclaimed stale job: {original.name}", fg="yellow")
        except OSError:
            pass


def _get_handlers():
    """Lazy import to avoid circular imports at module load time."""
    from .lib_zodoo_registry import (
        process_base_image_upload_job,
        process_registry_upload_job,
    )

    return {
        "registry_upload": process_registry_upload_job,
        "base_image_upload": process_base_image_upload_job,
    }


def _run_one(config, processing_path):
    body = json.loads(processing_path.read_text())
    job_type = body.get("type")
    payload = body.get("payload", {})
    handlers = _get_handlers()
    handler = handlers.get(job_type)
    if not handler:
        click.secho(
            f"No handler for job type {job_type!r}; marking failed.", fg="red"
        )
        _release_failed(processing_path)
        return False
    try:
        handler(config, payload)
    except Exception as e:
        click.secho(f"Job {body.get('id')} failed: {e}", fg="red")
        _release_failed(processing_path)
        return False
    processing_path.unlink()
    click.secho(f"Job {body.get('id')} done", fg="green")
    return True


def process_pending(config):
    qdir = _queue_dir(config)
    if not qdir or not qdir.exists():
        return 0
    _reclaim_stale(qdir)
    processed = 0
    for job in sorted(qdir.glob("*.json")):
        claimed = _claim(job)
        if not claimed:
            continue
        _run_one(config, claimed)
        processed += 1
    return processed


@cli.command(name="run-crontab")
@pass_config
def run_crontab_cmd(config):
    """Process pending background jobs in ``${run}/jobqueue/``.

    Intended to be invoked from the system crontab as a safety net for
    crashed/lost detached workers. Also triggered immediately by commands
    that enqueue work (e.g. ``odoo build``).
    """
    n = process_pending(config)
    click.secho(f"run-crontab: processed {n} job(s)", fg="green")
