"""Authentication endpoints: login (session cookie + CSRF token), logout, current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ..auth import AuthError, LoginLocked, Principal
from ..deps import SESSION_COOKIE, ApiError, ConsoleContext, client_ip, current_principal, get_ctx

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _user(principal: Principal) -> dict:
    return {"username": principal.username, "role": principal.role}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, ctx: ConsoleContext = Depends(get_ctx)):
    try:
        raw, principal = ctx.auth.login(body.username, body.password, ip=client_ip(request),
                                        user_agent=request.headers.get("user-agent", ""))
    except LoginLocked as exc:
        raise ApiError(429, "locked", str(exc), headers={"Retry-After": str(exc.retry_after)})
    except AuthError as exc:
        raise ApiError(401, "bad_credentials", str(exc))
    response.set_cookie(SESSION_COOKIE, raw, httponly=True, samesite="strict", path="/",
                        secure=request.url.scheme == "https", max_age=ctx.settings.session_max_days * 86400)
    return {"user": _user(principal), "csrf": principal.csrf}


@router.post("/auth/logout")
def logout(request: Request, response: Response, principal: Principal = Depends(current_principal),
           ctx: ConsoleContext = Depends(get_ctx)):
    ctx.auth.logout(principal, ip=client_ip(request))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(principal: Principal = Depends(current_principal)):
    return {"user": _user(principal), "csrf": principal.csrf, "via": principal.via}
