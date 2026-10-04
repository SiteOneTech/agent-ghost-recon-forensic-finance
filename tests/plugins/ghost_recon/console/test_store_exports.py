"""Console schema v3 and the H3 settings: export rows, the job-end notice argv, session purge, and a migration that
two processes can start at once."""
import threading
import time

import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings
from plugins.ghost_recon.console.store import (CONSOLE_MIGRATIONS, CONSOLE_SCHEMA, CONSOLE_SCHEMA_VERSION,
                                               EXPORT_PENDING, ConsoleStore, migrate_console)
from plugins.ghost_recon.core.db import connect, migrate


def test_settings_parse_the_notice_target_and_the_export_options():
    s = ConsoleSettings.from_mapping({"notify_target": " telegram:-1001234567890:17585 ",
                                      "export_include_unsealed": "true",
                                      "export_retention": {"count": "5", "days": 7}})
    assert s.notify_target == "telegram:-1001234567890:17585"
    assert s.export_include_unsealed is True
    assert (s.export_retention_count, s.export_retention_days) == (5, 7)


@pytest.mark.parametrize("target", ["-x", "telegram now", "tele gram", "a" * 201, "telegram\nx", 12])
def test_a_malformed_notice_target_disables_the_notice(target):
    assert ConsoleSettings.from_mapping({"notify_target": target}).notify_target == ""


def test_invalid_export_options_fall_back_to_the_defaults():
    d = ConsoleSettings()
    s = ConsoleSettings.from_mapping({"export_include_unsealed": "quizás", "export_retention": {"count": 0, "days": "x"}})
    assert (s.export_include_unsealed, s.export_retention_count, s.export_retention_days) == (
        d.export_include_unsealed, d.export_retention_count, d.export_retention_days)
    assert ConsoleSettings.from_mapping({"export_retention": [20, 30]}).export_retention_count == d.export_retention_count


def _h2_database(path):
    """A database exactly as H2 left it: schema v2 with one job."""
    conn = connect(path)
    migrate(conn)
    for stmt in CONSOLE_SCHEMA + CONSOLE_MIGRATIONS[2]:
        conn.execute(stmt)
    conn.execute("INSERT INTO console_schema_version(version) VALUES (2)")
    conn.execute("INSERT INTO console_jobs(command, folder, launched_by, created_at) VALUES"
                 " ('rerun-case', '/c', 'jean', '2026-10-03T10:00:00Z')")
    conn.commit()
    return conn


def test_an_h2_database_migrates_to_v3_once_and_keeps_its_jobs(gr_env):
    path = gr_env / "h2.db"
    _h2_database(path).close()
    first = ConsoleStore.open(path)
    again = ConsoleStore.open(path)
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "console_exports" in tables
    assert [tuple(r) for r in again.conn.execute("SELECT version FROM console_schema_version")] == [
        (CONSOLE_SCHEMA_VERSION,)]
    job = first.list_jobs()[0]
    assert job["command"] == "rerun-case" and job["notify_argv"] == []


def test_a_second_migrator_waits_for_the_first_and_finds_nothing_to_do(gr_env):
    """The server and a runner can open an H2 database together: the one that loses the race must not repeat a step
    (ALTER TABLE ADD COLUMN fails when run twice)."""
    path = gr_env / "race.db"
    _h2_database(path).close()
    first, second = connect(path), connect(path)
    first.execute("BEGIN IMMEDIATE")  # the first migrator is mid-way
    errors = []

    def migrate_second():
        try:
            migrate_console(second)
        except Exception as exc:  # what the test is about: no "duplicate column name"
            errors.append(exc)

    racer = threading.Thread(target=migrate_second)
    racer.start()
    time.sleep(0.3)  # the second has read version 2 and now waits for the write lock
    for stmt in CONSOLE_MIGRATIONS[3]:
        first.execute(stmt)
    first.execute("UPDATE console_schema_version SET version=3")
    first.commit()
    racer.join(timeout=10)
    assert not racer.is_alive() and errors == []
    assert [tuple(r) for r in second.execute("SELECT version FROM console_schema_version")] == [(3,)]


def test_jobs_keep_the_notice_target_and_argv(cstore):
    job = cstore.create_job(command="rerun-case", folder="/c", args={}, argv=["hermes"], launched_by="jean",
                            notify_target="telegram", notify_argv=["hermes", "send", "--to", "telegram"])
    assert job["notify_target"] == "telegram" and job["notify_argv"] == ["hermes", "send", "--to", "telegram"]
    bare = cstore.create_job(command="rerun-case", folder="/d", args={}, argv=["hermes"], launched_by="jean")
    assert bare["notify_target"] is None and bare["notify_argv"] == []


def test_export_rows_round_trip_and_update_only_while_expected(cstore):
    row = cstore.create_export(case_id="GRC-a", scope="audit", seq="A01", include_unsealed=False, created_by="vera")
    assert (row["status"], row["include_unsealed"], row["seq"]) == ("queued", False, "A01")
    assert cstore.update_export(row["id"], expect=("queued",), status="building", files_total=4)
    assert cstore.update_export(row["id"], status="failed", detail={"code": "seal_broken"})
    assert not cstore.update_export(row["id"], expect=EXPORT_PENDING, status="succeeded")  # a late writer loses
    stored = cstore.get_export(row["id"])
    assert stored["status"] == "failed" and stored["detail"] == {"code": "seal_broken"}
    assert cstore.get_export(row["id"] + 100) == {}


def test_export_writes_reject_unknown_fields_statuses_and_scopes(cstore):
    row = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=True, created_by="jean")
    with pytest.raises(ValueError):
        cstore.update_export(row["id"], case_id="GRC-b")
    with pytest.raises(ValueError):
        cstore.update_export(row["id"], status="paused")
    with pytest.raises(ValueError):
        cstore.create_export(case_id="GRC-a", scope="everything", seq=None, include_unsealed=False, created_by="jean")


def test_exports_are_listed_newest_first_and_by_status(cstore):
    a = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=False, created_by="jean")
    b = cstore.create_export(case_id="GRC-b", scope="case", seq=None, include_unsealed=False, created_by="jean")
    cstore.update_export(a["id"], status="succeeded")
    assert [e["id"] for e in cstore.list_exports()] == [b["id"], a["id"]]
    assert [e["id"] for e in cstore.list_exports(statuses=EXPORT_PENDING)] == [b["id"]]


def test_purge_sessions_drops_revoked_expired_and_idle_ones(cstore):
    user = cstore.create_user("jean", "hash", "admin")

    def session(token, last_seen, expires):
        return cstore.create_session(user_id=user["id"], token_sha256=token, csrf_token="c", expires_at=expires,
                                     ip="", user_agent="", now=last_seen)
    keep = session("keep", "2026-10-04T11:00:00Z", "2026-10-10T00:00:00Z")
    session("idle", "2026-10-03T20:00:00Z", "2026-10-10T00:00:00Z")
    session("expired", "2026-10-04T11:30:00Z", "2026-10-04T11:59:00Z")
    cstore.revoke_session(session("revoked", "2026-10-04T11:00:00Z", "2026-10-10T00:00:00Z"))
    assert cstore.purge_sessions(now="2026-10-04T12:00:00Z", idle_before="2026-10-04T00:00:00Z") == 3
    assert [r[0] for r in cstore.conn.execute("SELECT id FROM console_sessions")] == [keep]
