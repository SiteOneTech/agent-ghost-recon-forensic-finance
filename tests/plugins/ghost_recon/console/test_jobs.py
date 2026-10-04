"""JobService: preview = launched argv, one active job per folder or case plus a global limit, queue, cancel,
orphans (also while the server is the runner's parent) and a job that outlives the service that launched it."""
import sys
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


def test_a_runner_that_cannot_start_fails_the_job(make_jobs, case_root, cstore, tmp_path):
    jobs = make_jobs(runner=lambda job_id: [str(tmp_path / "no-such-runner")])
    job = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Roto"))), ADMIN)
    row = cstore.get_job(job["id"])
    assert row["status"] == "failed" and "no se pudo iniciar" in row["error"]
