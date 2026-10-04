"""Hardening left over from H1 and H2: the lockout holds against a burst, last-seen bookkeeping never fails a read,
an unhandled error keeps the envelope and the security headers, and a live stream stops for a user who lost access."""
import contextlib
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from plugins.ghost_recon.console import auth as auth_mod
from plugins.ghost_recon.console.auth import MAX_FAILURES, AuthError, AuthService, LoginLocked, Principal
from plugins.ghost_recon.console.commands import CommandError
from plugins.ghost_recon.console.settings import ConsoleSettings

BURST = 12


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def test_a_burst_of_parallel_guesses_is_held_to_the_lockout_window(cstore, monkeypatch):
    svc = AuthService(cstore, ConsoleSettings())
    svc.add_user("jean", "admin-pass-123", "admin")
    checked = []
    real = auth_mod.verify_password

    def slow(password, encoded):  # scrypt latency: every guess of the burst overlaps the others
        checked.append(password)
        time.sleep(0.2)
        return real(password, encoded)

    monkeypatch.setattr(auth_mod, "verify_password", slow)
    start = threading.Barrier(BURST)
    outcomes = []

    def guess(i):
        start.wait()
        try:
            svc.login("jean", f"wrong-guess-{i}", ip="10.0.0.7")
        except LoginLocked:
            outcomes.append("locked")
        except AuthError:
            outcomes.append("refused")

    threads = [threading.Thread(target=guess, args=(i,)) for i in range(BURST)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(checked) == MAX_FAILURES  # only the window's worth of guesses ever reached the password check
    assert outcomes.count("refused") == MAX_FAILURES and outcomes.count("locked") == BURST - MAX_FAILURES


def test_a_busy_database_never_fails_an_authenticated_read(cstore, monkeypatch):
    clock = _Clock()
    svc = AuthService(cstore, ConsoleSettings(), clock=clock)
    svc.add_user("jean", "admin-pass-123", "admin")
    raw, _ = svc.login("jean", "admin-pass-123")
    token, _ = svc.create_api_token("jean", "webapp")
    clock.now += timedelta(minutes=5)  # past the touch interval: both resolutions want to write last-seen

    def locked(*_args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cstore, "touch_session", locked)
    monkeypatch.setattr(cstore, "touch_token", locked)
    assert svc.resolve_session(raw).username == "jean"
    assert svc.resolve_bearer(token).username == "jean"


def test_an_unhandled_error_keeps_the_envelope_and_the_security_headers(app, client):
    def boom():
        raise RuntimeError("C:/casos/secreto/ruta.txt")

    app.add_api_route("/api/v1/_boom", boom)
    r = client.get("/api/v1/_boom")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert "secreto" not in r.text  # the exception text (paths) stays in the server log


def test_a_live_stream_stops_once_its_user_is_disabled(login_as, case_root, auth, jobs, monkeypatch):
    from plugins.ghost_recon.console.routers import jobs as jobs_routes
    monkeypatch.setattr(jobs_routes, "HEARTBEAT_S", 0.3)
    folder = case_root / "hang-case"
    folder.mkdir()
    (folder / "nota.txt").write_text("x", encoding="utf-8")
    admin = login_as("admin")
    job = admin.post("/api/v1/jobs", json={"command": "new-open-case", "folder": str(folder)}).json()["job"]
    viewer = login_as("viewer")
    # The job never ends: the stream can only end because its watcher lost access while it was open. The safety
    # cancel ends it anyway (as "cancelled") if the stream never asks again, so a regression fails instead of hanging.
    threading.Timer(1.0, auth.set_disabled, args=("vera", True)).start()
    admin_principal = Principal(1, "jean", "admin", "session")
    safety = threading.Timer(20.0, jobs.cancel, args=(job["id"], admin_principal))
    safety.start()
    try:
        with viewer.stream("GET", f"/api/v1/jobs/{job['id']}/events/stream") as r:
            text = "".join(r.iter_text())
        assert "event: status" in text and text.rstrip().endswith('{"status": "unauthenticated"}')
        assert admin.post(f"/api/v1/jobs/{job['id']}/cancel").status_code == 200
    finally:  # the hang-case agent never ends by itself: stop it whatever failed above
        safety.cancel()
        with contextlib.suppress(CommandError):  # already cancelled above (or by the safety timer)
            jobs.cancel(job["id"], admin_principal)
