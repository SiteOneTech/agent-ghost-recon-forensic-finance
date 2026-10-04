"""Job runner with the fake agent: states, session, phase, result and events land in the DB; the stored argv is what
runs; a cancel always wins over the runner's final write; the detached tree dies whole, on each OS."""
import json
import os
import subprocess
import sys
import threading

import pytest

from plugins.ghost_recon.console import jobfiles, procs
from plugins.ghost_recon.console.commands import agent_args
from plugins.ghost_recon.console.events import Normalizer
from plugins.ghost_recon.console.job_runner import SELF_CHECK, Runner
from plugins.ghost_recon.console.procs import RUNNER_MODULE


@pytest.fixture
def evidence(case_root):
    folder = case_root / "Caso Runner"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder


def _job(cstore, folder, hermes, command="new-open-case"):
    folder = folder.resolve()  # what commands.plan stores
    argv = hermes(agent_args(command, f'/{command} "{folder}"', ["-p", "default"]))
    return cstore.create_job(command=command, folder=str(folder), args={}, argv=argv, launched_by="jean")


def _run(cstore, store, job_id):
    return Runner(job_id, cstore=cstore, store=store, base=jobfiles.jobs_dir(), poll=0.05).run()


def _with_agent(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["pid"] else None


def test_runner_records_session_phase_result_events_and_the_case(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent({"steps": 3}))
    assert _run(cstore, store, job["id"]) == "succeeded"
    row = cstore.get_job(job["id"])
    case = store.get_case(str(evidence.resolve()))
    assert row["exit_code"] == 0 and row["case_id"] == case["id"]
    assert row["tokens"]["total"] > 0 and row["result_text"] and row["finished_at"]
    replay = Normalizer()
    for line in jobfiles.raw_path(jobfiles.jobs_dir(), job["id"]).read_text(encoding="utf-8").splitlines():
        replay.feed_line(line)
    assert (row["phase"], row["session_id"]) == (replay.phase, replay.session_id)  # the DB mirrors the stream
    events, _ = jobfiles.read_events(jobfiles.events_path(jobfiles.jobs_dir(), job["id"]))
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)) and events[-1]["kind"] == "result"
    finished = [e for e in store.list_events(case["id"]) if e["event_type"] == "console_job_finished"]
    assert finished and finished[-1]["actor"] == "jean"


def test_a_failed_agent_keeps_its_exit_code_and_error(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent({"exit_code": 3, "error": "proveedor sin cuota"}))
    assert _run(cstore, store, job["id"]) == "failed"
    row = cstore.get_job(job["id"])
    assert row["exit_code"] == 3 and "proveedor sin cuota" in row["error"]


def test_an_agent_without_a_result_record_fails(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent({"no_result": True}))
    assert _run(cstore, store, job["id"]) == "failed"
    assert "resultado final" in cstore.get_job(job["id"])["error"]


def test_the_runner_executes_exactly_the_stored_argv(cstore, store, evidence, fake_agent, tmp_path):
    record = tmp_path / "argv.json"
    job = _job(cstore, evidence, fake_agent({"record_argv": str(record)}))
    _run(cstore, store, job["id"])
    assert json.loads(record.read_text(encoding="utf-8")) == cstore.get_job(job["id"])["argv"][1:]


def test_a_job_cancelled_before_it_starts_never_launches_the_agent(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent())
    cstore.update_job(job["id"], status="cancelled")
    assert _run(cstore, store, job["id"]) == "cancelled"
    assert not jobfiles.raw_path(jobfiles.jobs_dir(), job["id"]).exists()


def test_a_cancel_wins_over_the_runner_final_write(cstore, store, evidence, fake_agent, wait_until):  # Review Focus 4
    job = _job(cstore, evidence, fake_agent({"steps": 400, "delay": 0.05}))
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(status=_run(cstore, store, job["id"])))
    worker.start()
    row = wait_until(lambda: _with_agent(cstore, job["id"]), message="agent started")
    assert cstore.update_job(job["id"], status="cancelled", error="cancelada por jean")
    worker.join(timeout=60)
    assert outcome["status"] == "cancelled"
    final = cstore.get_job(job["id"])
    assert (final["status"], final["error"]) == ("cancelled", "cancelada por jean")
    assert not procs.alive(row["pid"], row["pid_started"])


def test_the_runner_module_runs_a_job_to_completion(cstore, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent())
    r = subprocess.run([sys.executable, "-m", RUNNER_MODULE, str(job["id"]), "--poll", "0.05"],
                       cwd=procs.hermes_root(), env=procs.child_env(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert cstore.get_job(job["id"])["status"] == "succeeded"


def test_runner_entry_point_runs_through_this_installation_launcher():
    r = subprocess.run(procs.hermes_command(["--self-check"], module=RUNNER_MODULE), env=procs.child_env(),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    assert SELF_CHECK in r.stdout


def test_identity_guards_against_recycled_pids():
    me = os.getpid()
    assert procs.alive(me, procs.identity(me))
    assert not procs.alive(me, procs.identity(me) + 100)
    assert not procs.alive(None, None) and not procs.kill_tree(None, None)


def _hanging_tree(cstore, folder, fake_agent, wait_until):
    """A detached runner whose fake agent spawned a sleeping grandchild; returns (runner Popen, agent, grandchild)."""
    job = _job(cstore, folder, fake_agent({"hang": True}))
    runner = procs.spawn_detached([sys.executable, "-m", RUNNER_MODULE, str(job["id"]), "--poll", "0.05"],
                                  cwd=procs.hermes_root(), env=procs.child_env())
    raw = jobfiles.raw_path(jobfiles.jobs_dir(), job["id"])

    def grandchild():
        lines = raw.read_text(encoding="utf-8").splitlines() if raw.exists() else []
        hang = [json.loads(line) for line in lines if '"tool_call_id": "hang"' in line]
        return hang[0]["input"]["pid"] if hang else None

    pid = wait_until(grandchild, message="the fake agent's grandchild")
    agent = wait_until(lambda: _with_agent(cstore, job["id"]), message="agent pid")["pid"]
    return runner, agent, pid


def _kill_and_check(runner, agent, grandchild, wait_until):
    assert procs.kill_tree(runner.pid, procs.identity(runner.pid))
    wait_until(lambda: not any(procs.alive(p, None) for p in (runner.pid, agent, grandchild)),
               message="the whole tree gone")
    runner.wait(timeout=30)


@pytest.mark.platforms("posix")
def test_the_detached_runner_leads_its_session_and_dies_with_its_tree_posix(cstore, evidence, fake_agent, wait_until):
    runner, agent, grandchild = _hanging_tree(cstore, evidence, fake_agent, wait_until)
    assert os.getsid(runner.pid) == runner.pid  # start_new_session: a server restart cannot signal it
    _kill_and_check(runner, agent, grandchild, wait_until)


@pytest.mark.platforms("windows")
def test_the_detached_runner_dies_with_its_tree_windows(cstore, evidence, fake_agent, wait_until):
    runner, agent, grandchild = _hanging_tree(cstore, evidence, fake_agent, wait_until)
    _kill_and_check(runner, agent, grandchild, wait_until)
