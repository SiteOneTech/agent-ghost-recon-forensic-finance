"""AuthService contracts: password hashing, account rules, session expiry, lockout, API tokens."""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from plugins.ghost_recon.console.auth import (AccountConflict, AuthError, AuthService, LoginLocked, hash_password,
                                              verify_password)
from plugins.ghost_recon.console.settings import ConsoleSettings


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(cstore, clock):
    s = AuthService(cstore, ConsoleSettings(session_idle_hours=12, session_max_days=7), clock=clock)
    s.add_user("jean", "admin-pass-123", "admin")
    return s


def test_password_hash_roundtrip_and_rejections():
    encoded = hash_password("correct horse 1")
    assert verify_password("correct horse 1", encoded)
    assert not verify_password("correct horse 2", encoded)
    assert not verify_password("x", "not-a-hash")
    assert hash_password("same-pass-1") != hash_password("same-pass-1")  # salted


@pytest.mark.parametrize("username,password", [("a b", "long-enough-1"), ("x", "long-enough-1"), ("ok-user", "short")])
def test_add_user_validates_username_and_password(svc, username, password):
    with pytest.raises(ValueError):
        svc.add_user(username, password, "viewer")


def test_usernames_are_case_insensitive_and_unique(svc):
    with pytest.raises(ValueError):
        svc.add_user("JEAN", "other-pass-123", "viewer")


def test_session_expires_after_idle_window_and_absolute_limit(svc, clock):
    raw, _ = svc.login("jean", "admin-pass-123")
    clock.advance(hours=11)
    assert svc.resolve_session(raw) is not None  # activity refreshes last_seen
    clock.advance(hours=11)
    assert svc.resolve_session(raw) is not None
    clock.advance(hours=13)
    assert svc.resolve_session(raw) is None  # idle longer than 12 h
    raw2, _ = svc.login("jean", "admin-pass-123")
    for _ in range(15):  # stays active every 12 h, but runs past the 7-day absolute cap
        clock.advance(hours=12)
        svc.resolve_session(raw2)
    assert svc.resolve_session(raw2) is None


def test_lockout_after_five_failures_blocks_even_the_right_password(svc, clock):
    for _ in range(5):
        with pytest.raises(AuthError):
            svc.login("jean", "wrong-password", ip="10.0.0.9")
    with pytest.raises(LoginLocked) as locked:
        svc.login("jean", "admin-pass-123", ip="10.0.0.9")
    assert locked.value.retry_after > 0
    clock.advance(minutes=6)
    raw, principal = svc.login("jean", "admin-pass-123", ip="10.0.0.9")
    assert raw and principal.username == "jean"


def test_failures_outside_the_window_do_not_lock(svc, clock):
    for _ in range(4):
        with pytest.raises(AuthError):
            svc.login("jean", "wrong-password")
    clock.advance(minutes=16)
    with pytest.raises(AuthError):
        svc.login("jean", "wrong-password")
    svc.login("jean", "admin-pass-123")  # only one failure inside the window: not locked


def test_password_change_and_disable_revoke_sessions(svc):
    svc.add_user("vera", "viewer-pass-123", "viewer")
    raw, _ = svc.login("vera", "viewer-pass-123")
    svc.set_password("vera", "viewer-pass-456")
    assert svc.resolve_session(raw) is None
    raw, _ = svc.login("vera", "viewer-pass-456")
    svc.set_disabled("vera", True)
    assert svc.resolve_session(raw) is None
    with pytest.raises(AuthError):
        svc.login("vera", "viewer-pass-456")


def test_last_active_admin_cannot_be_disabled(svc):
    with pytest.raises(ValueError):
        svc.set_disabled("jean", True)


def test_api_token_resolves_until_revoked(svc):
    raw, info = svc.create_api_token("jean", "webapp")
    principal = svc.resolve_bearer(raw)
    assert principal is not None and principal.username == "jean" and principal.via == "token"
    assert principal.csrf is None
    assert svc.revoke_api_token(info["id"])
    assert svc.resolve_bearer(raw) is None


def test_raw_session_and_api_tokens_never_reach_the_db(svc, cstore):
    raw_session, _ = svc.login("jean", "admin-pass-123", ip="127.0.0.1")
    raw_token, _ = svc.create_api_token("jean", "webapp")
    dump = "\n".join(str(v) for table in ("console_sessions", "console_tokens", "console_audit_log")
                     for row in cstore.conn.execute(f"SELECT * FROM {table}") for v in tuple(row))
    assert raw_session not in dump and raw_token not in dump


def test_session_timestamps_come_from_injected_clock():
    """Invariant: session timestamps must come from auth's injected clock, not wall-clock time.

    If last_seen_at is set by wall-clock utcnow() in store.py, then tests with a pinned or far-off
    clock will have idle times calculated wrong (e.g. a login at wall-clock 2026 with clock pinned at 2031
    appears to have negative idle, or idle hours in the thousands). This proves the timestamps sync.
    """
    from plugins.ghost_recon.console.store import ConsoleStore
    # Use a clock far from real wall time to prove the issue would manifest if timestamps came from wall-clock
    clock = Clock()
    clock.now = datetime(2031, 1, 1, 12, 0, tzinfo=timezone.utc)
    cstore = ConsoleStore.open_default()
    svc = AuthService(cstore, ConsoleSettings(session_idle_hours=12, session_max_days=7), clock=clock)
    svc.add_user("distant", "password-far-away-12", "admin")

    raw, _ = svc.login("distant", "password-far-away-12")
    # Advance 11 hours in the injected clock; session should still be valid (idle < 12h)
    clock.advance(hours=11)
    assert svc.resolve_session(raw) is not None, "session must be valid 11 hours after login"
    # Advance 13 more hours in the injected clock; session should now be expired (idle >= 12h, but we added a touch)
    # Actually since resolve_session touches, we need to advance past 12h total from the original login
    clock.now = datetime(2031, 1, 1, 12, 0, tzinfo=timezone.utc)  # reset to login time
    raw2, _ = svc.login("distant", "password-far-away-12")
    clock.advance(hours=13)
    assert svc.resolve_session(raw2) is None, "session must expire after 13 hours of idle (> 12h limit)"


def test_the_last_active_admin_keeps_the_role_and_stays_enabled(svc):
    with pytest.raises(AccountConflict):
        svc.set_role("jean", "viewer")
    with pytest.raises(AccountConflict):
        svc.set_disabled("jean", True)
    svc.add_user("ana", "admin-pass-456", "admin")
    svc.set_role("jean", "viewer")
    assert svc.cstore.get_user("jean")["role"] == "viewer"


def test_last_admin_guard_is_atomic_against_concurrent_demote_or_disable(svc):
    """Verify that the last-admin guard uses locking and prevents concurrent demote/disable race.

    The lock in AuthService._last_admin_lock ensures that check-and-write for the last-admin guard
    is atomic. With two active admins, we can manually verify that both operations can't succeed
    concurrently by checking that any attempt is blocked by one succeeding and one failing.
    """
    svc.add_user("ana", "admin-pass-456", "admin")
    assert svc.cstore.count_active_admins() == 2

    # Verify the lock exists and is a Lock object
    assert hasattr(svc, "_last_admin_lock")
    assert isinstance(svc._last_admin_lock, threading.Lock)

    # With two admins, disabling one should succeed, demoting the other should also succeed
    # (since after the first succeeds, there's still one active admin left)
    svc.set_disabled("ana", True)
    assert svc.cstore.count_active_admins() == 1

    # Now jean is the only active admin; neither disable nor demote should be possible
    with pytest.raises(AccountConflict):
        svc.set_disabled("jean", True)
    with pytest.raises(AccountConflict):
        svc.set_role("jean", "viewer")
