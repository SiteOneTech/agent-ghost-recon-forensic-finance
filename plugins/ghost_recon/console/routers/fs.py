"""Folder browser endpoints (viewer): configured case roots, listing, search and pre-launch inspection, all jailed
to ``case_roots`` by ``fsjail``."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query

from .. import fsjail
from ..auth import Principal
from ..commands import MISSING_ROOTS_MESSAGE, NO_ROOTS_MESSAGE
from ..deps import ApiError, ConsoleContext, get_ctx, require
from ..store import ACTIVE_STATUSES

router = APIRouter(tags=["fs"])
_HTTP_STATUS = {"outside_roots": 403}


def _hint(ctx: ConsoleContext) -> str:
    return NO_ROOTS_MESSAGE if not ctx.settings.case_roots else MISSING_ROOTS_MESSAGE


def _roots(ctx: ConsoleContext) -> List:
    roots = ctx.jobs.roots()
    if not roots:
        raise ApiError(409, "no_case_roots", _hint(ctx))
    return roots


def _jailed(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except fsjail.FsJailError as exc:
        raise ApiError(_HTTP_STATUS.get(exc.code, 422), exc.code, exc.message) from exc


@router.get("/fs/roots")
def roots(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    found = ctx.jobs.roots()
    return {"items": fsjail.roots_view(found), "configured": bool(ctx.settings.case_roots),
            "hint": None if found else _hint(ctx)}


@router.get("/fs/list")
def list_folder(path: str = Query(..., min_length=1, max_length=4096), _: Principal = Depends(require("viewer")),
                ctx: ConsoleContext = Depends(get_ctx)):
    return _jailed(fsjail.list_dir, path, _roots(ctx), store=ctx.store, audits_dirname=ctx.jobs.audits_dirname())


@router.get("/fs/search")
def search(q: str = Query(..., max_length=200), _: Principal = Depends(require("viewer")),
           ctx: ConsoleContext = Depends(get_ctx)):
    return _jailed(fsjail.search, q, _roots(ctx), skip=(ctx.jobs.audits_dirname(),))


@router.get("/fs/inspect")
def inspect(path: str = Query(..., min_length=1, max_length=4096), _: Principal = Depends(require("viewer")),
            ctx: ConsoleContext = Depends(get_ctx)):
    return _jailed(fsjail.inspect, path, _roots(ctx), store=ctx.store, audits_dirname=ctx.jobs.audits_dirname(),
                   defaults=ctx.jobs.defaults(), active_jobs=ctx.cstore.list_jobs(statuses=ACTIVE_STATUSES))
