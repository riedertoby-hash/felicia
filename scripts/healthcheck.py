"""Container health check: calls /healthz with an allowed Host header (Django rejects unknown hosts)."""

import os
import sys
import urllib.request

host = (os.environ.get("DJANGO_ALLOWED_HOSTS") or "localhost").split(",")[0].strip()
req = urllib.request.Request("http://127.0.0.1:8000/healthz", headers={"Host": host, "X-Forwarded-Proto": "https"})
try:
    with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 - fixed local URL
        sys.exit(0 if resp.status == 200 else 1)
except Exception:  # noqa: BLE001
    sys.exit(1)
