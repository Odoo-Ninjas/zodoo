#!/usr/bin/python3
import arrow
import threading
import string
import fcntl
import os
import sys
import time
import logging
from croniter import croniter
from datetime import datetime
import click

FORMAT = "[%(levelname)s] %(name) -12s %(asctime)s %(message)s"
logging.basicConfig(format=FORMAT)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger("")  # root handler


@click.group()
def cli():
    pass


def get_jobs():
    now = datetime.now()
    for key in os.environ.keys():
        if key.startswith("CRONJOB_"):
            job = os.environ[key]
            if not job:
                continue

            # either 5 or 6 columns; it supports seconds
            schedule = job
            while schedule:
                try:
                    croniter(schedule, now)
                except Exception:
                    schedule = schedule[:-1]
                else:
                    break
            if not schedule:
                raise Exception(f"Invalid schedule: {job}")
            job_command = job[len(schedule) :].strip()
            itr = croniter(schedule, now)
            yield {
                "name": key.replace("CRONJOB_", ""),
                "schedule": schedule,
                "cmd": job_command,
                "base": now,
                "next": itr.get_next(datetime),
            }


def replace_params(text):
    # replace params in there
    def _replace_params(text):
        text = string.Template(text).substitute(os.environ)
        text = text.format(
            project_name=os.environ["PROJECT_NAME"],
            customs=os.environ["PROJECT_NAME"],
            date=datetime.now(),
        )
        return text

    while True:
        text = _replace_params(text)
        if _replace_params(text) == text:
            break
    return text


def _lauf(job_cmd, job_name):
    """Befehl ausfuehren UND den Rueckgabewert auswerten.

    Vorher stand hier ein blankes os.system(). Ein gescheiterter Job sah im
    Protokoll damit genauso aus wie ein gelungener - es gab nur die Zeile
    "Execution took 0.04 seconds". Genau so blieb am 04./05.09.2026 zwei
    Naechte lang unbemerkt, dass auf einer Instanz JEDER Job sofort mit
    Rueckgabewert 1 abbrach.

    Ein Cronjob, der scheitert, muss laut sein.
    """
    rc = os.system(job_cmd)
    # os.system liefert den wait()-Status, nicht den Rueckgabewert.
    code = os.waitstatus_to_exitcode(rc) if rc else 0
    if code:
        logger.error(
            f"Job {job_name or job_cmd} ist mit Rueckgabewert {code} "
            f"gescheitert: {job_cmd}"
        )
    return code


def execute(job_cmd, job_name=None):
    logger.info(f"Executing: {job_cmd}")

    job_cmd = replace_params(job_cmd)
    if job_cmd.startswith("odoo "):
        # PYTHONSAFEPATH: das `cd /opt/src` stellt sonst das Projektverzeichnis
        # an den Anfang von sys.path, und eine dort abgelegte Datei beschattet
        # das gleichnamige Standardmodul. Am 04.09.2026 lag in einem Projekt
        # ein Shell-Schnipsel namens `inspect.py` - zodoo starb daraufhin beim
        # Start mit "NameError: name 'env' is not defined", und ZWEI NAECHTE
        # lang lief auf dieser Instanz kein einziger Cronjob mehr: keine
        # Sicherung, kein check, kein Offsite, kein Dump. Das Projekt wird per
        # -p uebergeben, cwd auf sys.path braucht niemand.
        job_cmd = (
            "cd /opt/src;"
            "PYTHONSAFEPATH=1 odoo "
            f"-p {os.environ['PROJECT_NAME']} "
            f"{job_cmd[5:]}"
        )
    if not job_name:
        _lauf(job_cmd, job_name)
        return
    # One instance per job. The daemon scheduler itself cannot overlap a
    # job with itself (one thread per job, execute() blocks the loop), but
    # a manual `run.py run <JOB>` can collide with the daemon thread — and
    # e.g. two concurrent backups would corrupt the dump.
    # Lock failures other than "already locked" degrade to running WITHOUT
    # the lock: a raise here would kill the job's daemon thread for good
    # (_run_job's try wraps the whole loop), and a misleading skip would
    # disable the job permanently (e.g. flock unsupported on the fs).
    lock_file = f"/tmp/zodoo_cronjob_{job_name}.lock"
    try:
        lockf = open(lock_file, "w")
    except OSError as ex:
        logger.warning(
            f"Could not open lock file {lock_file} ({ex}) — "
            f"running {job_name} without overlap protection."
        )
        _lauf(job_cmd, job_name)
        return
    with lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning(
                f"Job {job_name} is already running — skipping this run."
            )
            return
        except OSError as ex:
            logger.warning(
                f"flock not available for {lock_file} ({ex}) — "
                f"running {job_name} without overlap protection."
            )
        _lauf(job_cmd, job_name)


@cli.command(name="run")
@click.argument("job", required=False)
def run_job(job):
    jobs = list(get_jobs())
    found = [x for x in jobs if x["name"] == job] if job else []
    if not found:
        click.secho(f"Job not found: {job}", fg="red")
        click.secho("\n\nThe following jobs exist:")
        for job in jobs:
            click.secho(f"Job: {job['name']}")
        sys.exit(-1)
    cmd = found[0]["cmd"]
    execute(cmd, job_name=found[0]["name"])


def _run_job(job):
    i = 0
    logger.info(f"Starting Loop for job {job['name']}")
    try:
        while True:
            now = datetime.utcnow()

            if not i % 3600:
                logging.info(
                    f"Next run of {job['cmd']} at {job['next']} - now is {now}"
                )

            if job["next"] < now:
                logger.info(f"Starting now the following job: {job['cmd']}")
                started = datetime.utcnow()
                try:
                    execute(job["cmd"], job_name=job["name"])
                finally:
                    end = datetime.now()
                logger.info(
                    f"{job['name']}: Execution took: "
                    f"{(end - started).total_seconds()}seconds"
                )

                itr = croniter(job["schedule"], arrow.get().naive)
                job["next"] = itr.get_next(datetime)

            time.sleep(1)
            i += 1
    except Exception as ex:
        logger.error(ex, stack_info=True)
        time.sleep(1)


@cli.command()
def daemon():
    logging.info("Starting daemon")
    jobs = list(get_jobs())
    for job in jobs:
        logging.info("Job: %s", job["name"])

    for job in jobs:
        logging.info("Scheduling Job: %s", job)
        logging.info(
            "With replaced values in looks like: %s",
            replace_params(job["cmd"]),
        )
    logger.info("--------------------- JOBS ------------------------")
    for job in jobs:
        logger.info(replace_params(job["cmd"]))

        t = threading.Thread(target=_run_job, args=(job,))
        t.daemon = True
        t.start()

    while True:
        time.sleep(10000000)


if __name__ == "__main__":
    cli()
