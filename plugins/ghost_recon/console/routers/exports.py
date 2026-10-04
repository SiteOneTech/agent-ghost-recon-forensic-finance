"""Export endpoints (viewer): the case tables as CSV/XLSX with the filters of their JSON endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from .. import readmodel, tables
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..downloads import attachment
from .cases import get_case_or_404

router = APIRouter(tags=["exports"])


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
