"""The job-end notice (spec §6.2, C10): the server plans the ``hermes send`` argv at launch, the runner sends it with a
summary when the job ends, an empty target sends nothing, and a failed notice never changes the job."""
import json
import logging
import time
from dataclasses import replace

import psutil

from plugins.ghost_recon.console import job_runner, jobfiles, procs
from plugins.ghost_recon.console.auth import Principal
from plugins.ghost_recon.console.commands import NOTIFY_SUBJECT, LaunchRequest, agent_args, notify_args
from plugins.ghost_recon.console.job_runner import Runner, notify_message

ADMIN = Principal(1, "jean", "admin", "session")
SECRET = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def _folder(case_root, name):
    folder = case_root / name
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder.resolve()


def _job(cstore, folder, hermes, target="telegram"):
    """A job as JobService.launch stores it: the agent argv and the notice argv, both through ``hermes``."""
    argv = hermes(agent_args("new-open-case", f'/new-open-case "{folder}"', ["-p", "default"]))
    notify = hermes(notify_args(target, ["-p", "default"])) if target else []
    return cstore.create_job(command="new-open-case", folder=str(folder), args={}, argv=argv, launched_by="jean",
                             notify_target=target or None, notify_argv=notify)


def _run(cstore, store, job_id):
    return Runner(job_id, cstore=cstore, store=store, base=jobfiles.jobs_dir(), poll=0.05).run()


def test_the_runner_sends_the_planned_notice_with_a_summary(cstore, store, case_root, fake_agent, tmp_path):
    record = tmp_path / "send.json"
    job = _job(cstore, _folder(case_root, "Caso Aviso"), fake_agent({"record_send": str(record)}))
    assert _run(cstore, store, job["id"]) == "succeeded"
    sent = json.loads(record.read_text(encoding="utf-8"))
    assert sent[:-1] == job["notify_argv"][1:]  # exactly the planned argv (the fake drops the interpreter) ...
    assert sent[-6:-1] == ["send", "--to", "telegram", "--subject", NOTIFY_SUBJECT]
    message = sent[-1]  # ... plus the summary as the message
    case = store.get_case(cstore.get_job(job["id"])["case_id"])
    assert message.startswith(f"Ejecución #{job['id']}") and "terminó" in message and case["name"] in message


def test_a_failed_job_is_notified_with_its_reason(cstore, store, case_root, fake_agent, tmp_path):
    record = tmp_path / "send.json"
    hermes = fake_agent({"record_send": str(record), "exit_code": 3, "error": f"401 con la clave {SECRET}"})
    job = _job(cstore, _folder(case_root, "Caso Falla"), hermes)
    assert _run(cstore, store, job["id"]) == "failed"
    message = json.loads(record.read_text(encoding="utf-8"))[-1]
    assert "falló" in message and "401" in message and SECRET not in message  # redacted like every console view


def test_a_notice_that_fails_never_changes_the_job(cstore, store, case_root, fake_agent, tmp_path, caplog):
    job = _job(cstore, _folder(case_root, "Caso Sin Aviso"), fake_agent({"send_exit_code": 1}))
    with caplog.at_level(logging.WARNING):
        assert _run(cstore, store, job["id"]) == "succeeded"
    assert "hermes send exited 1" in caplog.text
    broken = _job(cstore, _folder(case_root, "Caso Sin Ejecutable"), fake_agent())
    cstore.conn.execute("UPDATE console_jobs SET notify_argv=? WHERE id=?",
                        (json.dumps([str(tmp_path / "no-such-hermes")]), broken["id"]))
    cstore.conn.commit()
    assert _run(cstore, store, broken["id"]) == "succeeded"


def test_launch_plans_the_notice_only_when_a_target_is_configured(make_jobs, settings, case_root):
    quiet = make_jobs().launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Mudo"))), ADMIN)
    assert quiet["notify_target"] is None and quiet["notify_argv"] == []
    jobs = make_jobs(config=replace(settings, notify_target="telegram:-1001234567890"))
    loud = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Ruidoso"))), ADMIN)
    assert loud["notify_target"] == "telegram:-1001234567890"
    assert loud["notify_argv"] == jobs.hermes_command(notify_args("telegram:-1001234567890", procs.profile_args()))


def test_operator_text_never_becomes_an_attachment_directive():
    job = {"id": 7, "command": "rerun-case", "folder": "/casos/MEDIA:/etc/passwd"}
    case = {"id": "GRC-x-20261004", "name": "Caso MEDIA:/home/ghostrecon/.hermes/.env"}
    message = notify_message(job, "failed", case, {"id": "GRC-x-20261004/A02", "status": "open"},
                             "falló al leer MEDIA:C:/secretos.txt")
    assert "MEDIA:" not in message.upper()
    assert message.startswith("Ejecución #7 · Re-run · falló") and "A02 (open)" in message
    no_case = notify_message({**job, "id": 8, "folder": "/casos/MEDIA:informe"}, "succeeded", {}, None, None)
    assert "MEDIA:" not in no_case.upper() and "informe" in no_case  # the folder name, neutralised


def _senders(config_marker):
    return [p for p in psutil.process_iter(["cmdline"]) if config_marker in " ".join(p.info["cmdline"] or [])]


def test_a_notice_that_outlives_its_timeout_is_stopped_and_never_hangs_the_runner(
        cstore, store, case_root, fake_agent, monkeypatch, caplog):
    monkeypatch.setattr(job_runner, "NOTIFY_TIMEOUT_S", 1)
    hermes = fake_agent({"send_sleep_s": 60})
    job = _job(cstore, _folder(case_root, "Caso Lento"), hermes)
    marker = job["notify_argv"][2]  # the fake-agent config path: identifies its sender process
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        assert _run(cstore, store, job["id"]) == "succeeded"
    assert time.monotonic() - started < 30  # the sender sleeps 60 s: the runner did not wait for it
    assert "timed out" in caplog.text and cstore.get_job(job["id"])["status"] == "succeeded"
    assert not [p for p in _senders(marker) if "send" in p.info["cmdline"]]


def test_a_store_error_while_building_the_notice_leaves_the_job_alone(cstore, store, case_root, fake_agent, monkeypatch,
                                                                      caplog):
    job = _job(cstore, _folder(case_root, "Caso Tienda"), fake_agent())
    monkeypatch.setattr(store, "list_audits", lambda *_: (_ for _ in ()).throw(RuntimeError("disco lleno")))
    with caplog.at_level(logging.WARNING):
        assert _run(cstore, store, job["id"]) == "succeeded"
    assert "disco lleno" in caplog.text and cstore.get_job(job["id"])["status"] == "succeeded"
