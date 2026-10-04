"""Acceptance of H2 (spec §13): a real console server process drives the real job runner and the fake agent —
launch, follow live, restart the server without losing the job, cancel, and detect an orphan."""
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import httpx
import psutil
import pytest

from plugins.ghost_recon.console import procs
from plugins.ghost_recon.console.store import TERMINAL_STATUSES

SERVE = Path(__file__).resolve().parent / "serve_fake.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Console:
    """One real server process (serve_fake.py) on its own port, over the test DB."""

    def __init__(self, workdir: Path, case_root: Path, config: Path, tick: float):
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.log_path = workdir / f"server-{self.port}.log"
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVE), "--port", str(self.port), "--case-root", str(case_root),
             "--fake-config", str(config), "--tick", str(tick)],
            cwd=procs.hermes_root(), env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdout=self._log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    httpx.get(self.base + "/api/v1/auth/me", timeout=2)
                    return
                except httpx.TransportError:
                    assert self.proc.poll() is None, self.log_path.read_text(encoding="utf-8", errors="replace")
                    assert time.monotonic() < deadline, "the console did not start within 60 s"
                    time.sleep(0.2)
        except Exception:
            # If initialization fails, clean up the server process and log file before raising
            try:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait()
            finally:
                self._log.close()
            raise

    @contextlib.contextmanager
    def client(self) -> Iterator[httpx.Client]:
        with httpx.Client(base_url=self.base, timeout=20) as c:
            r = c.post("/api/v1/auth/login", json={"username": "jean", "password": "admin-pass-123"})
            assert r.status_code == 200, r.text
            c.headers["X-GR-CSRF"] = r.json()["csrf"]
            yield c

    def stop(self) -> None:
        """Stop server and close log file; always closes log even if server termination fails."""
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
        finally:
            self._log.close()


@pytest.fixture
def consoles(tmp_path, case_root, users, cstore):
    """Factory: start a real console with a fake-agent config; stops servers and leftover job trees at the end."""
    started = []

    def _start(config: dict, tick: float = 0.5) -> Console:
        path = tmp_path / f"fake-config-{len(started)}.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        console = Console(tmp_path, case_root, path, tick)
        started.append(console)
        return console

    yield _start
    # Attempt every cleanup independently; one failure never skips the rest.
    errors = []
    for console in started:
        try:
            console.stop()
        except Exception as e:
            errors.append(e)
    for job in cstore.list_jobs():
        try:
            procs.kill_tree(job["runner_pid"], job["runner_started"])
        except Exception as e:
            errors.append(e)
        try:
            procs.kill_tree(job["pid"], job["pid_started"])
        except Exception as e:
            errors.append(e)
    if errors:
        raise errors[0]


def _folder(case_root, name):
    folder = case_root / name
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder


def _finished(client, job_id):
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    return job if job["status"] in TERMINAL_STATUSES else None


def _with_agent(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["pid"] else None


def test_a_job_survives_a_server_restart_and_finishes(consoles, case_root, cstore, wait_until):
    # Long-running job so it's still active when the second server starts.
    config = {"default": {"steps": 60, "delay": 0.25}}
    first = consoles(config)
    with first.client() as c:
        job = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                           "folder": str(_folder(case_root, "Caso E2E"))}).json()["job"]
        wait_until(lambda: len(c.get(f"/api/v1/jobs/{job['id']}/events").json()["items"]) >= 3,
                   message="live events")
    # Read row and verify job is still running before stopping the server.
    row = cstore.get_job(job["id"])
    assert row["status"] == "running", "job must be running when first server is stopped"
    first.stop()
    assert procs.alive(row["runner_pid"], row["runner_started"]), "stopping the server must not stop the runner"
    # Second server must reconnect to the running job, not see it orphaned.
    second = consoles(config)
    with second.client() as c:
        job_after = c.get(f"/api/v1/jobs/{job['id']}").json()
        assert job_after["status"] == "running", "job must still be running after server restart"
        done = wait_until(lambda: _finished(c, job["id"]), timeout=180, message="job end")
        assert done["status"] == "succeeded" and done["case_id"] and done["progress"]["evidence"] >= 1
        events = c.get(f"/api/v1/jobs/{job['id']}/events").json()["items"]
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1)) and events[-1]["kind"] == "result"
        assert job["id"] in [j["id"] for j in c.get(f"/api/v1/cases/{done['case_id']}/jobs").json()["items"]]


def test_cancel_and_orphan_detection_through_a_real_server(consoles, case_root, cstore, wait_until):
    console = consoles({"default": {"hang": True}})
    with console.client() as c:
        doomed = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                              "folder": str(_folder(case_root, "Caso Cancelar"))}).json()["job"]
        row = wait_until(lambda: _with_agent(cstore, doomed["id"]), message="agent started")
        runner_pid, runner_started = row["runner_pid"], row["runner_started"]
        r = c.post(f"/api/v1/jobs/{doomed['id']}/cancel")
        assert r.status_code == 200 and r.json()["job"]["status"] == "cancelled"
        wait_until(lambda: not procs.alive(row["pid"], row["pid_started"]), message="cancelled agent gone")
        wait_until(lambda: not procs.alive(runner_pid, runner_started), message="cancelled runner gone")

        lost = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                            "folder": str(_folder(case_root, "Caso Huérfano"))}).json()["job"]
        row = wait_until(lambda: _with_agent(cstore, lost["id"]), message="agent started")
        psutil.Process(row["runner_pid"]).kill()  # the runner dies without writing its final state
        orphan = wait_until(lambda: _finished(c, lost["id"]), timeout=60, message="orphan verdict")
        assert orphan["status"] == "orphaned" and orphan["error"]
        wait_until(lambda: not procs.alive(row["pid"], row["pid_started"]), timeout=60, message="orphaned agent stopped")
        wait_until(lambda: not procs.alive(row["runner_pid"], row["runner_started"]), timeout=60, message="orphaned runner gone")
        assert "runner_log" in c.get(f"/api/v1/jobs/{lost['id']}/log").json()
