"""``hermes ghostrecon serve | user | token``: the console server and its accounts (no agent involved).

Only stdlib imports at module level: ``register`` runs whenever Hermes builds its CLI parser.
"""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import sys
from typing import Callable, Dict, List

CONSOLE_VERBS = ("serve", "user", "token")
ADMIN_HINT = "hermes ghostrecon user add <nombre> --role admin"


def register(subs) -> None:
    serve = subs.add_parser("serve", help="Start the Ghost Recon web console")
    serve.add_argument("--host", help="Bind address (default from config, 127.0.0.1)")
    serve.add_argument("--port", type=int, help="Port (default from config, 9230)")
    serve.add_argument("--allow-remote", action="store_true",
                       help="Allow a non-loopback bind (put a TLS proxy or a tunnel in front)")
    user = subs.add_parser("user", help="Console users")
    user_subs = user.add_subparsers(dest="user_command")
    add = user_subs.add_parser("add", help="Create a user")
    add.add_argument("username")
    add.add_argument("--role", choices=["admin", "viewer"], default="viewer")
    add.add_argument("--password-stdin", action="store_true", help="Read the password from stdin (one line)")
    user_subs.add_parser("list", help="List users")
    passwd = user_subs.add_parser("passwd", help="Change a password (closes the user's sessions)")
    passwd.add_argument("username")
    passwd.add_argument("--password-stdin", action="store_true")
    for verb in ("disable", "enable"):
        user_subs.add_parser(verb, help=f"{verb.capitalize()} a user").add_argument("username")
    token = subs.add_parser("token", help="Console API tokens (Bearer)")
    token_subs = token.add_subparsers(dest="token_command")
    create = token_subs.add_parser("create", help="Create a token (shown once)")
    create.add_argument("--user", required=True)
    create.add_argument("--name", required=True)
    token_subs.add_parser("list", help="List tokens (never shows the secret)")
    token_subs.add_parser("revoke", help="Revoke a token").add_argument("token_id", type=int)


def is_loopback(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError:
        return False


def serve_preflight(cstore, host: str, allow_remote: bool) -> List[str]:
    errors = []
    if cstore.count_active_admins() == 0:
        errors.append(f"no hay ningún usuario admin activo. Crea uno con: {ADMIN_HINT}")
    if not is_loopback(host) and not allow_remote:
        errors.append(f"--host {host} no es loopback: usa un túnel SSH/Tailscale, o --allow-remote detrás de un proxy TLS")
    return errors


def _services():
    from .auth import AuthService
    from .settings import load_settings
    from .store import ConsoleStore
    cstore = ConsoleStore.open_default()
    return cstore, AuthService(cstore, load_settings())


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Contraseña: ")
    if getpass.getpass("Repite la contraseña: ") != first:
        raise ValueError("las contraseñas no coinciden")
    return first


def cmd_serve(args: argparse.Namespace) -> int:
    from .. import runtime
    from .settings import load_settings
    from .store import ConsoleStore
    settings = load_settings(host=args.host, port=args.port)
    cstore = ConsoleStore.open_default()
    errors = serve_preflight(cstore, settings.host, args.allow_remote)
    for err in errors:
        print(f"error: {err}", file=sys.stderr)
    if errors:
        return 1
    if not is_loopback(settings.host):
        print("AVISO: la consola escucha fuera de loopback; ponla detrás de un proxy TLS o usa un túnel.", file=sys.stderr)
    import uvicorn
    from .app import create_app
    app = create_app(settings, runtime.store(), cstore)
    shown = "localhost" if is_loopback(settings.host) else settings.host
    print(f"Ghost Recon Console en http://{shown}:{settings.port}  (Ctrl+C para detener)", flush=True)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", proxy_headers=False,
                server_header=False)
    return 0


def _user_add(args, cstore, auth) -> int:
    user = auth.add_user(args.username, _read_password(args.password_stdin), args.role)
    cstore.log("user_add", username=user["username"], target=user["username"], detail={"role": user["role"], "via": "cli"})
    print(f"Usuario {user['username']} creado con rol {user['role']}.")
    return 0


def _user_list(args, cstore, auth) -> int:
    users = cstore.list_users()
    if not users:
        print(f"Sin usuarios. Crea el primero con: {ADMIN_HINT}")
    for u in users:
        state = "deshabilitado" if u["disabled"] else "activo"
        print(f"{u['username']:<24} {u['role']:<7} {state:<14} último acceso: {u['last_login_at'] or '—'}")
    return 0


def _user_passwd(args, cstore, auth) -> int:
    auth.set_password(args.username, _read_password(args.password_stdin))
    cstore.log("user_passwd", username=args.username, target=args.username, detail={"via": "cli"})
    print(f"Contraseña de {args.username} actualizada; sus sesiones abiertas se cerraron.")
    return 0


def _user_toggle(disabled: bool) -> Callable:
    def _handler(args, cstore, auth) -> int:
        auth.set_disabled(args.username, disabled)
        cstore.log("user_disable" if disabled else "user_enable", username=args.username, target=args.username,
                   detail={"via": "cli"})
        print(f"Usuario {args.username} {'deshabilitado' if disabled else 'habilitado'}.")
        return 0
    return _handler


def _token_create(args, cstore, auth) -> int:
    raw, info = auth.create_api_token(args.user, args.name)
    print(f"Token '{info['name']}' creado para {args.user}. Guárdalo ahora: no se volverá a mostrar.")
    print(raw)
    return 0


def _token_list(args, cstore, auth) -> int:
    for t in cstore.list_tokens():
        state = "revocado" if t["revoked"] else "activo"
        print(f"{t['id']:>4}  grt_{t['prefix']}_…  {t['name']:<20} {t['username']:<16} {state:<9} "
              f"último uso: {t['last_used_at'] or '—'}")
    return 0


def _token_revoke(args, cstore, auth) -> int:
    if not auth.revoke_api_token(args.token_id):
        print(f"error: token {args.token_id} no encontrado o ya revocado", file=sys.stderr)
        return 1
    print(f"Token {args.token_id} revocado.")
    return 0


USER_HANDLERS: Dict[str, Callable] = {"add": _user_add, "list": _user_list, "passwd": _user_passwd,
                                      "disable": _user_toggle(True), "enable": _user_toggle(False)}
TOKEN_HANDLERS: Dict[str, Callable] = {"create": _token_create, "list": _token_list, "revoke": _token_revoke}


def _run_group(handlers: Dict[str, Callable], verb, usage: str, args) -> int:
    handler = handlers.get(verb)
    if handler is None:
        print(f"uso: {usage}", file=sys.stderr)
        return 2
    cstore, auth = _services()
    return handler(args, cstore, auth)


def dispatch(args: argparse.Namespace) -> int:
    try:
        if args.gr_command == "serve":
            return cmd_serve(args)
        if args.gr_command == "user":
            return _run_group(USER_HANDLERS, getattr(args, "user_command", None),
                              "ghostrecon user {add,list,passwd,disable,enable}", args)
        return _run_group(TOKEN_HANDLERS, getattr(args, "token_command", None), "ghostrecon token {create,list,revoke}",
                          args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
