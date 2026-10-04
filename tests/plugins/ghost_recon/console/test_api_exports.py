"""Export API: a background build with progress whose download matches its SHA-256, the role rules of unsealed
audits, the preview of what goes in, a broken seal that fails the build, the audit trail, and builds that a server
restart interrupted."""
import hashlib
import sqlite3
import threading
import time
from dataclasses import replace

import pytest

from plugins.ghost_recon.console import exporter
from plugins.ghost_recon.console.auth import Principal
from plugins.ghost_recon.console.exports import ExportService


def _wait_done(c, wait_until, export_id):
    def done():
        row = c.get(f"/api/v1/exports/{export_id}").json()
        return row if row["status"] in ("succeeded", "failed") else None
    return wait_until(done, timeout=60, message="export end")


def _export(c, seeded, **body):
    return c.post(f"/api/v1/cases/{seeded['case_id']}/export", json=body)


def test_a_viewer_exports_the_case_and_downloads_exactly_the_hashed_zip(login_as, seeded, store, wait_until):
    c = login_as("viewer")
    r = _export(c, seeded)
    assert r.status_code == 202 and r.json()["export"]["status"] == "queued"
    row = _wait_done(c, wait_until, r.json()["export_id"])
    assert row["status"] == "succeeded" and row["files_done"] == row["files_total"] > 0
    assert row["detail"]["excluded"][0]["seq"] == "A02"  # open audit: left out by default
    zip_bytes = c.get(f"/api/v1/exports/{row['id']}/download")
    assert zip_bytes.status_code == 200 and zip_bytes.headers["content-type"] == "application/zip"
    assert hashlib.sha256(zip_bytes.content).hexdigest() == row["sha256"]
    sidecar = c.get(f"/api/v1/exports/{row['id']}/sha256").text
    assert sidecar == f"{row['sha256']}  {row['file_name']}\n"
    event = next(e for e in store.list_events(seeded["case_id"]) if e["event_type"] == "results_exported")
    assert event["actor"] == "vera" and event["ref"]["sha256"] == row["sha256"]
    actions = [(e["action"], e["username"]) for e in login_as("admin").get("/api/v1/system/audit-log").json()["items"]]
    assert {("export_request", "vera"), ("export", "vera"), ("export_download", "vera")} <= set(actions)


def test_only_an_admin_includes_unsealed_audits_and_they_come_marked_draft(login_as, seeded, wait_until):
    viewer = login_as("viewer")
    r = _export(viewer, seeded, include_unsealed=True)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert viewer.get(f"/api/v1/cases/{seeded['case_id']}/export/preview",
                      params={"include_unsealed": "true"}).status_code == 403
    admin = login_as("admin")
    row = _wait_done(admin, wait_until, _export(admin, seeded, include_unsealed=True).json()["export_id"])
    assert row["status"] == "succeeded" and row["detail"]["draft"] is True and "-DRAFT_" in row["file_name"]
    assert {a["seq"]: a["state"] for a in row["detail"]["audits"]} == {"A01": "SEALED", "A02": "DRAFT"}
    for path in ("", "/download", "/sha256"):  # a DRAFT export is read by admins only: status, ZIP and sidecar
        denied = viewer.get(f"/api/v1/exports/{row['id']}{path}")
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden", path
        assert admin.get(f"/api/v1/exports/{row['id']}{path}").status_code == 200, path
    log = admin.get("/api/v1/system/audit-log").json()["items"]
    assert sum(e["action"] == "export_download_denied" and e["username"] == "vera" for e in log) == 2


def test_the_configured_default_includes_unsealed_audits_for_admins_only(store, cstore, settings, auth, jobs,
                                                                        login_on, seeded):
    from plugins.ghost_recon.console.app import create_app
    app = create_app(replace(settings, export_include_unsealed=True), store, cstore, auth=auth, jobs=jobs)
    url = f"/api/v1/cases/{seeded['case_id']}/export/preview"
    admin = login_on(app, "admin").get(url).json()
    viewer = login_on(app, "viewer").get(url).json()
    assert admin["include_unsealed"] is True and [a["seq"] for a in admin["audits"]] == ["A01", "A02"]
    assert viewer["include_unsealed"] is False and [a["seq"] for a in viewer["audits"]] == ["A01"]
    assert viewer["can_include_unsealed"] is False and admin["can_include_unsealed"] is True


def test_the_preview_explains_what_stays_out_while_a_job_is_active(login_as, seeded, cstore):
    c = login_as("admin")
    url = f"/api/v1/cases/{seeded['case_id']}/export/preview"
    assert c.get(url, params={"include_unsealed": "true"}).json()["excluded"] == []
    cstore.create_job(command="rerun-case", folder=str(seeded["root"]), args={}, argv=["x"], launched_by="jean",
                      case_id=seeded["case_id"])  # queued: it may start writing at any moment
    preview = c.get(url, params={"include_unsealed": "true"}).json()
    assert [(e["seq"], e["reason"]) for e in preview["excluded"]] == [("A02", "job_running")] and preview["excluded"][0]["text"]
    r = c.post(f"/api/v1/cases/{seeded['case_id']}/export", json={"scope": "audit", "seq": "A02",
                                                                   "include_unsealed": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "job_running"


def test_a_case_has_one_pending_export_at_a_time(login_as, seeded, cstore, wait_until, monkeypatch):
    """A second «Exportar» while the first build is still queued or running is refused naming it, and no row is
    created; once the first ends the case exports again."""
    gate, real_build = threading.Event(), exporter.build

    def held_build(*args, **kwargs):
        gate.wait(30)
        return real_build(*args, **kwargs)
    monkeypatch.setattr(exporter, "build", held_build)
    c = login_as("viewer")
    try:
        first = _export(c, seeded).json()["export_id"]
        second = _export(c, seeded)
        assert second.status_code == 409 and second.json()["error"]["code"] == "export_pending"
        assert second.json()["error"]["export_id"] == first and f"#{first}" in second.json()["error"]["message"]
        assert [e["id"] for e in cstore.list_exports() if e["case_id"] == seeded["case_id"]] == [first]
    finally:
        gate.set()
    assert _wait_done(c, wait_until, first)["status"] == "succeeded"
    assert _export(c, seeded).status_code == 202


def test_an_export_whose_state_writes_keep_failing_never_blocks_its_case(login_as, seeded, cstore, wait_until,
                                                                          monkeypatch):
    """For the build of one export the database stays locked through every retry of its final write (and the
    worker's last attempt), so its row is left "building". The next «Exportar» of the case is still accepted once
    that build is over, and the stuck row ends failed as interrupted instead of blocking the case until a restart."""
    from plugins.ghost_recon.console import exports as exports_mod
    monkeypatch.setattr(exports_mod, "STATE_WRITE_BACKOFF_S", (0.0, 0.0))
    real_update, locked = cstore.update_export, {}

    def update_export(export_id, **fields):
        in_build = threading.current_thread().name == "gr-console-exports"  # the request's own writes go through
        final = fields.get("status") in ("succeeded", "failed")
        if in_build and final and locked.setdefault("id", export_id) == export_id:
            raise sqlite3.OperationalError("database is locked")
        return real_update(export_id, **fields)
    monkeypatch.setattr(cstore, "update_export", update_export)
    c = login_as("viewer")
    stuck = _export(c, seeded).json()["export_id"]
    fresh = wait_until(lambda: (r := _export(c, seeded)).status_code == 202 and r, timeout=20,
                       message="a new export of the case")
    assert locked["id"] == stuck
    row = cstore.get_export(stuck)
    assert row["status"] == "failed" and row["detail"] == {"code": "interrupted"} and "descartó" in row["error"]
    assert _wait_done(c, wait_until, fresh.json()["export_id"])["status"] == "succeeded"


def test_requests_that_could_never_build_are_refused_at_once(login_as, seeded):
    c = login_as("viewer")
    assert _export(c, seeded, scope="audit").status_code == 422  # no seq
    assert _export(c, seeded, scope="audit", seq="A09").json()["error"]["code"] == "not_found"
    unsealed = _export(c, seeded, scope="audit", seq="A02")
    assert unsealed.status_code == 409 and unsealed.json()["error"]["code"] == "not_sealed"
    assert c.get("/api/v1/exports/999").status_code == 404


def test_a_broken_seal_fails_the_build_naming_the_file(login_as, seeded, wait_until):
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    report.write_text(report.read_text(encoding="utf-8") + "\nalterado", encoding="utf-8")
    c = login_as("viewer")
    row = _wait_done(c, wait_until, _export(c, seeded).json()["export_id"])
    assert row["status"] == "failed" and row["detail"]["code"] == "seal_broken" and report.name in row["error"]
    assert c.get(f"/api/v1/exports/{row['id']}/download").status_code == 410
    log = login_as("admin").get("/api/v1/system/audit-log").json()["items"]
    assert any(e["action"] == "export_failed" and e["detail"]["code"] == "seal_broken" for e in log)


def test_builds_a_restart_interrupted_end_failed_and_leave_no_partial_file(cstore, store, settings, seeded, tmp_path):
    """Review Focus: the server stops while a ZIP is being built."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    building = cstore.create_export(case_id=seeded["case_id"], scope="case", seq=None, include_unsealed=False,
                                    created_by="vera")
    cstore.update_export(building["id"], status="building", files_total=10, files_done=3)
    queued = cstore.create_export(case_id=seeded["case_id"], scope="case", seq=None, include_unsealed=False,
                                  created_by="vera")
    (exports_dir / "GhostRecon_acme_case_20261004-1530.zip.part").write_bytes(b"PK\x03\x04 a medias")
    service = ExportService(cstore, store, settings, exports_dir=exports_dir)
    service.start()  # what the lifespan of a new server calls first
    service.stop()
    for export_id in (building["id"], queued["id"]):
        row = cstore.get_export(export_id)
        assert row["status"] == "failed" and row["detail"] == {"code": "interrupted"} and "reinici" in row["error"]
    assert list(exports_dir.iterdir()) == []


def test_stop_aborts_a_build_in_flight_and_nothing_is_left_behind(cstore, store, settings, seeded, tmp_path,
                                                                  monkeypatch):
    """stop() really stops: the running build fails as interrupted, no .part/.zip stays, and no download until done."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    packing, real_build = threading.Event(), exporter.build

    def slow_build(*args, progress=None, **kwargs):
        def slow_progress(done, total):
            packing.set()
            time.sleep(1)  # a large archive: the worker is still packing when the server stops
            progress(done, total)
        return real_build(*args, progress=slow_progress, **kwargs)
    monkeypatch.setattr(exporter, "build", slow_build)
    service = ExportService(cstore, store, settings, exports_dir=exports_dir)
    service.start()
    principal = Principal(user_id=1, username="vera", role="viewer", via="session")
    row = service.request(store.get_case(seeded["case_id"]), scope="case", seq=None, include_unsealed=False,
                          principal=principal)
    assert packing.wait(30)
    assert service.file_path(cstore.get_export(row["id"])) is None  # not finished: nothing to serve
    started = time.monotonic()
    service.stop()
    assert time.monotonic() - started < 25 and service._thread is None
    done = cstore.get_export(row["id"])
    assert done["status"] == "failed" and done["detail"] == {"code": "interrupted"} and "reinici" in done["error"]
    assert list(exports_dir.iterdir()) == []


def test_only_plain_names_inside_the_exports_folder_are_served(cstore, store, settings, tmp_path):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    (tmp_path / "secret.zip").write_bytes(b"x")
    (exports_dir / "ok.zip").write_bytes(b"x")
    service = ExportService(cstore, store, settings, exports_dir=exports_dir)
    served = lambda name: service.file_path({"status": "succeeded", "file_name": name})
    assert served("ok.zip") == exports_dir / "ok.zip"
    for bad in ("../secret.zip", "..\\secret.zip", str(tmp_path / "secret.zip"), "..", "."):
        assert served(bad) is None
