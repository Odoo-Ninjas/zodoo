#!/usr/bin/python3
import arrow
import threading
import string
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


def execute(job_cmd):
    logger.info(f"Executing: {job_cmd}")

    job_cmd = replace_params(job_cmd)
    if job_cmd.startswith("odoo "):
        job_cmd = (
            "cd /opt/src;"
            "odoo "
            f"-p {os.environ['PROJECT_NAME']} "
            f"{job_cmd[5:]}"
        )
    os.system(job_cmd)


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
    execute(cmd)


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
                    execute(job["cmd"])
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
