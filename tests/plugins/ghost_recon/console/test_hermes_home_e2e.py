"""The console inside a real Hermes home, without GHOSTRECON_DB (spec §4.3, §12): ``hermes ghostrecon user add`` and
``hermes ghostrecon serve`` load the plugin through Hermes' own discovery, read the console settings from that home's
config.yaml and find the database under plugin-data; the detached job runner and the agent write to that same
database, and the job-end notice reaches a fake ``hermes send``."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from plugins.ghost_recon.console import procs

SERVE = Path(__file__).resolve().parent / "serve_hermes.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "GHOSTRECON_DB"}  # the profile alone decides the DB
    env.update(HERMES_HOME=str(home), PYTHONIOENCODING="utf-8")
    return env


@pytest.fixture
def hermes_home(tmp_path):
    home, cases = tmp_path / "hermes-home", tmp_path / "Casos"
    home.mkdir()
    cases.mkdir()
    port = _free_port()
    console = {"case_roots": [str(cases)], "port": port, "notify_target": "telegram"}
    config = {"plugins": {"enabled": ["ghost-recon"], "entries": {"ghost-recon": {"settings": {"console": console}}}}}
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")  # JSON is valid YAML
    return {"home": home, "cases": cases, "port": port, "db": home / "plugin-data" / "ghost-recon" / "ghostrecon.db"}


def _wait(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        assert time.monotonic() < deadline, f"timed out after {timeout} s waiting for {message}"
        time.sleep(0.2)


def _up(base, server, log_path):
    try:
        return httpx.get(base + "/api/v1/auth/me", timeout=2).status_code == 401
    except httpx.TransportError:
        assert server.poll() is None, log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
        return False


def test_serve_and_its_runner_share_the_profile_database(hermes_home, tmp_path):
    env = _env(hermes_home["home"])
    added = subprocess.run([sys.executable, "-m", "hermes_cli.main", "ghostrecon", "user", "add", "jean", "--role",
                            "admin", "--password-stdin"], cwd=procs.hermes_root(), env=env, input="admin-pass-123\n",
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert added.returncode == 0, added.stderr[-3000:]
    assert hermes_home["db"].is_file()  # created under <home>/plugin-data/ghost-recon/
    record, fake = tmp_path / "send.json", tmp_path / "fake.json"
    fake.write_text(json.dumps({"default": {"steps": 2, "delay": 0.05, "record_send": str(record)}}),
                    encoding="utf-8")
    log_path = tmp_path / "serve.log"
    folder = hermes_home["cases"] / "Caso Perfil"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    base = f"http://127.0.0.1:{hermes_home['port']}"
    with open(log_path, "wb") as log:
        server = subprocess.Popen([sys.executable, str(SERVE), "--fake-config", str(fake)], cwd=procs.hermes_root(),
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            _wait(lambda: _up(base, server, log_path), 120, "the console to start")
            with httpx.Client(base_url=base, timeout=30) as c:
                r = c.post("/api/v1/auth/login", json={"username": "jean", "password": "admin-pass-123"})
                assert r.status_code == 200, r.text  # the admin the CLI created, in the same database
                c.headers["X-GR-CSRF"] = r.json()["csrf"]
                doctor = c.get("/api/v1/system/doctor").json()
                assert doctor["console"]["case_roots"] == [str(hermes_home["cases"])]  # from that home's config.yaml
                database = next(x["detail"] for x in doctor["checks"] if x["check"] == "database")
                assert Path(database.split(" · ")[0]).resolve() == hermes_home["db"].resolve()
                job = c.post("/api/v1/jobs", json={"command": "new-open-case", "folder": str(folder)}).json()["job"]
                done = _wait(lambda: (lambda j: j if j["status"] not in ("queued", "running") else None)(
                    c.get(f"/api/v1/jobs/{job['id']}").json()), 180, "the job to end")
                # Only the detached runner writes "succeeded" and the case id, and only the fake agent opens the
                # case: the server reading both back from its database proves all three share it.
                assert done["status"] == "succeeded" and done["case_id"], done
                assert c.get(f"/api/v1/cases/{done['case_id']}").json()["case"]["root_path"] == str(folder.resolve())
            _wait(record.is_file, 60, "the job-end notice")  # sent right after the runner's final write
        finally:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()  # never leave a stuck server behind a failed run
                server.wait(timeout=30)
    sent = json.loads(record.read_text(encoding="utf-8"))
    assert sent[sent.index("--to") + 1] == "telegram" and sent[-1].startswith(f"Ejecución #{job['id']}")
