"""Folder endpoints: viewer-readable, jailed to case_roots, and a plain explanation when no root is configured."""
import hashlib
from dataclasses import replace


def test_roots_list_search_and_inspect_for_a_viewer(login_as, seeded, case_root):
    c = login_as("viewer")
    roots = c.get("/api/v1/fs/roots").json()
    assert [r["path"] for r in roots["items"]] == [str(case_root.resolve())] and roots["configured"]
    assert roots["items"][0]["free_bytes"] > 0
    listing = c.get("/api/v1/fs/list", params={"path": roots["items"][0]["path"]}).json()
    demo = next(i for i in listing["items"] if i["name"] == "demo-case")
    assert demo["case"]["id"] == seeded["case_id"] and demo["case"]["sealed"] == 1 and demo["files"] > 0
    assert [f["path"] for f in c.get("/api/v1/fs/search", params={"q": "DEMO"}).json()["items"]] == [demo["path"]]
    info = c.get("/api/v1/fs/inspect", params={"path": demo["path"]}).json()
    assert info["context"]["sha256"] == hashlib.sha256((seeded["root"] / "context.md").read_bytes()).hexdigest()
    assert info["case"]["id"] == seeded["case_id"] and info["suggested_command"] == "rerun-case"
    assert sum(t["count"] for t in info["by_type"]) == info["files"]


def test_paths_outside_the_roots_or_with_traversal_are_rejected(login_as, gr_env, case_root):
    c = login_as("viewer")
    outside = c.get("/api/v1/fs/list", params={"path": str(gr_env / "db")})
    assert outside.status_code == 403 and outside.json()["error"]["code"] == "outside_roots"
    traversal = c.get("/api/v1/fs/inspect", params={"path": str(case_root) + "/../db"})
    assert traversal.status_code == 422 and traversal.json()["error"]["code"] == "bad_path"
    assert c.get("/api/v1/fs/search", params={"q": "a"}).json()["error"]["code"] == "bad_query"


def test_the_folder_browser_requires_login(client, case_root):
    assert client.get("/api/v1/fs/roots").status_code == 401
    assert client.get("/api/v1/fs/list", params={"path": str(case_root)}).status_code == 401


def test_without_case_roots_the_console_names_the_missing_setting(store, cstore, auth, settings, make_jobs, login_on):
    from plugins.ghost_recon.console.app import create_app
    bare = replace(settings, case_roots=())
    c = login_on(create_app(bare, store, cstore, auth=auth, jobs=make_jobs(config=bare)), "admin")
    roots = c.get("/api/v1/fs/roots").json()
    assert roots["items"] == [] and not roots["configured"] and "case_roots" in roots["hint"]
    listing = c.get("/api/v1/fs/list", params={"path": "/"})
    assert listing.status_code == 409 and listing.json()["error"]["code"] == "no_case_roots"
    preview = c.post("/api/v1/jobs/preview", json={"command": "new-open-case", "folder": "/x"})
    assert preview.status_code == 409 and preview.json()["error"]["code"] == "no_case_roots"
    doctor = c.get("/api/v1/system/doctor").json()
    assert not doctor["ok"] and any(ch["check"] == "console.case_roots" and not ch["ok"] for ch in doctor["checks"])


def test_the_doctor_reports_each_case_root(login_as, case_root):
    body = login_as("viewer").get("/api/v1/system/doctor").json()
    roots = [ch for ch in body["checks"] if ch["check"].startswith("console.case_roots")]
    assert len(roots) == 1 and roots[0]["ok"] and body["console"]["case_roots"] == [str(case_root)]
