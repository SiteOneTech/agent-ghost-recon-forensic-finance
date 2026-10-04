"""JobService: preview = launched argv, one active job per folder or case plus a global limit, queue, cancel,
orphans (also while the server is the runner's parent) and a job that outlives the service that launched it."""
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import psutil
import pytest

from plugins.ghost_recon.console import procs
from plugins.ghost_recon.console.auth import Principal
from plugins.ghost_recon.console.commands import CommandError, LaunchRequest
from plugins.ghost_recon.console.jobs import JobService
from plugins.ghost_recon.console.store import TERMINAL_STATUSES, ConsoleStore

ADMIN = Principal(1, "jean", "admin", "session")


def sleeper(job_id):
    """Stands in for a runner that stays alive and never writes (limits and queue only)."""
    return [sys.executable, "-c", "import time; time.sleep(120)"]


def _folder(case_root, name):
    folder = case_root / name
    folder.mkdir()
    (folder / "nota.txt").write_text("x", encoding="utf-8")
    return folder


def _done(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["status"] in TERMINAL_STATUSES else None


def _with_agent(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["pid"] else None


def test_the_preview_is_the_argv_the_launch_stores_and_runs(make_jobs, case_root, cstore, wait_until):
    jobs = make_jobs()
    req = LaunchRequest("new-open-case", str(_folder(case_root, "Caso Uno")), notes="El periodo es 2026.")
    preview = jobs.preview(req, "jean")
    job = jobs.launch(req, ADMIN)
    assert job["argv"] == preview["argv"] and preview["display"]
    assert job["context_file"] == preview["context_file"] and Path(job["context_file"]).is_file()
    assert wait_until(lambda: _done(cstore, job["id"]), timeout=60)["status"] == "succeeded"
    assert any(e["action"] == "job_launch" and e["target"] == f"job:{job['id']}" for e in cstore.list_audit_log())


def test_one_active_job_per_folder_and_the_global_limit(make_jobs, settings, seeded, case_root, cstore):
    jobs = make_jobs(runner=sleeper, config=replace(settings, max_parallel_jobs=2))
    rerun = jobs.launch(LaunchRequest("rerun-case", str(seeded["root"])), ADMIN)
    review = jobs.launch(LaunchRequest("review-case", str(seeded["root"])), ADMIN)
    other = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Dos"))), ADMIN)
    third = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Tres"))), ADMIN)

    def status(job):
        return cstore.get_job(job["id"])["status"]

    assert [status(j) for j in (rerun, review, other, third)] == ["running", "queued", "running", "queued"]
    assert "cola" in jobs.queue_note(str(seeded["root"].resolve()))
    row = cstore.get_job(rerun["id"])
    procs.kill_tree(row["runner_pid"], row["runner_started"])
    cstore.update_job(rerun["id"], status="succeeded")  # what the real runner writes when it ends
    jobs.tick()
    assert (status(review), status(third)) == ("running", "queued")  # the folder is free; the global limit is not


def test_the_same_order_twice_on_a_folder_is_409(make_jobs, seeded):
    jobs = make_jobs(runner=sleeper)
    jobs.launch(LaunchRequest("rerun-case", str(seeded["root"])), ADMIN)
    with pytest.raises(CommandError) as err:
        jobs.launch(LaunchRequest("rerun-case", str(seeded["root"])), ADMIN)
    assert (err.value.status, err.value.code) == (409, "already_active")


def test_cancel_a_queued_and_a_running_job(make_jobs, settings, case_root, cstore, fake_agent, wait_until):
    jobs = make_jobs(hermes=fake_agent({"hang": True}), config=replace(settings, max_parallel_jobs=1))
    running = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso A"))), ADMIN)
    queued = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso B"))), ADMIN)
    assert cstore.get_job(queued["id"])["status"] == "queued"
    assert jobs.cancel(queued["id"], ADMIN)["status"] == "cancelled"
    row = wait_until(lambda: _with_agent(cstore, running["id"]), message="agent started")
    assert jobs.cancel(running["id"], ADMIN)["status"] == "cancelled"
    wait_until(lambda: not procs.alive(row["pid"], row["pid_started"])
               and not procs.alive(row["runner_pid"], row["runner_started"]), message="tree stopped")
    with pytest.raises(CommandError) as err:
        jobs.cancel(running["id"], ADMIN)
    assert (err.value.status, err.value.code) == (409, "not_active")
    assert sum(1 for e in cstore.list_audit_log() if e["action"] == "job_cancel") == 2


def test_a_runner_killed_while_the_server_is_its_parent_is_orphaned(make_jobs, case_root, cstore, fake_agent,
                                                                    wait_until):  # Review Focus 3
    jobs = make_jobs(hermes=fake_agent({"hang": True}))
    job = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Huérfano"))), ADMIN)
    row = wait_until(lambda: _with_agent(cstore, job["id"]), message="agent started")
    psutil.Process(row["runner_pid"]).kill()  # dies without a final write; this process has not reaped it yet
    wait_until(lambda: not procs.alive(row["runner_pid"], row["runner_started"]), message="runner gone")
    assert jobs.reconcile() == [job["id"]]
    final = cstore.get_job(job["id"])
    assert final["status"] == "orphaned" and final["error"]
    wait_until(lambda: not procs.alive(row["pid"], row["pid_started"]), message="the agent left behind is stopped")


def test_a_runner_without_a_known_start_time_is_never_taken_for_alive(make_jobs, case_root, cstore, monkeypatch):
    jobs = make_jobs(runner=lambda job_id: [sys.executable, "-c", "pass"])
    job = cstore.create_job(command="new-open-case", folder=str(_folder(case_root, "Caso Sin Huella")), args={},
                            argv=["x"], launched_by="jean")
    unrelated = subprocess.Popen(sleeper(0))
    try:
        # A live PID that is not this job's runner: without a start time, nothing proves it is the runner.
        assert cstore.update_job(job["id"], status="running", runner_pid=unrelated.pid, runner_started=None)
        assert not procs.alive(unrelated.pid, None)
        assert jobs.reconcile() == [job["id"]] and cstore.get_job(job["id"])["status"] == "orphaned"
        assert unrelated.poll() is None  # and nothing signalled it
    finally:
        unrelated.kill()
        unrelated.wait(timeout=30)
    # A runner whose identity cannot be read at spawn never runs unidentified: the job fails to start.
    monkeypatch.setattr(procs, "identity", lambda pid: None)
    started = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Sin Identidad"))), ADMIN)
    row = cstore.get_job(started["id"])
    assert row["status"] == "failed" and row["runner_started"] is None and "verificar" in row["error"]


def test_a_job_outlives_the_service_that_launched_it(make_jobs, case_root, cstore, store, settings, fake_agent,
                                                     module_runner, wait_until):
    first = make_jobs(hermes=fake_agent({"steps": 60, "delay": 0.1}))
    job = first.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Reinicio"))), ADMIN)
    del first  # the "server" goes away without touching its runner
    second = JobService(ConsoleStore.open_default(), store, settings, hermes_command=fake_agent(),
                        runner_command=module_runner(), tick_seconds=0)
    second.start()
    assert second.reconcile() == []  # found again in the DB, not an orphan
    assert wait_until(lambda: _done(cstore, job["id"]), timeout=90)["status"] == "succeeded"
    second.stop()


def _db_case(store, folder, out_dir):
    return store.create_case(id=f"GRC-{folder.name.replace(' ', '-')}", slug=folder.name.lower().replace(" ", "-"),
                             name=folder.name, root_path=str(folder.resolve()), audits_dir="GhostRecon_Audits",
                             meta={"out_dir": out_dir})


def test_a_case_results_root_that_is_unsafe_or_outside_the_roots_is_refused(make_jobs, case_root, gr_env, store,
                                                                            cstore):
    jobs = make_jobs(runner=sleeper)
    quoted = _folder(case_root, "Caso Comillas")
    _db_case(store, quoted, str(case_root / "Salidas" / 'inj"ected'))
    with pytest.raises(CommandError) as err:
        jobs.launch(LaunchRequest("rerun-case", str(quoted), notes="nota"), ADMIN)
    assert (err.value.status, err.value.code) == (422, "invalid_argument") and "comillas" in err.value.message
    outside = _folder(case_root, "Caso Fuera")
    _db_case(store, outside, str(gr_env / "elsewhere" / "salidas"))
    with pytest.raises(CommandError) as err:
        jobs.launch(LaunchRequest("rerun-case", str(outside), notes="nota"), ADMIN)
    assert (err.value.status, err.value.code) == (409, "results_outside_roots") and "case_roots" in err.value.message
    assert not (case_root / "Salidas").exists() and not (gr_env / "elsewhere").exists()  # nothing written
    assert cstore.list_jobs() == []


def test_a_runner_that_cannot_start_fails_the_job(make_jobs, case_root, cstore, tmp_path):
    jobs = make_jobs(runner=lambda job_id: [str(tmp_path / "no-such-runner")])
    job = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Roto"))), ADMIN)
    row = cstore.get_job(job["id"])
    assert row["status"] == "failed" and "no se pudo iniciar" in row["error"]


def test_an_agent_stamped_after_the_reconcile_snapshot_is_still_stopped(make_jobs, case_root, cstore, monkeypatch):
    """The runner stamps its agent pid between reconcile's listing and its liveness check, then dies: the agent
    must be killed from the row as it is when orphaned, not from the stale snapshot."""
    jobs = make_jobs(runner=sleeper)
    runner = subprocess.Popen(sleeper(0))
    agent = subprocess.Popen(sleeper(0))
    try:
        runner_started, agent_started = procs.identity(runner.pid), procs.identity(agent.pid)
        job = cstore.create_job(command="new-open-case", folder=str(_folder(case_root, "Caso Carrera")), args={},
                                argv=["x"], launched_by="jean")
        assert cstore.update_job(job["id"], status="running", runner_pid=runner.pid, runner_started=runner_started)
        real_alive = procs.alive

        def alive_after_the_stamp(pid, started):
            if pid == runner.pid:
                assert cstore.update_job(job["id"], expect=("running",), pid=agent.pid, pid_started=agent_started)
                procs.kill_tree(runner.pid, runner_started)
                runner.wait(timeout=30)
            return real_alive(pid, started)

        monkeypatch.setattr(procs, "alive", alive_after_the_stamp)
        assert jobs.reconcile() == [job["id"]]
        assert cstore.get_job(job["id"])["status"] == "orphaned"
        monkeypatch.setattr(procs, "alive", real_alive)
        deadline = time.monotonic() + 30
        while real_alive(agent.pid, agent_started) and agent.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert agent.poll() is not None or not real_alive(agent.pid, agent_started)
    finally:
        for proc in (runner, agent):
            proc.kill()
            proc.wait(timeout=30)
