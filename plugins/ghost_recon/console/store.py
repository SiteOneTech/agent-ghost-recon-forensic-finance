"""``console_*`` tables in the Ghost Recon DB: users, sessions, API tokens, audit log and the seal-check cache.

The console opens its OWN connection to the same SQLite file (WAL), so it never shares a connection or lock with
the case ``Store``. Case tables are only read here, for cross-case queries the case ``Store`` does not offer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.db import connect, migrate as migrate_case_schema, utcnow

CONSOLE_SCHEMA_VERSION = 1
ROLES = ("viewer", "admin")
_JSON_COLS = ("detail", "ref")
_USER_FIELDS = frozenset({"password_hash", "disabled", "last_login_at", "role"})

CONSOLE_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS console_schema_version (version INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS console_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('viewer', 'admin')),
        disabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS console_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES console_users(id) ON DELETE CASCADE,
        token_sha256 TEXT NOT NULL UNIQUE,
        csrf_token TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT,
        revoked INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS console_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES console_users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        token_sha256 TEXT NOT NULL UNIQUE,
        prefix TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS console_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        user_id INTEGER,
        username TEXT,
        ip TEXT,
        action TEXT NOT NULL,
        target TEXT,
        detail TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS console_seal_checks (
        audit_id TEXT PRIMARY KEY,
        ok INTEGER NOT NULL,
        checked_at TEXT NOT NULL,
        checked_by TEXT,
        detail TEXT NOT NULL DEFAULT '{}'
    )""",
]


def migrate_console(conn: sqlite3.Connection) -> int:
    for stmt in CONSOLE_SCHEMA:
        conn.execute(stmt)
    if conn.execute("SELECT version FROM console_schema_version").fetchone() is None:
        conn.execute("INSERT INTO console_schema_version(version) VALUES (?)", (CONSOLE_SCHEMA_VERSION,))
    conn.commit()
    return CONSOLE_SCHEMA_VERSION


def _d(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    for key in _JSON_COLS:
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except ValueError:
                pass
    return d


def _j(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


class ConsoleStore:
    """Reads/writes of the console tables. Thread-safe: one RLock around the private connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute("PRAGMA busy_timeout=5000")
            migrate_case_schema(self.conn)  # case tables first: cross-case reads join them
            migrate_console(self.conn)

    @classmethod
    def open(cls, path: str | Path) -> "ConsoleStore":
        return cls(connect(path))

    @classmethod
    def open_default(cls) -> "ConsoleStore":
        """Own connection to the active profile's Ghost Recon DB (see ``runtime.open_connection``)."""
        from .. import runtime
        return cls(runtime.open_connection())

    # ---------------------------------------------------------------- helpers
    def _all(self, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [_d(r) for r in self.conn.execute(sql, args)]

    def _one(self, sql: str, args: tuple = ()) -> Dict[str, Any]:
        with self._lock:
            return _d(self.conn.execute(sql, args).fetchone())

    def _insert(self, sql: str, args: tuple) -> int:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return int(cur.lastrowid)

    def _update(self, sql: str, args: tuple) -> int:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.rowcount

    # ---------------------------------------------------------------- users
    def create_user(self, username: str, password_hash: str, role: str) -> Dict[str, Any]:
        if role not in ROLES:
            raise ValueError(f"rol debe ser uno de {ROLES}")
        try:
            uid = self._insert("INSERT INTO console_users(username, password_hash, role, created_at) VALUES (?,?,?,?)",
                               (username, password_hash, role, utcnow()))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"el usuario ya existe: {username}") from exc
        return self.get_user_by_id(uid)

    def get_user(self, username: str) -> Dict[str, Any]:
        return self._one("SELECT * FROM console_users WHERE username=?", (username,))

    def get_user_by_id(self, user_id: int) -> Dict[str, Any]:
        return self._one("SELECT * FROM console_users WHERE id=?", (user_id,))

    def list_users(self) -> List[Dict[str, Any]]:
        return self._all("SELECT id, username, role, disabled, created_at, last_login_at FROM console_users ORDER BY username")

    def update_user(self, username: str, **fields: Any) -> bool:
        unknown = set(fields) - _USER_FIELDS
        if unknown:
            raise ValueError(f"campos no editables: {sorted(unknown)}")
        cols = ", ".join(f"{k}=?" for k in fields)
        return self._update(f"UPDATE console_users SET {cols} WHERE username=?", (*fields.values(), username)) > 0

    def count_active_admins(self) -> int:
        return int(self._one("SELECT COUNT(*) AS n FROM console_users WHERE role='admin' AND disabled=0")["n"])

    # ---------------------------------------------------------------- sessions
    def create_session(self, *, user_id: int, token_sha256: str, csrf_token: str, expires_at: str,
                       ip: str, user_agent: str) -> int:
        now = utcnow()
        return self._insert(
            "INSERT INTO console_sessions(user_id, token_sha256, csrf_token, created_at, last_seen_at, expires_at, ip,"
            " user_agent) VALUES (?,?,?,?,?,?,?,?)", (user_id, token_sha256, csrf_token, now, now, expires_at, ip, user_agent))

    def get_session(self, token_sha256: str) -> Dict[str, Any]:
        return self._one("SELECT s.*, u.username, u.role, u.disabled FROM console_sessions s"
                         " JOIN console_users u ON u.id = s.user_id WHERE s.token_sha256=?", (token_sha256,))

    def touch_session(self, session_id: int, ts: str) -> None:
        self._update("UPDATE console_sessions SET last_seen_at=? WHERE id=?", (ts, session_id))

    def revoke_session(self, session_id: int) -> None:
        self._update("UPDATE console_sessions SET revoked=1 WHERE id=?", (session_id,))

    def revoke_user_sessions(self, user_id: int) -> None:
        self._update("UPDATE console_sessions SET revoked=1 WHERE user_id=?", (user_id,))

    # ---------------------------------------------------------------- API tokens
    def create_token(self, *, user_id: int, name: str, token_sha256: str, prefix: str) -> int:
        return self._insert("INSERT INTO console_tokens(user_id, name, token_sha256, prefix, created_at) VALUES (?,?,?,?,?)",
                            (user_id, name, token_sha256, prefix, utcnow()))

    def get_token(self, token_sha256: str) -> Dict[str, Any]:
        return self._one("SELECT t.*, u.username, u.role, u.disabled FROM console_tokens t"
                         " JOIN console_users u ON u.id = t.user_id WHERE t.token_sha256=?", (token_sha256,))

    def list_tokens(self) -> List[Dict[str, Any]]:
        return self._all("SELECT t.id, t.name, t.prefix, t.created_at, t.last_used_at, t.revoked, u.username"
                         " FROM console_tokens t JOIN console_users u ON u.id = t.user_id ORDER BY t.id")

    def revoke_token(self, token_id: int) -> bool:
        return self._update("UPDATE console_tokens SET revoked=1 WHERE id=? AND revoked=0", (token_id,)) > 0

    def touch_token(self, token_id: int, ts: str) -> None:
        self._update("UPDATE console_tokens SET last_used_at=? WHERE id=?", (ts, token_id))

    # ---------------------------------------------------------------- audit log
    def log(self, action: str, *, user_id: Optional[int] = None, username: Optional[str] = None,
            ip: Optional[str] = None, target: Optional[str] = None, detail: Optional[dict] = None) -> int:
        return self._insert("INSERT INTO console_audit_log(ts, user_id, username, ip, action, target, detail)"
                            " VALUES (?,?,?,?,?,?,?)", (utcnow(), user_id, username, ip, action, target, _j(detail)))

    def list_audit_log(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._all("SELECT * FROM console_audit_log ORDER BY id DESC LIMIT ?", (int(limit),))

    # ---------------------------------------------------------------- seal-check cache
    def save_seal_check(self, audit_id: str, ok: bool, detail: Dict[str, Any], checked_by: str) -> Dict[str, Any]:
        with self._lock:
            self.conn.execute(
                "INSERT INTO console_seal_checks(audit_id, ok, checked_at, checked_by, detail) VALUES (?,?,?,?,?)"
                " ON CONFLICT(audit_id) DO UPDATE SET ok=excluded.ok, checked_at=excluded.checked_at,"
                " checked_by=excluded.checked_by, detail=excluded.detail",
                (audit_id, 1 if ok else 0, utcnow(), checked_by, _j(detail)))
            self.conn.commit()
        return self.get_seal_check(audit_id)

    def get_seal_check(self, audit_id: str) -> Dict[str, Any]:
        row = self._one("SELECT * FROM console_seal_checks WHERE audit_id=?", (audit_id,))
        if row:
            row["ok"] = bool(row["ok"])
        return row

    # ---------------------------------------------------------------- cross-case reads
    def recent_events(self, limit: int = 15) -> List[Dict[str, Any]]:
        return self._all("SELECT t.id, t.case_id, t.audit_id, t.ts, t.event_type, t.actor, t.description,"
                         " c.name AS case_name FROM timeline t JOIN cases c ON c.id = t.case_id"
                         " ORDER BY t.ts DESC, t.id DESC LIMIT ?", (int(limit),))
