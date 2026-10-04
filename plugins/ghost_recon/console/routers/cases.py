"""Case endpoints (read-only): list, detail, timeline, findings, evidence, criteria and research notes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core import service
from .. import readmodel
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, get_ctx, require

router = APIRouter(tags=["cases"])


def get_case_or_404(ctx: ConsoleContext, case_id: str) -> dict:
    case = ctx.store.get_case(case_id)
    if not case or case["id"] != case_id:  # canonical ids only (get_case also matches slug / root path)
        raise ApiError(404, "not_found", f"caso no encontrado: {case_id}")
    return case


@router.get("/cases")
def list_cases(q: str = "", status: str = "", risk: str = "", _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    if risk not in ("", "any", *readmodel.RISKS):
        raise ApiError(422, "invalid_argument", f"riesgo desconocido: {risk} (any, {', '.join(readmodel.RISKS)})")
    return {"items": readmodel.list_cases(ctx.store, ctx.cstore, q=q, status=status, risk=risk)}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return readmodel.case_detail(ctx.store, ctx.cstore, get_case_or_404(ctx, case_id))


@router.get("/cases/{case_id}/timeline")
def case_timeline(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    t = service.timeline(ctx.store, case_id)
    return {"items": readmodel.timeline_rows(ctx.store, case_id, readmodel.TableFilters()), "audits": t["audits"],
            "findings_evolution": t["findings_evolution"]}


@router.get("/cases/{case_id}/findings")
def findings(case_id: str, kind: str = "", risk: str = "", status: str = "", q: str = "",
             _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    filters = readmodel.TableFilters(kind=kind, risk=risk, status=status, q=q)
    return {"items": readmodel.findings_rows(ctx.store, case_id, filters)}


@router.get("/cases/{case_id}/findings/{finding_id}")
def finding(case_id: str, finding_id: str, _: Principal = Depends(require("viewer")),
            ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    row = ctx.store.get_finding(case_id, finding_id)
    if not row:
        raise ApiError(404, "not_found", f"hallazgo no encontrado: {finding_id}")
    return row


@router.get("/cases/{case_id}/evidence")
def evidence(case_id: str, status: str = "", audit: str = "", q: str = "", cursor: str = "", limit: int = 100,
             _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    rows = readmodel.evidence_rows(ctx.store, case_id, readmodel.TableFilters(status=status, audit=audit, q=q))
    items, next_cursor = readmodel.page(rows, cursor, limit)
    return {"items": items, "next_cursor": next_cursor, "total": len(rows)}


@router.get("/cases/{case_id}/evidence/stats")
def evidence_stats(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    rows = ctx.store.list_evidence(case_id)
    return {"statuses": ctx.store.evidence_stats(case_id), "blocks": readmodel.count_by(rows, "block"),
            "types": readmodel.count_by(rows, "ext")}


@router.get("/cases/{case_id}/criteria")
def criteria(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    return {"items": readmodel.criteria_rows(ctx.store, case_id, readmodel.TableFilters())}


@router.get("/cases/{case_id}/research")
def research(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    return {"items": ctx.store.list_research_notes(case_id)}
