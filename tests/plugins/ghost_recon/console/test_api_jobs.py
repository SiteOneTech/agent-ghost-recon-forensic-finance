"""Job endpoints: role gates, the preview is what runs, live events (JSON and SSE), cancel, log, Home counters."""
import json
from dataclasses import replace

from plugins.ghost_recon.console.events import PHASES
from plugins.ghost_recon.console.store import TERMINAL_STATUSES


def _folder(case_root, name):
    folder = case_root / name
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder


def _finished(client, job_id):
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    return job if job["status"] in TERMINAL_STATUSES else None


def test_a_viewer_cannot_preview_launch_or_cancel(login_as, case_root):
    c = login_as("viewer")
    body = {"command": "new-open-case", "folder": str(_folder(case_root, "Caso Visor"))}
    for url in ("/api/v1/jobs/preview", "/api/v1/jobs", "/api/v1/jobs/1/cancel"):
        r = c.post(url, json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_the_preview_is_exactly_what_the_launch_runs(login_as, case_root, argv_record, store,
                                                     wait_until):  # Review Focus 2
    c = login_as("admin")
    body = {"command": "new-open-case", "folder": str(_folder(case_root, "Caso Logística Norte")),
            "name": "Logística Norte", "currency": "usd", "lang": "es", "notes": "Declaración del gerente."}
    preview = c.post("/api/v1/jobs/preview", json=body).json()
    launched = c.post("/api/v1/jobs", json=body)
    assert launched.status_code == 202
    job = launched.json()["job"]
    assert job["argv"] == preview["argv"] and job["display"] == preview["display"]
    done = wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    assert done["status"] == "succeeded" and done["case_id"]
    assert json.loads(argv_record.read_text(encoding="utf-8")) == job["argv"][1:]  # what the agent received
    evidence = store.list_evidence(done["case_id"])
    assert evidence and not any("_console" in e["path"] or e["path"].startswith("GhostRecon_Audits")
                                for e in evidence)  # the combined context never becomes evidence


def test_events_json_and_sse_agree_and_a_reconnect_resumes(login_as, case_root, wait_until):  # Review Focus 5
    c = login_as("admin")
    folder = str(_folder(case_root, "Caso SSE"))
    job = c.post("/api/v1/jobs", json={"command": "new-open-case", "folder": folder}).json()["job"]
    wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    items = c.get(f"/api/v1/jobs/{job['id']}/events").json()["items"]
    seqs = [e["seq"] for e in items]
    assert seqs == list(range(1, len(seqs) + 1)) and items[-1]["kind"] == "result"
    tail = c.get(f"/api/v1/jobs/{job['id']}/events", params={"after": seqs[-2]}).json()
    assert [e["seq"] for e in tail["items"]] == [seqs[-1]] and tail["last_seq"] == seqs[-1]

    def stream(headers=None):
        with c.stream("GET", f"/api/v1/jobs/{job['id']}/events/stream", headers=headers or {}) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            text = "".join(r.iter_text())
        return [int(line[4:]) for line in text.splitlines() if line.startswith("id: ")], text

    ids, text = stream()
    assert ids == seqs and "event: status" in text and "event: end" in text
    resumed, _ = stream({"Last-Event-ID": str(seqs[2])})
    assert resumed == seqs[3:]


def test_a_finished_job_offers_terminal_and_chat_resume(store, cstore, auth, settings, make_jobs, login_on, case_root,
                                                        wait_until):
    from plugins.ghost_recon.console.app import create_app
    with_chat = replace(settings, dashboard_url="http://127.0.0.1:9119")
    c = login_on(create_app(with_chat, store, cstore, auth=auth, jobs=make_jobs(config=with_chat)), "admin")
    folder = str(_folder(case_root, "Caso Chat"))
    job = c.post("/api/v1/jobs", json={"command": "new-open-case", "folder": folder}).json()["job"]
    done = wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    sid = done["session_id"]
    assert sid and done["resume"]["terminal"].split()[-2:] == ["--resume", sid]
    assert done["resume"]["chat_url"] == f"http://127.0.0.1:9119/chat?resume={sid}"
    assert done["progress"]["evidence"] >= 1 and done["tokens"]["total"] > 0 and done["result_text"]
    assert [p["id"] for p in done["phases"]] == [p for p, _ in PHASES]


def test_home_counts_active_jobs_and_cancel_stops_them(login_as, case_root, wait_until):
    c = login_as("admin")
    job = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                       "folder": str(_folder(case_root, "hang-case"))}).json()["job"]
    wait_until(lambda: c.get(f"/api/v1/jobs/{job['id']}").json()["session_id"], message="agent init")
    overview = c.get("/api/v1/system/overview").json()
    assert overview["kpis"]["jobs_active"] == 1 and [j["id"] for j in overview["active_jobs"]] == [job["id"]]
    cancelled = c.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["job"]["status"] == "cancelled"
    again = c.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_active"
    assert c.get("/api/v1/system/overview").json()["kpis"]["jobs_active"] == 0


def test_job_lists_case_jobs_timeline_and_log(login_as, seeded, store, wait_until):
    c = login_as("admin")
    job = c.post("/api/v1/jobs", json={"command": "rerun-case", "folder": str(seeded["root"])}).json()["job"]
    assert job["case_id"] == seeded["case_id"]
    wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    assert [j["id"] for j in c.get(f"/api/v1/cases/{seeded['case_id']}/jobs").json()["items"]] == [job["id"]]
    assert c.get("/api/v1/jobs", params={"status": "active"}).json()["items"] == []
    done = c.get("/api/v1/jobs", params={"status": "succeeded", "case": seeded["case_id"]}).json()["items"]
    assert [j["id"] for j in done] == [job["id"]]
    assert c.get("/api/v1/jobs", params={"status": "nope"}).status_code == 422
    assert "session_id: fake-" in c.get(f"/api/v1/jobs/{job['id']}/log").json()["log"]
    kinds = {e["event_type"] for e in store.list_events(seeded["case_id"])}
    assert {"console_job_launched", "console_job_finished"} <= kinds


def test_conflicts_come_back_as_plain_409s(login_as, seeded):
    r = login_as("admin").post("/api/v1/jobs/preview", json={"command": "new-open-case",
                                                             "folder": str(seeded["root"])})
    assert r.status_code == 409 and r.json()["error"]["code"] == "use_rerun" and "Re-run" in r.json()["error"]["message"]


def test_unknown_jobs_are_404(login_as):
    c = login_as("viewer")
    assert c.get("/api/v1/jobs/999").json()["error"]["code"] == "not_found"
    assert c.get("/api/v1/jobs/999/events").status_code == 404
