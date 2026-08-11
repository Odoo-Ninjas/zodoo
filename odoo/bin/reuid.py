#!/usr/bin/env python3
import argparse
import os
import pwd
import subprocess
import sys


def run(cmd):
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd)


def owns_pid1(uid):
    """True if PID 1 runs as `uid`.

    /proc/1 is owned by the user PID 1 runs as - that is the one usermod will
    refuse to touch. Missing /proc (not Linux, no procfs) means we cannot
    tell, and then we let usermod decide as before.
    """
    try:
        return os.stat("/proc/1").st_uid == uid
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Find user by OLD_UID and change it to NEW_UID."
    )
    parser.add_argument(
        "--old-uid", type=int, required=True, help="Existing UID to search for"
    )
    parser.add_argument(
        "--new-uid", type=int, required=True, help="New UID to assign"
    )
    args = parser.parse_args()

    old_uid = args.old_uid
    new_uid = args.new_uid

    # 1) User mit old_uid finden
    try:
        entry = pwd.getpwuid(old_uid)
    except KeyError:
        print(f"No user found for UID {old_uid} gefunden.")
        sys.exit(0)

    username = entry.pw_name
    print(f"Gefunden: User '{username}' hat UID {old_uid}")

    # 1b) Safety check: gehoert PID 1 diesem User? Dann weigert sich usermod
    # ("user root is currently used by process 1") und der Container stirbt
    # mit einer Meldung, die nichts ueber die Ursache sagt. Die Ursache ist
    # praktisch immer OWNER_UID=0 in den Settings.
    if owns_pid1(old_uid):
        print(
            f"ABBRUCH: UID {old_uid} gehoert '{username}', und dieser User "
            f"besitzt PID 1 - usermod kann ihn nicht umbenennen.\n"
            f"Ursache ist OWNER_UID={old_uid} in den Settings des Projekts "
            f"(${{project}}/.odoo/run/settings). OWNER_UID muss der Host-User "
            f"sein, dem die Dateien gehoeren, nicht root.\n"
            f"Entsteht typischerweise durch 'sudo -iu <user>' aus einer "
            f"Root-Shell (setzt SUDO_USER=root); 'su - <user>' vermeidet es."
        )
        sys.exit(1)

    # 2) Safety check: existiert new_uid schon?
    try:
        other = pwd.getpwuid(new_uid)
        print(
            f"ABBRUCH: UID {new_uid} existiert schon und gehört zu '{other.pw_name}'."
        )
        sys.exit(0)
    except KeyError:
        pass  # UID ist frei

    # 3) UID ändern
    run(["usermod", "-u", str(new_uid), username])

    print("Fertig.")
    print(f"Neue UID von '{username}': {pwd.getpwnam(username).pw_uid}")


if __name__ == "__main__":
    main()
