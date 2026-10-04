"""SQLite schema and data-access layer for Ghost Recon cases.

Contract:
    * ``connect(path)`` opens a connection outside Hermes (CLI standalone, tests). Inside Hermes the caller
      passes the connection from ``plugins.plugin_storage.plugin_db("ghost-recon", "ghostrecon.db")``.
    * ``Store(conn)`` owns every read/write. Rows are returned as plain dicts; JSON columns are decoded.
    * ``migrate(conn)`` is idempotent and versioned (``schema_version`` table).
    * IDs: cases ``GRC-<slug>-<yyyymmdd>``; audits ``<case>/A01``; reviews ``<case>/R01``;
      findings ``EXC-nn`` / ``ANO-nn`` / ``FND-nn`` / ``Q-nn`` and criteria ``CRIT-nn`` are per case and
      continue the series across audits (``next_series_id``).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = 1

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL UNIQUE,
        audits_dir TEXT NOT NULL DEFAULT 'GhostRecon_Audits',
        status TEXT NOT NULL DEFAULT 'open',
        base_currency TEXT NOT NULL DEFAULT 'USD',
        language TEXT NOT NULL DEFAULT 'es',
        context_md TEXT,
        last_audit_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS audits (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        folder TEXT NOT NULL,
        parent_audit_id TEXT,
        context_md TEXT,
        out_override TEXT,
        started_at TEXT NOT NULL,
        sealed_at TEXT,
        seal_sha256 TEXT,
        model_json TEXT,
        summary TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        filename TEXT NOT NULL,
        ext TEXT NOT NULL DEFAULT '',
        size INTEGER NOT NULL DEFAULT 0,
        mtime TEXT,
        sha256 TEXT NOT NULL,
        md5 TEXT NOT NULL DEFAULT '',
        zip_member INTEGER NOT NULL DEFAULT 0,
        first_audit_id TEXT,
        status TEXT NOT NULL DEFAULT 'NEW',
        block TEXT NOT NULL DEFAULT 'other',
        doc_type TEXT,
        doc_date TEXT,
        entity TEXT,
        review_status TEXT NOT NULL DEFAULT 'Pending',
        confidence TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}',
        UNIQUE(case_id, path)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_evidence_hash ON evidence(case_id, sha256)""",
    """CREATE TABLE IF NOT EXISTS findings (
        id TEXT NOT NULL,
        case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        audit_id TEXT,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        amount REAL,
        currency TEXT,
        entity TEXT,
        counterparty TEXT,
        date TEXT,
        category TEXT,
        risk TEXT NOT NULL DEFAULT 'medium',
        confidence TEXT NOT NULL DEFAULT 'UNRESOLVED',
        label TEXT NOT NULL DEFAULT 'UNKNOWN',
        status TEXT NOT NULL DEFAULT 'open',
        evidence_refs TEXT NOT NULL DEFAULT '[]',
        next_evidence TEXT,
        owner TEXT,
        history TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (case_id, id)
    )""",
    """CREATE TABLE IF NOT EXISTS criteria (
        id TEXT NOT NULL,
        case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        audit_id TEXT,
        date TEXT,
        author TEXT NOT NULL,
        text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending_agreement',
        created_at TEXT NOT NULL,
        PRIMARY KEY (case_id, id)
    )""",
    """CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        path TEXT NOT NULL,
        format TEXT NOT NULL,
        version TEXT NOT NULL DEFAULT 'v1',
        sha256 TEXT NOT NULL DEFAULT '',
        size INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        role TEXT,
        status TEXT NOT NULL DEFAULT 'planned',
        started_at TEXT NOT NULL,
        finished_at TEXT,
        input TEXT NOT NULL DEFAULT '{}',
        output TEXT NOT NULL DEFAULT '{}',
        summary TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        audit_id TEXT,
        ts TEXT NOT NULL,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT 'ghost-recon',
        description TEXT NOT NULL,
        ref TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS research_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        audit_id TEXT,
        action TEXT NOT NULL,
        query TEXT NOT NULL DEFAULT '',
        url TEXT,
        title TEXT,
        snippet TEXT,
        relevance REAL,
        sha256 TEXT NOT NULL DEFAULT '',
        saved_path TEXT,
        created_at TEXT NOT NULL
    )""",
]

FINDING_PREFIX = {"exception": "EXC", "anomaly": "ANO", "finding": "FND", "question": "Q"}
JSON_COLS = {"meta", "summary", "evidence_refs", "history", "input", "output", "ref"}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a Ghost Recon DB outside Hermes (tests / standalone CLI). WAL + foreign keys."""
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    for stmt in SCHEMA:
        conn.execute(stmt)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(row[0]) < SCHEMA_VERSION:
        # Future migrations go here, keyed on the stored version.
        conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
    conn.commit()
    return SCHEMA_VERSION


def _row(r: Any) -> Dict[str, Any]:
    if r is None:
        return {}
    d = dict(r) if not isinstance(r, dict) else dict(r)
    for k in list(d):
        if k in JSON_COLS and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def _j(v: Any) -> str:
    return json.dumps(v if v is not None else {}, ensure_ascii=False, default=str)


def _locked(fn):
    """Serialise Store methods: one connection is shared by every session/thread of a gateway process."""
    def wrapper(self, *a, **k):
        with self._lock:
            try:
                return fn(self, *a, **k)
            except Exception:
                # A failed write (e.g. "database is locked") leaves the implicit transaction open, and every later
                # read on the shared connection would see that stale snapshot and later writes would fail.
                self.conn.rollback()
                raise
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class Store:
    """All reads and writes. Methods commit; callers never touch the connection. Thread-safe (RLock)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._lock = threading.RLock()
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        with self._lock:
            migrate(conn)


    # ---------------------------------------------------------------- cases
    @_locked
    def create_case(self, *, id: str, slug: str, name: str, root_path: str, audits_dir: str,
                    base_currency: str = "USD", language: str = "es", context_md: Optional[str] = None,
                    meta: Optional[dict] = None) -> Dict[str, Any]:
        now = utcnow()
        self.conn.execute(
            "INSERT INTO cases(id, slug, name, root_path, audits_dir, status, base_currency, language, context_md,"
            " created_at, updated_at, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (id, slug, name, root_path, audits_dir, "open", base_currency, language, context_md, now, now, _j(meta)),
        )
        self.conn.commit()
        return self.get_case(id)

    @_locked
    def get_case(self, key: str) -> Dict[str, Any]:
        """Lookup by id, slug or root_path (exact)."""
        r = self.conn.execute(
            "SELECT * FROM cases WHERE id=? OR slug=? OR root_path=? LIMIT 1", (key, key, key)).fetchone()
        return _row(r)

    @_locked
    def list_cases(self) -> List[Dict[str, Any]]:
        return [_row(r) for r in self.conn.execute("SELECT * FROM cases ORDER BY created_at DESC")]

    @_locked
    def update_case(self, case_id: str, **fields: Any) -> None:
        self._update("cases", "id", case_id, fields)

    # ---------------------------------------------------------------- audits
    @_locked
    def next_audit_seq(self, case_id: str, kind_prefix: str = "A") -> int:
        like = f"{case_id}/{kind_prefix}%"
        r = self.conn.execute("SELECT MAX(seq) FROM audits WHERE case_id=? AND id LIKE ?", (case_id, like)).fetchone()
        return int(r[0] or 0) + 1

    @_locked
    def create_audit(self, *, id: str, case_id: str, seq: int, kind: str, folder: str,
                     parent_audit_id: Optional[str] = None, context_md: Optional[str] = None,
                     out_override: Optional[str] = None, meta: Optional[dict] = None) -> Dict[str, Any]:
        now = utcnow()
        self.conn.execute(
            "INSERT INTO audits(id, case_id, seq, kind, status, folder, parent_audit_id, context_md, out_override,"
            " started_at, created_at, updated_at, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (id, case_id, seq, kind, "open", folder, parent_audit_id, context_md, out_override, now, now, now, _j(meta)),
        )
        self.conn.execute("UPDATE cases SET last_audit_id=?, updated_at=? WHERE id=?", (id, now, case_id))
        self.conn.commit()
        return self.get_audit(id)

    @_locked
    def get_audit(self, audit_id: str) -> Dict[str, Any]:
        return _row(self.conn.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone())

    @_locked
    def list_audits(self, case_id: str, kinds: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM audits WHERE case_id=? ORDER BY started_at, id", (case_id,))
        out = [_row(r) for r in rows]
        if kinds:
            ks = set(kinds)
            out = [a for a in out if a["kind"] in ks]
        return out

    @_locked
    def last_sealed_audit(self, case_id: str) -> Dict[str, Any]:
        r = self.conn.execute(
            "SELECT * FROM audits WHERE case_id=? AND status='sealed' AND kind IN ('initial','rerun')"
            " ORDER BY seq DESC LIMIT 1", (case_id,)).fetchone()
        return _row(r)

    @_locked
    def update_audit(self, audit_id: str, **fields: Any) -> None:
        self._update("audits", "id", audit_id, fields)

    # ---------------------------------------------------------------- evidence
    @_locked
    def known_hashes(self, case_id: str, exclude_audit_id: Optional[str] = None) -> Dict[str, str]:
        """sha256 -> path of evidence AUDITED before (assigned to an audit other than the excluded one).
        Rows registered by ``open_case`` but not yet assigned to an audit are not 'known'."""
        q = "SELECT sha256, path FROM evidence WHERE case_id=? AND first_audit_id IS NOT NULL"
        args: list = [case_id]
        if exclude_audit_id:
            q += " AND first_audit_id<>?"
            args.append(exclude_audit_id)
        return {r[0]: r[1] for r in self.conn.execute(q, args)}

    @_locked
    def upsert_evidence(self, case_id: str, rows: Iterable[Dict[str, Any]], *, preserve_assigned: bool = False) -> int:
        """Insert new paths; refresh size/mtime/hash/block of known paths. With ``preserve_assigned`` rows already
        assigned to an audit are left untouched (``open_case`` must never overwrite an audited hash)."""
        now = utcnow()
        n = 0
        for row in rows:
            existing = self.conn.execute(
                "SELECT id, first_audit_id, status FROM evidence WHERE case_id=? AND path=?",
                (case_id, row["path"])).fetchone()
            if existing:
                if preserve_assigned and existing[1]:
                    continue
                self.conn.execute(
                    "UPDATE evidence SET size=?, mtime=?, sha256=?, md5=?, block=?, updated_at=? WHERE id=?",
                    (row.get("size", 0), row.get("mtime"), row["sha256"], row.get("md5", ""),
                     row.get("block", "other"), now, existing[0]))
            else:
                self.conn.execute(
                    "INSERT INTO evidence(case_id, path, filename, ext, size, mtime, sha256, md5, zip_member,"
                    " first_audit_id, status, block, doc_type, created_at, updated_at, meta)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (case_id, row["path"], row["filename"], row.get("ext", ""), row.get("size", 0), row.get("mtime"),
                     row["sha256"], row.get("md5", ""), 1 if row.get("zip_member") else 0, row.get("first_audit_id"),
                     row.get("status", "NEW"), row.get("block", "other"), row.get("doc_type"), now, now,
                     _j(row.get("meta"))))
            n += 1
        self.conn.commit()
        return n

    @_locked
    def list_evidence(self, case_id: str, *, first_audit_id: Optional[str] = None, status: Optional[str] = None,
                      block: Optional[str] = None, limit: int = 0) -> List[Dict[str, Any]]:
        q = "SELECT * FROM evidence WHERE case_id=?"
        args: list = [case_id]
        if first_audit_id:
            q += " AND first_audit_id=?"; args.append(first_audit_id)
        if status:
            q += " AND status=?"; args.append(status)
        if block:
            q += " AND block=?"; args.append(block)
        q += " ORDER BY path"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [_row(r) for r in self.conn.execute(q, args)]

    @_locked
    def evidence_stats(self, case_id: str, first_audit_id: Optional[str] = None) -> Dict[str, int]:
        q = "SELECT status, COUNT(*) FROM evidence WHERE case_id=?"
        args: list = [case_id]
        if first_audit_id:
            q += " AND first_audit_id=?"; args.append(first_audit_id)
        q += " GROUP BY status"
        stats = {r[0]: r[1] for r in self.conn.execute(q, args)}
        stats["total"] = sum(stats.values())
        return stats

    @_locked
    def update_evidence(self, case_id: str, path: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [(_j(v) if k in JSON_COLS else v) for k, v in fields.items()]
        self.conn.execute(f"UPDATE evidence SET {cols} WHERE case_id=? AND path=?", (*vals, case_id, path))
        self.conn.commit()

    # ---------------------------------------------------------------- findings / criteria
    @_locked
    def next_series_id(self, case_id: str, prefix: str, table: str = "findings") -> str:
        like = f"{prefix}-%"
        rows = self.conn.execute(f"SELECT id FROM {table} WHERE case_id=? AND id LIKE ?", (case_id, like))
        mx = 0
        for (fid,) in rows:
            tail = fid.rsplit("-", 1)[-1]
            if tail.isdigit():
                mx = max(mx, int(tail))
        return f"{prefix}-{mx + 1:02d}"

    @_locked
    def upsert_finding(self, case_id: str, audit_id: Optional[str], f: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update one finding. Without ``id`` a new id in the kind's series is assigned.
        Every update appends a history entry {audit_id, ts, change}."""
        now = utcnow()
        kind = f.get("kind", "exception")
        prefix = FINDING_PREFIX.get(kind, "FND")
        fid = f.get("id") or self.next_series_id(case_id, prefix)
        existing = self.conn.execute("SELECT * FROM findings WHERE case_id=? AND id=?", (case_id, fid)).fetchone()
        allowed = ("title", "description", "amount", "currency", "entity", "counterparty", "date", "category",
                   "risk", "confidence", "label", "status", "evidence_refs", "next_evidence", "owner", "meta")
        if existing:
            ex = _row(existing)
            changes = {k: f[k] for k in allowed if k in f and f[k] != ex.get(k)}
            hist = ex.get("history") or []
            hist.append({"audit_id": audit_id, "ts": now, "change": changes or "touched"})
            sets = {k: (_j(v) if k in JSON_COLS else v) for k, v in changes.items()}
            sets.update({"history": _j(hist), "audit_id": audit_id, "updated_at": now})
            cols = ", ".join(f"{k}=?" for k in sets)
            self.conn.execute(f"UPDATE findings SET {cols} WHERE case_id=? AND id=?", (*sets.values(), case_id, fid))
        else:
            hist = [{"audit_id": audit_id, "ts": now, "change": "created"}]
            self.conn.execute(
                "INSERT INTO findings(id, case_id, audit_id, kind, title, description, amount, currency, entity,"
                " counterparty, date, category, risk, confidence, label, status, evidence_refs, next_evidence, owner,"
                " history, created_at, updated_at, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fid, case_id, audit_id, kind, f.get("title", fid), f.get("description", ""), f.get("amount"),
                 f.get("currency"), f.get("entity"), f.get("counterparty"), f.get("date"), f.get("category"),
                 f.get("risk", "medium"), f.get("confidence", "UNRESOLVED"), f.get("label", "UNKNOWN"),
                 f.get("status", "open"), _j(f.get("evidence_refs") or []), f.get("next_evidence"), f.get("owner"),
                 _j(hist), now, now, _j(f.get("meta"))))
        self.conn.commit()
        return self.get_finding(case_id, fid)

    @_locked
    def get_finding(self, case_id: str, fid: str) -> Dict[str, Any]:
        return _row(self.conn.execute("SELECT * FROM findings WHERE case_id=? AND id=?", (case_id, fid)).fetchone())

    @_locked
    def list_findings(self, case_id: str, *, kind: Optional[str] = None, status: Optional[str] = None,
                      audit_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM findings WHERE case_id=?"
        args: list = [case_id]
        if kind:
            q += " AND kind=?"; args.append(kind)
        if status:
            q += " AND status=?"; args.append(status)
        if audit_id:
            q += " AND audit_id=?"; args.append(audit_id)
        q += " ORDER BY kind, id"
        return [_row(r) for r in self.conn.execute(q, args)]

    @_locked
    def add_criterion(self, case_id: str, audit_id: Optional[str], author: str, text: str,
                      date: Optional[str] = None, status: str = "pending_agreement") -> Dict[str, Any]:
        cid = self.next_series_id(case_id, "CRIT", table="criteria")
        self.conn.execute(
            "INSERT INTO criteria(id, case_id, audit_id, date, author, text, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (cid, case_id, audit_id, date or utcnow()[:10], author, text, status, utcnow()))
        self.conn.commit()
        return _row(self.conn.execute("SELECT * FROM criteria WHERE case_id=? AND id=?", (case_id, cid)).fetchone())

    @_locked
    def list_criteria(self, case_id: str) -> List[Dict[str, Any]]:
        return [_row(r) for r in self.conn.execute("SELECT * FROM criteria WHERE case_id=? ORDER BY id", (case_id,))]

    # ---------------------------------------------------------------- reports / runs / timeline / research
    @_locked
    def add_report(self, audit_id: str, kind: str, path: str, fmt: str, *, version: str = "v1",
                   sha256: str = "", size: int = 0, meta: Optional[dict] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO reports(audit_id, kind, path, format, version, sha256, size, created_at, meta)"
            " VALUES (?,?,?,?,?,?,?,?,?)", (audit_id, kind, path, fmt, version, sha256, size, utcnow(), _j(meta)))
        self.conn.commit()
        return int(cur.lastrowid)

    @_locked
    def list_reports(self, audit_id: str) -> List[Dict[str, Any]]:
        return [_row(r) for r in self.conn.execute(
            "SELECT * FROM reports WHERE audit_id=? ORDER BY created_at, id", (audit_id,))]

    @_locked
    def add_run(self, audit_id: str, kind: str, *, role: Optional[str] = None, status: str = "planned",
                input: Optional[dict] = None, output: Optional[dict] = None, summary: str = "") -> int:
        now = utcnow()
        cur = self.conn.execute(
            "INSERT INTO runs(audit_id, kind, role, status, started_at, finished_at, input, output, summary)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (audit_id, kind, role, status, now, now if status in ("done", "failed") else None,
             _j(input), _j(output), summary))
        self.conn.commit()
        return int(cur.lastrowid)

    @_locked
    def update_run(self, run_id: int, **fields: Any) -> None:
        if fields.get("status") in ("done", "failed") and "finished_at" not in fields:
            fields["finished_at"] = utcnow()
        self._update("runs", "id", run_id, fields, touch=False)

    @_locked
    def list_runs(self, audit_id: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM runs WHERE audit_id=?"
        args: list = [audit_id]
        if kind:
            q += " AND kind=?"; args.append(kind)
        return [_row(r) for r in self.conn.execute(q + " ORDER BY id", args)]

    @_locked
    def add_event(self, case_id: str, event_type: str, description: str, *, audit_id: Optional[str] = None,
                  actor: str = "ghost-recon", ref: Optional[dict] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO timeline(case_id, audit_id, ts, event_type, actor, description, ref) VALUES (?,?,?,?,?,?,?)",
            (case_id, audit_id, utcnow(), event_type, actor, description, _j(ref)))
        self.conn.commit()
        return int(cur.lastrowid)

    @_locked
    def list_events(self, case_id: str) -> List[Dict[str, Any]]:
        return [_row(r) for r in self.conn.execute(
            "SELECT * FROM timeline WHERE case_id=? ORDER BY ts, id", (case_id,))]

    @_locked
    def add_research_note(self, case_id: str, audit_id: Optional[str], action: str, query: str, *,
                          url: Optional[str] = None, title: Optional[str] = None, snippet: Optional[str] = None,
                          relevance: Optional[float] = None, sha256: str = "", saved_path: Optional[str] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO research_notes(case_id, audit_id, action, query, url, title, snippet, relevance, sha256,"
            " saved_path, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (case_id, audit_id, action, query, url, title, snippet, relevance, sha256, saved_path, utcnow()))
        self.conn.commit()
        return int(cur.lastrowid)

    @_locked
    def list_research_notes(self, case_id: str, audit_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM research_notes WHERE case_id=?"
        args: list = [case_id]
        if audit_id:
            q += " AND audit_id=?"; args.append(audit_id)
        return [_row(r) for r in self.conn.execute(q + " ORDER BY id", args)]

    # ---------------------------------------------------------------- export
    @_locked
    def export_case(self, case_id: str) -> Dict[str, Any]:
        case = self.get_case(case_id)
        if not case:
            return {}
        return {
            "case": case,
            "audits": self.list_audits(case_id),
            "evidence": self.list_evidence(case_id),
            "findings": self.list_findings(case_id),
            "criteria": self.list_criteria(case_id),
            "reports": [rep for a in self.list_audits(case_id) for rep in self.list_reports(a["id"])],
            "runs": [run for a in self.list_audits(case_id) for run in self.list_runs(a["id"])],
            "timeline": self.list_events(case_id),
            "research_notes": self.list_research_notes(case_id),
            "exported_at": utcnow(),
        }

    @_locked
    def import_case(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Re-create a case from ``export_case`` output (or a ``case.json`` mirror). Existing rows are kept."""
        case = data.get("case") or {}
        if not case:
            raise ValueError("import_case: missing 'case'")
        if not self.get_case(case["id"]):
            self.create_case(id=case["id"], slug=case["slug"], name=case["name"], root_path=case["root_path"],
                             audits_dir=case.get("audits_dir", "GhostRecon_Audits"),
                             base_currency=case.get("base_currency", "USD"), language=case.get("language", "es"),
                             context_md=case.get("context_md"), meta=case.get("meta") or {})
        for a in data.get("audits") or []:
            if not self.get_audit(a["id"]):
                self.create_audit(id=a["id"], case_id=case["id"], seq=a["seq"], kind=a["kind"], folder=a["folder"],
                                  parent_audit_id=a.get("parent_audit_id"), context_md=a.get("context_md"),
                                  out_override=a.get("out_override"), meta=a.get("meta") or {})
                self.update_audit(a["id"], status=a.get("status", "open"), sealed_at=a.get("sealed_at"),
                                  seal_sha256=a.get("seal_sha256"), model_json=a.get("model_json"),
                                  summary=a.get("summary") or {})
        if data.get("evidence"):
            self.upsert_evidence(case["id"], data["evidence"])
        for f in data.get("findings") or []:
            self.upsert_finding(case["id"], f.get("audit_id"), f)
        for c in data.get("criteria") or []:
            if not self.conn.execute("SELECT 1 FROM criteria WHERE case_id=? AND id=?", (case["id"], c["id"])).fetchone():
                self.conn.execute(
                    "INSERT INTO criteria(id, case_id, audit_id, date, author, text, status, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)", (c["id"], case["id"], c.get("audit_id"), c.get("date"), c["author"],
                                                  c["text"], c.get("status", "pending_agreement"), c.get("created_at") or utcnow()))
        self.conn.commit()
        return self.get_case(case["id"])

    # ---------------------------------------------------------------- internals
    def _update(self, table: str, key: str, value: Any, fields: Dict[str, Any], touch: bool = True) -> None:
        if not fields:
            return
        if touch:
            fields = {**fields, "updated_at": utcnow()}
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [(_j(v) if k in JSON_COLS else v) for k, v in fields.items()]
        self.conn.execute(f"UPDATE {table} SET {cols} WHERE {key}=?", (*vals, value))
        self.conn.commit()
