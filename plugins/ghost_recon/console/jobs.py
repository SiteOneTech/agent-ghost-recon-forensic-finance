"""JobService: create, queue, dispatch, cancel and supervise console jobs (spec §6.2).

Each job runs in its own detached ``job_runner`` process and the ``console_jobs`` row is the only state the server and
the runner share, so a server restart never touches a running audit: the new server finds it in the DB. ``dispatch``
honours one active job per folder or case and ``max_parallel_jobs`` overall; it runs at start-up, after every launch
and cancel, and on each ``tick`` (every ``tick_seconds``), which also reaps finished runner children and declares
``orphaned`` a running job whose runner is gone (stopping the agent it left behind).
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .. import runtime
from ..core import casefolder as cf
from ..core.db import Store, utcnow
from . import commands, fsjail, jobfiles, procs
from .auth import Principal
from .commands import CommandError, LaunchRequest
from .settings import ConsoleSettings
from .store import ACTIVE_STATUSES, ConsoleStore

logger = logging.getLogger(__name__)
ORPHAN_ERROR = "el proceso de la ejecución terminó sin registrar su estado final"
NO_IDENTITY_ERROR = "no se pudo verificar el proceso de la ejecución al iniciarla (PID y hora de inicio)"


class JobService:
    def __init__(self, cstore: ConsoleStore, store: Store, settings: ConsoleSettings, *,
                 hermes_command: Optional[Callable[[Sequence[str]], List[str]]] = None,
                 runner_command: Optional[Callable[[int], List[str]]] = None, tick_seconds: float = 10.0,
                 stream_poll: float = 1.0):
        self.cstore = cstore
        self.store = store
        self.settings = settings
        self.hermes_command = hermes_command or procs.hermes_command
        self.runner_command = runner_command or procs.runner_command
        self.jobs_dir: Path = jobfiles.jobs_dir()
        self.tick_seconds = tick_seconds
        self.stream_poll = stream_poll
        self._lock = threading.RLock()
        self._children: Dict[int, subprocess.Popen] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ configuration
    def roots(self) -> List[Path]:
        return fsjail.configured_roots(self.settings.case_roots)

    @staticmethod
    def audits_dirname() -> str:
        return str(runtime.setting("audits_dirname") or cf.DEFAULT_AUDITS_DIR)

    @staticmethod
    def defaults() -> Dict[str, str]:
        return {"currency": str(runtime.setting("base_currency") or "USD"),
                "lang": str(runtime.setting("language") or "es")}

    # ------------------------------------------------------------------ orders
    def plan(self, req: LaunchRequest, username: str) -> Dict[str, Any]:
        return commands.plan(req, store=self.store, roots=self.roots(), audits_dirname=self.audits_dirname(),
                             username=username, profile_args=procs.profile_args(), hermes=self.hermes_command)

    def active_for_folder(self, folder: str) -> List[Dict[str, Any]]:
        key = fsjail.folder_key(folder)
        return [j for j in self.cstore.list_jobs(statuses=ACTIVE_STATUSES) if fsjail.folder_key(j["folder"]) == key]

    def queue_note(self, folder: str) -> Optional[str]:
        same = self.active_for_folder(folder)
        if same:
            return f"Hay una ejecución activa en esta carpeta (#{same[-1]['id']}): esta quedará en cola hasta que termine."
        running = self.cstore.list_jobs(statuses=("running",))
        if len(running) >= self.settings.max_parallel_jobs:
            return (f"Ya hay {len(running)} ejecuciones en curso (límite {self.settings.max_parallel_jobs}): "
                    "esta quedará en cola.")
        return None

    def preview(self, req: LaunchRequest, username: str) -> Dict[str, Any]:
        p = self.plan(req, username)
        return {**p, "display": commands.display_command(p["argv"]), "queue_note": self.queue_note(p["folder"])}

    def launch(self, req: LaunchRequest, principal: Principal, ip: str = "") -> Dict[str, Any]:
        with self._lock:
            p = self.plan(req, principal.username)
            for job in self.active_for_folder(p["folder"]):
                if job["command"] == p["command"]:
                    raise CommandError(409, "already_active", "Ya hay una ejecución de esta orden activa o en cola "
                                                              f"para esta carpeta (#{job['id']}).")
            if p["notes"]:
                commands.write_combined_context(p, principal.username, utcnow())
            case_id = p["case"]["id"] if p["case"] and p["case"]["source"] == "db" else None
            job = self.cstore.create_job(command=p["command"], folder=p["folder"], args=p["args"], argv=p["argv"],
                                         launched_by=principal.username, context_file=p["context_file"] or None,
                                         case_id=case_id)
            self.cstore.log("job_launch", user_id=principal.user_id, username=principal.username, ip=ip,
                            target=f"job:{job['id']}", detail={"command": p["command"], "folder": p["folder"],
                                                               "case_id": case_id})
            self._timeline(job, "console_job_launched",
                           f"Ejecución #{job['id']} ({p['command']}) lanzada desde la consola", principal.username)
            self.dispatch()
            return self.cstore.get_job(job["id"])

    def cancel(self, job_id: int, principal: Principal, ip: str = "") -> Dict[str, Any]:
        with self._lock:
            job = self.cstore.get_job(job_id)
            if not job:
                raise CommandError(404, "not_found", f"ejecución no encontrada: {job_id}")
            if job["status"] not in ACTIVE_STATUSES or not self.cstore.update_job(
                    job_id, expect=ACTIVE_STATUSES, status="cancelled", finished_at=utcnow(),
                    error=f"cancelada por {principal.username}"):
                raise CommandError(409, "not_active", "la ejecución ya no está activa")
            current = self.cstore.get_job(job_id)
            procs.kill_tree(current["runner_pid"], current["runner_started"])
            procs.kill_tree(current["pid"], current["pid_started"])  # an agent that outlived its runner
            self.cstore.log("job_cancel", user_id=principal.user_id, username=principal.username, ip=ip,
                            target=f"job:{job_id}", detail={"was": job["status"]})
            self._timeline(current, "console_job_cancelled", f"Ejecución #{job_id} ({job['command']}) cancelada",
                           principal.username)
            self.dispatch()
            return self.cstore.get_job(job_id)

    # ------------------------------------------------------------------ supervision
    def dispatch(self) -> List[int]:
        """Start queued jobs, oldest first, while the limits allow: one active job per folder or case, and
        ``max_parallel_jobs`` running in total."""
        with self._lock:
            self._reap()
            running = self.cstore.list_jobs(statuses=("running",))
            busy = {fsjail.folder_key(j["folder"]) for j in running}
            busy_cases = {j["case_id"] for j in running if j["case_id"]}
            started: List[int] = []
            for job in self.cstore.list_jobs(statuses=("queued",), oldest_first=True, limit=1000):
                if len(running) + len(started) >= self.settings.max_parallel_jobs:
                    break
                key = fsjail.folder_key(job["folder"])
                if key in busy or (job["case_id"] and job["case_id"] in busy_cases):
                    continue
                if self._start_runner(job):
                    started.append(job["id"])
                    busy.add(key)
                    if job["case_id"]:
                        busy_cases.add(job["case_id"])
            return started

    def reconcile(self) -> List[int]:
        """A ``running`` job whose runner process is gone (crash, OOM, killed) becomes ``orphaned``; the agent it
        left behind is stopped, so two agents never work the same folder."""
        with self._lock:
            self._reap()
            orphaned: List[int] = []
            for job in self.cstore.list_jobs(statuses=("running",)):
                if procs.alive(job["runner_pid"], job["runner_started"]):
                    continue
                if self.cstore.update_job(job["id"], expect=("running",), status="orphaned", finished_at=utcnow(),
                                          error=ORPHAN_ERROR):
                    procs.kill_tree(job["pid"], job["pid_started"])
                    self._timeline(job, "console_job_finished",
                                   f"Ejecución #{job['id']} ({job['command']}) terminó sin estado final",
                                   job["launched_by"])
                    orphaned.append(job["id"])
            return orphaned

    def tick(self) -> None:
        self.reconcile()
        self.dispatch()

    def start(self) -> None:
        """Server start-up: find the jobs again in the DB (orphans, queue), then keep ticking in the background."""
        self.tick()
        if self.tick_seconds > 0 and self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="gr-console-jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------------ internals
    def _loop(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            try:
                self.tick()
            except Exception:  # a failed tick must not end supervision; the next one retries
                logger.exception("ghost-recon console: job supervision tick failed")

    def _reap(self) -> None:
        """Wait for runner children that ended, so they never linger as zombies on POSIX."""
        for job_id, proc in list(self._children.items()):
            if proc.poll() is not None:
                del self._children[job_id]

    def _start_runner(self, job: Dict[str, Any]) -> bool:
        log = open(jobfiles.runner_log_path(self.jobs_dir, job["id"]), "ab")
        try:
            proc = procs.spawn_detached(self.runner_command(job["id"]), cwd=procs.hermes_root(),
                                        env=procs.child_env(), stderr=log)
        except OSError as exc:
            self.cstore.update_job(job["id"], expect=("queued",), status="failed", finished_at=utcnow(),
                                   error=f"no se pudo iniciar la ejecución: {exc}")
            return False
        finally:
            log.close()
        self._children[job["id"]] = proc  # reaped by _reap whatever happens next
        started = procs.identity(proc.pid)
        if started is None:  # one retry; a runner that cannot be fingerprinted never runs unidentified
            time.sleep(0.1)
            started = procs.identity(proc.pid)
        if started is None:
            # The runner obeys the row: finding it failed, it exits without starting (or stops) its agent.
            self.cstore.update_job(job["id"], expect=ACTIVE_STATUSES, status="failed", finished_at=utcnow(),
                                   error=NO_IDENTITY_ERROR)
            return False
        # The runner may already have marked the row running; a cancel in between leaves it cancelled.
        if not self.cstore.update_job(job["id"], expect=ACTIVE_STATUSES, status="running", runner_pid=proc.pid,
                                      runner_started=started, started_at=utcnow()):
            procs.kill_tree(proc.pid, started)
            return False
        return True

    def _case_id(self, job: Dict[str, Any]) -> Optional[str]:
        if job.get("case_id"):
            return job["case_id"]
        case = self.store.get_case(job["folder"])
        return case.get("id") if case else None

    def _timeline(self, job: Dict[str, Any], event_type: str, text: str, actor: str) -> None:
        case_id = self._case_id(job)
        if case_id:
            self.store.add_event(case_id, event_type, text, actor=actor, ref={"job_id": job["id"]})
