"""Periodic clean-up of the console, in one place: expired or revoked sessions, results ZIPs past ``export_retention``
(at most the newest ``count`` finished exports and none older than ``days`` days, spec §11-12) and the per-job files
of jobs that ended more than ``days`` days ago. Runs at start-up and then every ``interval_s`` (and the export part
after every finished build, from ``ExportService``); it never touches an export that is being built nor the files of
a queued or running job. A file that cannot be removed (e.g. a ZIP being downloaded on Windows) is logged and left for
the next pass; the rest of the pass goes on."""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from . import jobfiles
from .paths import file_inside
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


def _cutoff(settings: ConsoleSettings, now: datetime) -> str:
    return _stamp(now - timedelta(days=settings.export_retention_days))


def remove_file(path: Path) -> bool:
    """Remove one file; False (logged) when the OS refuses, so the pass goes on with the next one."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("ghost-recon console: could not remove %s (next pass retries): %s", path.name, exc)
        return False
    return True


def prune_exports(cstore: ConsoleStore, settings: ConsoleSettings, exports_dir: Path, now: datetime) -> int:
    """Delete the archives (and their .sha256) past retention; their rows stay, marked ``expired``. Files are only
    ever removed as plain names directly inside ``exports_dir``. A row whose files could not all be removed stays
    ``succeeded`` (its ZIP is still there and downloadable) and the next pass tries again."""
    cutoff, kept, removed = _cutoff(settings, now), 0, 0
    for row in cstore.list_exports(statuses=("succeeded",), limit=_ALL):  # newest first
        if kept < settings.export_retention_count and (row["finished_at"] or "") >= cutoff:
            kept += 1
            continue
        names = (row["file_name"], f"{row['file_name']}.sha256") if row["file_name"] else ()
        paths = [path for path in (file_inside(exports_dir, name) for name in names) if path is not None]
        if all([remove_file(path) for path in paths]):
            removed += cstore.update_export(row["id"], expect=("succeeded",), status="expired")
    return removed


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

    def prune_exports(self) -> int:
        return prune_exports(self.cstore, self.settings, self.exports_dir, self.clock())

    def prune_job_files(self) -> int:
        """Remove ``<id>.jsonl``, ``.log``, ``.events.jsonl``, ``.runner.log`` and the work dir ``<id>/`` of jobs that
        finished before the cutoff. The job rows (status, result, tokens) stay."""
        cutoff, pruned = _cutoff(self.settings, self.clock()), 0
        for job in self.cstore.list_jobs(statuses=TERMINAL_STATUSES, limit=_ALL):
            if not job.get("finished_at") or job["finished_at"] >= cutoff:
                continue
            found = False
            for path in (jobfiles.raw_path(self.jobs_dir, job["id"]), jobfiles.log_path(self.jobs_dir, job["id"]),
                         jobfiles.events_path(self.jobs_dir, job["id"]),
                         jobfiles.runner_log_path(self.jobs_dir, job["id"])):
                if path.exists():
                    found = remove_file(path) or found
            work = jobfiles.work_dir(self.jobs_dir, job["id"])
            if work.is_dir():
                shutil.rmtree(work, ignore_errors=True)
                found = True
            pruned += found
        return pruned

    def start(self) -> None:
        try:
            self.run_once()
        except Exception:  # a locked file or a database error in a pass must not abort the console's start-up
            logger.exception("ghost-recon console: housekeeping pass failed")
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
