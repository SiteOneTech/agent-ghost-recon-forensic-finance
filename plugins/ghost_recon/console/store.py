"""``console_*`` tables in the Ghost Recon DB: users, sessions, API tokens, audit log, seal-check cache, jobs and
exports.

The console opens its OWN connection to the same SQLite file (WAL), so it never shares a connection or lock with
the case ``Store``. Case tables are only read here, for cross-case queries the case ``Store`` does not offer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.db import connect, migrate as migrate_case_schema, utcnow

CONSOLE_SCHEMA_VERSION = 3
ROLES = ("viewer", "admin")
JOB_COMMANDS = ("new-open-case", "rerun-case", "review-case")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "orphaned")
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "orphaned")
EXPORT_SCOPES = ("case", "audit")
EXPORT_STATUSES = ("queued", "building", "succeeded", "failed", "expired")
EXPORT_PENDING = ("queued", "building")
_JSON_COLS = ("detail", "ref", "args", "argv", "tokens", "notify_argv")
_USER_FIELDS = frozenset({"password_hash", "disabled", "last_login_at", "role"})
_JOB_FIELDS = frozenset({"case_id", "context_file", "status", "pid", "pid_started", "runner_pid", "runner_started",
                         "session_id", "exit_code", "started_at", "finished_at", "result_text", "tokens", "error",
                         "phase", "notify_target"})
_EXPORT_FIELDS = frozenset({"status", "files_total", "files_done", "size", "sha256", "file_name", "error", "detail",
                            "started_at", "finished_at"})

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

# Version 1 is CONSOLE_SCHEMA above (H1; never edited). Each later version lists the statements that take a database
# from the previous version to it; migrate_console applies the missing ones in order.
CONSOLE_MIGRATIONS: Dict[int, List[str]] = {
    2: [
        """CREATE TABLE IF NOT EXISTS console_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command TEXT NOT NULL CHECK (command IN ('new-open-case', 'rerun-case', 'review-case')),
            case_id TEXT,
            folder TEXT NOT NULL,
            args TEXT NOT NULL DEFAULT '{}',
            argv TEXT NOT NULL DEFAULT '[]',
            context_file TEXT,
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'orphaned')),
            pid INTEGER,
            pid_started REAL,
            runner_pid INTEGER,
            runner_started REAL,
            session_id TEXT,
            exit_code INTEGER,
            launched_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            result_text TEXT,
            tokens TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            phase TEXT,
            notify_target TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS console_jobs_status ON console_jobs(status)",
        "CREATE INDEX IF NOT EXISTS console_jobs_case ON console_jobs(case_id)",
    ],
    3: [
        """CREATE TABLE IF NOT EXISTS console_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            scope TEXT NOT NULL CHECK (scope IN ('case', 'audit')),
            seq TEXT,
            include_unsealed INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'building', 'succeeded', 'failed', 'expired')),
            files_total INTEGER NOT NULL DEFAULT 0,
            files_done INTEGER NOT NULL DEFAULT 0,
            size INTEGER,
            sha256 TEXT,
            file_name TEXT,
            error TEXT,
            detail TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS console_exports_case ON console_exports(case_id)",
        # The ``hermes send`` argv of the job-end notice, planned by the server at launch like ``argv``.
        "ALTER TABLE console_jobs ADD COLUMN notify_argv TEXT NOT NULL DEFAULT '[]'",
    ],
}


def _stored_version(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT version FROM console_schema_version").fetchone()
    return int(row[0]) if row is not None else None


def migrate_console(conn: sqlite3.Connection) -> int:
    """Idempotent and versioned: the v1 baseline, then every migration above the stored version, then the new
    version in the one-row ``console_schema_version`` table.

    The server, its runners and the CLI may open the database at the same moment, and a step such as ``ALTER TABLE``
    cannot run twice. So the steps run inside ``BEGIN IMMEDIATE`` after reading the version again: a second migrator
    waits for the first one's commit and then finds nothing left to do."""
    for stmt in CONSOLE_SCHEMA:
        conn.execute(stmt)
    conn.commit()
    if (_stored_version(conn) or 0) >= CONSOLE_SCHEMA_VERSION:
        return CONSOLE_SCHEMA_VERSION
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = _stored_version(conn)
        if current is None:
            conn.execute("INSERT INTO console_schema_version(version) VALUES (1)")
            current = 1
        for version in sorted(v for v in CONSOLE_MIGRATIONS if v > current):
            for stmt in CONSOLE_MIGRATIONS[version]:
                conn.execute(stmt)
            conn.execute("UPDATE console_schema_version SET version=?", (version,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
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

    def _write(self, sql: str, args: tuple) -> sqlite3.Cursor:
        with self._lock:
            try:
                cur = self.conn.execute(sql, args)
                self.conn.commit()
            except sqlite3.Error:
                # A failed write (e.g. "database is locked") leaves the implicit transaction open, and every later
                # read on this connection would see that stale snapshot: a runner would never notice a cancel.
                self.conn.rollback()
                raise
            return cur

    def _insert(self, sql: str, args: tuple) -> int:
        return int(self._write(sql, args).lastrowid)

    def _update(self, sql: str, args: tuple) -> int:
        return self._write(sql, args).rowcount

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
                       ip: str, user_agent: str, now: str) -> int:
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

    def purge_sessions(self, *, now: str, idle_before: str) -> int:
        """Delete revoked sessions and the ones past their absolute or idle expiry; the number deleted. The stamps
        are ISO-8601 UTC strings in one format, so text order is time order."""
        return self._update("DELETE FROM console_sessions WHERE revoked=1 OR expires_at <= ? OR last_seen_at < ?",
                            (now, idle_before))

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
        self._write("INSERT INTO console_seal_checks(audit_id, ok, checked_at, checked_by, detail) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(audit_id) DO UPDATE SET ok=excluded.ok, checked_at=excluded.checked_at,"
                    " checked_by=excluded.checked_by, detail=excluded.detail",
                    (audit_id, 1 if ok else 0, utcnow(), checked_by, _j(detail)))
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

    # ---------------------------------------------------------------- jobs
    def create_job(self, *, command: str, folder: str, args: Dict[str, Any], argv: List[str], launched_by: str,
                   context_file: Optional[str] = None, case_id: Optional[str] = None,
                   notify_target: Optional[str] = None, notify_argv: Optional[List[str]] = None) -> Dict[str, Any]:
        if command not in JOB_COMMANDS:
            raise ValueError(f"orden desconocida: {command}")
        job_id = self._insert(
            "INSERT INTO console_jobs(command, case_id, folder, args, argv, context_file, status, launched_by,"
            " created_at, notify_target, notify_argv) VALUES (?,?,?,?,?,?,'queued',?,?,?,?)",
            (command, case_id, folder, _j(args), _j([str(a) for a in argv]), context_file, launched_by, utcnow(),
             notify_target or None, _j([str(a) for a in notify_argv or []])))
        return self.get_job(job_id)

    def get_job(self, job_id: int) -> Dict[str, Any]:
        return self._one("SELECT * FROM console_jobs WHERE id=?", (int(job_id),))

    def list_jobs(self, *, statuses: Iterable[str] = (), case_id: str = "", folder: str = "", limit: int = 200,
                  oldest_first: bool = False, before_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Newest first (oldest first for the dispatcher). ``case_id`` and ``folder`` together match either: a
        case's jobs include the ones launched on its folder before the case existed. ``before_id`` continues a
        newest-first page after the last id it returned."""
        where: List[str] = []
        args: List[Any] = []
        statuses = tuple(statuses)
        if statuses:
            where.append(f"status IN ({','.join('?' * len(statuses))})")
            args += statuses
        if before_id is not None:
            where.append("id < ?")
            args.append(int(before_id))
        scope = [(col, value) for col, value in (("case_id", case_id), ("folder", folder)) if value]
        if scope:
            where.append("(" + " OR ".join(f"{col}=?" for col, _ in scope) + ")")
            args += [value for _, value in scope]
        sql = "SELECT * FROM console_jobs" + (f" WHERE {' AND '.join(where)}" if where else "")
        sql += f" ORDER BY id {'ASC' if oldest_first else 'DESC'} LIMIT ?"
        return self._all(sql, (*args, int(limit)))

    def update_job(self, job_id: int, *, expect: Iterable[str] = (), **fields: Any) -> bool:
        """Update a job; with ``expect``, only while its status is one of those, so a cancel or an orphan verdict
        always wins over a late writer. True when the row matched."""
        unknown = set(fields) - _JOB_FIELDS
        if unknown or not fields:
            raise ValueError(f"campos no editables: {sorted(unknown) or 'ninguno'}")
        if "status" in fields and fields["status"] not in JOB_STATUSES:
            raise ValueError(f"estado inválido: {fields['status']}")
        expect = tuple(expect)
        values = [_j(v) if k == "tokens" else v for k, v in fields.items()]
        sql = f"UPDATE console_jobs SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?"
        if expect:
            sql += f" AND status IN ({','.join('?' * len(expect))})"
        return self._update(sql, (*values, int(job_id), *expect)) > 0

    # ---------------------------------------------------------------- exports
    def create_export(self, *, case_id: str, scope: str, seq: Optional[str], include_unsealed: bool,
                      created_by: str) -> Dict[str, Any]:
        if scope not in EXPORT_SCOPES:
            raise ValueError(f"alcance desconocido: {scope}")
        export_id = self._insert(
            "INSERT INTO console_exports(case_id, scope, seq, include_unsealed, status, created_by, created_at)"
            " VALUES (?,?,?,?,'queued',?,?)", (case_id, scope, seq, 1 if include_unsealed else 0, created_by, utcnow()))
        return self.get_export(export_id)

    def get_export(self, export_id: int) -> Dict[str, Any]:
        row = self._one("SELECT * FROM console_exports WHERE id=?", (int(export_id),))
        if row:
            row["include_unsealed"] = bool(row["include_unsealed"])
        return row

    def list_exports(self, *, statuses: Iterable[str] = (), limit: int = 1000) -> List[Dict[str, Any]]:
        """Newest first."""
        statuses = tuple(statuses)
        where = f" WHERE status IN ({','.join('?' * len(statuses))})" if statuses else ""
        rows = self._all(f"SELECT * FROM console_exports{where} ORDER BY id DESC LIMIT ?", (*statuses, int(limit)))
        for row in rows:
            row["include_unsealed"] = bool(row["include_unsealed"])
        return rows

    def update_export(self, export_id: int, *, expect: Iterable[str] = (), **fields: Any) -> bool:
        """Update an export; with ``expect``, only while its status is one of those. True when the row matched."""
        unknown = set(fields) - _EXPORT_FIELDS
        if unknown or not fields:
            raise ValueError(f"campos no editables: {sorted(unknown) or 'ninguno'}")
        if "status" in fields and fields["status"] not in EXPORT_STATUSES:
            raise ValueError(f"estado inválido: {fields['status']}")
        expect = tuple(expect)
        values = [_j(v) if k == "detail" else v for k, v in fields.items()]
        sql = f"UPDATE console_exports SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?"
        if expect:
            sql += f" AND status IN ({','.join('?' * len(expect))})"
        return self._update(sql, (*values, int(export_id), *expect)) > 0
