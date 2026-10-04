"""ExportService: background builds of results ZIPs (spec §11) and their rows in ``console_exports``.

A request is checked at once (``exporter.select``: a refused export never gets a row; a case with an export still
queued or building here gets ``export_pending``, while a pending row this service is not handling, left behind by a
build whose state writes kept failing, is failed as interrupted so it never blocks the case), then built by one
worker thread, one archive at a time, with per-file progress in its row. The console audit log gets
``export_request`` and then ``export`` or ``export_failed``; the case timeline gets ``results_exported`` with the
ZIP's SHA-256. After every finished build the retention pass of ``housekeeping`` runs, so ``export_retention`` holds
between its hourly passes. A build does not survive a server
restart: at start-up every export still queued or building is marked failed, and every file of the exports folder
that no finished export owns (partial ``.part``, an archive whose row never succeeded) is removed, so a row never
stays "building" forever and nothing piles up. Files of the exports folder are only ever served or removed as plain
names directly inside it (``paths.file_inside``).
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from ..core.db import Store, utcnow
from . import exporter, fsjail, housekeeping
from .auth import Principal
from .exporter import ExportError
from .paths import file_inside
from .settings import ConsoleSettings
from .store import ACTIVE_STATUSES, EXPORT_PENDING, ConsoleStore

logger = logging.getLogger(__name__)
INTERRUPTED = "La exportación se interrumpió porque la consola se reinició: vuelve a exportar."
INTERNAL = "Error interno al construir el ZIP; el detalle quedó en el log del servidor."
PROGRESS_EVERY_S = 0.5
STOP_JOIN_S = 30.0
STATE_WRITE_BACKOFF_S = (0.2, 0.5, 1.0)
ORPHAN_SUFFIXES = (".zip", ".zip.sha256", ".part")
_ALL = 1_000_000


class _Halted(Exception):
    """Raised from the progress callback to abort the build in flight when the service stops."""


def is_draft(row: Dict[str, Any]) -> bool:
    """An export that carries unsealed audits: once built its manifest says so (``detail.draft``); until then the
    request's ``include_unsealed`` stands in for it."""
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    return bool(detail["draft"]) if "draft" in detail else bool(row.get("include_unsealed"))


def _retrying(write: Callable[[], Any]) -> Any:
    """A state write the export cannot do without (claim, succeeded, failed): "database is locked" past the busy
    timeout is retried with a short backoff; the last failure propagates."""
    for delay in STATE_WRITE_BACKOFF_S:
        try:
            return write()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            logger.warning("ghost-recon console: export state write: %s; retrying in %.1f s", exc, delay)
            time.sleep(delay)
    return write()


class ExportService:
    def __init__(self, cstore: ConsoleStore, store: Store, settings: ConsoleSettings, *,
                 exports_dir: Optional[Path] = None):
        self.cstore = cstore
        self.store = store
        self.settings = settings
        self.dir = Path(exports_dir) if exports_dir else exporter.exports_dir()
        self._queue: "queue.Queue[Optional[int]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._halt = threading.Event()
        self._requests = threading.Lock()  # the pending check and the new row are one step (a double click)
        self._owned: Set[int] = set()  # exports this service has queued or is building (guarded by _requests)

    # ------------------------------------------------------------------ requests
    def busy(self, case: Dict[str, Any]) -> bool:
        """A job is queued or running on the case (by case id, or on its folder before the case existed)."""
        key = fsjail.folder_key(case["root_path"])
        return any(j["case_id"] == case["id"] or fsjail.folder_key(j["folder"]) == key
                   for j in self.cstore.list_jobs(statuses=ACTIVE_STATUSES))

    def selection(self, case: Dict[str, Any], *, scope: str, seq: Optional[str],
                  include_unsealed: bool) -> exporter.Selection:
        return exporter.select(self.store, case, scope=scope, seq=seq, include_unsealed=include_unsealed,
                               busy=self.busy(case))

    def preview(self, case: Dict[str, Any], *, scope: str, seq: Optional[str], include_unsealed: bool) -> Dict:
        return exporter.selection_view(self.selection(case, scope=scope, seq=seq, include_unsealed=include_unsealed))

    def request(self, case: Dict[str, Any], *, scope: str, seq: Optional[str], include_unsealed: bool,
                principal: Principal, ip: str = "") -> Dict[str, Any]:
        """Queue an export; ExportError right away when it could never be built or while the case already has one
        queued or building (one at a time per case: the queue and the disk stay bounded). A pending row of the case
        that this service neither queued nor is building is stale (its build gave up on a locked database): it is
        failed as interrupted and never blocks the case."""
        self.selection(case, scope=scope, seq=seq, include_unsealed=include_unsealed)
        with self._requests:
            for pending in self.cstore.list_exports(statuses=EXPORT_PENDING, case_id=case["id"]):
                if pending["id"] in self._owned:
                    raise ExportError(409, "export_pending", "Ya hay una exportación en curso para este caso "
                                      f"(#{pending['id']}).", extra={"export_id": pending["id"]})
                self._fail(pending, "interrupted", INTERRUPTED)
            row = self.cstore.create_export(case_id=case["id"], scope=scope, seq=seq if scope == "audit" else None,
                                            include_unsealed=include_unsealed, created_by=principal.username)
            self._owned.add(row["id"])
        self.cstore.log("export_request", user_id=principal.user_id, username=principal.username, ip=ip,
                        target=f"export:{row['id']}", detail={"case_id": case["id"], "scope": scope,
                                                              "seq": row["seq"], "include_unsealed": include_unsealed})
        self._queue.put(row["id"])
        return row

    def file_path(self, row: Dict[str, Any]) -> Optional[Path]:
        """The finished archive of an export, while it is still on disk."""
        if row.get("status") != "succeeded":
            return None
        return self._inside(row.get("file_name"))

    def sidecar_path(self, row: Dict[str, Any]) -> Optional[Path]:
        """The ``.sha256`` beside the finished archive."""
        archive = self.file_path(row)
        return self._inside(f"{archive.name}.sha256") if archive else None

    def _inside(self, name: Optional[str]) -> Optional[Path]:
        """A plain file name that resolves directly inside the exports folder, else None."""
        return file_inside(self.dir, name)

    def _discard(self, file_name: str) -> None:
        """Remove a published archive and its sidecar that no row will ever own."""
        for name in (file_name, f"{file_name}.sha256"):
            path = self._inside(name)
            if path is not None:
                housekeeping.remove_file(path)

    # ------------------------------------------------------------------ building
    def build(self, export_id: int) -> Dict[str, Any]:
        row = self.cstore.get_export(export_id)
        # The claim is retried too: a row stuck "queued" would also block the case's next export (export_pending).
        if not row or not _retrying(lambda: self.cstore.update_export(
                export_id, expect=("queued",), status="building", started_at=utcnow())):
            return row
        last = [0.0]

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            if self._halt.is_set():
                raise _Halted
            if done == total or now - last[0] >= PROGRESS_EVERY_S:
                last[0] = now
                try:  # progress is best effort: a busy database never stops the build
                    self.cstore.update_export(export_id, expect=("building",), files_done=done, files_total=total)
                except sqlite3.Error as exc:
                    logger.debug("ghost-recon console: export %s progress not saved: %s", export_id, exc)

        try:
            case = self.store.get_case(row["case_id"])
            if not case:
                raise ExportError(404, "not_found", "El caso ya no existe.")
            sel = self.selection(case, scope=row["scope"], seq=row["seq"], include_unsealed=row["include_unsealed"])
            result = exporter.build(self.store, self.cstore, sel, export_id=export_id, exported_by=row["created_by"],
                                    dest_dir=self.dir, progress=progress)
        except _Halted:
            self._fail(row, "interrupted", INTERRUPTED, expect=("building",))
        except ExportError as exc:
            self._fail(row, exc.code, exc.message)
        except Exception:
            logger.exception("ghost-recon console: export %s failed", export_id)
            self._fail(row, "internal", INTERNAL)
        else:
            if self._succeed(row, case, result):
                self._prune()
        return self.cstore.get_export(export_id)

    def _log(self, action: str, row: Dict[str, Any], detail: Dict[str, Any]) -> None:
        user = self.cstore.get_user(row["created_by"])
        self.cstore.log(action, user_id=(user or {}).get("id"), username=row["created_by"], target=f"export:{row['id']}",
                        detail={"case_id": row["case_id"], **detail})

    def _succeed(self, row: Dict[str, Any], case: Dict[str, Any], result: Dict[str, Any]) -> bool:
        manifest = result["manifest"]
        files = len(manifest["files"])
        detail = {"audits": [{"seq": a["seq"], "state": a["state"]} for a in manifest["audits"]],
                  "excluded": manifest["excluded"], "skipped": manifest["skipped"], "draft": manifest["draft"]}
        try:
            recorded = _retrying(lambda: self.cstore.update_export(
                row["id"], expect=("building",), status="succeeded", finished_at=utcnow(), size=result["size"],
                sha256=result["sha256"], file_name=result["file_name"], files_done=files, files_total=files,
                detail=detail))
        except Exception:
            self._discard(result["file_name"])  # the row never got to own the archive just published
            raise
        if not recorded:  # a restart or stale verdict already stands; the late result is not recorded
            self._discard(result["file_name"])
            return False
        self._log("export", row, {"scope": row["scope"], "seq": row["seq"], "draft": manifest["draft"],
                                  "file": result["file_name"], "size": result["size"], "sha256": result["sha256"]})
        what = row["seq"] or "caso completo"
        draft = ", con auditorías abiertas (borrador)" if manifest["draft"] else ""
        self.store.add_event(case["id"], "results_exported",
                             f"Resultados exportados ({what}{draft}) · ZIP SHA-256 {result['sha256']}",
                             actor=row["created_by"],
                             ref={"export_id": row["id"], "file": result["file_name"], "sha256": result["sha256"],
                                  "scope": row["scope"], "seq": row["seq"], "draft": manifest["draft"]})
        return True

    def _fail(self, row: Dict[str, Any], code: str, message: str, expect=EXPORT_PENDING) -> None:
        if not _retrying(lambda: self.cstore.update_export(row["id"], expect=expect, status="failed",
                                                           finished_at=utcnow(), error=message,
                                                           detail={"code": code})):
            return
        self._log("export_failed", row, {"code": code, "message": message})

    def _give_up(self, export_id: int) -> None:
        """The worker's last word on a build whose bookkeeping failed: one more attempt to end its row failed, so the
        dialog stops polling. If the database still refuses, the next request for the case finds the row stale."""
        try:
            row = self.cstore.get_export(export_id)
            if row and self.cstore.update_export(export_id, expect=EXPORT_PENDING, status="failed",
                                                 finished_at=utcnow(), error=INTERNAL, detail={"code": "internal"}):
                self._log("export_failed", row, {"code": "internal", "message": INTERNAL})
        except Exception as exc:
            logger.warning("ghost-recon console: export %s left pending: %s", export_id, exc)

    def _prune(self) -> None:
        """The retention part of housekeeping, right after a build, so ``export_retention`` holds between passes."""
        try:
            housekeeping.prune_exports(self.cstore, self.settings, self.dir, datetime.now(timezone.utc))
        except Exception:  # the export itself is done and recorded; the hourly pass retries the clean-up
            logger.exception("ghost-recon console: export retention after a build failed")

    # ------------------------------------------------------------------ lifecycle
    def recover(self) -> List[int]:
        """Start-up: an export left queued or building by a previous server never finishes; fail it. Then remove
        every archive, sidecar or ``.part`` of the exports folder that no succeeded export owns (partial files, an
        archive whose row never succeeded), each through the same containment check as the downloads."""
        interrupted = [row["id"] for row in self.cstore.list_exports(statuses=EXPORT_PENDING)
                       if self.cstore.update_export(row["id"], expect=EXPORT_PENDING, status="failed",
                                                    finished_at=utcnow(), error=INTERRUPTED,
                                                    detail={"code": "interrupted"})]
        owned = set()
        for row in self.cstore.list_exports(statuses=("succeeded",), limit=_ALL):
            if row["file_name"]:
                owned.update((row["file_name"], f"{row['file_name']}.sha256"))
        names = sorted(p.name for p in self.dir.iterdir()) if self.dir.is_dir() else []
        for name in names:
            path = self._inside(name) if name.endswith(ORPHAN_SUFFIXES) and name not in owned else None
            if path is not None:
                housekeeping.remove_file(path)
        return interrupted

    def start(self) -> None:
        if self._thread is None:  # never while a build is in flight: its .part is not an orphan
            self.recover()
            self._halt.clear()
            with self._requests:
                while not self._queue.empty():  # leftovers of a previous run: recover() failed those rows
                    self._queue.get_nowait()
                self._owned.clear()
            self._thread = threading.Thread(target=self._loop, name="gr-console-exports", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Abort the build in flight (its row fails as interrupted, its .part goes) and leave queued ones queued:
        recover() fails them at the next start."""
        if self._thread is not None:
            self._halt.set()
            self._queue.put(None)
            self._thread.join(timeout=STOP_JOIN_S)
            if not self._thread.is_alive():
                self._thread = None

    def _loop(self) -> None:
        while not self._halt.is_set():
            export_id = self._queue.get()
            if export_id is None or self._halt.is_set():
                return
            try:
                self.build(export_id)
            except Exception:  # a failed bookkeeping write must not end the worker
                logger.exception("ghost-recon console: export worker error on %s", export_id)
                self._give_up(export_id)
            finally:
                with self._requests:
                    self._owned.discard(export_id)
