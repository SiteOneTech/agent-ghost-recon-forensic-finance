"""Detached job runner: one process per console job (``python -m plugins.ghost_recon.console.job_runner <id>``).

It runs the agent argv stored in ``console_jobs`` — exactly what the preview showed — from its own empty working
directory ``<id>/`` (never the evidence folder), with stdout → ``<id>.jsonl`` and stderr → ``<id>.log``, normalizes
the stream into ``<id>.events.jsonl``, keeps ``phase``/``session_id``/``case_id`` current and writes the final state.
The console server is never its required parent: the job survives a server restart and the new server finds it in the
DB. Every write is conditional on the row still being ``running``, so a cancel (or an orphan verdict) always wins; the
runner then stops the agent and exits. When the job ends (succeeded or failed) and a notice target is configured, the
runner runs the ``hermes send`` argv the server planned, with a short summary; the notice is best effort and never
changes the job.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core import ids
from ..core.db import Store, utcnow
from . import commands, events, jobfiles, procs
from .store import ACTIVE_STATUSES, ConsoleStore

RESULT_TEXT_MAX = 20_000
SELF_CHECK = "ghost-recon job runner ok"
NO_IDENTITY_ERROR = "no se pudo verificar el proceso del agente al iniciarlo (PID y hora de inicio)"
ESSENTIAL_WRITE_BACKOFF_S = (0.5, 1.0, 2.0, 4.0)
NOTIFY_TIMEOUT_S = 60
NOTIFY_ERROR_MAX = 300
_MEDIA_RE = re.compile(r"MEDIA:", re.IGNORECASE)
logger = logging.getLogger(__name__)


def notify_message(job: Dict[str, Any], status: str, case: Dict[str, Any], last_audit: Optional[Dict[str, Any]],
                   error: Optional[str]) -> str:
    """The job-end notice: order, outcome, case and last audit, and the (redacted) reason of a failure. Text the
    operator controls (case and folder names, the agent's error) can never turn into a ``MEDIA:`` attachment of
    ``hermes send``, and the message always starts with a word, never with a flag."""
    verb = "terminó" if status == "succeeded" else "falló"
    order = commands.ORDER_LABELS.get(job["command"], job["command"])
    where = f"{case['name']} ({case['id']})" if case else Path(job["folder"]).name
    lines = [f"Ejecución #{job['id']} · {order} · {verb}", f"Caso: {where}"]
    if last_audit:
        lines.append(f"Última auditoría: {ids.short_audit(last_audit['id'])} ({last_audit['status']})")
    if error:
        from agent.redact import redact_sensitive_text
        lines.append(f"Motivo: {redact_sensitive_text(str(error), force=True)[:NOTIFY_ERROR_MAX]}")
    return _MEDIA_RE.sub("MEDIA :", "\n".join(lines))


def _retrying(write: Callable[[], Any]) -> Any:
    """An essential write (the agent's PID, the final state, the timeline event): a transient
    ``sqlite3.OperationalError`` ("database is locked" past the busy timeout) is retried with backoff; the last failure
    propagates, and the caller's abort path applies."""
    for delay in ESSENTIAL_WRITE_BACKOFF_S:
        try:
            return write()
        except sqlite3.OperationalError as exc:
            logger.warning("ghost-recon job runner: %s; retrying in %.1f s", exc, delay)
            time.sleep(delay)
    return write()


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
        self.work = jobfiles.work_dir(base, job_id)
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
        running (stamping ``runner_pid`` with the PID it spawned) right after spawning us, possibly before we start.
        That PID is ours or our parent's: one launcher hop sits in between (a venv ``python.exe`` redirector on
        Windows, an exec wrapper on POSIX). A ``running`` row stamped with any other PID belongs to another runner,
        and a second agent must never start for it."""
        if not job or job["status"] not in ACTIVE_STATUSES:
            return False
        owner = job.get("runner_pid")
        return not (job["status"] == "running" and owner and int(owner) not in (os.getpid(), os.getppid()))

    def run(self) -> str:
        job = self.cstore.get_job(self.job_id)
        if not self._is_mine(job):
            return job.get("status", "missing") if job else "missing"
        if not self.cstore.update_job(self.job_id, expect=ACTIVE_STATUSES, status="running"):
            return self._status()
        self.reported = {k: job.get(k) for k in ("case_id", "phase", "session_id")}
        try:
            # Never the evidence folder: Hermes reads instructions from its cwd and writes relative paths there.
            self.work.mkdir(parents=True, exist_ok=True)
            with open(self.raw, "ab") as out, open(self.log, "ab") as err:
                agent = subprocess.Popen(job["argv"], stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                         cwd=self.work, env=procs.child_env())
        except OSError as exc:
            self._finish(job, {"status": "failed", "exit_code": None, "error": f"no se pudo iniciar el agente: {exc}"})
            return self._status()
        started = procs.identity(agent.pid)
        if started is None:  # one retry; an agent that cannot be fingerprinted could never be stopped safely
            time.sleep(0.1)
            started = procs.identity(agent.pid)
        if started is None:
            agent.kill()  # still our unreaped child, so its PID cannot have been recycled
            agent.wait(timeout=30)
            self._finish(job, {"status": "failed", "exit_code": agent.returncode, "error": NO_IDENTITY_ERROR})
            return self._status()
        try:
            _retrying(lambda: self.cstore.update_job(self.job_id, expect=("running",), pid=agent.pid,
                                                     pid_started=started))
            return self._supervise(job, agent, started)
        except BaseException as exc:
            self._abort(job, agent, started, exc)
            raise

    def _supervise(self, job: Dict[str, Any], agent: subprocess.Popen, started: float) -> str:
        while agent.poll() is None:
            if not self._pump(job, final=False):
                procs.kill_tree(agent.pid, started)
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
        try:
            current = {"phase": self.norm.phase, "session_id": self.norm.session_id or None,
                       "case_id": self.reported.get("case_id") or self._case_id(job)}
            changed = {k: v for k, v in current.items() if v and v != self.reported.get(k)}
            if changed:
                ok = self.cstore.update_job(self.job_id, expect=("running",), **changed)
                self.reported.update(changed)
                return ok
            return self._status() == "running"
        except sqlite3.OperationalError as exc:
            # A transient lock must not kill a healthy audit: skip this cycle's write. ``reported`` is unchanged, so
            # the next cycle retries it (the final state carries phase/session/case anyway).
            logger.warning("ghost-recon job runner: %s; the progress write is retried next cycle", exc)
            return True

    def _finish(self, job: Dict[str, Any], state: Dict[str, Any]) -> None:
        result = self.norm.result or {}
        fields: Dict[str, Any] = {"status": state["status"], "exit_code": state["exit_code"], "error": state["error"],
                                  "finished_at": utcnow(), "tokens": result.get("tokens") or {}}
        text = (result.get("text") or self.norm.text)[:RESULT_TEXT_MAX]
        case_id = self.reported.get("case_id") or self._case_id(job)
        extra = {"result_text": text, "phase": self.norm.phase, "session_id": self.norm.session_id,
                 "case_id": case_id}
        fields.update({k: v for k, v in extra.items() if v})
        if not _retrying(lambda: self.cstore.update_job(self.job_id, expect=("running",), **fields)):
            return  # cancelled or declared orphan meanwhile: that verdict stands, and nobody is told otherwise
        if case_id:
            verb = "terminó" if state["status"] == "succeeded" else "falló"
            _retrying(lambda: self.store.add_event(
                case_id, "console_job_finished", f"Ejecución #{self.job_id} ({job['command']}) {verb}",
                actor=job["launched_by"], ref={"job_id": self.job_id, "status": state["status"],
                                               "session_id": self.norm.session_id or None}))
        self._notify(job, state["status"], case_id, state["error"])

    def _notify(self, job: Dict[str, Any], status: str, case_id: Optional[str], error: Optional[str]) -> None:
        """``hermes send`` to the configured target (spec §6.2), with the argv the server planned plus the summary.
        Best effort: a failure goes to the runner log and the job keeps its final state."""
        argv = job.get("notify_argv") or []
        if not argv:
            return
        case = self.store.get_case(case_id) if case_id else {}
        audits = self.store.list_audits(case_id) if case else []
        message = notify_message(job, status, case, audits[-1] if audits else None, error)
        try:
            done = subprocess.run([*argv, message], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, cwd=self.work, env=procs.child_env(),
                                  timeout=NOTIFY_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("ghost-recon job runner: the job-end notice was not sent: %s", exc)
            return
        if done.returncode != 0:
            logger.warning("ghost-recon job runner: hermes send exited %s: %s", done.returncode,
                           done.stdout.decode("utf-8", "replace")[-500:])


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
