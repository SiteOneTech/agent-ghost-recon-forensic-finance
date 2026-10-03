"""Audit endpoints: seal-check cache, tamper detection and deliverable downloads (role + path containment)."""
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


def _url(seeded, seq):
    return f"/api/v1/cases/{seeded['case_id']}/audits/{seq}"


def test_audit_detail_includes_completion_checks(login_as, seeded):
    d = login_as("viewer").get(_url(seeded, "A01")).json()
    assert d["status"] == "sealed" and {"manifest", "report_md", "validation"} <= set(d["completion"]["checks"])
    assert login_as("viewer").get(_url(seeded, "Z99")).status_code == 404


def test_verify_caches_ok_and_flips_the_case_seal_state(login_as, seeded):
    c = login_as("viewer")
    r = c.post(_url(seeded, "A01") + "/verify")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert c.get("/api/v1/cases").json()["items"][0]["seal_state"] == "ok"
    assert c.get(_url(seeded, "A01")).json()["seal_check"]["ok"] is True


def test_tampered_sealed_file_is_reported_as_broken(login_as, seeded):
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    report.write_text(report.read_text(encoding="utf-8") + "\nalterado", encoding="utf-8")
    c = login_as("viewer")
    body = c.post(_url(seeded, "A01") + "/verify").json()
    assert body["ok"] is False and any(p.startswith("06_Report/") for p in body["detail"]["modified"])
    assert c.get("/api/v1/cases").json()["items"][0]["seal_state"] == "broken"


def test_verifying_an_open_audit_is_409(login_as, seeded):
    r = login_as("viewer").post(_url(seeded, "A02") + "/verify")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_sealed"


def test_viewer_downloads_sealed_reports_and_bytes_match_the_registered_hash(login_as, seeded):
    c = login_as("viewer")
    reports = c.get(_url(seeded, "A01") + "/reports").json()["items"]
    rep = next(r for r in reports if r["format"] == "md")
    r = c.get(_url(seeded, "A01") + f"/reports/{rep['id']}/download")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert hashlib.sha256(r.content).hexdigest() == rep["sha256"]


def test_open_audit_deliverables_are_admin_only(login_as, seeded):
    url = _url(seeded, "A02")
    rep = login_as("admin").get(url + "/reports").json()["items"][0]
    viewer = login_as("viewer").get(url + f"/reports/{rep['id']}/download")
    assert viewer.status_code == 403 and viewer.json()["error"]["code"] == "not_sealed"
    assert login_as("admin").get(url + f"/reports/{rep['id']}/download").status_code == 200


def test_a_report_row_pointing_at_evidence_is_never_served(login_as, seeded, store):
    evidence_file = seeded["root"] / "Bancos" / "extracto_2026-01.txt"
    rid = store.list_reports(seeded["a1"])[0]["id"]
    store.conn.execute("UPDATE reports SET path=? WHERE id=?", (str(evidence_file), rid))
    store.conn.commit()
    r = login_as("admin").get(_url(seeded, "A01") + f"/reports/{rid}/download")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_missing"


def test_a_registered_report_whose_file_was_deleted_is_404(login_as, seeded, store):
    rep = store.list_reports(seeded["a2"])[0]
    Path(rep["path"]).unlink()
    r = login_as("admin").get(_url(seeded, "A02") + f"/reports/{rep['id']}/download")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_missing"


def test_bearer_tokens_skip_csrf_but_keep_their_role(app, auth, users, seeded):
    raw, _ = auth.create_api_token("vera", "webapp")
    with TestClient(app, base_url="http://localhost") as c:
        c.headers["Authorization"] = f"Bearer {raw}"
        assert c.post(_url(seeded, "A01") + "/verify").status_code == 200  # no CSRF header needed
        assert c.get("/api/v1/system/audit-log").status_code == 403  # viewer token on an admin route


def test_downloads_and_verifications_are_audited(login_as, seeded):
    c = login_as("admin")
    c.post(_url(seeded, "A01") + "/verify")
    rep = c.get(_url(seeded, "A01") + "/reports").json()["items"][0]
    c.get(_url(seeded, "A01") + f"/reports/{rep['id']}/download")
    actions = {e["action"] for e in c.get("/api/v1/system/audit-log").json()["items"]}
    assert {"seal_verify", "report_download"} <= actions
