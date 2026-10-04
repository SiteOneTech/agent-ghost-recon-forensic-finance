"""Housekeeping: sessions past their expiry go, results ZIPs keep at most the newest ``count`` and none older than
``days``, and old job files go while active jobs keep theirs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from plugins.ghost_recon.console import jobfiles
from plugins.ghost_recon.console.housekeeping import Housekeeping

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _stamp(**ago):
    return (NOW - timedelta(**ago)).isoformat().replace("+00:00", "Z")


def _keeper(cstore, settings, tmp_path, **retention):
    exports_dir, jobs_dir = tmp_path / "exports", tmp_path / "jobs"
    exports_dir.mkdir(exist_ok=True)
    jobs_dir.mkdir(exist_ok=True)
    config = replace(settings, **retention)
    return Housekeeping(cstore, config, exports_dir=exports_dir, jobs_dir=jobs_dir, clock=lambda: NOW)


def test_sessions_past_their_idle_or_absolute_expiry_and_revoked_ones_go(cstore, settings, tmp_path):
    user = cstore.create_user("jean", "hash", "admin")

    def session(token, seen, expires):
        return cstore.create_session(user_id=user["id"], token_sha256=token, csrf_token="c", expires_at=expires,
                                     ip="", user_agent="", now=seen)
    fresh = session("fresh", _stamp(hours=1), _stamp(days=-6))
    session("idle", _stamp(hours=settings.session_idle_hours + 1), _stamp(days=-6))
    session("expired", _stamp(minutes=5), _stamp(minutes=1))
    cstore.revoke_session(session("revoked", _stamp(minutes=5), _stamp(days=-6)))
    assert _keeper(cstore, settings, tmp_path).purge_sessions() == 3
    assert [r[0] for r in cstore.conn.execute("SELECT id FROM console_sessions")] == [fresh]


def test_exports_keep_the_newest_count_and_nothing_older_than_days(cstore, settings, tmp_path):
    keeper = _keeper(cstore, settings, tmp_path, export_retention_count=2, export_retention_days=30)
    made = {}
    for name, age in (("viejo", {"days": 40}), ("tercero", {"days": 2}), ("segundo", {"days": 1}),
                      ("nuevo", {"minutes": 5})):
        row = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=False,
                                   created_by="vera")
        file_name = f"GhostRecon_a_case_{name}.zip"
        for path in (keeper.exports_dir / file_name, keeper.exports_dir / f"{file_name}.sha256"):
            path.write_bytes(b"x")
        cstore.update_export(row["id"], status="succeeded", file_name=file_name, finished_at=_stamp(**age))
        made[name] = row["id"]
    building = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=False,
                                    created_by="vera")
    cstore.update_export(building["id"], status="building", started_at=_stamp(days=60))
    assert keeper.prune_exports() == 2
    status = {name: cstore.get_export(eid)["status"] for name, eid in made.items()}
    assert status == {"viejo": "expired", "tercero": "expired", "segundo": "succeeded", "nuevo": "succeeded"}
    assert sorted(p.name for p in keeper.exports_dir.iterdir()) == sorted(
        f"GhostRecon_a_case_{n}.zip{s}" for n in ("segundo", "nuevo") for s in ("", ".sha256"))
    assert cstore.get_export(building["id"])["status"] == "building"


def test_old_job_files_go_and_active_jobs_keep_theirs(cstore, settings, tmp_path):
    keeper = _keeper(cstore, settings, tmp_path, export_retention_days=30)
    base = keeper.jobs_dir

    def job(status, finished):
        row = cstore.create_job(command="rerun-case", folder="/c", args={}, argv=["x"], launched_by="jean")
        cstore.update_job(row["id"], status=status, **({"finished_at": finished} if finished else {}))
        for path in (jobfiles.raw_path(base, row["id"]), jobfiles.log_path(base, row["id"]),
                     jobfiles.events_path(base, row["id"]), jobfiles.runner_log_path(base, row["id"])):
            path.write_text("x", encoding="utf-8")
        jobfiles.work_dir(base, row["id"]).mkdir()
        return row["id"]
    old, recent, running = job("succeeded", _stamp(days=40)), job("failed", _stamp(days=1)), job("running", None)
    assert keeper.prune_job_files() == 1
    left = {p.name for p in base.iterdir()}
    assert not any(name.split(".")[0] == str(old) for name in left)
    for kept in (recent, running):
        assert {f"{kept}.jsonl", f"{kept}.log", f"{kept}.events.jsonl", f"{kept}.runner.log", str(kept)} <= left
    assert cstore.get_job(old)["status"] == "succeeded"  # the row and its result stay


def test_the_console_cleans_up_when_it_starts(store, cstore, settings, auth, jobs):
    from plugins.ghost_recon.console.app import create_app
    user = cstore.create_user("old", "hash", "viewer")
    cstore.create_session(user_id=user["id"], token_sha256="gone", csrf_token="c", expires_at="2020-01-02T00:00:00Z",
                          ip="", user_agent="", now="2020-01-01T00:00:00Z")
    with TestClient(create_app(settings, store, cstore, auth=auth, jobs=jobs), base_url="http://localhost"):
        assert cstore.conn.execute("SELECT COUNT(*) FROM console_sessions").fetchone()[0] == 0
