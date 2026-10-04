"""Deliverables of sealed audits are re-hashed on download: a file that no longer matches its seal is refused by name
(409 hash_mismatch) and every refused download is in the console audit log."""
from pathlib import Path


def _url(seeded, seq):
    return f"/api/v1/cases/{seeded['case_id']}/audits/{seq}"


def _denied(login_as):
    log = login_as("admin").get("/api/v1/system/audit-log").json()["items"]
    return [e for e in log if e["action"] == "report_download_denied"]


def test_a_tampered_sealed_deliverable_is_refused_by_name_and_logged(login_as, seeded, store):
    report = next(r for r in store.list_reports(seeded["a1"]) if r["format"] == "md")
    path = Path(report["path"])
    path.write_bytes(path.read_bytes() + b"\nalterado")
    r = login_as("viewer").get(_url(seeded, "A01") + f"/reports/{report['id']}/download")
    assert r.status_code == 409 and r.json()["error"]["code"] == "hash_mismatch"
    assert path.name in r.json()["error"]["message"]
    denied = _denied(login_as)
    assert denied[0]["username"] == "vera" and denied[0]["detail"]["code"] == "hash_mismatch"
    assert denied[0]["detail"]["file"].endswith(path.name)


def test_a_sealed_deliverable_outside_its_seal_or_without_one_is_refused(login_as, seeded, store):
    extra = seeded["a1_folder"] / "06_Report" / "anexo.md"
    extra.write_text("añadido después del sello\n", encoding="utf-8")  # inside the folder, never sealed
    rid = store.add_report(seeded["a1"], "annex_md", str(extra), "md")
    c = login_as("viewer")
    r = c.get(_url(seeded, "A01") + f"/reports/{rid}/download")
    assert r.status_code == 409 and "anexo.md" in r.json()["error"]["message"]
    (seeded["a1_folder"] / "SEALED.json").unlink()
    original = next(x for x in store.list_reports(seeded["a1"]) if x["format"] == "md")
    assert c.get(_url(seeded, "A01") + f"/reports/{original['id']}/download").status_code == 409
    assert {e["detail"]["reason"] for e in _denied(login_as)} == {"not_in_seal", "no_seal_manifest"}


def test_every_refused_download_is_logged_with_its_reason(login_as, seeded, store):
    open_report = store.list_reports(seeded["a2"])[0]
    viewer = login_as("viewer")
    assert viewer.get(_url(seeded, "A02") + f"/reports/{open_report['id']}/download").status_code == 403
    Path(open_report["path"]).unlink()
    assert login_as("admin").get(_url(seeded, "A02") + f"/reports/{open_report['id']}/download").status_code == 404
    assert sorted(e["detail"]["code"] for e in _denied(login_as)) == ["file_missing", "not_sealed"]


def test_an_intact_sealed_deliverable_downloads_with_its_name(login_as, seeded, store):
    report = next(r for r in store.list_reports(seeded["a1"]) if r["format"] == "md")
    r = login_as("viewer").get(_url(seeded, "A01") + f"/reports/{report['id']}/download")
    assert r.status_code == 200 and r.content == Path(report["path"]).read_bytes()
    assert Path(report["path"]).name in r.headers["content-disposition"]
    assert _denied(login_as) == []
