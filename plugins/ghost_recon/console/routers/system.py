"""System endpoints: control-panel overview, environment doctor and the console audit log."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from .. import CONSOLE_VERSION, readmodel
from ..auth import Principal
from ..commands import NO_ROOTS_MESSAGE
from ..deps import ConsoleContext, get_ctx, require
from ..settings import ConsoleSettings

router = APIRouter(tags=["system"])


def _approvals_mode() -> str:
    try:
        from hermes_cli.config import cfg_get, load_config_readonly
        return str(cfg_get(load_config_readonly(), "approvals", "single_query_mode", default="deny"))
    except Exception:  # standalone (outside Hermes): Hermes' documented default
        return "deny"


def _case_root_checks(settings: ConsoleSettings) -> List[Dict[str, Any]]:
    """One check per configured case root (exists, free space); no root configured is itself a failed check."""
    if not settings.case_roots:
        return [{"check": "console.case_roots", "ok": False, "detail": NO_ROOTS_MESSAGE}]
    checks = []
    for raw in settings.case_roots:
        path = Path(raw).expanduser()
        try:
            free = shutil.disk_usage(path).free if path.is_dir() else None
        except OSError:
            free = None
        checks.append({"check": f"console.case_roots: {raw}", "ok": free is not None,
                       "detail": f"{free / 1024 ** 3:.1f} GB libres" if free is not None
                       else "la carpeta no existe o no se puede leer"})
    return checks


@router.get("/system/overview")
def overview(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return readmodel.overview(ctx.store, ctx.cstore)


@router.get("/system/doctor")
def doctor(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    from ...commands import doctor_report
    report = doctor_report()
    mode = _approvals_mode()
    outcome = "aprobados automáticamente" if mode == "approve" else "bloqueados"
    roots = _case_root_checks(ctx.settings)
    checks = report["checks"] + [{"check": "approvals.single_query_mode", "ok": True,
                                  "detail": f"{mode}: comandos peligrosos en ejecuciones desatendidas {outcome}"}]
    return {"ok": report["ok"] and all(c["ok"] for c in roots), "checks": checks + roots,
            "settings": report["settings"],
            "console": {"version": CONSOLE_VERSION, "host": ctx.settings.host, "port": ctx.settings.port,
                        "case_roots": list(ctx.settings.case_roots), "max_parallel_jobs": ctx.settings.max_parallel_jobs,
                        "dashboard_url": ctx.settings.dashboard_url or None}}


@router.get("/system/audit-log")
def audit_log(limit: int = Query(200, ge=1, le=1000), _: Principal = Depends(require("admin")),
              ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.cstore.list_audit_log(limit)}
