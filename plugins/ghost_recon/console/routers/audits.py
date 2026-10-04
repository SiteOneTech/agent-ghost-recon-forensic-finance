"""Audit endpoints: detail with completion checks, internal runs, seal verification and deliverable downloads."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from ...core import service
from .. import integrity, readmodel
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..downloads import attachment
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
    check = integrity.record_seal_check(ctx.store, ctx.cstore, audit, principal.username)
    ctx.cstore.log("seal_verify", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=audit["id"], detail={"ok": check["ok"]})
    return {"audit_id": audit["id"], "ok": check["ok"], "checked_at": check["checked_at"], "detail": check["detail"]}


@router.get("/cases/{case_id}/audits/{seq}/reports")
def audit_reports(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
                  ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    return {"items": [{"id": r["id"], "kind": r["kind"], "format": r["format"], "version": r["version"],
                       "size": r["size"], "sha256": r["sha256"], "name": Path(r["path"]).name,
                       "created_at": r["created_at"]} for r in ctx.store.list_reports(audit["id"])]}


def _refuse(ctx: ConsoleContext, request: Request, principal: Principal, target: str, status: int, code: str,
            message: str, **detail) -> ApiError:
    """Every refused download is in the console audit log, with who asked and why."""
    ctx.cstore.log("report_download_denied", user_id=principal.user_id, username=principal.username,
                   ip=client_ip(request), target=target, detail={"code": code, **detail})
    return ApiError(status, code, message)


@router.get("/cases/{case_id}/audits/{seq}/reports/{report_id}/download")
def download_report(case_id: str, seq: str, report_id: int, request: Request,
                    principal: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """A deliverable of a sealed audit is re-hashed and served only if it still matches its seal entry and the hash
    the pack registered (409 ``hash_mismatch`` otherwise). Open audits' deliverables are for admins only."""
    audit = get_audit_or_404(ctx, case_id, seq)
    target = f"{audit['id']}#{report_id}"
    sealed = audit["status"] == "sealed"
    if not sealed and not principal.has("admin"):
        raise _refuse(ctx, request, principal, target, 403, "not_sealed",
                      "los entregables de auditorías abiertas solo los descarga un admin")
    report = next((r for r in ctx.store.list_reports(audit["id"]) if r["id"] == report_id), None)
    path = resolve_within(report["path"], [audit["folder"]]) if report else None
    if path is None or not path.is_file():
        raise _refuse(ctx, request, principal, target, 404, "file_missing",
                      "el archivo del entregable no está en la carpeta de la auditoría")
    if sealed:
        try:
            data = integrity.verified_bytes(Path(audit["folder"]), path, registered=report["sha256"] or "")
        except integrity.IntegrityError as exc:
            raise _refuse(ctx, request, principal, target, 409, "hash_mismatch",
                          f"El entregable no coincide con el sello de la auditoría: {exc.message}. "
                          "Verifica los sellos del caso antes de usarlo.", file=exc.rel, reason=exc.code)
    else:
        data = path.read_bytes()
    ctx.cstore.log("report_download", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=target, detail={"file": path.name})
    return attachment(data, path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
