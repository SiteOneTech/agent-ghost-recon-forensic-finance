"""Console authentication: scrypt passwords, server-side sessions, API tokens and login lockout.

Raw session and API tokens are never stored, only their SHA-256. Time comes from an injectable clock so expiry
and lockout are testable without sleeping.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .settings import ConsoleSettings
from .store import ROLES, ConsoleStore

_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
_SCRYPT_MAXMEM = 64 * 1024 * 1024
ROLE_RANK = {"viewer": 1, "admin": 2}
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
MIN_PASSWORD = 10
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=5)
TOUCH_EVERY = timedelta(seconds=60)
TOKEN_PREFIX = "grt"
_dummy_hash: Optional[str] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, maxmem=_SCRYPT_MAXMEM, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = encoded.split("$")
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p),
                                maxmem=_SCRYPT_MAXMEM, dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def _equalising_hash() -> str:
    """Hash checked when the user does not exist, so a miss costs the same time as a wrong password."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_urlsafe(16))
    return _dummy_hash


class AccountError(ValueError):
    """An account rule the caller can fix; ``status`` and ``code`` map it to the API error envelope."""
    status = 422
    code = "invalid_argument"


class UnknownUser(AccountError):
    status = 404
    code = "not_found"


class AccountConflict(AccountError):
    status = 409
    code = "conflict"


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(f"la contraseña debe tener al menos {MIN_PASSWORD} caracteres")


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str
    via: str  # "session" | "token"
    session_id: Optional[int] = None
    csrf: Optional[str] = None

    def has(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK[role]


class AuthError(Exception):
    """Bad credentials or unusable account; the message is safe to show to the user."""


class LoginLocked(AuthError):
    def __init__(self, retry_after: int):
        super().__init__(f"demasiados intentos fallidos; reintenta en {retry_after} s")
        self.retry_after = retry_after


class AuthService:
    def __init__(self, cstore: ConsoleStore, settings: ConsoleSettings, clock: Callable[[], datetime] = _utcnow):
        self.cstore = cstore
        self.settings = settings
        self.clock = clock
        self._failures: Dict[str, List[datetime]] = {}
        self._locked_until: Dict[str, datetime] = {}
        self._last_admin_lock = threading.Lock()  # protects last-admin checks from concurrent demote/disable

    # ------------------------------------------------------------------ accounts
    def add_user(self, username: str, password: str, role: str) -> Dict:
        username = (username or "").strip().lower()
        if not USERNAME_RE.match(username):
            raise AccountError("usuario: 2-32 caracteres en minúscula (a-z, 0-9, punto, guion o guion bajo)")
        if role not in ROLES:
            raise AccountError(f"rol debe ser uno de {ROLES}")
        _check_password(password)
        try:
            return self.cstore.create_user(username, hash_password(password), role)
        except ValueError as exc:  # UNIQUE(username)
            raise AccountConflict(str(exc)) from exc

    def set_password(self, username: str, password: str) -> None:
        _check_password(password)
        user = self._require_user(username)
        self.cstore.update_user(user["username"], password_hash=hash_password(password))
        self.cstore.revoke_user_sessions(user["id"])

    def set_disabled(self, username: str, disabled: bool) -> None:
        user = self._require_user(username)
        with self._last_admin_lock:
            if disabled and self._is_last_active_admin(user):
                raise AccountConflict("no se puede deshabilitar el último admin activo")
            self.cstore.update_user(user["username"], disabled=1 if disabled else 0)
        if disabled:
            self.cstore.revoke_user_sessions(user["id"])

    def set_role(self, username: str, role: str) -> None:
        """Change a user's role; the last active admin cannot be demoted (nobody could administer the console)."""
        if role not in ROLES:
            raise AccountError(f"rol debe ser uno de {ROLES}")
        user = self._require_user(username)
        with self._last_admin_lock:
            if role != "admin" and self._is_last_active_admin(user):
                raise AccountConflict("no se puede quitar el rol admin al último admin activo")
            self.cstore.update_user(user["username"], role=role)

    def _is_last_active_admin(self, user: Dict) -> bool:
        return user["role"] == "admin" and not user["disabled"] and self.cstore.count_active_admins() <= 1

    def _require_user(self, username: str) -> Dict:
        user = self.cstore.get_user((username or "").strip().lower())
        if not user:
            raise UnknownUser(f"usuario no encontrado: {username}")
        return user

    # ------------------------------------------------------------------ login and sessions
    def login(self, username: str, password: str, *, ip: str = "", user_agent: str = "") -> Tuple[str, Principal]:
        uname = (username or "").strip().lower()
        keys = [f"u:{uname}", f"ip:{ip}"]
        now = self.clock()
        for key in keys:
            until = self._locked_until.get(key)
            if until and until > now:
                raise LoginLocked(int((until - now).total_seconds()) + 1)
        user = self.cstore.get_user(uname)
        valid = verify_password(password or "", user["password_hash"] if user else _equalising_hash())
        if not (user and valid and not user["disabled"]):
            self._register_failure(keys, now)
            self.cstore.log("login_failed", username=uname, ip=ip)
            raise AuthError("usuario o contraseña incorrectos")
        for key in keys:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)
        raw = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        sid = self.cstore.create_session(user_id=user["id"], token_sha256=_sha(raw), csrf_token=csrf,
                                         expires_at=_iso(now + timedelta(days=self.settings.session_max_days)),
                                         ip=ip, user_agent=(user_agent or "")[:200], now=_iso(now))
        self.cstore.update_user(uname, last_login_at=_iso(now))
        self.cstore.log("login", user_id=user["id"], username=uname, ip=ip)
        return raw, Principal(user["id"], uname, user["role"], "session", sid, csrf)

    def _register_failure(self, keys: List[str], now: datetime) -> None:
        for key in keys:
            recent = [t for t in self._failures.get(key, []) if now - t < FAILURE_WINDOW] + [now]
            if len(recent) >= MAX_FAILURES:
                self._locked_until[key] = now + LOCK_DURATION
                recent = []
            self._failures[key] = recent

    def resolve_session(self, raw: str) -> Optional[Principal]:
        if not raw:
            return None
        s = self.cstore.get_session(_sha(raw))
        if not s or s["revoked"] or s["disabled"]:
            return None
        now = self.clock()
        if _parse(s["expires_at"]) <= now:
            return None
        idle = now - _parse(s["last_seen_at"])
        if idle > timedelta(hours=self.settings.session_idle_hours):
            return None
        if idle >= TOUCH_EVERY:
            self.cstore.touch_session(s["id"], _iso(now))
        return Principal(s["user_id"], s["username"], s["role"], "session", s["id"], s["csrf_token"])

    def logout(self, principal: Principal, ip: str = "") -> None:
        if principal.session_id:
            self.cstore.revoke_session(principal.session_id)
        self.cstore.log("logout", user_id=principal.user_id, username=principal.username, ip=ip)

    # ------------------------------------------------------------------ API tokens
    def create_api_token(self, username: str, name: str, *, actor: Optional[Principal] = None,
                         ip: str = "") -> Tuple[str, Dict]:
        """Create a Bearer token; the raw value is returned once. ``actor`` is who acts (an admin in the console);
        the CLI omits it and the owner is recorded, as before."""
        user = self._require_user(username)
        if user["disabled"]:
            raise AccountConflict("el usuario está deshabilitado")
        label = (name or "").strip()[:80] or "token"
        prefix = secrets.token_hex(4)
        raw = f"{TOKEN_PREFIX}_{prefix}_{secrets.token_urlsafe(32)}"
        token_id = self.cstore.create_token(user_id=user["id"], name=label, token_sha256=_sha(raw), prefix=prefix)
        self.cstore.log("token_create", user_id=actor.user_id if actor else user["id"],
                        username=actor.username if actor else user["username"], ip=ip or None, target=str(token_id),
                        detail={"name": label, "user": user["username"]})
        return raw, {"id": token_id, "prefix": prefix, "name": label}

    def resolve_bearer(self, raw: str) -> Optional[Principal]:
        if not raw or not raw.startswith(f"{TOKEN_PREFIX}_"):
            return None
        t = self.cstore.get_token(_sha(raw))
        if not t or t["revoked"] or t["disabled"]:
            return None
        now = self.clock()
        if not t["last_used_at"] or now - _parse(t["last_used_at"]) >= TOUCH_EVERY:
            self.cstore.touch_token(t["id"], _iso(now))
        return Principal(t["user_id"], t["username"], t["role"], "token")

    def revoke_api_token(self, token_id: int, *, actor: Optional[Principal] = None, ip: str = "") -> bool:
        revoked = self.cstore.revoke_token(token_id)
        if revoked:
            self.cstore.log("token_revoke", user_id=actor.user_id if actor else None,
                            username=actor.username if actor else None, ip=ip or None, target=str(token_id))
        return revoked
