"""System endpoints: control-panel overview, environment doctor and the console audit log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import CONSOLE_VERSION, readmodel
from ..auth import Principal
from ..deps import ConsoleContext, get_ctx, require

router = APIRouter(tags=["system"])


def _approvals_mode() -> str:
    try:
        from hermes_cli.config import cfg_get, load_config_readonly
        return str(cfg_get(load_config_readonly(), "approvals", "single_query_mode", default="deny"))
    except Exception:  # standalone (outside Hermes): Hermes' documented default
        return "deny"


@router.get("/system/overview")
def overview(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return readmodel.overview(ctx.store, ctx.cstore)


@router.get("/system/doctor")
def doctor(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    from ...commands import doctor_report
    report = doctor_report()
    mode = _approvals_mode()
    outcome = "aprobados automáticamente" if mode == "approve" else "bloqueados"
    checks = report["checks"] + [{"check": "approvals.single_query_mode", "ok": True,
                                  "detail": f"{mode}: comandos peligrosos en ejecuciones desatendidas {outcome}"}]
    return {"ok": report["ok"], "checks": checks, "settings": report["settings"],
            "console": {"version": CONSOLE_VERSION, "host": ctx.settings.host, "port": ctx.settings.port}}


@router.get("/system/audit-log")
def audit_log(limit: int = Query(200, ge=1, le=1000), _: Principal = Depends(require("admin")),
              ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.cstore.list_audit_log(limit)}
