import requests
import time

GECKODRIVER_URL = "http://127.0.0.1:4444"

# Step 1: Start a new session
session_url = f"{GECKODRIVER_URL}/session"
payload = {"capabilities": {"alwaysMatch": {"browserName": "firefox"}}}

resp = requests.post(session_url, json=payload)
resp.raise_for_status()

session_id = resp.json()["value"]["sessionId"]
print(f"Session started: {session_id}")

# Step 2: Navigate to www.ard.de
navigate_url = f"{GECKODRIVER_URL}/session/{session_id}/url"
requests.post(navigate_url, json={"url": "https://www.zebroo.de"})

# Step 3: Sleep to let the page load visibly
print("Page opened. Waiting 10 seconds...")
time.sleep(10000)

# Step 4: Close the session
delete_url = f"{GECKODRIVER_URL}/session/{session_id}"
requests.delete(delete_url)
print("Session closed.")
