"""FastAPI dependencies shared by the routers: app context, principal resolution, role checks, API errors."""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from ..core.db import Store
from .auth import AuthService, Principal
from .settings import ConsoleSettings
from .store import ConsoleStore

CSRF_HEADER = "x-gr-csrf"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ApiError(HTTPException):
    """HTTP error rendered as ``{"error": {"code", "message"}}`` by the app's exception handler."""

    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status_code=status, detail={"code": code, "message": message}, headers=headers)


@dataclass
class ConsoleContext:
    settings: ConsoleSettings
    store: Store
    cstore: ConsoleStore
    auth: AuthService


def get_ctx(request: Request) -> ConsoleContext:
    return request.app.state.gr


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def session_cookie_name(settings: ConsoleSettings) -> str:
    """Per-console cookie name: browsers share host-only cookies across ports, so each console needs its own."""
    return f"gr_session_{settings.port}"


def _same(sent: str, expected: str) -> bool:
    return hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))


def current_principal(request: Request, ctx: ConsoleContext = Depends(get_ctx)) -> Principal:
    """Bearer token (API clients, CSRF-exempt: no cookie involved) or session cookie (browser, CSRF-checked)."""
    authz = request.headers.get("authorization", "")
    if authz[:7].lower() == "bearer ":
        principal = ctx.auth.resolve_bearer(authz[7:].strip())
        if principal is None:
            raise ApiError(401, "invalid_token", "token inválido o revocado")
        return principal
    principal = ctx.auth.resolve_session(request.cookies.get(session_cookie_name(ctx.settings), ""))
    if principal is None:
        raise ApiError(401, "unauthenticated", "inicia sesión")
    if request.method not in SAFE_METHODS and not _same(request.headers.get(CSRF_HEADER, ""), principal.csrf or ""):
        raise ApiError(403, "csrf", "falta o no coincide la cabecera anti-CSRF")
    return principal


def require(role: str):
    """Dependency factory: the principal must hold ``role`` (admin implies viewer)."""
    def _dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has(role):
            raise ApiError(403, "forbidden", f"requiere rol {role}")
        return principal
    return _dependency
