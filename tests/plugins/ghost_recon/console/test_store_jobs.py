"""console_jobs and the new console settings: versioned migration from an H1 database, conditional job updates."""
import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings
from plugins.ghost_recon.console.store import ACTIVE_STATUSES, CONSOLE_SCHEMA, CONSOLE_SCHEMA_VERSION, ConsoleStore
from plugins.ghost_recon.core.db import connect, migrate


def test_settings_parse_case_roots_job_limit_and_dashboard_url():
    s = ConsoleSettings.from_mapping({"case_roots": ["/casos", " ", "/casos", "/otros"], "max_parallel_jobs": "3",
                                      "dashboard_url": "http://127.0.0.1:9119/"})
    assert s.case_roots == ("/casos", "/otros")
    assert s.max_parallel_jobs == 3 and s.dashboard_url == "http://127.0.0.1:9119"


def test_invalid_job_settings_fall_back_to_safe_defaults():
    d = ConsoleSettings()
    s = ConsoleSettings.from_mapping({"case_roots": "/casos", "max_parallel_jobs": 0,
                                      "dashboard_url": "javascript:alert(1)"})
    assert (s.case_roots, s.max_parallel_jobs, s.dashboard_url) == ((), d.max_parallel_jobs, "")


def test_an_h1_database_migrates_to_the_current_version_once(gr_env):
    path = gr_env / "h1.db"
    conn = connect(path)
    migrate(conn)
    for stmt in CONSOLE_SCHEMA:  # exactly what H1 created
        conn.execute(stmt)
    conn.execute("INSERT INTO console_schema_version(version) VALUES (1)")
    conn.commit()
    ConsoleStore(conn)
    again = ConsoleStore.open(path)
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "console_jobs" in tables
    versions = [tuple(r) for r in again.conn.execute("SELECT version FROM console_schema_version")]
    assert versions == [(CONSOLE_SCHEMA_VERSION,)]


def test_job_rows_round_trip_argv_and_json_columns(cstore):
    argv = ["/opt/h/.hermes/bin/hermes", "-q", '/new-open-case "/casos/Caso Logística"']
    job = cstore.create_job(command="new-open-case", folder="/casos/Caso Logística", args={"name": "Logística"},
                            argv=argv, launched_by="jean")
    assert job["status"] == "queued" and job["argv"] == argv and job["args"] == {"name": "Logística"}
    cstore.update_job(job["id"], tokens={"total": 15})
    assert cstore.get_job(job["id"])["tokens"] == {"total": 15}
    assert cstore.get_job(job["id"] + 100) == {}


def test_status_updates_only_apply_while_the_expected_status_holds(cstore):
    job = cstore.create_job(command="rerun-case", folder="/c", args={}, argv=["x"], launched_by="jean")
    assert cstore.update_job(job["id"], expect=("queued",), status="running")
    assert cstore.update_job(job["id"], status="cancelled")
    assert not cstore.update_job(job["id"], expect=ACTIVE_STATUSES, status="failed")  # a late writer loses
    assert cstore.get_job(job["id"])["status"] == "cancelled"


def test_job_writes_reject_unknown_fields_statuses_and_orders(cstore):
    job = cstore.create_job(command="review-case", folder="/c", args={}, argv=["x"], launched_by="jean")
    with pytest.raises(ValueError):
        cstore.update_job(job["id"], argv=["y"])
    with pytest.raises(ValueError):
        cstore.update_job(job["id"], status="paused")
    with pytest.raises(ValueError):
        cstore.create_job(command="rm-rf", folder="/c", args={}, argv=["x"], launched_by="jean")


def test_jobs_are_listed_by_status_and_by_case_or_folder(cstore):
    a = cstore.create_job(command="new-open-case", folder="/c/a", args={}, argv=["x"], launched_by="jean")
    b = cstore.create_job(command="rerun-case", folder="/c/b", args={}, argv=["x"], launched_by="jean",
                          case_id="GRC-b")
    cstore.update_job(b["id"], status="succeeded")
    assert [j["id"] for j in cstore.list_jobs()] == [b["id"], a["id"]]
    assert [j["id"] for j in cstore.list_jobs(statuses=ACTIVE_STATUSES)] == [a["id"]]
    both = cstore.list_jobs(case_id="GRC-b", folder="/c/a", oldest_first=True)
    assert [j["id"] for j in both] == [a["id"], b["id"]]


def test_a_write_that_hits_a_lock_never_leaves_later_reads_stale(cstore):
    """A runner that skips a locked progress write must still see a cancel written afterwards by another process."""
    import sqlite3
    from plugins.ghost_recon import runtime
    job = cstore.create_job(command="new-open-case", folder="/c/x", args={}, argv=["x"], launched_by="jean")
    cstore.update_job(job["id"], status="running")
    other = runtime.open_connection()
    cstore.conn.execute("PRAGMA busy_timeout=50")
    other.execute("UPDATE console_jobs SET phase='swarm' WHERE id=?", (job["id"],))  # holds the write lock
    with pytest.raises(sqlite3.OperationalError):
        cstore.update_job(job["id"], expect=("running",), phase="intake")
    other.commit()
    assert cstore.get_job(job["id"])["status"] == "running"
    other.execute("UPDATE console_jobs SET status='cancelled' WHERE id=?", (job["id"],))
    other.commit()
    other.close()
    assert cstore.get_job(job["id"])["status"] == "cancelled"
