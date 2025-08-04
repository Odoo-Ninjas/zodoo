#!/usr/bin/env python3

import subprocess
import time
import sys

def check_wmctrl():
    try:
        subprocess.run(["wmctrl", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError:
        print("❌ wmctrl is installed but returned an error.")
        sys.exit(1)
    except FileNotFoundError:
        print("❌ wmctrl not found. Install it with: sudo apt install wmctrl")
        sys.exit(1)

def get_firefox_window_ids():
    try:
        result = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        firefox_ids = []
        for line in lines:
            if "firefox" in line.lower():
                win_id = line.split()[0]
                firefox_ids.append(win_id)
        return firefox_ids
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Failed to run wmctrl: {e}")
        return []

def maximize_window(win_id):
    try:
        subprocess.run(["wmctrl", "-i", "-r", win_id, "-b", "add,maximized_vert,maximized_horz"], check=True)
        print(f"🪟 Maximized window {win_id}")
    except subprocess.CalledProcessError:
        print(f"⚠️ Failed to maximize window {win_id}")

def main():
    print("🔁 Watching for Firefox windows... (Press Ctrl+C to stop)")
    check_wmctrl()

    while True:
        window_ids = get_firefox_window_ids()
        for win_id in window_ids:
            maximize_window(win_id)
        time.sleep(2)

if __name__ == "__main__":
    main()