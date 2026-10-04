"""Job endpoints: role gates, the preview is what runs, live events (JSON and SSE), cancel, log, Home counters."""
import json
import shlex
from dataclasses import replace

import pytest

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


def test_a_context_md_changed_after_the_preview_is_refused(login_as, case_root, cstore):
    c = login_as("admin")
    folder = _folder(case_root, "Caso Contexto")
    (folder / "context.md").write_bytes(b"uno\n")
    body = {"command": "new-open-case", "folder": str(folder), "notes": "nota"}
    reviewed = c.post("/api/v1/jobs/preview", json=body).json()["original_context"]["sha256"]
    (folder / "context.md").write_bytes(b"dos\n")  # edited after the operator reviewed it
    r = c.post("/api/v1/jobs", json={**body, "context_sha256": reviewed})
    assert r.status_code == 409 and r.json()["error"]["code"] == "context_changed"
    assert "revísalo" in r.json()["error"]["message"]
    bare = _folder(case_root, "Caso Sin Contexto")
    assert c.post("/api/v1/jobs/preview", json={**body, "folder": str(bare)}).json()["original_context"] is None
    (bare / "context.md").write_bytes(b"nuevo\n")  # appeared after a preview that had none
    r = c.post("/api/v1/jobs", json={**body, "folder": str(bare), "context_sha256": "none"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "context_changed"
    assert cstore.list_jobs() == []


def test_an_unchanged_context_md_launches(login_as, case_root, wait_until):
    c = login_as("admin")
    folder = _folder(case_root, "Caso Mismo Contexto")
    (folder / "context.md").write_bytes(b"uno\n")
    bare = _folder(case_root, "Caso Nunca Contexto")
    launched = []
    for target in (folder, bare):
        body = {"command": "new-open-case", "folder": str(target), "notes": "nota"}
        preview = c.post("/api/v1/jobs/preview", json=body).json()
        reviewed = (preview["original_context"] or {}).get("sha256") or "none"
        r = c.post("/api/v1/jobs", json={**body, "context_sha256": reviewed})
        assert r.status_code == 202 and r.json()["job"]["context_file"] == preview["context_file"]
        launched.append(r.json()["job"]["id"])
    for job_id in launched:
        wait_until(lambda: _finished(c, job_id), timeout=60, message="job end")


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


ODD_SESSION = 'sesión "rara" 2026'


def _resume_command(login_as, cstore, case_root):
    job = cstore.create_job(command="new-open-case", folder=str(_folder(case_root, "Caso Sesión")), args={},
                            argv=["hermes"], launched_by="jean")
    cstore.update_job(job["id"], status="succeeded", session_id=ODD_SESSION)
    return login_as("viewer").get(f"/api/v1/jobs/{job['id']}").json()["resume"]["terminal"]


@pytest.mark.platforms("posix")
def test_the_resume_command_quotes_the_session_id_posix(login_as, cstore, case_root):
    assert shlex.split(_resume_command(login_as, cstore, case_root))[-2:] == ["--resume", ODD_SESSION]


@pytest.mark.platforms("windows")
def test_the_resume_command_quotes_the_session_id_windows(login_as, cstore, case_root):
    import ctypes
    count = ctypes.c_int()
    to_argv = ctypes.windll.shell32.CommandLineToArgvW
    to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    parsed = to_argv(_resume_command(login_as, cstore, case_root), ctypes.byref(count))
    assert [parsed[i] for i in range(count.value)][-2:] == ["--resume", ODD_SESSION]


def test_the_job_list_pages_with_a_working_cursor(login_as, cstore, case_root):
    folder = str(_folder(case_root, "Caso Páginas"))
    ids = [cstore.create_job(command="new-open-case", folder=folder, args={}, argv=["x"], launched_by="jean")["id"]
           for _ in range(3)]
    for job_id in ids:
        cstore.update_job(job_id, status="succeeded")
    c = login_as("viewer")
    first = c.get("/api/v1/jobs", params={"limit": 2}).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    rest = c.get("/api/v1/jobs", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert rest["next_cursor"] is None
    assert [j["id"] for j in first["items"] + rest["items"]] == sorted(ids, reverse=True)  # newest first, no gaps
    assert c.get("/api/v1/jobs", params={"cursor": "abc"}).status_code == 422
    assert c.get("/api/v1/jobs", params={"cursor": "9" * 20}).status_code == 422  # would overflow SQLite INTEGER


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


def _read_stream(client, job_id, *, headers=None, params=None, limit=60.0):
    """Frames of the SSE stream until it ends; the deadline keeps a broken stream from hanging the suite."""
    import time
    deadline = time.monotonic() + limit
    text = []
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events/stream", headers=headers or {},
                       params=params or {}) as r:
        assert r.status_code == 200
        for chunk in r.iter_text():
            text.append(chunk)
            assert time.monotonic() < deadline, "stream did not end in time"
            if "event: end" in "".join(text):
                break
    joined = "".join(text)
    return [int(line[4:]) for line in joined.splitlines() if line.startswith("id: ")], joined


def test_a_live_stream_delivers_every_event_through_result_before_end(login_as, case_root):
    c = login_as("admin")
    job = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                       "folder": str(_folder(case_root, "Caso Vivo"))}).json()["job"]
    ids, text = _read_stream(c, job["id"])  # opened right away: the job is still running
    assert ids and ids == list(range(1, len(ids) + 1))
    assert '"kind": "result"' in text and text.index('"kind": "result"') < text.index("event: end")
    assert ids == [e["seq"] for e in c.get(f"/api/v1/jobs/{job['id']}/events").json()["items"]]


def test_stream_after_parameter_and_non_ascii_last_event_id(login_as, case_root, wait_until):
    c = login_as("admin")
    job = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                       "folder": str(_folder(case_root, "Caso Despues"))}).json()["job"]
    wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    everything, _ = _read_stream(c, job["id"])
    assert _read_stream(c, job["id"], params={"after": everything[1]})[0] == everything[2:]
    assert _read_stream(c, job["id"], headers={"Last-Event-ID": "\u00b2".encode("latin-1")})[0] == everything  # not a 500


SECRET = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def test_secrets_in_logs_errors_and_events_never_reach_viewers(login_as, cstore, case_root, jobs):  # spec §9
    from plugins.ghost_recon.console import jobfiles
    job = cstore.create_job(command="new-open-case", folder=str(_folder(case_root, "Caso Secreto")), args={},
                            argv=["hermes"], launched_by="jean")
    cstore.update_job(job["id"], status="failed", error=f"401 con la clave {SECRET}", result_text=f"usé {SECRET}")
    jobfiles.log_path(jobs.jobs_dir, job["id"]).write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    jobfiles.runner_log_path(jobs.jobs_dir, job["id"]).write_text(f"fallo con {SECRET}\n", encoding="utf-8")
    jobfiles.append_events(jobfiles.events_path(jobs.jobs_dir, job["id"]), [
        {"seq": 1, "ts": "", "kind": "warning", "phase": None, "title": "terminal falló",
         "detail": f"curl -H 'Authorization: Bearer {SECRET}'", "level": "warning"}])
    c = login_as("viewer")
    log = c.get(f"/api/v1/jobs/{job['id']}/log").json()
    seen = [c.get(f"/api/v1/jobs/{job['id']}").text, c.get(f"/api/v1/jobs/{job['id']}/events").text,
            json.dumps(log), _read_stream(c, job["id"])[1]]
    assert all(SECRET not in text for text in seen)
    assert "OPENAI_API_KEY=" in log["log"]  # the line stays readable, only the value is masked
