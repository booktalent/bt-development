"""Cleanup helper: inspect + delete TEST_* media created during iter73 UI testing."""
import os
import re
from pathlib import Path

import requests
from dotenv import dotenv_values

env = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or env["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE}/api"
CREDS = Path("/app/memory/test_credentials.md").read_text()
pwd = re.search(r"\|\s*`priya@booktalent\.com`\s*\|\s*`([^`]+)`", CREDS).group(1)

s = requests.Session()
r = s.post(f"{API}/auth/login", json={"email": "priya@booktalent.com", "password": pwd}, timeout=30)
r.raise_for_status()
items = s.get(f"{API}/media", timeout=30).json()
print("total", len(items))
for it in items[:6]:
    tr = s.get(f"{API}/media/{it['id']}/thumb", timeout=30)
    print(it.get("title"), "| order:", it.get("order"), "| created:", it.get("created_at"),
          "| mime:", it.get("mime"), "| thumb:", tr.status_code, len(tr.content))
tests = [it for it in items if (it.get("title") or "").startswith("TEST_")]
print("deleting", len(tests), "TEST_ items")
for it in tests:
    s.delete(f"{API}/media/{it['id']}", timeout=30)
print("remaining", len(s.get(f"{API}/media", timeout=30).json()))
