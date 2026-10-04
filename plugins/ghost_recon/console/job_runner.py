"""Detached job runner: one process per console job (``python -m plugins.ghost_recon.console.job_runner <id>``).

It runs the agent argv stored in ``console_jobs`` — exactly what the preview showed — with stdout → ``<id>.jsonl`` and
stderr → ``<id>.log``, normalizes the stream into ``<id>.events.jsonl``, keeps ``phase``/``session_id``/``case_id``
current and writes the final state. The console server is never its required parent: the job survives a server
restart and the new server finds it in the DB. Every write is conditional on the row still being ``running``, so a
cancel (or an orphan verdict) always wins; the runner then stops the agent and exits.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.db import Store, utcnow
from . import events, jobfiles, procs
from .store import ACTIVE_STATUSES, ConsoleStore

RESULT_TEXT_MAX = 20_000
SELF_CHECK = "ghost-recon job runner ok"


def final_state(returncode: int, result: Optional[Dict[str, Any]], stderr_tail: str) -> Dict[str, Any]:
    """``succeeded`` only when the process exited 0 and the stream closed with a clean ``result`` record."""
    if result is None:
        hint = f": {stderr_tail}" if stderr_tail else ""
        return {"status": "failed", "exit_code": returncode,
                "error": f"el agente terminó sin emitir el resultado final{hint}"}
    ok = returncode == 0 and int(result.get("exit_code") or 0) == 0 and not result.get("error")
    error = result.get("error") or (None if ok else f"el agente terminó con código {returncode}")
    return {"status": "succeeded" if ok else "failed", "exit_code": returncode, "error": error}


class Runner:
    """Runs one job; ``run`` returns the job's final status as the DB holds it."""

    def __init__(self, job_id: int, *, cstore: ConsoleStore, store: Store, base: Path, poll: float = 1.0):
        self.job_id = int(job_id)
        self.cstore = cstore
        self.store = store
        self.poll = poll
        self.raw = jobfiles.raw_path(base, job_id)
        self.log = jobfiles.log_path(base, job_id)
        self.events = jobfiles.events_path(base, job_id)
        self.norm = events.Normalizer()
        self.offset = 0
        self.reported: Dict[str, Any] = {}

    def _status(self) -> str:
        return self.cstore.get_job(self.job_id).get("status", "missing")

    def _case_id(self, job: Dict[str, Any]) -> Optional[str]:
        case = self.store.get_case(job["folder"])
        return case.get("id") if case else None

    def _is_mine(self, job: Dict[str, Any]) -> bool:
        """The one "is this job mine" decision. The claim accepts ``running`` because the launcher flips the row to
        running (stamping ``runner_pid``) right after spawning us, possibly before we start; a ``running`` row
        stamped with another runner's PID belongs to that runner, and a second agent must never start for it."""
        if not job or job["status"] not in ACTIVE_STATUSES:
            return False
        owner = job.get("runner_pid")
        return not (job["status"] == "running" and owner and int(owner) != os.getpid())

    def run(self) -> str:
        job = self.cstore.get_job(self.job_id)
        if not self._is_mine(job):
            return job.get("status", "missing") if job else "missing"
        if not self.cstore.update_job(self.job_id, expect=ACTIVE_STATUSES, status="running"):
            return self._status()
        self.reported = {k: job.get(k) for k in ("case_id", "phase", "session_id")}
        try:
            with open(self.raw, "ab") as out, open(self.log, "ab") as err:
                agent = subprocess.Popen(job["argv"], stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                         cwd=job["folder"], env=procs.child_env())
        except OSError as exc:
            self._finish(job, {"status": "failed", "exit_code": None, "error": f"no se pudo iniciar el agente: {exc}"})
            return self._status()
        started = procs.identity(agent.pid)
        try:
            self.cstore.update_job(self.job_id, expect=("running",), pid=agent.pid, pid_started=started)
            return self._supervise(job, agent)
        except BaseException as exc:
            self._abort(job, agent, started, exc)
            raise

    def _supervise(self, job: Dict[str, Any], agent: subprocess.Popen) -> str:
        while agent.poll() is None:
            if not self._pump(job, final=False):
                procs.kill_tree(agent.pid, None)
                agent.wait(timeout=30)
                return self._status()
            time.sleep(self.poll)
        self._pump(job, final=True)
        self._finish(job, final_state(agent.returncode, self.norm.result, jobfiles.tail(self.log, lines=5)))
        return self._status()

    def _abort(self, job: Dict[str, Any], agent: subprocess.Popen, started: Optional[float], exc: BaseException) -> None:
        """An unexpected error after the agent started: never leave it running unsupervised. Kill its tree, then mark
        the job failed conditionally on ``running`` so a cancel or orphan verdict still wins."""
        procs.kill_tree(agent.pid, started)
        try:
            agent.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        error = f"error interno del runner: {type(exc).__name__}: {exc}"[:500]
        try:
            self.cstore.update_job(self.job_id, expect=("running",), status="failed", error=error,
                                   exit_code=agent.returncode, finished_at=utcnow())
        except Exception:  # the store itself may be what failed; the original exception is re-raised by the caller
            pass

    def _pump(self, job: Dict[str, Any], *, final: bool) -> bool:
        """Normalize what the agent wrote since the last call and keep phase/session/case current. False when the
        row is no longer ``running`` (cancelled, or declared orphan): the runner must stop."""
        lines, self.offset = jobfiles.read_lines(self.raw, self.offset, final=final)
        new: List[Dict[str, Any]] = [event for line in lines for event in self.norm.feed_line(line)]
        if final or not lines:
            new += self.norm.flush()  # an idle stream closes the pending group of generic tools
        jobfiles.append_events(self.events, new)
        current = {"phase": self.norm.phase, "session_id": self.norm.session_id or None,
                   "case_id": self.reported.get("case_id") or self._case_id(job)}
        changed = {k: v for k, v in current.items() if v and v != self.reported.get(k)}
        if changed:
            self.reported.update(changed)
            return self.cstore.update_job(self.job_id, expect=("running",), **changed)
        return self._status() == "running"

    def _finish(self, job: Dict[str, Any], state: Dict[str, Any]) -> None:
        result = self.norm.result or {}
        fields: Dict[str, Any] = {"status": state["status"], "exit_code": state["exit_code"], "error": state["error"],
                                  "finished_at": utcnow(), "tokens": result.get("tokens") or {}}
        text = (result.get("text") or self.norm.text)[:RESULT_TEXT_MAX]
        case_id = self.reported.get("case_id") or self._case_id(job)
        extra = {"result_text": text, "phase": self.norm.phase, "session_id": self.norm.session_id,
                 "case_id": case_id}
        fields.update({k: v for k, v in extra.items() if v})
        if self.cstore.update_job(self.job_id, expect=("running",), **fields) and case_id:
            verb = "terminó" if state["status"] == "succeeded" else "falló"
            self.store.add_event(case_id, "console_job_finished", f"Ejecución #{self.job_id} ({job['command']}) {verb}",
                                 actor=job["launched_by"], ref={"job_id": self.job_id, "status": state["status"],
                                                                "session_id": self.norm.session_id or None})


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost-recon-job-runner", description="Run one Ghost Recon console job.")
    parser.add_argument("job_id", type=int, nargs="?")
    parser.add_argument("--poll", type=float, default=1.0, help="Seconds between reads of the agent output")
    parser.add_argument("--self-check", action="store_true",
                        help="Check that this interpreter can run console jobs, then exit")
    args = parser.parse_args(argv)
    if args.self_check:
        procs.child_env()
        if procs.identity(os.getpid()) is None:
            print("psutil no puede leer los procesos de esta máquina", file=sys.stderr)
            return 1
        print(SELF_CHECK, flush=True)
        return 0
    if args.job_id is None:
        parser.error("falta job_id")
    from .. import runtime
    status = Runner(args.job_id, cstore=ConsoleStore.open_default(), store=runtime.store(), base=jobfiles.jobs_dir(),
                    poll=args.poll).run()
    return 0 if status in ("succeeded", "cancelled") else 1


if __name__ == "__main__":
    sys.exit(main())
