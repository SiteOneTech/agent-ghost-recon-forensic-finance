"""Periodic clean-up of the console, in one place: expired or revoked sessions, results ZIPs past ``export_retention``
(at most the newest ``count`` finished exports and none older than ``days`` days, spec §11-12) and the per-job files
of jobs that ended more than ``days`` days ago. Runs at start-up and then every ``interval_s``; it never touches an
export that is being built nor the files of a queued or running job."""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from . import jobfiles
from .settings import ConsoleSettings
from .store import TERMINAL_STATUSES, ConsoleStore

logger = logging.getLogger(__name__)
INTERVAL_S = 3600.0
_ALL = 1_000_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    """The console's ISO-8601 UTC form ("2026-10-04T12:00:00Z"): text order is time order."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Housekeeping:
    def __init__(self, cstore: ConsoleStore, settings: ConsoleSettings, *, exports_dir: Path, jobs_dir: Path,
                 clock: Callable[[], datetime] = _utcnow, interval_s: float = INTERVAL_S):
        self.cstore = cstore
        self.settings = settings
        self.exports_dir = Path(exports_dir)
        self.jobs_dir = Path(jobs_dir)
        self.clock = clock
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def run_once(self) -> Dict[str, int]:
        return {"sessions": self.purge_sessions(), "exports": self.prune_exports(),
                "job_files": self.prune_job_files()}

    def purge_sessions(self) -> int:
        now = self.clock()
        return self.cstore.purge_sessions(now=_stamp(now),
                                          idle_before=_stamp(now - timedelta(hours=self.settings.session_idle_hours)))

    def _cutoff(self) -> str:
        return _stamp(self.clock() - timedelta(days=self.settings.export_retention_days))

    def prune_exports(self) -> int:
        """Delete the archives (and their .sha256) past retention; their rows stay, marked ``expired``."""
        cutoff, kept, removed = self._cutoff(), 0, 0
        for row in self.cstore.list_exports(statuses=("succeeded",), limit=_ALL):  # newest first
            if kept < self.settings.export_retention_count and (row["finished_at"] or "") >= cutoff:
                kept += 1
                continue
            if row["file_name"]:
                for name in (row["file_name"], f"{row['file_name']}.sha256"):
                    (self.exports_dir / name).unlink(missing_ok=True)
            removed += self.cstore.update_export(row["id"], expect=("succeeded",), status="expired")
        return removed

    def prune_job_files(self) -> int:
        """Remove ``<id>.jsonl``, ``.log``, ``.events.jsonl``, ``.runner.log`` and the work dir ``<id>/`` of jobs that
        finished before the cutoff. The job rows (status, result, tokens) stay."""
        cutoff, pruned = self._cutoff(), 0
        for job in self.cstore.list_jobs(statuses=TERMINAL_STATUSES, limit=_ALL):
            if not job.get("finished_at") or job["finished_at"] >= cutoff:
                continue
            found = False
            for path in (jobfiles.raw_path(self.jobs_dir, job["id"]), jobfiles.log_path(self.jobs_dir, job["id"]),
                         jobfiles.events_path(self.jobs_dir, job["id"]),
                         jobfiles.runner_log_path(self.jobs_dir, job["id"])):
                if path.exists():
                    path.unlink(missing_ok=True)
                    found = True
            work = jobfiles.work_dir(self.jobs_dir, job["id"])
            if work.is_dir():
                shutil.rmtree(work, ignore_errors=True)
                found = True
            pruned += found
        return pruned

    def start(self) -> None:
        self.run_once()
        if self.interval_s > 0 and self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="gr-console-housekeeping", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.run_once()
            except Exception:  # a failed pass must not end the clean-up; the next one retries
                logger.exception("ghost-recon console: housekeeping pass failed")
