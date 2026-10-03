"""Audit endpoints: detail with completion checks, internal runs, seal verification and deliverable downloads."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from ...core import service
from .. import readmodel
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..paths import resolve_within
from .cases import get_case_or_404

router = APIRouter(tags=["audits"])
SEQ_RE = re.compile(r"^[AR]\d{2,3}$")


def get_audit_or_404(ctx: ConsoleContext, case_id: str, seq: str) -> dict:
    get_case_or_404(ctx, case_id)
    audit = ctx.store.get_audit(f"{case_id}/{seq}") if SEQ_RE.match(seq) else {}
    if not audit:
        raise ApiError(404, "not_found", f"auditoría no encontrada: {seq}")
    return audit


@router.get("/cases/{case_id}/audits/{seq}")
def audit_detail(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
                 ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    return {**readmodel.audit_view(ctx.store, ctx.cstore, audit), "parent_audit_id": audit.get("parent_audit_id"),
            "context_md": audit.get("context_md"), "summary": audit.get("summary") or {},
            "completion": service.completion_report(ctx.store, audit)}


@router.get("/cases/{case_id}/audits/{seq}/runs")
def audit_runs(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.store.list_runs(get_audit_or_404(ctx, case_id, seq)["id"])}


@router.post("/cases/{case_id}/audits/{seq}/verify")
def verify_seal(case_id: str, seq: str, request: Request, principal: Principal = Depends(require("viewer")),
                ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    if audit["status"] != "sealed":
        raise ApiError(409, "not_sealed", "solo se verifican auditorías selladas")
    result = service.verify_audit(ctx.store, audit["id"])
    ok = bool(result.get("ok")) and result.get("db_matches") is not False
    detail = {k: result.get(k) for k in ("missing", "added", "modified", "file_count", "manifest_sha256", "db_matches")}
    check = ctx.cstore.save_seal_check(audit["id"], ok, detail, principal.username)
    ctx.cstore.log("seal_verify", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=audit["id"], detail={"ok": ok})
    return {"audit_id": audit["id"], "ok": ok, "checked_at": check["checked_at"], "detail": detail}


@router.get("/cases/{case_id}/audits/{seq}/reports")
def audit_reports(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
                  ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    return {"items": [{"id": r["id"], "kind": r["kind"], "format": r["format"], "version": r["version"],
                       "size": r["size"], "sha256": r["sha256"], "name": Path(r["path"]).name,
                       "created_at": r["created_at"]} for r in ctx.store.list_reports(audit["id"])]}


@router.get("/cases/{case_id}/audits/{seq}/reports/{report_id}/download")
def download_report(case_id: str, seq: str, report_id: int, request: Request,
                    principal: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    if audit["status"] != "sealed" and not principal.has("admin"):
        raise ApiError(403, "not_sealed", "los entregables de auditorías abiertas solo los descarga un admin")
    report = next((r for r in ctx.store.list_reports(audit["id"]) if r["id"] == report_id), None)
    path = resolve_within(report["path"], [audit["folder"]]) if report else None
    if path is None or not path.is_file():
        raise ApiError(404, "file_missing", "el archivo del entregable no está en la carpeta de la auditoría")
    ctx.cstore.log("report_download", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=f"{audit['id']}#{report_id}", detail={"file": path.name})
    return FileResponse(path, filename=path.name,
                        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
