# DOES NOT SEEM TO WORK ANYMORE - could not telnet localhost 2002
import os
import time
import subprocess
import sys
import signal

# Exit early if NO_SOFFICE is set to "1"
if os.environ.get("NO_SOFFICE") == "1":
    sys.exit(0)

# Kill existing soffice processes that use the specific socket/port
while True:
    try:
        subprocess.run(
            ["pkill", "-9", "-f", r"soffice\.bin.*socket.*port=2002"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(2)
    except subprocess.CalledProcessError:
        break  # No more matching processes

# Start LibreOffice in headless mode
while True:
    soffice_path = "/usr/lib/libreoffice/program/soffice.bin"
    if os.path.exists(soffice_path):
        subprocess.Popen(
            [
                "sudo", "-u", "odoo",
                soffice_path,
                "--headless", "--calc",
                '--accept=socket,host=127.0.0.1,port=2002;urp;StarOffice.ServiceManager'
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        # Equivalent to `reset` in terminal (optional: here just print a newline)
        print("\033c", end="", flush=True)
        sys.exit(0)
    time.sleep(2)