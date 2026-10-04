"""Cross-case search (viewer): ``GET /search?q=&types=case,finding,evidence,criteria&limit=``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import search as search_mod
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, get_ctx, require

router = APIRouter(tags=["search"])


@router.get("/search")
def search(q: str = Query(..., min_length=search_mod.MIN_QUERY, max_length=search_mod.MAX_QUERY), types: str = "",
           limit: int = Query(search_mod.DEFAULT_LIMIT, ge=1, le=search_mod.MAX_LIMIT),
           _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    wanted = tuple(dict.fromkeys(t.strip() for t in types.split(",") if t.strip())) or search_mod.TYPES
    unknown = [t for t in wanted if t not in search_mod.TYPES]
    if unknown:
        raise ApiError(422, "invalid_argument", f"tipo desconocido: {', '.join(unknown)} "
                                                f"(válidos: {', '.join(search_mod.TYPES)})")
    if len(q.strip()) < search_mod.MIN_QUERY:
        raise ApiError(422, "invalid_argument", f"escribe al menos {search_mod.MIN_QUERY} caracteres")
    return search_mod.search(ctx.store, q, types=wanted, limit=limit)
