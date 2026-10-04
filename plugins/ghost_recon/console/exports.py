"""ExportService: background builds of results ZIPs (spec §11) and their rows in ``console_exports``.

A request is checked at once (``exporter.select``: a refused export never gets a row), then built by one worker
thread, one archive at a time, with per-file progress in its row. The console audit log gets ``export_request`` and
then ``export`` or ``export_failed``; the case timeline gets ``results_exported`` with the ZIP's SHA-256. A build does
not survive a server restart: at start-up every export still queued or building is marked failed and partial files
are removed, so a row never stays "building" forever.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.db import Store, utcnow
from . import exporter, fsjail
from .auth import Principal
from .exporter import ExportError
from .settings import ConsoleSettings
from .store import ACTIVE_STATUSES, EXPORT_PENDING, ConsoleStore

logger = logging.getLogger(__name__)
INTERRUPTED = "La exportación se interrumpió porque la consola se reinició: vuelve a exportar."
INTERNAL = "Error interno al construir el ZIP; el detalle quedó en el log del servidor."
PROGRESS_EVERY_S = 0.5
STOP_JOIN_S = 30.0


class _Halted(Exception):
    """Raised from the progress callback to abort the build in flight when the service stops."""


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
        """Queue an export; ExportError right away when it could never be built."""
        self.selection(case, scope=scope, seq=seq, include_unsealed=include_unsealed)
        row = self.cstore.create_export(case_id=case["id"], scope=scope, seq=seq if scope == "audit" else None,
                                        include_unsealed=include_unsealed, created_by=principal.username)
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
        if not name or name in (".", "..") or "/" in name or "\\" in name or Path(name).is_absolute():
            return None
        path = self.dir / name
        try:
            if path.resolve().parent != self.dir.resolve():
                return None
        except OSError:
            return None
        return path if path.is_file() else None

    # ------------------------------------------------------------------ building
    def build(self, export_id: int) -> Dict[str, Any]:
        row = self.cstore.get_export(export_id)
        if not row or not self.cstore.update_export(export_id, expect=("queued",), status="building",
                                                    started_at=utcnow()):
            return row
        last = [0.0]

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            if self._halt.is_set():
                raise _Halted
            if done == total or now - last[0] >= PROGRESS_EVERY_S:
                last[0] = now
                self.cstore.update_export(export_id, expect=("building",), files_done=done, files_total=total)

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
            self._succeed(row, case, result)
        return self.cstore.get_export(export_id)

    def _log(self, action: str, row: Dict[str, Any], detail: Dict[str, Any]) -> None:
        user = self.cstore.get_user(row["created_by"])
        self.cstore.log(action, user_id=(user or {}).get("id"), username=row["created_by"], target=f"export:{row['id']}",
                        detail={"case_id": row["case_id"], **detail})

    def _succeed(self, row: Dict[str, Any], case: Dict[str, Any], result: Dict[str, Any]) -> None:
        manifest = result["manifest"]
        files = len(manifest["files"])
        detail = {"audits": [{"seq": a["seq"], "state": a["state"]} for a in manifest["audits"]],
                  "excluded": manifest["excluded"], "skipped": manifest["skipped"], "draft": manifest["draft"]}
        if not self.cstore.update_export(row["id"], expect=("building",), status="succeeded", finished_at=utcnow(),
                                         size=result["size"], sha256=result["sha256"], file_name=result["file_name"],
                                         files_done=files, files_total=files, detail=detail):
            return  # a restart verdict already stands; the late result is not recorded
        self._log("export", row, {"scope": row["scope"], "seq": row["seq"], "draft": manifest["draft"],
                                  "file": result["file_name"], "size": result["size"], "sha256": result["sha256"]})
        what = row["seq"] or "caso completo"
        draft = ", con auditorías abiertas (borrador)" if manifest["draft"] else ""
        self.store.add_event(case["id"], "results_exported",
                             f"Resultados exportados ({what}{draft}) · ZIP SHA-256 {result['sha256']}",
                             actor=row["created_by"],
                             ref={"export_id": row["id"], "file": result["file_name"], "sha256": result["sha256"],
                                  "scope": row["scope"], "seq": row["seq"], "draft": manifest["draft"]})

    def _fail(self, row: Dict[str, Any], code: str, message: str, expect=EXPORT_PENDING) -> None:
        if not self.cstore.update_export(row["id"], expect=expect, status="failed", finished_at=utcnow(),
                                         error=message, detail={"code": code}):
            return
        self._log("export_failed", row, {"code": code, "message": message})

    # ------------------------------------------------------------------ lifecycle
    def recover(self) -> List[int]:
        """Start-up: an export left queued or building by a previous server never finishes; fail it and remove the
        partial archives."""
        interrupted = [row["id"] for row in self.cstore.list_exports(statuses=EXPORT_PENDING)
                       if self.cstore.update_export(row["id"], expect=EXPORT_PENDING, status="failed",
                                                    finished_at=utcnow(), error=INTERRUPTED,
                                                    detail={"code": "interrupted"})]
        for part in self.dir.glob("*.zip.part"):
            part.unlink(missing_ok=True)
        return interrupted

    def start(self) -> None:
        self.recover()
        if self._thread is None:
            self._halt.clear()
            while not self._queue.empty():  # leftovers of a previous run: recover() failed those rows
                self._queue.get_nowait()
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
            except Exception:  # a failed bookkeeping write must not end the worker; the row shows what it reached
                logger.exception("ghost-recon console: export worker error on %s", export_id)
