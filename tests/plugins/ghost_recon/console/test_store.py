"""Console tables live beside the case tables without disturbing them; settings degrade to defaults."""
import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings
from plugins.ghost_recon.console.store import ConsoleStore


def test_console_migration_is_idempotent_and_keeps_the_case_schema(store, cstore):
    again = ConsoleStore.open_default()
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"console_users", "console_sessions", "console_tokens", "console_audit_log", "console_seal_checks"} <= tables
    assert {"cases", "audits", "findings", "evidence", "timeline"} <= tables
    assert again.conn.execute("SELECT COUNT(*) FROM console_schema_version").fetchone()[0] == 1
    assert store.list_cases() == []


def test_users_are_unique_and_active_admins_are_counted(cstore):
    cstore.create_user("jean", "hash-1", "admin")
    cstore.create_user("vera", "hash-2", "viewer")
    with pytest.raises(ValueError):
        cstore.create_user("jean", "hash-3", "viewer")
    with pytest.raises(ValueError):
        cstore.create_user("eve", "hash-4", "root")
    assert cstore.count_active_admins() == 1
    cstore.update_user("jean", disabled=1)
    assert cstore.count_active_admins() == 0


def test_seal_check_cache_keeps_only_the_latest_result(cstore):
    cstore.save_seal_check("GRC-x/A01", True, {"modified": []}, "jean")
    latest = cstore.save_seal_check("GRC-x/A01", False, {"modified": ["06_Report/a.md"]}, "vera")
    assert latest["ok"] is False and latest["checked_by"] == "vera"
    assert latest["detail"]["modified"] == ["06_Report/a.md"]
    assert cstore.get_seal_check("GRC-x/A02") == {}


def test_recent_events_span_cases_newest_first(store, cstore, demo_case):
    from plugins.ghost_recon.core import service
    service.open_case(store, str(demo_case), name="Acme Demo")
    events = cstore.recent_events(5)
    assert events and all(e["case_name"] == "Acme Demo" for e in events)
    stamps = [e["ts"] for e in events]
    assert stamps == sorted(stamps, reverse=True)


def test_settings_fall_back_to_defaults_on_invalid_values():
    d = ConsoleSettings()
    assert ConsoleSettings.from_mapping("not-a-mapping") == d
    s = ConsoleSettings.from_mapping({"port": "nope", "session_idle_hours": -1})
    assert (s.port, s.session_idle_hours) == (d.port, d.session_idle_hours)


def test_settings_apply_valid_values_and_keep_loopback_hosts():
    s = ConsoleSettings.from_mapping({"port": "9300", "session_idle_hours": 4, "allowed_hosts": ["Consola.Local"]})
    assert (s.port, s.session_idle_hours) == (9300, 4)
    assert {"localhost", "127.0.0.1", "::1", "consola.local"} <= set(s.allowed_hosts)
