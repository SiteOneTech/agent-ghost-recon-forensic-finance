"""Account administration (admin only): users, password resets, enable/disable, roles and API tokens.

The same AuthService rules as the CLI (username shape, 10-character passwords, the last active admin). Every change
goes to console_audit_log with the acting admin; an admin cannot disable or change the role of their own account here
(the guard against locking the console out from the browser)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..auth import AccountError, Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require

router = APIRouter(tags=["users"])
_PUBLIC_USER = ("id", "username", "role", "disabled", "created_at", "last_login_at")


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: Literal["viewer", "admin"] = "viewer"
    password: str = Field(min_length=1, max_length=256)
    password_confirm: str = Field(min_length=1, max_length=256)


class NewPassword(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    password_confirm: str = Field(min_length=1, max_length=256)


class RoleChange(BaseModel):
    role: Literal["viewer", "admin"]


class NewToken(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)


def _confirmed(password: str, again: str) -> str:
    if password != again:
        raise ApiError(422, "password_mismatch", "las contraseñas no coinciden")
    return password


def _not_self(principal: Principal, username: str) -> None:
    if username.strip().lower() == principal.username:
        raise ApiError(409, "self_action", "no puedes deshabilitar ni cambiar el rol de tu propio usuario")


def _account(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AccountError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc


def _log(ctx: ConsoleContext, request: Request, principal: Principal, action: str, target: str, **detail) -> None:
    ctx.cstore.log(action, user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=target, detail={**detail, "via": "console"})


@router.get("/users")
def list_users(_: Principal = Depends(require("admin")), ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.cstore.list_users()}


@router.post("/users", status_code=201)
def create_user(body: NewUser, request: Request, principal: Principal = Depends(require("admin")),
                ctx: ConsoleContext = Depends(get_ctx)):
    user = _account(ctx.auth.add_user, body.username, _confirmed(body.password, body.password_confirm), body.role)
    _log(ctx, request, principal, "user_add", user["username"], role=user["role"])
    return {"user": {key: user[key] for key in _PUBLIC_USER}}


@router.post("/users/{username}/password")
def reset_password(username: str, body: NewPassword, request: Request,
                   principal: Principal = Depends(require("admin")), ctx: ConsoleContext = Depends(get_ctx)):
    _account(ctx.auth.set_password, username, _confirmed(body.password, body.password_confirm))
    _log(ctx, request, principal, "user_passwd", username.strip().lower())
    return {"ok": True}


@router.post("/users/{username}/disable")
def disable_user(username: str, request: Request, principal: Principal = Depends(require("admin")),
                 ctx: ConsoleContext = Depends(get_ctx)):
    _not_self(principal, username)
    _account(ctx.auth.set_disabled, username, True)
    _log(ctx, request, principal, "user_disable", username.strip().lower())
    return {"ok": True}


@router.post("/users/{username}/enable")
def enable_user(username: str, request: Request, principal: Principal = Depends(require("admin")),
                ctx: ConsoleContext = Depends(get_ctx)):
    _account(ctx.auth.set_disabled, username, False)
    _log(ctx, request, principal, "user_enable", username.strip().lower())
    return {"ok": True}


@router.post("/users/{username}/role")
def change_role(username: str, body: RoleChange, request: Request, principal: Principal = Depends(require("admin")),
                ctx: ConsoleContext = Depends(get_ctx)):
    _not_self(principal, username)
    _account(ctx.auth.set_role, username, body.role)
    _log(ctx, request, principal, "user_role", username.strip().lower(), role=body.role)
    return {"ok": True}


@router.get("/tokens")
def list_tokens(_: Principal = Depends(require("admin")), ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.cstore.list_tokens()}


@router.post("/tokens", status_code=201)
def create_token(body: NewToken, request: Request, principal: Principal = Depends(require("admin")),
                 ctx: ConsoleContext = Depends(get_ctx)):
    raw, info = _account(ctx.auth.create_api_token, body.username, body.name, actor=principal, ip=client_ip(request))
    return {"token": raw, **info, "username": body.username.strip().lower()}


@router.post("/tokens/{token_id}/revoke")
def revoke_token(token_id: int, request: Request, principal: Principal = Depends(require("admin")),
                 ctx: ConsoleContext = Depends(get_ctx)):
    if not ctx.auth.revoke_api_token(token_id, actor=principal, ip=client_ip(request)):
        raise ApiError(404, "not_found", f"token no encontrado o ya revocado: {token_id}")
    return {"ok": True}
