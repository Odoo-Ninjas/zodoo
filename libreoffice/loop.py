#!/usr/bin/python3

import subprocess
import time
import os
import logging

INPUT = os.getenv("INPUT")
OUTPUT = os.getenv("OUTPUT")
FORMAT = "[%(levelname)s] %(name) -12s %(asctime)s %(message)s"
logging.basicConfig(format=FORMAT)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger("")  # root handler

logger.info("Starting libreoffice converter daemon")


def setup_dir(d):
    if not os.path.exists(d):
        os.makedirs(d)
    os.system(f"chown 1000:1000 '{d}'")
    os.system(f"chmod a+rw '{d}'")


setup_dir(INPUT)
setup_dir(OUTPUT)

while True:
    files = os.listdir(INPUT)
    for filename in files:
        filepath = os.path.join(INPUT, filename)

        try:
            subprocess.check_call(
                [
                    "/usr/bin/soffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    OUTPUT,
                    filepath,
                ],
                timeout=10,
            )
        except Exception:
            logger.error(f"Error converting File: {filename}")
        finally:
            os.unlink(filepath)
        del filename
    time.sleep(1.0)
