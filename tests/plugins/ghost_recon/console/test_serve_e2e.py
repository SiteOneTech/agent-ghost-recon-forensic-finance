"""Real `serve` process: binds loopback, enforces auth, serves the frontend and logs in end to end."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[4]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_end_to_end(gr_env, auth):
    auth.add_user("jean", "admin-pass-123", "admin")
    port = _free_port()
    env = {**os.environ, "GHOSTRECON_DB": str(gr_env / "db" / "ghostrecon.db"), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-m", "plugins.ghost_recon.cli", "serve", "--port", str(port)],
                            cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                first = httpx.get(base + "/api/v1/auth/me", timeout=2)
                break
            except httpx.TransportError:
                assert proc.poll() is None, proc.stdout.read().decode("utf-8", "replace")
                assert time.monotonic() < deadline, "the console did not start within 30 s"
                time.sleep(0.2)
        assert first.status_code == 401
        with httpx.Client(base_url=base, timeout=5) as c:
            assert c.get("/").headers["content-type"].startswith("text/html")
            assert c.post("/api/v1/auth/login", json={"username": "jean", "password": "admin-pass-123"}).status_code == 200
            assert c.get("/api/v1/auth/me").json()["user"]["role"] == "admin"
    finally:
        proc.terminate()
        proc.wait(timeout=15)
