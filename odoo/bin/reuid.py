#!/usr/bin/env python3
import argparse
import pwd
import subprocess
import sys


def run(cmd):
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd)


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
