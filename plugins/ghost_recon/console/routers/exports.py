"""Export endpoints (viewer): the results ZIP of a case or an audit (built in the background; unsealed audits only for
an admin, and a DRAFT export is read by admins only) and the case tables as CSV/XLSX with the filters of their JSON
endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import readmodel, tables
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..downloads import attachment
from ..exporter import ExportError
from ..exports import is_draft
from ..store import EXPORT_PENDING
from .cases import get_case_or_404

router = APIRouter(tags=["exports"])
SEQ_PATTERN = r"^[AR]\d{2,3}$"
DRAFT_ADMIN_ONLY = "Solo un admin puede descargar exportaciones con auditorías sin sellar."


class ExportBody(BaseModel):
    scope: Literal["case", "audit"] = "case"
    seq: Optional[str] = Field(None, pattern=SEQ_PATTERN)
    include_unsealed: Optional[bool] = None  # None: the configured default (export_include_unsealed), admins only


def _include_unsealed(ctx: ConsoleContext, principal: Principal, asked: Optional[bool]) -> bool:
    if asked is None:
        return ctx.settings.export_include_unsealed and principal.has("admin")
    if asked and not principal.has("admin"):
        raise ApiError(403, "forbidden", "solo un admin exporta auditorías sin sellar")
    return asked


def _api_error(exc: ExportError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message, extra=exc.extra)


def _scope(scope: str, seq: Optional[str]) -> None:
    if scope == "audit" and not seq:
        raise ApiError(422, "invalid_argument", "falta la auditoría (seq) para exportar una sola auditoría")


def _export_or_404(ctx: ConsoleContext, export_id: int) -> dict:
    row = ctx.cstore.get_export(export_id)
    if not row:
        raise ApiError(404, "not_found", f"exportación no encontrada: {export_id}")
    return row


def _draft_guard(ctx: ConsoleContext, row: dict, principal: Principal, request: Optional[Request] = None) -> dict:
    """A DRAFT export (unsealed audits inside) is read by admins only. A refused download (``request`` given) is in
    the console audit log, like a refused deliverable download."""
    if is_draft(row) and not principal.has("admin"):
        if request is not None:
            ctx.cstore.log("export_download_denied", user_id=principal.user_id, username=principal.username,
                           ip=client_ip(request), target=f"export:{row['id']}",
                           detail={"code": "forbidden", "case_id": row["case_id"], "file": row["file_name"]})
        raise ApiError(403, "forbidden", DRAFT_ADMIN_ONLY)
    return row


@router.get("/cases/{case_id}/export/preview")
def export_preview(case_id: str, scope: Literal["case", "audit"] = "case",
                   seq: Optional[str] = Query(None, pattern=SEQ_PATTERN), include_unsealed: Optional[bool] = None,
                   principal: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """What an export would take and why the other audits stay out, without building anything."""
    case = get_case_or_404(ctx, case_id)
    _scope(scope, seq)
    include = _include_unsealed(ctx, principal, include_unsealed)
    try:
        view = ctx.exports.preview(case, scope=scope, seq=seq, include_unsealed=include)
    except ExportError as exc:
        raise _api_error(exc) from exc
    return {**view, "include_unsealed": include, "can_include_unsealed": principal.has("admin")}


@router.post("/cases/{case_id}/export", status_code=202)
def export_case(case_id: str, body: ExportBody, request: Request, principal: Principal = Depends(require("viewer")),
                ctx: ConsoleContext = Depends(get_ctx)):
    case = get_case_or_404(ctx, case_id)
    _scope(body.scope, body.seq)
    include = _include_unsealed(ctx, principal, body.include_unsealed)
    try:
        row = ctx.exports.request(case, scope=body.scope, seq=body.seq, include_unsealed=include,
                                  principal=principal, ip=client_ip(request))
    except ExportError as exc:
        raise _api_error(exc) from exc
    return {"export_id": row["id"], "export": row}


@router.get("/exports/{export_id}")
def export_status(export_id: int, principal: Principal = Depends(require("viewer")),
                  ctx: ConsoleContext = Depends(get_ctx)):
    """State, progress (files_done / files_total), size and SHA-256 once built; ``available``: its ZIP is on disk."""
    row = _draft_guard(ctx, _export_or_404(ctx, export_id), principal)
    return {**row, "available": ctx.exports.file_path(row) is not None}


def _finished_file(ctx: ConsoleContext, request: Request, principal: Principal, export_id: int):
    row = _draft_guard(ctx, _export_or_404(ctx, export_id), principal, request)
    if row["status"] in EXPORT_PENDING:
        raise ApiError(409, "not_ready", "el ZIP todavía se está construyendo")
    path = ctx.exports.file_path(row)
    if path is None:
        raise _gone()
    return row, path


def _gone() -> ApiError:
    return ApiError(410, "gone", "este ZIP no está disponible (falló o se eliminó por antigüedad): vuelve a exportar")


@router.get("/exports/{export_id}/download")
def export_download(export_id: int, request: Request, principal: Principal = Depends(require("viewer")),
                    ctx: ConsoleContext = Depends(get_ctx)):
    row, path = _finished_file(ctx, request, principal, export_id)
    try:
        path.stat()
    except OSError as exc:
        raise _gone() from exc
    ctx.cstore.log("export_download", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=f"export:{export_id}", detail={"case_id": row["case_id"], "file": row["file_name"]})
    return FileResponse(path, filename=row["file_name"], media_type="application/zip")


@router.get("/exports/{export_id}/sha256")
def export_sidecar(export_id: int, request: Request, principal: Principal = Depends(require("viewer")),
                   ctx: ConsoleContext = Depends(get_ctx)):
    """The ``<zip>.sha256`` beside the archive (``sha256sum -c`` format)."""
    row, _archive = _finished_file(ctx, request, principal, export_id)
    sidecar = ctx.exports.sidecar_path(row)
    try:
        data = sidecar.read_bytes() if sidecar else None
    except OSError:
        data = None
    if data is None:
        raise _gone()
    return attachment(data, sidecar.name, "text/plain; charset=utf-8")


@router.get("/cases/{case_id}/{table}.{fmt}")
def table_file(case_id: str, table: str, fmt: str, request: Request, kind: str = "", risk: str = "",
               status: str = "", q: str = "", audit: str = "", principal: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    """``table`` ∈ findings | evidence | timeline | criteria, ``fmt`` ∈ csv | xlsx; every row that matches the filters
    (no pagination)."""
    case = get_case_or_404(ctx, case_id)
    spec, writer = tables.TABLES.get(table), tables.WRITERS.get(fmt)
    if spec is None or writer is None:
        raise ApiError(404, "not_found", f"tabla o formato desconocido: {table}.{fmt}")
    filters = readmodel.TableFilters(kind=kind, risk=risk, status=status, q=q, audit=audit)
    rows = readmodel.TABLE_ROWS[table](ctx.store, case_id, filters)
    write, media_type = writer
    try:
        data = write(spec, rows, case)
    except tables.XlsxUnavailable as exc:
        raise ApiError(503, "xlsx_unavailable", str(exc)) from exc
    ctx.cstore.log("table_export", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=case_id, detail={"table": table, "format": fmt, "rows": len(rows),
                                           "filters": {k: v for k, v in asdict(filters).items() if v}})
    return attachment(data, tables.file_name(case, table, fmt), media_type)
