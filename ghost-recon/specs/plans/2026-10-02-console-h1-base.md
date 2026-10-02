# Consola Ghost Recon · H1 (Base) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tener la consola web Ghost Recon funcionando en su hito base:
- `hermes ghostrecon serve` en loopback, con login, usuarios y tokens;
- API de solo lectura sobre la BD de casos;
- verificación de sellos cacheada y descarga de entregables;
- frontend con Inicio, Casos, Página del caso (7 pestañas) y Sistema.

**Architecture:**
- Un paquete `plugins/ghost_recon/console/` dentro del plugin existente:
  - `ConsoleStore` maneja tablas `console_*` con su propia conexión a la misma `ghostrecon.db`;
  - `AuthService` (scrypt, sesiones de servidor, tokens Bearer, bloqueo);
  - una app FastAPI con routers finos sobre funciones de lectura puras (`readmodel.py`).
- El frontend son módulos ES sin build servidos por la propia app.
- El core de Hermes no cambia.

**Tech Stack:** Python 3.14, FastAPI/Starlette y uvicorn (ya son dependencias del core), SQLite (WAL), pytest con `scripts/run_tests.sh`, JS en módulos ES nativos y CSS con variables.

**Spec:** `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (léela entera antes de empezar; este plan implementa su hito H1, §13).

## Global Constraints

- Solo se tocan `plugins/ghost_recon/`, `ghost-recon/` y `tests/plugins/ghost_recon/`. **Cero cambios al core de Hermes.**
- **Ninguna dependencia nueva.** FastAPI, Starlette, uvicorn y httpx ya están en `pyproject.toml`.
- La consola **solo escribe tablas `console_*`**. Las tablas de caso se leen a través de `core` (`Store`, `service`).
- La configuración vive solo en `config.yaml` → `plugins.entries.ghost-recon.settings.console` (dict). No hay env vars nuevas; `GHOSTRECON_DB` ya existe y se usa para standalone y tests.
- Escucha por defecto en `127.0.0.1:9230`. Fuera de loopback exige `--allow-remote`.
- Frontend: sin CDN ni recursos externos. CSP `default-src 'self'`. Los datos **nunca** pasan por `innerHTML`; todo va por `textContent` mediante el helper `h()`. Solo se enlazan URLs `http(s)`.
- El texto de UI va en español; el código y los comentarios, en inglés (igual que `core/`).
- Contraseñas: mínimo 10 caracteres; scrypt n=2^15, r=8, p=1, sal de 16 B. Sesiones y tokens se guardan solo como SHA-256.
- Sesión: inactividad 12 h y máximo absoluto 7 días. Bloqueo: 5 fallos en 15 min bloquean 5 min, por usuario y por IP.
- Pruebas siempre con `scripts/run_tests.sh` (nunca `pytest` directo):
  - son contratos de comportamiento, sin pruebas que lean código fuente ni que congelen valores;
  - las diferencias por SO llevan `@pytest.mark.platforms(...)`, nunca `skipif`.
- Commits: un commit por tarea, en convención `type(scope): …`, terminando con la línea `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Carpetas de caso con acentos y espacios** ("Caso Logística Norte", "extracto ñ.txt"): la API y las URLs deben ir y volver intactas. La prueba vive en la Tarea 4.
2. **BD recién instalada, sin casos:** Inicio y Casos devuelven ceros y listas vacías, nunca un 500. La prueba vive en la Tarea 4.
3. **Entregable registrado cuyo archivo fue borrado o movido:** debe dar `404 file_missing`, no un 500. La prueba vive en la Tarea 5.
4. **Cookie de sesión falsa o de otra consola/perfil:** debe dar `401` limpio. La prueba vive en la Tarea 3.
5. **Windows sirviendo `.js` como `text/plain`** (el registro de Windows puede mapearlo así): con `nosniff` el navegador rechaza los módulos y la consola queda en blanco. La prueba vive en la Tarea 7.

---

### Task 0: Entorno de pruebas del worktree

**Files:** ninguno (solo entorno).

- [ ] **Step 1: Construir el venv de pruebas.** Desde la raíz del worktree:

```bash
python -m pm.build_env --source . --out .venv --group dev --group test
```

Expected: termina con `✓ Installing Python dependencies` y la ruta de `.venv/.../python`.

- [ ] **Step 2: Línea base verde de Ghost Recon**

```bash
scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py -q
```

Expected: `0 failed`. Sin `openpyxl` y `reportlab` hay 2 skipped, que son los tests del pack completo.

---

### Task 1: Ajustes, `ConsoleStore` y conexión compartida

**Files:**
- Modify: `plugins/ghost_recon/runtime.py` (extraer `open_connection()`)
- Create: `plugins/ghost_recon/console/__init__.py`
- Create: `plugins/ghost_recon/console/settings.py`
- Create: `plugins/ghost_recon/console/store.py`
- Create: `tests/plugins/ghost_recon/console/__init__.py` (vacío)
- Create: `tests/plugins/ghost_recon/console/conftest.py`
- Test: `tests/plugins/ghost_recon/console/test_store.py`

**Interfaces:**
- Consumes: `plugins.ghost_recon.core.db.connect`, `migrate`, `utcnow`; `runtime.db_path()`, `PLUGIN_NAME`, `DB_FILENAME`.
- Produces:
  - `runtime.open_connection() -> sqlite3.Connection`.
  - `ConsoleSettings` (dataclass congelado): `host: str`, `port: int`, `session_idle_hours: int`, `session_max_days: int`, `allowed_hosts: tuple[str, ...]`; `ConsoleSettings.from_mapping(raw) -> ConsoleSettings`; `load_settings(*, host=None, port=None) -> ConsoleSettings`.
  - `ConsoleStore(conn)` y `ConsoleStore.open_default()`, con estos métodos:
    - usuarios: `create_user(username, password_hash, role) -> dict`, `get_user(username) -> dict`, `get_user_by_id(uid) -> dict`, `list_users() -> list[dict]`, `update_user(username, **fields) -> bool`, `count_active_admins() -> int`;
    - sesiones: `create_session(*, user_id, token_sha256, csrf_token, expires_at, ip, user_agent) -> int`, `get_session(token_sha256) -> dict` (incluye `username`, `role` y `disabled` del usuario), `touch_session(session_id, ts)`, `revoke_session(session_id)`, `revoke_user_sessions(user_id)`;
    - tokens: `create_token(*, user_id, name, token_sha256, prefix) -> int`, `get_token(token_sha256) -> dict`, `list_tokens() -> list[dict]`, `revoke_token(token_id) -> bool`, `touch_token(token_id, ts)`;
    - registro: `log(action, *, user_id=None, username=None, ip=None, target=None, detail=None) -> int`, `list_audit_log(limit=200) -> list[dict]`;
    - sellos: `save_seal_check(audit_id, ok, detail, checked_by) -> dict` (`ok` como bool), `get_seal_check(audit_id) -> dict` (`{}` si no hay);
    - lectura entre casos: `recent_events(limit=15) -> list[dict]` (filas de timeline más `case_name`, de la más reciente a la más antigua).
  - Constantes: `ROLES = ("viewer", "admin")`.

- [ ] **Step 1: Crear el paquete de pruebas y el conftest**

`tests/plugins/ghost_recon/console/__init__.py`: archivo vacío.

`tests/plugins/ghost_recon/console/conftest.py`:

```python
"""Fixtures for the console tests (they build on tests/plugins/ghost_recon/conftest.py: gr_env, store, demo_case)."""
import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings

ADMIN = ("jean", "admin-pass-123")
VIEWER = ("vera", "viewer-pass-123")


@pytest.fixture
def settings():
    return ConsoleSettings()


@pytest.fixture
def cstore(store):
    """Console store on its own connection to the same temp DB as ``store`` (case tables already migrated)."""
    from plugins.ghost_recon.console.store import ConsoleStore
    return ConsoleStore.open_default()
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_store.py`:

```python
"""Console tables live beside the case tables without disturbing them; settings degrade to defaults."""
import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings
from plugins.ghost_recon.console.store import ConsoleStore


def test_console_migration_is_idempotent_and_keeps_the_case_schema(store, cstore):
    again = ConsoleStore.open_default()
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"console_users", "console_sessions", "console_tokens", "console_audit_log", "console_seal_checks"} <= tables
    assert {"cases", "audits", "findings", "evidence", "timeline"} <= tables
    assert again.conn.execute("SELECT COUNT(*) FROM console_schema_version").fetchone()[0] == 1
    assert store.list_cases() == []


def test_users_are_unique_and_active_admins_are_counted(cstore):
    cstore.create_user("jean", "hash-1", "admin")
    cstore.create_user("vera", "hash-2", "viewer")
    with pytest.raises(ValueError):
        cstore.create_user("jean", "hash-3", "viewer")
    with pytest.raises(ValueError):
        cstore.create_user("eve", "hash-4", "root")
    assert cstore.count_active_admins() == 1
    cstore.update_user("jean", disabled=1)
    assert cstore.count_active_admins() == 0


def test_seal_check_cache_keeps_only_the_latest_result(cstore):
    cstore.save_seal_check("GRC-x/A01", True, {"modified": []}, "jean")
    latest = cstore.save_seal_check("GRC-x/A01", False, {"modified": ["06_Report/a.md"]}, "vera")
    assert latest["ok"] is False and latest["checked_by"] == "vera"
    assert latest["detail"]["modified"] == ["06_Report/a.md"]
    assert cstore.get_seal_check("GRC-x/A02") == {}


def test_recent_events_span_cases_newest_first(store, cstore, demo_case):
    from plugins.ghost_recon.core import service
    service.open_case(store, str(demo_case), name="Acme Demo")
    events = cstore.recent_events(5)
    assert events and all(e["case_name"] == "Acme Demo" for e in events)
    stamps = [e["ts"] for e in events]
    assert stamps == sorted(stamps, reverse=True)


def test_settings_fall_back_to_defaults_on_invalid_values():
    d = ConsoleSettings()
    assert ConsoleSettings.from_mapping("not-a-mapping") == d
    s = ConsoleSettings.from_mapping({"port": "nope", "session_idle_hours": -1})
    assert (s.port, s.session_idle_hours) == (d.port, d.session_idle_hours)


def test_settings_apply_valid_values_and_keep_loopback_hosts():
    s = ConsoleSettings.from_mapping({"port": "9300", "session_idle_hours": 4, "allowed_hosts": ["Consola.Local"]})
    assert (s.port, s.session_idle_hours) == (9300, 4)
    assert {"localhost", "127.0.0.1", "::1", "consola.local"} <= set(s.allowed_hosts)
```

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console/test_store.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console'`.

- [ ] **Step 4: Extraer `open_connection()` en `runtime.py`**

En `plugins/ghost_recon/runtime.py`, añade esta función justo antes de `def store()`:

```python
def open_connection():
    """New connection to the profile's Ghost Recon DB: Hermes' ``plugin_db`` inside Hermes (WAL with its
    network-filesystem fallbacks), ``GHOSTRECON_DB`` / the fallback path outside Hermes (tests, standalone)."""
    if not os.environ.get("GHOSTRECON_DB"):
        try:
            from plugins.plugin_storage import plugin_db
            return plugin_db(PLUGIN_NAME, DB_FILENAME)
        except Exception:  # outside Hermes: plugin storage unavailable, use the plain file
            pass
    return connect(db_path())
```

Después, en `store()`, sustituye este bloque:

```python
            conn = None
            if not os.environ.get("GHOSTRECON_DB"):
                try:
                    from plugins.plugin_storage import plugin_db
                    conn = plugin_db(PLUGIN_NAME, DB_FILENAME)
                except Exception:
                    conn = None
            if conn is None:
                conn = connect(path)
            st = Store(conn)
```

por:

```python
            st = Store(open_connection())
```

- [ ] **Step 5: Crear `console/__init__.py`**

```python
"""Ghost Recon console: a standalone web console (``hermes ghostrecon serve``) over the case DB.

Spec: ghost-recon/specs/2026-10-02-ghost-recon-console-design.md. The console reads case data through ``core`` and
writes only its own ``console_*`` tables; it never edits findings, criteria or sealed audits.
"""

CONSOLE_VERSION = "0.1.0"
```

- [ ] **Step 6: Crear `console/settings.py`**

```python
"""Console settings: ``plugins.entries.ghost-recon.settings.console`` in config.yaml, with safe defaults."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


@dataclass(frozen=True)
class ConsoleSettings:
    host: str = "127.0.0.1"
    port: int = 9230
    session_idle_hours: int = 12
    session_max_days: int = 7
    allowed_hosts: tuple = LOOPBACK_HOSTS

    @classmethod
    def from_mapping(cls, raw: Any) -> "ConsoleSettings":
        """Tolerant parse: unknown keys are ignored, invalid or non-positive numbers fall back to the default."""
        raw = raw if isinstance(raw, Mapping) else {}
        d = cls()

        def positive_int(key: str, default: int) -> int:
            try:
                value = int(raw.get(key, default))
            except (TypeError, ValueError):
                return default
            return value if value > 0 else default

        extra = raw.get("allowed_hosts")
        hosts = tuple(str(h).strip().lower() for h in extra if str(h).strip()) if isinstance(extra, (list, tuple)) else ()
        return cls(host=str(raw.get("host") or d.host), port=positive_int("port", d.port),
                   session_idle_hours=positive_int("session_idle_hours", d.session_idle_hours),
                   session_max_days=positive_int("session_max_days", d.session_max_days),
                   allowed_hosts=tuple(dict.fromkeys(LOOPBACK_HOSTS + hosts)))


def load_settings(*, host: Optional[str] = None, port: Optional[int] = None) -> ConsoleSettings:
    """The plugin's ``console`` settings (inside Hermes) with CLI overrides applied."""
    from .. import runtime
    settings = ConsoleSettings.from_mapping(runtime.setting("console", {}))
    if host:
        settings = replace(settings, host=host)
    if port:
        settings = replace(settings, port=int(port))
    return settings
```

- [ ] **Step 7: Crear `console/store.py`**

```python
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
```

- [ ] **Step 8: Ejecutar las pruebas nuevas y la regresión del plugin**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon -q`
Expected: `0 failed`. Pasan los 6 tests nuevos y no se rompe ningún test existente tras el cambio en `runtime.store()`.

- [ ] **Step 9: Commit**

```bash
git add plugins/ghost_recon/runtime.py plugins/ghost_recon/console tests/plugins/ghost_recon/console
git commit -m "feat(ghost-recon): console settings and console_* tables on the case DB

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `AuthService` (contraseñas, sesiones, bloqueo, tokens)

**Files:**
- Create: `plugins/ghost_recon/console/auth.py`
- Modify: `tests/plugins/ghost_recon/console/conftest.py` (añadir `auth` y `users`)
- Test: `tests/plugins/ghost_recon/console/test_auth.py`

**Interfaces:**
- Consumes: `ConsoleStore` (Tarea 1), `ConsoleSettings`.
- Produces:
  - `hash_password(pw) -> str`, `verify_password(pw, encoded) -> bool`.
  - `Principal(user_id, username, role, via, session_id=None, csrf=None)` con `.has(role) -> bool`.
  - Excepciones `AuthError` y `LoginLocked(AuthError)`, esta última con `.retry_after: int`.
  - `AuthService(cstore, settings, clock=...)` con:
    - `add_user(username, password, role) -> dict`, `set_password(username, password)`, `set_disabled(username, disabled)`;
    - `login(username, password, *, ip="", user_agent="") -> tuple[str, Principal]`;
    - `resolve_session(raw) -> Principal | None`, `logout(principal, ip="")`;
    - `create_api_token(username, name) -> tuple[str, dict]`, `resolve_bearer(raw) -> Principal | None`, `revoke_api_token(token_id) -> bool`.

- [ ] **Step 1: Añadir fixtures al conftest**

Añade al final de `tests/plugins/ghost_recon/console/conftest.py`:

```python
@pytest.fixture
def auth(cstore, settings):
    from plugins.ghost_recon.console.auth import AuthService
    return AuthService(cstore, settings)


@pytest.fixture
def users(auth):
    auth.add_user(ADMIN[0], ADMIN[1], "admin")
    auth.add_user(VIEWER[0], VIEWER[1], "viewer")
    return {"admin": ADMIN, "viewer": VIEWER}
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_auth.py`:

```python
"""AuthService contracts: password hashing, account rules, session expiry, lockout, API tokens."""
from datetime import datetime, timedelta, timezone

import pytest

from plugins.ghost_recon.console.auth import AuthError, AuthService, LoginLocked, hash_password, verify_password
from plugins.ghost_recon.console.settings import ConsoleSettings


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(cstore, clock):
    s = AuthService(cstore, ConsoleSettings(session_idle_hours=12, session_max_days=7), clock=clock)
    s.add_user("jean", "admin-pass-123", "admin")
    return s


def test_password_hash_roundtrip_and_rejections():
    encoded = hash_password("correct horse 1")
    assert verify_password("correct horse 1", encoded)
    assert not verify_password("correct horse 2", encoded)
    assert not verify_password("x", "not-a-hash")
    assert hash_password("same-pass-1") != hash_password("same-pass-1")  # salted


@pytest.mark.parametrize("username,password", [("a b", "long-enough-1"), ("x", "long-enough-1"), ("ok-user", "short")])
def test_add_user_validates_username_and_password(svc, username, password):
    with pytest.raises(ValueError):
        svc.add_user(username, password, "viewer")


def test_usernames_are_case_insensitive_and_unique(svc):
    with pytest.raises(ValueError):
        svc.add_user("JEAN", "other-pass-123", "viewer")


def test_session_expires_after_idle_window_and_absolute_limit(svc, clock):
    raw, _ = svc.login("jean", "admin-pass-123")
    clock.advance(hours=11)
    assert svc.resolve_session(raw) is not None  # activity refreshes last_seen
    clock.advance(hours=11)
    assert svc.resolve_session(raw) is not None
    clock.advance(hours=13)
    assert svc.resolve_session(raw) is None  # idle longer than 12 h
    raw2, _ = svc.login("jean", "admin-pass-123")
    for _ in range(15):  # stays active every 12 h, but runs past the 7-day absolute cap
        clock.advance(hours=12)
        svc.resolve_session(raw2)
    assert svc.resolve_session(raw2) is None


def test_lockout_after_five_failures_blocks_even_the_right_password(svc, clock):
    for _ in range(5):
        with pytest.raises(AuthError):
            svc.login("jean", "wrong-password", ip="10.0.0.9")
    with pytest.raises(LoginLocked) as locked:
        svc.login("jean", "admin-pass-123", ip="10.0.0.9")
    assert locked.value.retry_after > 0
    clock.advance(minutes=6)
    raw, principal = svc.login("jean", "admin-pass-123", ip="10.0.0.9")
    assert raw and principal.username == "jean"


def test_failures_outside_the_window_do_not_lock(svc, clock):
    for _ in range(4):
        with pytest.raises(AuthError):
            svc.login("jean", "wrong-password")
    clock.advance(minutes=16)
    with pytest.raises(AuthError):
        svc.login("jean", "wrong-password")
    svc.login("jean", "admin-pass-123")  # only one failure inside the window: not locked


def test_password_change_and_disable_revoke_sessions(svc):
    svc.add_user("vera", "viewer-pass-123", "viewer")
    raw, _ = svc.login("vera", "viewer-pass-123")
    svc.set_password("vera", "viewer-pass-456")
    assert svc.resolve_session(raw) is None
    raw, _ = svc.login("vera", "viewer-pass-456")
    svc.set_disabled("vera", True)
    assert svc.resolve_session(raw) is None
    with pytest.raises(AuthError):
        svc.login("vera", "viewer-pass-456")


def test_last_active_admin_cannot_be_disabled(svc):
    with pytest.raises(ValueError):
        svc.set_disabled("jean", True)


def test_api_token_resolves_until_revoked(svc):
    raw, info = svc.create_api_token("jean", "webapp")
    principal = svc.resolve_bearer(raw)
    assert principal is not None and principal.username == "jean" and principal.via == "token"
    assert principal.csrf is None
    assert svc.revoke_api_token(info["id"])
    assert svc.resolve_bearer(raw) is None


def test_raw_session_and_api_tokens_never_reach_the_db(svc, cstore):
    raw_session, _ = svc.login("jean", "admin-pass-123", ip="127.0.0.1")
    raw_token, _ = svc.create_api_token("jean", "webapp")
    dump = "\n".join(str(v) for table in ("console_sessions", "console_tokens", "console_audit_log")
                     for row in cstore.conn.execute(f"SELECT * FROM {table}") for v in tuple(row))
    assert raw_session not in dump and raw_token not in dump
```

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console/test_auth.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console.auth'`.

- [ ] **Step 4: Crear `console/auth.py`**

```python
"""Console authentication: scrypt passwords, server-side sessions, API tokens and login lockout.

Raw session and API tokens are never stored, only their SHA-256. Time comes from an injectable clock so expiry
and lockout are testable without sleeping.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
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


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"la contraseña debe tener al menos {MIN_PASSWORD} caracteres")


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

    # ------------------------------------------------------------------ accounts
    def add_user(self, username: str, password: str, role: str) -> Dict:
        username = (username or "").strip().lower()
        if not USERNAME_RE.match(username):
            raise ValueError("usuario: 2-32 caracteres en minúscula (a-z, 0-9, punto, guion o guion bajo)")
        if role not in ROLES:
            raise ValueError(f"rol debe ser uno de {ROLES}")
        _check_password(password)
        return self.cstore.create_user(username, hash_password(password), role)

    def set_password(self, username: str, password: str) -> None:
        _check_password(password)
        user = self._require_user(username)
        self.cstore.update_user(user["username"], password_hash=hash_password(password))
        self.cstore.revoke_user_sessions(user["id"])

    def set_disabled(self, username: str, disabled: bool) -> None:
        user = self._require_user(username)
        if disabled and user["role"] == "admin" and not user["disabled"] and self.cstore.count_active_admins() <= 1:
            raise ValueError("no se puede deshabilitar el último admin activo")
        self.cstore.update_user(user["username"], disabled=1 if disabled else 0)
        if disabled:
            self.cstore.revoke_user_sessions(user["id"])

    def _require_user(self, username: str) -> Dict:
        user = self.cstore.get_user((username or "").strip().lower())
        if not user:
            raise ValueError(f"usuario no encontrado: {username}")
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
                                         ip=ip, user_agent=(user_agent or "")[:200])
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
    def create_api_token(self, username: str, name: str) -> Tuple[str, Dict]:
        user = self._require_user(username)
        if user["disabled"]:
            raise ValueError("el usuario está deshabilitado")
        label = (name or "").strip()[:80] or "token"
        prefix = secrets.token_hex(4)
        raw = f"{TOKEN_PREFIX}_{prefix}_{secrets.token_urlsafe(32)}"
        token_id = self.cstore.create_token(user_id=user["id"], name=label, token_sha256=_sha(raw), prefix=prefix)
        self.cstore.log("token_create", user_id=user["id"], username=user["username"], target=str(token_id),
                        detail={"name": label})
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

    def revoke_api_token(self, token_id: int) -> bool:
        revoked = self.cstore.revoke_token(token_id)
        if revoked:
            self.cstore.log("token_revoke", target=str(token_id))
        return revoked
```

- [ ] **Step 5: Ejecutar y ver que pasan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed` (Tareas 1 y 2).

- [ ] **Step 6: Commit**

```bash
git add plugins/ghost_recon/console/auth.py tests/plugins/ghost_recon/console
git commit -m "feat(ghost-recon): console auth (scrypt, sessions, lockout, API tokens)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: App FastAPI, dependencias y router de autenticación

**Files:**
- Create: `plugins/ghost_recon/console/deps.py`
- Create: `plugins/ghost_recon/console/app.py`
- Create: `plugins/ghost_recon/console/routers/__init__.py`
- Create: `plugins/ghost_recon/console/routers/auth.py`
- Create: `plugins/ghost_recon/console/static/index.html`
- Modify: `tests/plugins/ghost_recon/console/conftest.py` (añadir `app`, `client`, `login_as`)
- Test: `tests/plugins/ghost_recon/console/test_api_security.py`

**Interfaces:**
- Consumes: `AuthService`, `Principal`, `AuthError`, `LoginLocked` (Tarea 2); `ConsoleStore`, `ConsoleSettings`; `core.db.Store`.
- Produces:
  - `deps.py`:
    - `SESSION_COOKIE = "gr_session"`, `CSRF_HEADER = "x-gr-csrf"`;
    - `ApiError(status, code, message, headers=None)` (subclase de `HTTPException`);
    - `ConsoleContext(settings, store, cstore, auth)`;
    - `get_ctx(request)`, `client_ip(request)`, `current_principal(...)`, `require(role)`.
  - `app.py`: `create_app(settings, store, cstore, *, auth=None) -> FastAPI`, `host_allowed(host_header, settings) -> bool`, `ROUTERS` (tupla de módulos con `router`), `STATIC_DIR`.
  - Rutas: `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`, `GET /api/v1/openapi.json`, `GET /`, `/static/*`.
  - Errores siempre con la forma `{"error": {"code": str, "message": str}}`.

- [ ] **Step 1: Añadir fixtures al conftest**

Añade al final de `tests/plugins/ghost_recon/console/conftest.py`:

```python
@pytest.fixture
def app(store, cstore, settings, auth):
    from plugins.ghost_recon.console.app import create_app
    return create_app(settings, store, cstore, auth=auth)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def login_as(app, users):
    """Factory: a logged-in TestClient for 'admin' or 'viewer', with its CSRF header preset."""
    from fastapi.testclient import TestClient
    opened = []

    def _login(role: str):
        c = TestClient(app, base_url="http://localhost")
        c.__enter__()
        opened.append(c)
        username, password = users[role]
        r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        c.headers["X-GR-CSRF"] = r.json()["csrf"]
        return c

    yield _login
    for c in opened:
        c.__exit__(None, None, None)
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_api_security.py`:

```python
"""HTTP security contracts of the console: auth gate, Host check, headers, cookies, CSRF, lockout, logout."""
from fastapi.testclient import TestClient


def test_api_requires_authentication(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_forged_or_foreign_session_cookie_is_a_clean_401(client):
    client.cookies.set("gr_session", "forged-or-from-another-console")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_foreign_host_header_is_rejected(app):
    with TestClient(app, base_url="http://evil.example") as c:
        r = c.get("/api/v1/auth/me")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_host"


def test_loopback_host_on_any_port_reaches_the_auth_gate(app):
    with TestClient(app, base_url="http://localhost:19230") as c:  # e.g. an SSH tunnel on another local port
        assert c.get("/api/v1/auth/me").status_code == 401


def test_security_headers_on_page_and_api(client):
    page = client.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    api = client.get("/api/v1/auth/me")
    assert api.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in api.headers["content-security-policy"]


def test_login_sets_an_httponly_strict_cookie_and_returns_csrf(client, users):
    r = client.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]})
    assert r.status_code == 200 and r.json()["csrf"] and r.json()["user"]["role"] == "admin"
    cookie = r.headers["set-cookie"].lower()
    assert "gr_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie


def test_bad_credentials_are_401_then_lockout_is_429(client, users):
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "jean", "password": "wrong-password"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    r = client.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_state_changing_requests_need_the_csrf_header(client, users):
    r = client.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]})
    csrf = r.json()["csrf"]
    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "csrf"
    assert client.post("/api/v1/auth/logout", headers={"X-GR-CSRF": csrf}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401  # session revoked by logout


def test_openapi_schema_is_behind_login(client, users):
    assert client.get("/api/v1/openapi.json").status_code == 401
    client.post("/api/v1/auth/login", json={"username": "vera", "password": users["viewer"][1]})
    assert "/api/v1/auth/login" in client.get("/api/v1/openapi.json").json()["paths"]


def test_invalid_login_body_is_a_422_envelope(client):
    r = client.post("/api/v1/auth/login", json={"username": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
```

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console/test_api_security.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console.app'`.

- [ ] **Step 4: Crear `console/deps.py`**

```python
"""FastAPI dependencies shared by the routers: app context, principal resolution, role checks, API errors."""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from ..core.db import Store
from .auth import AuthService, Principal
from .settings import ConsoleSettings
from .store import ConsoleStore

SESSION_COOKIE = "gr_session"
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
    principal = ctx.auth.resolve_session(request.cookies.get(SESSION_COOKIE, ""))
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
```

- [ ] **Step 5: Crear `console/routers/__init__.py` y `console/routers/auth.py`**

`routers/__init__.py`:

```python
"""One router module per API resource; each exposes ``router`` and is mounted under /api/v1 by ``create_app``."""
```

`routers/auth.py`:

```python
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
```

- [ ] **Step 6: Crear `console/static/index.html`**

```html
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ghost Recon · Consola</title>
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/theme.css">
  <link rel="stylesheet" href="/static/app.css">
  <script type="module" src="/static/app.js"></script>
</head>
<body>
  <div id="app" class="boot">Cargando…</div>
</body>
</html>
```

- [ ] **Step 7: Crear `console/app.py`**

```python
"""``create_app``: the Ghost Recon console FastAPI app — JSON API under /api/v1 plus the static frontend."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.db import Store
from . import CONSOLE_VERSION
from .auth import AuthService
from .deps import ConsoleContext, current_principal
from .routers import auth as auth_routes
from .settings import ConsoleSettings
from .store import ConsoleStore

STATIC_DIR = Path(__file__).parent / "static"
# The Windows registry can map .js to text/plain; under nosniff the browser then refuses the ES modules.
for _mime, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("image/svg+xml", ".svg")):
    mimetypes.add_type(_mime, _ext)

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}
ROUTERS = (auth_routes,)


def host_allowed(host_header: str, settings: ConsoleSettings) -> bool:
    """The Host header's hostname (port ignored, IPv6 brackets stripped) must be a configured host (DNS rebinding)."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return bool(host) and (host in settings.allowed_hosts or host == settings.host.lower())


def create_app(settings: ConsoleSettings, store: Store, cstore: ConsoleStore, *,
               auth: Optional[AuthService] = None) -> FastAPI:
    app = FastAPI(title="Ghost Recon Console", version=CONSOLE_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gr = ConsoleContext(settings=settings, store=store, cstore=cstore,
                                  auth=auth or AuthService(cstore, settings))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if host_allowed(request.headers.get("host", ""), settings):
            response = await call_next(request)
        else:
            response = JSONResponse({"error": {"code": "bad_host", "message": "host no permitido"}}, status_code=400)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": f"http_{exc.status_code}",
                                                                   "message": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": {"code": "invalid_request", "message": "parámetros inválidos",
                                       "fields": jsonable_encoder(exc.errors())}}, status_code=422)

    for module in ROUTERS:
        app.include_router(module.router, prefix="/api/v1")

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    def openapi(_=Depends(current_principal)):
        return app.openapi()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    return app
```

- [ ] **Step 8: Ejecutar y ver que pasan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`.

- [ ] **Step 9: Commit**

```bash
git add plugins/ghost_recon/console tests/plugins/ghost_recon/console
git commit -m "feat(ghost-recon): console FastAPI app with auth routes, host check and security headers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Lectura — Inicio, Casos y Sistema

**Files:**
- Create: `plugins/ghost_recon/console/paths.py` (solo `case_results_root`; `resolve_within` llega en la Tarea 5)
- Create: `plugins/ghost_recon/console/readmodel.py`
- Create: `plugins/ghost_recon/console/routers/system.py`
- Create: `plugins/ghost_recon/console/routers/cases.py`
- Modify: `plugins/ghost_recon/console/app.py` (`ROUTERS`)
- Modify: `tests/plugins/ghost_recon/console/conftest.py` (fixture `seeded`)
- Test: `tests/plugins/ghost_recon/console/test_api_cases.py`

**Interfaces:**
- Consumes:
  - de `core`: `Store`, `service.timeline`, `service.open_case`, `service.start_audit`, `service.upsert_findings`, `service.add_criterion`, `service.record_run`, `service.seal_audit`, `pack.build_pack`, `ids.short_audit`, `casefolder.audits_root`;
  - `ConsoleStore.get_seal_check` y `recent_events`; `require`, `get_ctx` y `ApiError`; `commands.doctor_report()`.
- Produces:
  - `paths.case_results_root(case: dict) -> Path`.
  - `readmodel`:
    - constantes `RISKS` y `MAX_PAGE = 500`;
    - `count_by(rows, key)`, `open_by_risk(findings)`;
    - `audit_view(store, cstore, audit) -> dict` (claves: `id, seq, kind, status, folder, started_at, sealed_at, seal_sha256, seal_check, reports`);
    - `seal_state(audit_views) -> "ok" | "broken" | "unverified" | "none"`;
    - `case_row(store, cstore, case) -> dict` (claves: `id, name, root_path, status, base_currency, language, audits_count, sealed_count, last_audit, open_by_risk, open_total, evidence_total, last_activity, seal_state`);
    - `list_cases(store, cstore, *, q="", status="")`, `overview(store, cstore)`, `case_detail(store, cstore, case)`;
    - `filter_findings(rows, *, kind="", risk="", status="", q="")`, `filter_evidence(rows, *, q="")`;
    - `page(rows, cursor="", limit=100) -> (items, next_cursor)`.
  - `routers/cases.get_case_or_404(ctx, case_id) -> dict`, que reutiliza la Tarea 5.
  - Rutas:
    - `GET /system/overview|doctor|audit-log`;
    - `GET /cases`, `GET /cases/{id}`, `GET /cases/{id}/timeline|findings|findings/{fid}|evidence|evidence/stats|criteria|research`.

- [ ] **Step 1: Añadir la fixture `seeded` al conftest**

Añade al inicio de `tests/plugins/ghost_recon/console/conftest.py`, junto a los imports, `from pathlib import Path`. Después añade al final:

```python
def _seal_with_md_pack(store, audit_id, folder: Path, report_md: str) -> None:
    """Seal an audit with an md-only pack (forced: pdf/xlsx need the plugin's optional deps)."""
    from plugins.ghost_recon.core import casefolder as cf, service
    from plugins.ghost_recon.core.reports import pack
    cf.write_json(folder, "03_Extracted_Data/model.json", {"kpis": {"total": 1}})
    cf.write_text(folder, "06_Report/report.md", report_md)
    pack.build_pack(store, audit_id, formats=["md"])
    service.record_run(store, audit_id, "validation", role="A", status="done", summary="ok")
    assert service.seal_audit(store, audit_id, force=True)["sealed"]


@pytest.fixture
def seeded(store, demo_case):
    """Demo case: A01 sealed (3 findings, 1 criterion, md pack) and A02 open (rerun) with an md report."""
    from plugins.ghost_recon.core import casefolder as cf, service
    from plugins.ghost_recon.core.reports import pack
    case_id = service.open_case(store, str(demo_case), name="Acme Demo")["case"]["id"]
    a1 = service.start_audit(store, case_id, "initial")
    a1_id = a1["audit"]["id"]
    service.upsert_findings(store, a1_id, [
        {"kind": "exception", "title": "Pagos Zelle sin factura", "amount": 12450.0, "risk": "high",
         "counterparty": "Socio B"},
        {"kind": "anomaly", "title": "Factura posterior al pago", "amount": 3200.0, "risk": "medium"},
        {"kind": "question", "title": "¿Quién autorizó el acta?", "risk": "low", "status": "closed"},
    ])
    service.add_criterion(store, a1_id, "Gerencia", "Periodo ene–jun 2026")
    _seal_with_md_pack(store, a1_id, Path(a1["folder"]), "## 1. Respuesta\n\nTexto.\n")
    (demo_case / "Bancos" / "nuevo.txt").write_text("nuevo", encoding="utf-8")
    a2 = service.start_audit(store, case_id, "rerun")
    a2_folder = Path(a2["folder"])
    cf.write_text(a2_folder, "06_Report/report.md", "## 1. Respuesta\n\nBorrador.\n")
    pack.build_pack(store, a2["audit"]["id"], formats=["md"])
    return {"case_id": case_id, "a1": a1_id, "a2": a2["audit"]["id"], "a1_folder": Path(a1["folder"]),
            "a2_folder": a2_folder, "root": demo_case}
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_api_cases.py`:

```python
"""Read API over the case DB: every figure the console shows must agree with the case Store."""


def test_overview_on_an_empty_db_returns_zeros(login_as):
    o = login_as("viewer").get("/api/v1/system/overview").json()
    assert o["kpis"]["cases_total"] == 0 and o["kpis"]["open_total"] == 0
    assert o["recent_cases"] == [] and o["recent_events"] == []


def test_overview_totals_agree_with_case_rows(login_as, seeded):
    c = login_as("viewer")
    o = c.get("/api/v1/system/overview").json()
    rows = c.get("/api/v1/cases").json()["items"]
    assert o["kpis"]["open_total"] == sum(r["open_total"] for r in rows)
    assert o["kpis"]["audits_sealed"] == sum(r["sealed_count"] for r in rows)
    assert o["recent_events"] and o["recent_events"][0]["case_name"] == "Acme Demo"


def test_case_list_open_counts_match_the_store(login_as, seeded, store):
    rows = login_as("viewer").get("/api/v1/cases").json()["items"]
    row = next(r for r in rows if r["id"] == seeded["case_id"])
    open_findings = [f for f in store.list_findings(seeded["case_id"]) if f["status"] == "open"]
    assert row["open_total"] == len(open_findings)
    for risk in ("critical", "high", "medium", "low"):
        assert row["open_by_risk"][risk] == sum(1 for f in open_findings if f["risk"] == risk)
    assert row["audits_count"] == len(store.list_audits(seeded["case_id"]))
    assert row["seal_state"] == "unverified"  # a sealed audit exists and nobody has verified it yet


def test_case_list_filters_by_text_and_status(login_as, seeded):
    c = login_as("viewer")
    assert [r["id"] for r in c.get("/api/v1/cases", params={"q": "ACME"}).json()["items"]] == [seeded["case_id"]]
    assert c.get("/api/v1/cases", params={"q": "no-such-case"}).json()["items"] == []
    assert c.get("/api/v1/cases", params={"status": "archived"}).json()["items"] == []


def test_case_detail_lists_audits_in_store_order(login_as, seeded, store):
    d = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}").json()
    assert [a["id"] for a in d["audits"]] == [a["id"] for a in store.list_audits(seeded["case_id"])]
    assert [a["seq"] for a in d["audits"]] == ["A01", "A02"]
    assert d["results_root"].endswith("GhostRecon_Audits")


def test_unknown_case_is_404_with_error_envelope(login_as):
    r = login_as("viewer").get("/api/v1/cases/GRC-nope-20260101")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_findings_filters_agree_with_the_store(login_as, seeded, store):
    c = login_as("viewer")
    base = f"/api/v1/cases/{seeded['case_id']}/findings"
    high = c.get(base, params={"risk": "high"}).json()["items"]
    assert high and all(f["risk"] == "high" for f in high)
    assert len(c.get(base).json()["items"]) == len(store.list_findings(seeded["case_id"]))
    assert [f["title"] for f in c.get(base, params={"q": "zelle"}).json()["items"]] == ["Pagos Zelle sin factura"]
    assert all(f["status"] == "open" for f in c.get(base, params={"status": "open"}).json()["items"])
    assert c.get(f"{base}/{high[0]['id']}").json()["history"]
    assert c.get(f"{base}/EXC-99").status_code == 404


def test_evidence_pages_cover_every_row_exactly_once(login_as, seeded, store):
    c = login_as("viewer")
    url = f"/api/v1/cases/{seeded['case_id']}/evidence"
    seen, cursor = [], None
    while True:
        body = c.get(url, params={"limit": 3, **({"cursor": cursor} if cursor else {})}).json()
        seen += [e["path"] for e in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    expected = [e["path"] for e in store.list_evidence(seeded["case_id"])]
    assert sorted(seen) == sorted(expected) and len(seen) == len(set(seen))


def test_evidence_limit_is_clamped(login_as, seeded):
    c = login_as("viewer")
    url = f"/api/v1/cases/{seeded['case_id']}/evidence"
    assert len(c.get(url, params={"limit": 100000}).json()["items"]) <= 500
    assert len(c.get(url, params={"limit": -5}).json()["items"]) == 1


def test_evidence_stats_add_up_to_the_total(login_as, seeded):
    s = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/evidence/stats").json()
    assert sum(v for k, v in s["statuses"].items() if k != "total") == s["statuses"]["total"]
    assert sum(s["blocks"].values()) == s["statuses"]["total"]


def test_timeline_is_newest_first(login_as, seeded):
    items = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/timeline").json()["items"]
    stamps = [e["ts"] for e in items]
    assert stamps and stamps == sorted(stamps, reverse=True)


def test_criteria_and_research_lists(login_as, seeded, store):
    c = login_as("viewer")
    crit = c.get(f"/api/v1/cases/{seeded['case_id']}/criteria").json()["items"]
    assert [x["id"] for x in crit] == [x["id"] for x in store.list_criteria(seeded["case_id"])]
    assert c.get(f"/api/v1/cases/{seeded['case_id']}/research").json()["items"] == []


def test_case_folder_with_accents_and_spaces_round_trips(login_as, store, gr_env):
    from plugins.ghost_recon.core import service
    folder = gr_env / "Caso Logística Norte"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto ñ.txt").write_text("x", encoding="utf-8")
    case_id = service.open_case(store, str(folder), name="Logística Norte")["case"]["id"]
    c = login_as("viewer")
    d = c.get(f"/api/v1/cases/{case_id}").json()
    assert d["case"]["name"] == "Logística Norte" and d["case"]["root_path"].endswith("Caso Logística Norte")
    paths = [e["path"] for e in c.get(f"/api/v1/cases/{case_id}/evidence", params={"q": "ñ"}).json()["items"]]
    assert paths == ["Bancos/extracto ñ.txt"]


def test_audit_log_is_admin_only(login_as):
    assert login_as("viewer").get("/api/v1/system/audit-log").status_code == 403
    items = login_as("admin").get("/api/v1/system/audit-log").json()["items"]
    assert any(e["action"] == "login" for e in items)


def test_doctor_reports_core_and_console_checks(login_as):
    body = login_as("viewer").get("/api/v1/system/doctor").json()
    names = {c["check"] for c in body["checks"]}
    assert {"database", "approvals.single_query_mode"} <= names
    assert body["console"]["port"] > 0
```

> `evidence.path` se guarda siempre en forma POSIX (`core/casefolder.inventory` usa `relative_to(root).as_posix()`), así que `"Bancos/extracto ñ.txt"` es la misma cadena en todos los SO.

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console/test_api_cases.py -q`
Expected: FAIL con 404 en `/api/v1/system/overview` y `/api/v1/cases` (los routers aún no existen).

- [ ] **Step 4: Crear `console/paths.py`**

```python
"""Filesystem paths the console reasons about: a case's results root and (Task 5) path containment."""

from __future__ import annotations

from pathlib import Path

from ..core import casefolder as cf


def case_results_root(case: dict) -> Path:
    """Where a case's outputs live: ``<root>/<audits_dir>`` or the case's ``--out`` override."""
    return cf.audits_root(Path(case["root_path"]), case["audits_dir"], (case.get("meta") or {}).get("out_dir"))
```

- [ ] **Step 5: Crear `console/readmodel.py`**

```python
"""Read models for the console API: plain dicts built from the case ``Store`` and the console tables. No writes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..core import ids
from ..core.db import Store
from .paths import case_results_root
from .store import ConsoleStore

RISKS = ("critical", "high", "medium", "low")
MAX_PAGE = 500
FINDING_TEXT_FIELDS = ("id", "title", "description", "counterparty", "entity", "category")
EVIDENCE_TEXT_FIELDS = ("path", "filename", "sha256", "doc_type", "entity")


def count_by(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        k = row.get(key) or "?"
        out[k] = out.get(k, 0) + 1
    return out


def open_by_risk(findings: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    out = {r: 0 for r in RISKS}
    for f in findings:
        if f.get("status") == "open":
            risk = f.get("risk") or "medium"
            out[risk] = out.get(risk, 0) + 1
    return out


def audit_view(store: Store, cstore: ConsoleStore, audit: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": audit["id"], "seq": ids.short_audit(audit["id"]), "kind": audit["kind"], "status": audit["status"],
            "folder": audit["folder"], "started_at": audit["started_at"], "sealed_at": audit.get("sealed_at"),
            "seal_sha256": audit.get("seal_sha256"), "seal_check": cstore.get_seal_check(audit["id"]) or None,
            "reports": len(store.list_reports(audit["id"]))}


def seal_state(audits: List[Dict[str, Any]]) -> str:
    """Case-level seal summary from the cached checks: a broken seal wins; unchecked sealed audits = unverified."""
    checks = [a["seal_check"] for a in audits if a["status"] == "sealed"]
    if not checks:
        return "none"
    if any(c is not None and not c["ok"] for c in checks):
        return "broken"
    return "ok" if all(c is not None for c in checks) else "unverified"


def case_row(store: Store, cstore: ConsoleStore, case: Dict[str, Any]) -> Dict[str, Any]:
    audits = [audit_view(store, cstore, a) for a in store.list_audits(case["id"])]
    events = store.list_events(case["id"])
    risk = open_by_risk(store.list_findings(case["id"]))
    return {"id": case["id"], "name": case["name"], "root_path": case["root_path"], "status": case["status"],
            "base_currency": case["base_currency"], "language": case["language"],
            "audits_count": len(audits), "sealed_count": sum(1 for a in audits if a["status"] == "sealed"),
            "last_audit": audits[-1] if audits else None, "open_by_risk": risk, "open_total": sum(risk.values()),
            "evidence_total": store.evidence_stats(case["id"]).get("total", 0),
            "last_activity": events[-1]["ts"] if events else case["updated_at"], "seal_state": seal_state(audits)}


def _recent_first(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: r["last_activity"] or "", reverse=True)


def list_cases(store: Store, cstore: ConsoleStore, *, q: str = "", status: str = "") -> List[Dict[str, Any]]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if any(needle in r[k].lower() for k in ("name", "id", "root_path"))]
    return _recent_first(rows)


def overview(store: Store, cstore: ConsoleStore) -> Dict[str, Any]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    risk = {r: sum(row["open_by_risk"].get(r, 0) for row in rows) for r in RISKS}
    return {"kpis": {"cases_total": len(rows), "cases_active": sum(1 for r in rows if r["status"] == "open"),
                     "audits_sealed": sum(r["sealed_count"] for r in rows), "open_by_risk": risk,
                     "open_total": sum(risk.values()), "jobs_active": 0},
            "recent_cases": _recent_first(rows)[:8], "recent_events": cstore.recent_events(15)}


def case_detail(store: Store, cstore: ConsoleStore, case: Dict[str, Any]) -> Dict[str, Any]:
    findings = store.list_findings(case["id"])
    return {"case": case, "summary": case_row(store, cstore, case), "results_root": str(case_results_root(case)),
            "audits": [audit_view(store, cstore, a) for a in store.list_audits(case["id"])],
            "findings": {"total": len(findings), "by_kind": count_by(findings, "kind"),
                         "by_status": count_by(findings, "status")},
            "evidence": store.evidence_stats(case["id"]), "criteria": len(store.list_criteria(case["id"])),
            "research_notes": len(store.list_research_notes(case["id"]))}


def _matches(row: Dict[str, Any], needle: str, fields: Tuple[str, ...]) -> bool:
    return any(needle in str(row.get(k) or "").lower() for k in fields)


def filter_findings(rows: List[Dict[str, Any]], *, kind: str = "", risk: str = "", status: str = "",
                    q: str = "") -> List[Dict[str, Any]]:
    needle = q.strip().lower()
    return [f for f in rows if (not kind or f["kind"] == kind) and (not risk or f["risk"] == risk)
            and (not status or f["status"] == status) and (not needle or _matches(f, needle, FINDING_TEXT_FIELDS))]


def filter_evidence(rows: List[Dict[str, Any]], *, q: str = "") -> List[Dict[str, Any]]:
    needle = q.strip().lower()
    return [e for e in rows if not needle or _matches(e, needle, EVIDENCE_TEXT_FIELDS)]


def page(rows: List[Dict[str, Any]], cursor: str = "", limit: int = 100) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Offset pagination; the cursor is the next offset as a string, limit clamped to [1, MAX_PAGE]."""
    try:
        start = max(0, int(cursor or 0))
    except ValueError:
        start = 0
    end = start + max(1, min(int(limit), MAX_PAGE))
    return rows[start:end], (str(end) if end < len(rows) else None)
```

- [ ] **Step 6: Crear `console/routers/system.py`**

```python
"""System endpoints: control-panel overview, environment doctor and the console audit log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import CONSOLE_VERSION, readmodel
from ..auth import Principal
from ..deps import ConsoleContext, get_ctx, require

router = APIRouter(tags=["system"])


def _approvals_mode() -> str:
    try:
        from hermes_cli.config import cfg_get, load_config_readonly
        return str(cfg_get(load_config_readonly(), "approvals", "single_query_mode", default="deny"))
    except Exception:  # standalone (outside Hermes): Hermes' documented default
        return "deny"


@router.get("/system/overview")
def overview(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return readmodel.overview(ctx.store, ctx.cstore)


@router.get("/system/doctor")
def doctor(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    from ..commands import doctor_report
    report = doctor_report()
    mode = _approvals_mode()
    outcome = "aprobados automáticamente" if mode == "approve" else "bloqueados"
    checks = report["checks"] + [{"check": "approvals.single_query_mode", "ok": True,
                                  "detail": f"{mode}: comandos peligrosos en ejecuciones desatendidas {outcome}"}]
    return {"ok": report["ok"], "checks": checks, "settings": report["settings"],
            "console": {"version": CONSOLE_VERSION, "host": ctx.settings.host, "port": ctx.settings.port}}


@router.get("/system/audit-log")
def audit_log(limit: int = Query(200, ge=1, le=1000), _: Principal = Depends(require("admin")),
              ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.cstore.list_audit_log(limit)}
```

- [ ] **Step 7: Crear `console/routers/cases.py`**

```python
"""Case endpoints (read-only): list, detail, timeline, findings, evidence, criteria and research notes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core import service
from .. import readmodel
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, get_ctx, require

router = APIRouter(tags=["cases"])


def get_case_or_404(ctx: ConsoleContext, case_id: str) -> dict:
    case = ctx.store.get_case(case_id)
    if not case or case["id"] != case_id:  # canonical ids only (get_case also matches slug / root path)
        raise ApiError(404, "not_found", f"caso no encontrado: {case_id}")
    return case


@router.get("/cases")
def list_cases(q: str = "", status: str = "", _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": readmodel.list_cases(ctx.store, ctx.cstore, q=q, status=status)}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return readmodel.case_detail(ctx.store, ctx.cstore, get_case_or_404(ctx, case_id))


@router.get("/cases/{case_id}/timeline")
def case_timeline(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    t = service.timeline(ctx.store, case_id)
    return {"items": sorted(t["events"], key=lambda e: (e["ts"], e["id"]), reverse=True), "audits": t["audits"],
            "findings_evolution": t["findings_evolution"]}


@router.get("/cases/{case_id}/findings")
def findings(case_id: str, kind: str = "", risk: str = "", status: str = "", q: str = "",
             _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    return {"items": readmodel.filter_findings(ctx.store.list_findings(case_id), kind=kind, risk=risk,
                                               status=status, q=q)}


@router.get("/cases/{case_id}/findings/{finding_id}")
def finding(case_id: str, finding_id: str, _: Principal = Depends(require("viewer")),
            ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    row = ctx.store.get_finding(case_id, finding_id)
    if not row:
        raise ApiError(404, "not_found", f"hallazgo no encontrado: {finding_id}")
    return row


@router.get("/cases/{case_id}/evidence")
def evidence(case_id: str, status: str = "", audit: str = "", q: str = "", cursor: str = "", limit: int = 100,
             _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    rows = ctx.store.list_evidence(case_id, status=status or None,
                                   first_audit_id=f"{case_id}/{audit}" if audit else None)
    rows = readmodel.filter_evidence(rows, q=q)
    items, next_cursor = readmodel.page(rows, cursor, limit)
    return {"items": items, "next_cursor": next_cursor, "total": len(rows)}


@router.get("/cases/{case_id}/evidence/stats")
def evidence_stats(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    rows = ctx.store.list_evidence(case_id)
    return {"statuses": ctx.store.evidence_stats(case_id), "blocks": readmodel.count_by(rows, "block"),
            "types": readmodel.count_by(rows, "ext")}


@router.get("/cases/{case_id}/criteria")
def criteria(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    return {"items": ctx.store.list_criteria(case_id)}


@router.get("/cases/{case_id}/research")
def research(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    return {"items": ctx.store.list_research_notes(case_id)}
```

- [ ] **Step 8: Montar los routers en `app.py`**

En `plugins/ghost_recon/console/app.py`, sustituye:

```python
from .routers import auth as auth_routes
```

por:

```python
from .routers import auth as auth_routes, cases as cases_routes, system as system_routes
```

y `ROUTERS = (auth_routes,)` por:

```python
ROUTERS = (auth_routes, system_routes, cases_routes)
```

- [ ] **Step 9: Ejecutar y ver que pasan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`.

- [ ] **Step 10: Commit**

```bash
git add plugins/ghost_recon/console tests/plugins/ghost_recon/console
git commit -m "feat(ghost-recon): console read API for overview, cases, findings, evidence and system

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Auditorías — detalle, verificación de sellos y descargas

**Files:**
- Modify: `plugins/ghost_recon/console/paths.py` (añadir `resolve_within`)
- Create: `plugins/ghost_recon/console/routers/audits.py`
- Modify: `plugins/ghost_recon/console/app.py` (`ROUTERS`)
- Test: `tests/plugins/ghost_recon/console/test_paths.py`
- Test: `tests/plugins/ghost_recon/console/test_api_audits.py`

**Interfaces:**
- Consumes:
  - `service.verify_audit` y `service.completion_report`; `ConsoleStore.save_seal_check` y `log`;
  - `readmodel.audit_view`; `routers.cases.get_case_or_404`; `deps.require` y `client_ip`.
- Produces:
  - `paths.resolve_within(candidate, roots) -> Path | None`.
  - Rutas:
    - `GET /cases/{id}/audits/{seq}` (incluye `completion`);
    - `GET …/runs`;
    - `POST …/verify` → `{audit_id, ok, checked_at, detail}`; `409 not_sealed` si la auditoría está abierta;
    - `GET …/reports` → `items[{id, kind, format, version, size, sha256, name, created_at}]`;
    - `GET …/reports/{rid}/download`: `403 not_sealed` para un viewer en una auditoría abierta; `404 file_missing` si el archivo falta o queda fuera de la carpeta de la auditoría.

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_paths.py`:

```python
"""Path containment: only paths that resolve inside an allowed root are accepted."""
import os

import pytest

from plugins.ghost_recon.console.paths import resolve_within


def test_inside_outside_and_missing(tmp_path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    inside = root / "a" / "f.txt"
    inside.write_text("x", encoding="utf-8")
    outside = tmp_path / "other.txt"
    outside.write_text("y", encoding="utf-8")
    assert resolve_within(inside, [root]) == inside.resolve()
    assert resolve_within(root / "a" / ".." / ".." / "other.txt", [root]) is None
    assert resolve_within(outside, [root]) is None
    assert resolve_within(root / "missing.txt", [root]) is None
    assert resolve_within(inside, []) is None


@pytest.mark.platforms("posix")
def test_symlink_escaping_the_root_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("s", encoding="utf-8")
    os.symlink(secret, root / "link.txt")
    assert resolve_within(root / "link.txt", [root]) is None


@pytest.mark.platforms("windows")
def test_windows_containment_ignores_letter_case(tmp_path):
    root = tmp_path / "Root"
    root.mkdir()
    f = root / "Informe.md"
    f.write_text("x", encoding="utf-8")
    assert resolve_within(str(f).upper(), [root]) is not None
```

`tests/plugins/ghost_recon/console/test_api_audits.py`:

```python
"""Audit endpoints: seal-check cache, tamper detection and deliverable downloads (role + path containment)."""
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


def _url(seeded, seq):
    return f"/api/v1/cases/{seeded['case_id']}/audits/{seq}"


def test_audit_detail_includes_completion_checks(login_as, seeded):
    d = login_as("viewer").get(_url(seeded, "A01")).json()
    assert d["status"] == "sealed" and {"manifest", "report_md", "validation"} <= set(d["completion"]["checks"])
    assert login_as("viewer").get(_url(seeded, "Z99")).status_code == 404


def test_verify_caches_ok_and_flips_the_case_seal_state(login_as, seeded):
    c = login_as("viewer")
    r = c.post(_url(seeded, "A01") + "/verify")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert c.get("/api/v1/cases").json()["items"][0]["seal_state"] == "ok"
    assert c.get(_url(seeded, "A01")).json()["seal_check"]["ok"] is True


def test_tampered_sealed_file_is_reported_as_broken(login_as, seeded):
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    report.write_text(report.read_text(encoding="utf-8") + "\nalterado", encoding="utf-8")
    c = login_as("viewer")
    body = c.post(_url(seeded, "A01") + "/verify").json()
    assert body["ok"] is False and any(p.startswith("06_Report/") for p in body["detail"]["modified"])
    assert c.get("/api/v1/cases").json()["items"][0]["seal_state"] == "broken"


def test_verifying_an_open_audit_is_409(login_as, seeded):
    r = login_as("viewer").post(_url(seeded, "A02") + "/verify")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_sealed"


def test_viewer_downloads_sealed_reports_and_bytes_match_the_registered_hash(login_as, seeded):
    c = login_as("viewer")
    reports = c.get(_url(seeded, "A01") + "/reports").json()["items"]
    rep = next(r for r in reports if r["format"] == "md")
    r = c.get(_url(seeded, "A01") + f"/reports/{rep['id']}/download")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert hashlib.sha256(r.content).hexdigest() == rep["sha256"]


def test_open_audit_deliverables_are_admin_only(login_as, seeded):
    url = _url(seeded, "A02")
    rep = login_as("admin").get(url + "/reports").json()["items"][0]
    viewer = login_as("viewer").get(url + f"/reports/{rep['id']}/download")
    assert viewer.status_code == 403 and viewer.json()["error"]["code"] == "not_sealed"
    assert login_as("admin").get(url + f"/reports/{rep['id']}/download").status_code == 200


def test_a_report_row_pointing_at_evidence_is_never_served(login_as, seeded, store):
    evidence_file = seeded["root"] / "Bancos" / "extracto_2026-01.txt"
    rid = store.list_reports(seeded["a1"])[0]["id"]
    store.conn.execute("UPDATE reports SET path=? WHERE id=?", (str(evidence_file), rid))
    store.conn.commit()
    r = login_as("admin").get(_url(seeded, "A01") + f"/reports/{rid}/download")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_missing"


def test_a_registered_report_whose_file_was_deleted_is_404(login_as, seeded, store):
    rep = store.list_reports(seeded["a2"])[0]
    Path(rep["path"]).unlink()
    r = login_as("admin").get(_url(seeded, "A02") + f"/reports/{rep['id']}/download")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_missing"


def test_bearer_tokens_skip_csrf_but_keep_their_role(app, auth, users, seeded):
    raw, _ = auth.create_api_token("vera", "webapp")
    with TestClient(app, base_url="http://localhost") as c:
        c.headers["Authorization"] = f"Bearer {raw}"
        assert c.post(_url(seeded, "A01") + "/verify").status_code == 200  # no CSRF header needed
        assert c.get("/api/v1/system/audit-log").status_code == 403  # viewer token on an admin route


def test_downloads_and_verifications_are_audited(login_as, seeded):
    c = login_as("admin")
    c.post(_url(seeded, "A01") + "/verify")
    rep = c.get(_url(seeded, "A01") + "/reports").json()["items"][0]
    c.get(_url(seeded, "A01") + f"/reports/{rep['id']}/download")
    actions = {e["action"] for e in c.get("/api/v1/system/audit-log").json()["items"]}
    assert {"seal_verify", "report_download"} <= actions
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console/test_paths.py tests/plugins/ghost_recon/console/test_api_audits.py -q`
Expected: FAIL con `ImportError: cannot import name 'resolve_within'` y 404 en las rutas de auditoría.

- [ ] **Step 3: Añadir `resolve_within` a `console/paths.py`**

Añade `import os` y `from typing import Iterable, Optional` a los imports, y esta función al final:

```python
def resolve_within(candidate, roots: Iterable) -> Optional[Path]:
    """``candidate`` resolved (symlinks followed) when it lies inside one of ``roots``; otherwise None.
    Missing paths, other drives and anything that escapes a root all return None. Case-insensitive on Windows."""
    try:
        path = Path(candidate).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    target = os.path.normcase(str(path))
    for root in roots:
        try:
            base = os.path.normcase(str(Path(root).resolve(strict=True)))
            if os.path.commonpath([base, target]) == base:
                return path
        except (OSError, RuntimeError, ValueError):  # unresolvable root or a different drive
            continue
    return None
```

- [ ] **Step 4: Crear `console/routers/audits.py`**

```python
"""Audit endpoints: detail with completion checks, internal runs, seal verification and deliverable downloads."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from ...core import service
from .. import readmodel
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..paths import resolve_within
from .cases import get_case_or_404

router = APIRouter(tags=["audits"])
SEQ_RE = re.compile(r"^[AR]\d{2,3}$")


def get_audit_or_404(ctx: ConsoleContext, case_id: str, seq: str) -> dict:
    get_case_or_404(ctx, case_id)
    audit = ctx.store.get_audit(f"{case_id}/{seq}") if SEQ_RE.match(seq) else {}
    if not audit:
        raise ApiError(404, "not_found", f"auditoría no encontrada: {seq}")
    return audit


@router.get("/cases/{case_id}/audits/{seq}")
def audit_detail(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
                 ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    return {**readmodel.audit_view(ctx.store, ctx.cstore, audit), "parent_audit_id": audit.get("parent_audit_id"),
            "context_md": audit.get("context_md"), "summary": audit.get("summary") or {},
            "completion": service.completion_report(ctx.store, audit)}


@router.get("/cases/{case_id}/audits/{seq}/runs")
def audit_runs(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.store.list_runs(get_audit_or_404(ctx, case_id, seq)["id"])}


@router.post("/cases/{case_id}/audits/{seq}/verify")
def verify_seal(case_id: str, seq: str, request: Request, principal: Principal = Depends(require("viewer")),
                ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    if audit["status"] != "sealed":
        raise ApiError(409, "not_sealed", "solo se verifican auditorías selladas")
    result = service.verify_audit(ctx.store, audit["id"])
    ok = bool(result.get("ok")) and result.get("db_matches") is not False
    detail = {k: result.get(k) for k in ("missing", "added", "modified", "file_count", "manifest_sha256", "db_matches")}
    check = ctx.cstore.save_seal_check(audit["id"], ok, detail, principal.username)
    ctx.cstore.log("seal_verify", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=audit["id"], detail={"ok": ok})
    return {"audit_id": audit["id"], "ok": ok, "checked_at": check["checked_at"], "detail": detail}


@router.get("/cases/{case_id}/audits/{seq}/reports")
def audit_reports(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
                  ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    return {"items": [{"id": r["id"], "kind": r["kind"], "format": r["format"], "version": r["version"],
                       "size": r["size"], "sha256": r["sha256"], "name": Path(r["path"]).name,
                       "created_at": r["created_at"]} for r in ctx.store.list_reports(audit["id"])]}


@router.get("/cases/{case_id}/audits/{seq}/reports/{report_id}/download")
def download_report(case_id: str, seq: str, report_id: int, request: Request,
                    principal: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    if audit["status"] != "sealed" and not principal.has("admin"):
        raise ApiError(403, "not_sealed", "los entregables de auditorías abiertas solo los descarga un admin")
    report = next((r for r in ctx.store.list_reports(audit["id"]) if r["id"] == report_id), None)
    path = resolve_within(report["path"], [audit["folder"]]) if report else None
    if path is None or not path.is_file():
        raise ApiError(404, "file_missing", "el archivo del entregable no está en la carpeta de la auditoría")
    ctx.cstore.log("report_download", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=f"{audit['id']}#{report_id}", detail={"file": path.name})
    return FileResponse(path, filename=path.name,
                        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
```

- [ ] **Step 5: Montar el router**

En `app.py`, cambia el import de routers por:

```python
from .routers import audits as audits_routes, auth as auth_routes, cases as cases_routes, system as system_routes
```

y `ROUTERS` por:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes)
```

- [ ] **Step 6: Ejecutar y ver que pasan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`. En Windows, `test_symlink_escaping_the_root_is_rejected` se salta por su marca `posix`; en Linux y macOS se salta `test_windows_containment_ignores_letter_case`.

- [ ] **Step 7: Commit**

```bash
git add plugins/ghost_recon/console tests/plugins/ghost_recon/console
git commit -m "feat(ghost-recon): console audit endpoints with cached seal checks and contained downloads

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: CLI — `serve`, `user`, `token`

**Files:**
- Create: `plugins/ghost_recon/console/cli.py`
- Modify: `plugins/ghost_recon/cli.py` (registro y despacho de los verbos de consola)
- Test: `tests/plugins/ghost_recon/console/test_cli.py`
- Test: `tests/plugins/ghost_recon/console/test_serve_e2e.py`

**Interfaces:**
- Consumes: `ConsoleStore.open_default`, `AuthService`, `load_settings`, `create_app`, `runtime.store()`.
- Produces:
  - `console.cli.CONSOLE_VERBS = ("serve", "user", "token")`;
  - `register(subs)` y `dispatch(args) -> int`;
  - `is_loopback(host) -> bool` y `serve_preflight(cstore, host, allow_remote) -> list[str]`.
  - Comandos:
    - `hermes ghostrecon serve [--host H] [--port N] [--allow-remote]`;
    - `user add <nombre> --role admin|viewer [--password-stdin]`, `user list|passwd|disable|enable`;
    - `token create --user U --name N`, `token list`, `token revoke <id>`.

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_cli.py`:

```python
"""`ghostrecon user|token|serve` through the real CLI entry point (standalone module on the temp DB)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.ghost_recon.console.cli import is_loopback, serve_preflight

REPO = Path(__file__).resolve().parents[4]


def _cli(gr_env, *args, stdin=""):
    env = {**os.environ, "GHOSTRECON_DB": str(gr_env / "db" / "ghostrecon.db"), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "plugins.ghost_recon.cli", *args], cwd=REPO, env=env, input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_user_and_token_lifecycle(gr_env):
    added = _cli(gr_env, "user", "add", "jean", "--role", "admin", "--password-stdin", stdin="admin-pass-123\n")
    assert added.returncode == 0, added.stderr
    listed = _cli(gr_env, "user", "list").stdout
    assert "jean" in listed and "admin" in listed
    created = _cli(gr_env, "token", "create", "--user", "jean", "--name", "webapp")
    token = next(w for w in created.stdout.split() if w.startswith("grt_"))
    tokens = _cli(gr_env, "token", "list").stdout
    assert "webapp" in tokens and token not in tokens


def test_duplicate_user_fails_cleanly(gr_env):
    _cli(gr_env, "user", "add", "jean", "--role", "admin", "--password-stdin", stdin="admin-pass-123\n")
    dup = _cli(gr_env, "user", "add", "jean", "--role", "viewer", "--password-stdin", stdin="other-pass-123\n")
    assert dup.returncode == 1 and "error" in dup.stderr


def test_serve_refuses_to_start_without_an_admin(gr_env):
    r = _cli(gr_env, "serve", "--port", "1")
    assert r.returncode == 1 and "user add" in r.stderr


@pytest.mark.parametrize("host,expected", [("127.0.0.1", True), ("localhost", True), ("::1", True),
                                           ("0.0.0.0", False), ("192.168.1.20", False)])
def test_is_loopback(host, expected):
    assert is_loopback(host) is expected


def test_preflight_requires_allow_remote_for_non_loopback(cstore, auth):
    auth.add_user("jean", "admin-pass-123", "admin")
    assert serve_preflight(cstore, "0.0.0.0", allow_remote=False)
    assert serve_preflight(cstore, "0.0.0.0", allow_remote=True) == []
    assert serve_preflight(cstore, "127.0.0.1", allow_remote=False) == []
```

`tests/plugins/ghost_recon/console/test_serve_e2e.py`:

```python
"""Real `serve` process: binds loopback, enforces auth, serves the frontend and logs in end to end."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[4]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_end_to_end(gr_env, auth):
    auth.add_user("jean", "admin-pass-123", "admin")
    port = _free_port()
    env = {**os.environ, "GHOSTRECON_DB": str(gr_env / "db" / "ghostrecon.db"), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-m", "plugins.ghost_recon.cli", "serve", "--port", str(port)],
                            cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                first = httpx.get(base + "/api/v1/auth/me", timeout=2)
                break
            except httpx.TransportError:
                assert proc.poll() is None, proc.stdout.read().decode("utf-8", "replace")
                assert time.monotonic() < deadline, "the console did not start within 30 s"
                time.sleep(0.2)
        assert first.status_code == 401
        with httpx.Client(base_url=base, timeout=5) as c:
            assert c.get("/").headers["content-type"].startswith("text/html")
            assert c.post("/api/v1/auth/login", json={"username": "jean", "password": "admin-pass-123"}).status_code == 200
            assert c.get("/api/v1/auth/me").json()["user"]["role"] == "admin"
    finally:
        proc.terminate()
        proc.wait(timeout=15)
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console/test_cli.py tests/plugins/ghost_recon/console/test_serve_e2e.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console.cli'`.

- [ ] **Step 3: Crear `console/cli.py`**

El módulo solo importa la stdlib a nivel de módulo: `register()` corre cada vez que Hermes construye su parser.

```python
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
```

- [ ] **Step 4: Conectar los verbos en `plugins/ghost_recon/cli.py`**

1. En el docstring del módulo, añade al final de la lista de verbos esta línea: `       | serve [--port] | user add|list|passwd|disable|enable | token create|list|revoke   (consola web)`.
2. Debajo de `from .core.reports import pack as pack_mod`, añade:

```python
from .console import cli as console_cli
```

3. Al final de `register_cli(...)`, añade:

```python
    console_cli.register(subs)
```

4. En `main(...)`, justo después de `cmd = getattr(args, "gr_command", None)` y antes de `st = runtime.store()`, añade:

```python
    if cmd in console_cli.CONSOLE_VERBS:
        return console_cli.dispatch(args)
```

- [ ] **Step 5: Ejecutar y ver que pasan**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon -q`
Expected: `0 failed`. Incluye el E2E real de `serve` en un puerto libre.

- [ ] **Step 6: Commit**

```bash
git add plugins/ghost_recon/cli.py plugins/ghost_recon/console/cli.py tests/plugins/ghost_recon/console
git commit -m "feat(ghost-recon): hermes ghostrecon serve/user/token for the console

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Frontend base — tema, shell, login, Inicio, Casos, Sistema y demo

**Files:**
- Create: `plugins/ghost_recon/console/static/theme.css`
- Create: `plugins/ghost_recon/console/static/app.css`
- Create: `plugins/ghost_recon/console/static/favicon.svg`
- Create: `plugins/ghost_recon/console/static/lib/dom.js`
- Create: `plugins/ghost_recon/console/static/lib/api.js`
- Create: `plugins/ghost_recon/console/static/lib/format.js`
- Create: `plugins/ghost_recon/console/static/views/components.js`
- Create: `plugins/ghost_recon/console/static/views/login.js`
- Create: `plugins/ghost_recon/console/static/views/home.js`
- Create: `plugins/ghost_recon/console/static/views/cases.js`
- Create: `plugins/ghost_recon/console/static/views/system.js`
- Create: `plugins/ghost_recon/console/static/views/case.js` (provisional: solo encabezado; se completa en la Tarea 8)
- Create: `plugins/ghost_recon/console/static/app.js`
- Create: `ghost-recon/demo/console_demo.py`
- Test: `tests/plugins/ghost_recon/console/test_static.py`

**Interfaces:**
- Consumes: la API de las Tareas 3 a 5 (`/auth/*`, `/system/*`, `/cases*`).
- Produces (JS, módulos ES):
  - `lib/dom.js`: `h(tag, attrs, ...children)`, `append(el, children)`, `mount(target, ...children)`.
  - `lib/api.js`: `api(path, {method, body, query})`, `setCsrf(token)`, `downloadUrl(path)`, `class ApiError {status, code, message, data}`.
  - `lib/format.js`: `RISKS`, `RISK_LABEL`, `label.{auditStatus,auditKind,findingKind}`, `fmtDate`, `fmtDay`, `fmtAmount`, `fmtBytes`, `chip`, `riskChip`, `riskChips`, `sealChip`, `sealCheckChip`, `shortHash`, `safeHref`.
  - `views/components.js`: `kpi`, `emptyState`, `errorState`, `dataTable(columns, rows, opts)`, `toggleDetail(tr, build)`, `casesTable(rows)`, `debounce(fn, ms)`.
  - Cada vista exporta `async render(ctx) -> Node`.

- [ ] **Step 1: Escribir la prueba que falla (Review Focus #5)**

`tests/plugins/ghost_recon/console/test_static.py`:

```python
"""Frontend assets are served with module-safe MIME types (Windows can map .js to text/plain) and no auth."""


def test_frontend_assets_have_module_safe_types(client):
    for path, expected in (("/static/app.js", "text/javascript"), ("/static/lib/api.js", "text/javascript"),
                           ("/static/app.css", "text/css"), ("/static/theme.css", "text/css"),
                           ("/static/favicon.svg", "image/svg+xml")):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith(expected), (path, r.headers["content-type"])
        assert r.headers["x-content-type-options"] == "nosniff"


def test_unknown_asset_is_404(client):
    assert client.get("/static/nope.js").status_code == 404
```

- [ ] **Step 2: Ejecutarla y ver que falla**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console/test_static.py -q`
Expected: FAIL con 404 en `/static/app.js`.

- [ ] **Step 3: Crear `static/theme.css`**

```css
/* Ghost Recon theme tokens. Replace this file to apply a brand: colors, type and the logo words. */
:root {
  --gr-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --gr-mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
  --gr-logo-left: "GHOST";
  --gr-logo-right: "RECON";
  --gr-radius: 6px;

  --gr-bg: #f4f6f9;
  --gr-surface: #ffffff;
  --gr-border: #dfe4ec;
  --gr-row-border: #eef1f5;
  --gr-row-hover: #f6f8fb;
  --gr-row-detail: #f8fafc;
  --gr-input-border: #c9d2df;
  --gr-text: #1d2433;
  --gr-muted: #66738a;

  --gr-topbar: #101826;
  --gr-topbar-text: #e8edf5;
  --gr-topbar-input: #1e2a3d;
  --gr-sidebar: #16202f;
  --gr-sidebar-text: #b7c3d4;
  --gr-sidebar-active: #24324a;
  --gr-accent: #59d3a5;

  --gr-primary: #2f6fed;
  --gr-primary-text: #ffffff;
  --gr-ghost-bg: #e8edf5;

  --gr-ok-bg: #d1fadf;   --gr-ok: #05603a;
  --gr-info-bg: #dbe8ff; --gr-info: #1849a9;
  --gr-risk-critical-bg: #fbd5d5; --gr-risk-critical: #8a1c1c;
  --gr-risk-high-bg: #fde2e1;     --gr-risk-high: #b42318;
  --gr-risk-medium-bg: #fef0c7;   --gr-risk-medium: #93370d;
  --gr-risk-low-bg: #eef1f5;      --gr-risk-low: #475467;
}
```

- [ ] **Step 4: Crear `static/app.css`**

```css
/* Layout and components. Colors and type come from theme.css. No inline styles anywhere (CSP style-src 'self'). */
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body { font-family: var(--gr-font); font-size: 14px; color: var(--gr-text); background: var(--gr-bg); }
a { color: var(--gr-primary); }
:focus-visible { outline: 2px solid var(--gr-primary); outline-offset: 2px; }
.mono { font-family: var(--gr-mono); font-size: 12.5px; word-break: break-all; }
.muted { color: var(--gr-muted); }
.boot { padding: 2rem; color: var(--gr-muted); }

/* shell */
.shell { display: grid; grid-template-columns: 200px 1fr; grid-template-rows: 52px 1fr;
  grid-template-areas: "top top" "side main"; min-height: 100vh; }
.topbar { grid-area: top; display: flex; align-items: center; gap: 12px; padding: 0 16px;
  background: var(--gr-topbar); color: var(--gr-topbar-text); }
.brand { text-decoration: none; font-weight: 800; letter-spacing: .08em; color: var(--gr-topbar-text); white-space: nowrap; }
.brand::before { content: var(--gr-logo-left); }
.brand::after { content: " " var(--gr-logo-right); color: var(--gr-accent); }
.search { flex: 1; max-width: 520px; background: var(--gr-topbar-input); color: var(--gr-topbar-text); border: 0;
  border-radius: var(--gr-radius); padding: 7px 10px; font: inherit; }
.search:disabled { opacity: .6; cursor: not-allowed; }
.who { margin-left: auto; color: var(--gr-sidebar-text); font-size: 13px; }
.sidebar { grid-area: side; background: var(--gr-sidebar); padding: 12px 0; display: flex; flex-direction: column; }
.nav-item { display: block; padding: 9px 18px; color: var(--gr-sidebar-text); text-decoration: none;
  border-left: 3px solid transparent; }
.nav-item.active { background: var(--gr-sidebar-active); color: #fff; border-left-color: var(--gr-accent); }
.nav-item:hover:not(.soon) { color: #fff; }
.nav-item.soon { opacity: .5; cursor: not-allowed; }
.main { grid-area: main; padding: 20px 24px; min-width: 0; }
.page h1 { margin: 0 0 14px; font-size: 22px; }

/* cards and grids */
.card { background: var(--gr-surface); border: 1px solid var(--gr-border); border-radius: var(--gr-radius);
  padding: 14px 16px; margin-bottom: 16px; overflow-x: auto; }
.card h2 { margin: 0 0 10px; font-size: 15px; }
.card h3, .detail h3 { margin: 12px 0 6px; font-size: 12.5px; color: var(--gr-muted); text-transform: uppercase; letter-spacing: .04em; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }

/* buttons */
.btn { background: var(--gr-primary); color: var(--gr-primary-text); border: 0; border-radius: var(--gr-radius);
  padding: 7px 12px; font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
.btn.ghost { background: var(--gr-ghost-bg); color: var(--gr-text); }
.btn.small { padding: 5px 9px; font-size: 12.5px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }

/* kpis */
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
.kpi { background: var(--gr-surface); border: 1px solid var(--gr-border); border-radius: var(--gr-radius); padding: 10px 14px; }
.kpi-value { font-size: 24px; font-weight: 700; }
.kpi-title { color: var(--gr-muted); font-size: 12.5px; }
.kpi-extra { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px; font-size: 12px; color: var(--gr-muted); }

/* chips */
.chip { display: inline-block; border-radius: 10px; padding: 1px 8px; font-size: 11.5px; font-weight: 700;
  margin-right: 4px; white-space: nowrap; }
.chip.ok { background: var(--gr-ok-bg); color: var(--gr-ok); }
.chip.info { background: var(--gr-info-bg); color: var(--gr-info); }
.chip.muted { background: var(--gr-risk-low-bg); color: var(--gr-risk-low); }
.chip.risk-critical { background: var(--gr-risk-critical-bg); color: var(--gr-risk-critical); }
.chip.risk-high { background: var(--gr-risk-high-bg); color: var(--gr-risk-high); }
.chip.risk-medium { background: var(--gr-risk-medium-bg); color: var(--gr-risk-medium); }
.chip.risk-low { background: var(--gr-risk-low-bg); color: var(--gr-risk-low); }
.chips, .checks { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }

/* tables */
table.data { width: 100%; border-collapse: collapse; }
table.data th { text-align: left; color: var(--gr-muted); font-weight: 600; font-size: 12.5px; padding: 6px 8px;
  border-bottom: 1px solid var(--gr-border); }
table.data td { padding: 7px 8px; border-bottom: 1px solid var(--gr-row-border); vertical-align: top; }
table.data .num { text-align: right; font-variant-numeric: tabular-nums; }
tr.clickable { cursor: pointer; }
tr.clickable:hover td { background: var(--gr-row-hover); }
tr.detail-row > td { background: var(--gr-row-detail); }
.detail { padding: 4px 2px; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; margin: 0; }
.kv dt { color: var(--gr-muted); }
.kv dd { margin: 0; }
.history { margin: 0; padding-left: 20px; }

/* filters, tabs, case header */
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.filters input, .filters select { font: inherit; padding: 6px 8px; border: 1px solid var(--gr-input-border);
  border-radius: var(--gr-radius); background: var(--gr-surface); color: var(--gr-text); }
.filters input[type="search"] { min-width: 260px; }
.tabs { display: flex; flex-wrap: wrap; gap: 18px; border-bottom: 1px solid var(--gr-border); margin-bottom: 14px; }
.tab { padding: 8px 0; color: var(--gr-muted); text-decoration: none; border-bottom: 2px solid transparent; }
.tab.active { color: var(--gr-text); font-weight: 700; border-bottom-color: var(--gr-primary); }
.tab.soon { opacity: .5; cursor: not-allowed; }
.case-head { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.case-head h1 { margin-bottom: 4px; }
.case-head p { margin: 0; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }

/* states */
.empty { padding: 18px; text-align: center; color: var(--gr-muted); }
.error { padding: 10px 12px; border-radius: var(--gr-radius); background: var(--gr-risk-high-bg); color: var(--gr-risk-high); }

/* login */
.login-page { min-height: 100vh; display: grid; place-items: center; background: var(--gr-topbar); padding: 16px; }
.login-card { width: min(360px, 100%); background: var(--gr-surface); border-radius: 10px; padding: 26px 24px;
  display: flex; flex-direction: column; gap: 8px; }
.login-card .brand { color: var(--gr-text); font-size: 22px; }
.login-card h1 { margin: 0 0 8px; font-size: 16px; color: var(--gr-muted); font-weight: 600; }
.login-card input { font: inherit; padding: 8px 10px; border: 1px solid var(--gr-input-border); border-radius: var(--gr-radius); }
.login-card .btn { margin-top: 8px; }
.login-msg { min-height: 1.2em; margin: 4px 0 0; color: var(--gr-risk-high); font-size: 13px; }

/* narrow screens */
@media (max-width: 900px) {
  .shell { grid-template-columns: 1fr; grid-template-rows: auto auto 1fr; grid-template-areas: "top" "side" "main"; }
  .topbar { flex-wrap: wrap; padding: 8px 12px; }
  .search { order: 5; flex-basis: 100%; max-width: none; }
  .sidebar { flex-direction: row; overflow-x: auto; padding: 0; }
  .nav-item { border-left: 0; border-bottom: 3px solid transparent; }
  .nav-item.active { border-bottom-color: var(--gr-accent); }
  .main { padding: 16px; }
}
```

- [ ] **Step 5: Crear `static/favicon.svg`**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#101826"/><path d="M9 22V10h8a5 5 0 0 1 0 10h-4" fill="none" stroke="#59d3a5" stroke-width="3" stroke-linecap="round"/><circle cx="23" cy="23" r="2.5" fill="#59d3a5"/></svg>
```

- [ ] **Step 6: Crear `static/lib/dom.js`**

```js
// Minimal DOM builder. Text always goes through text nodes (textContent), never innerHTML.

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  return append(el, children);
}

export function mount(target, ...children) {
  target.replaceChildren();
  return append(target, children);
}
```

- [ ] **Step 7: Crear `static/lib/api.js`**

```js
// JSON client for /api/v1: cookie session plus the anti-CSRF header; a 401 sends the user to the login view.
const BASE = "/api/v1";
let csrf = null;

export class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export function setCsrf(token) {
  csrf = token || null;
}

export function downloadUrl(path) {
  return BASE + path;
}

export async function api(path, { method = "GET", body, query } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-GR-CSRF"] = csrf;
  const res = await fetch(url, {
    method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body),
  });
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const err = (data && data.error) || {};
    if (res.status === 401 && !path.startsWith("/auth/")) window.location.hash = "#/login";
    throw new ApiError(res.status, err.code || `http_${res.status}`, err.message || res.statusText, data);
  }
  return data;
}
```

- [ ] **Step 8: Crear `static/lib/format.js`**

```js
// Formatting helpers shared by the views. They return text or nodes built with h(), never HTML strings.
import { h } from "./dom.js";

export const RISKS = ["critical", "high", "medium", "low"];
export const RISK_LABEL = { critical: "crítico", high: "alto", medium: "medio", low: "bajo" };
const SEAL = {
  ok: ["sello OK", "ok"],
  broken: ["sello alterado", "risk-high"],
  unverified: ["sin verificar", "info"],
  none: ["sin sellar", "muted"],
};
const AUDIT_STATUS = { open: "abierta", in_progress: "en curso", validated: "validada", sealed: "sellada", failed: "fallida" };
const AUDIT_KIND = { initial: "inicial", rerun: "re-run", review: "revisión" };
const FINDING_KIND = { exception: "excepción", anomaly: "anomalía", finding: "hallazgo", question: "pregunta" };

export const label = {
  auditStatus: (s) => AUDIT_STATUS[s] || s,
  auditKind: (k) => AUDIT_KIND[k] || k,
  findingKind: (k) => FINDING_KIND[k] || k,
};

function parse(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = parse(iso);
  return d ? d.toLocaleString("es", { dateStyle: "medium", timeStyle: "short" }) : String(iso);
}

export function fmtDay(iso) {
  if (!iso) return "—";
  const d = parse(iso);
  return d ? d.toLocaleDateString("es", { dateStyle: "medium" }) : String(iso);
}

export function fmtAmount(value, currency) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  const text = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  return currency ? `${text} ${currency}` : text;
}

export function fmtBytes(value) {
  let n = Number(value) || 0;
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let i = -1;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(1)} ${units[i]}`;
}

export function chip(text, variant = "muted", title) {
  return h("span", { class: `chip ${variant}`, title }, text);
}

export function riskChip(risk, count) {
  const name = RISK_LABEL[risk] || risk;
  return chip(count === undefined ? name : `${count} ${name}`, `risk-${risk}`);
}

export function riskChips(byRisk) {
  const parts = RISKS.filter((r) => (byRisk || {})[r] > 0).map((r) => riskChip(r, byRisk[r]));
  return parts.length ? parts : [chip("ninguno", "muted")];
}

export function sealChip(state) {
  const [text, variant] = SEAL[state] || SEAL.none;
  return chip(text, variant);
}

export function sealCheckChip(audit) {
  if (audit.status !== "sealed") return chip("sin sellar", "muted");
  const check = audit.seal_check;
  if (!check) return chip("sin verificar", "info");
  const title = `verificado ${fmtDate(check.checked_at)} por ${check.checked_by || "—"}`;
  return check.ok ? chip("sello OK", "ok", title) : chip("sello alterado", "risk-high", title);
}

export function shortHash(sha) {
  return sha ? `${sha.slice(0, 12)}…` : "—";
}

// Research URLs are external content: only http(s) becomes a link (never javascript:, data:, …).
export function safeHref(url) {
  return /^https?:\/\//i.test(String(url || "")) ? String(url) : null;
}
```

- [ ] **Step 9: Crear `static/views/components.js`**

```js
// Shared view pieces: KPI tiles, data tables with expandable rows, empty/error states, the cases table, debounce.
import { h } from "../lib/dom.js";
import { fmtDate, label, riskChips, sealChip } from "../lib/format.js";

export function kpi(value, title, extra) {
  return h("div", { class: "kpi" },
    h("div", { class: "kpi-value" }, value === null || value === undefined ? "—" : String(value)),
    h("div", { class: "kpi-title" }, title),
    extra ? h("div", { class: "kpi-extra" }, extra) : null);
}

export function emptyState(text) {
  return h("div", { class: "empty" }, text);
}

export function errorState(err) {
  return h("div", { class: "error", role: "alert" }, `No se pudo cargar: ${(err && err.message) || err}`);
}

/** columns: [{ title, cell(row) -> node|string|array, class? }]; opts: { empty, onRow(row, tr) }. */
export function dataTable(columns, rows, opts = {}) {
  if (!rows || !rows.length) return emptyState(opts.empty || "Sin datos.");
  const head = h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.class, scope: "col" }, c.title))));
  const body = h("tbody");
  for (const row of rows) {
    const tr = h("tr", {}, columns.map((c) => h("td", { class: c.class }, c.cell(row))));
    if (opts.onRow) {
      tr.classList.add("clickable");
      tr.tabIndex = 0;
      const open = () => opts.onRow(row, tr);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    }
    body.append(tr);
  }
  return h("table", { class: "data" }, head, body);
}

/** Toggle a full-width detail row under `tr`; `build` is async and returns the detail node. */
export async function toggleDetail(tr, build) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("detail-row")) {
    next.remove();
    return;
  }
  const cell = h("td", { colspan: String(tr.children.length) }, "Cargando…");
  tr.after(h("tr", { class: "detail-row" }, cell));
  try {
    cell.replaceChildren(await build());
  } catch (err) {
    cell.replaceChildren(errorState(err));
  }
}

export function casesTable(rows) {
  return dataTable([
    { title: "Caso", cell: (r) => h("a", { href: `#/cases/${encodeURIComponent(r.id)}` }, r.name) },
    { title: "Última auditoría", cell: (r) => (r.last_audit
      ? `${r.last_audit.seq} · ${label.auditStatus(r.last_audit.status)} · ${fmtDate(r.last_audit.started_at)}` : "—") },
    { title: "Abiertos", cell: (r) => riskChips(r.open_by_risk) },
    { title: "Sello", cell: (r) => sealChip(r.seal_state) },
    { title: "Última actividad", cell: (r) => fmtDate(r.last_activity) },
  ], rows, { empty: "Todavía no hay casos. Se crean con /new-open-case (desde la consola en H2)." });
}

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
```

- [ ] **Step 10: Crear las vistas `login.js`, `home.js`, `cases.js` y `system.js`**

`static/views/login.js`:

```js
import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";

export async function render({ onLogin }) {
  const user = h("input", { id: "login-user", name: "username", autocomplete: "username", required: true, autofocus: true });
  const pass = h("input", { id: "login-pass", name: "password", type: "password", autocomplete: "current-password", required: true });
  const msg = h("p", { class: "login-msg", role: "alert" });
  const submit = h("button", { class: "btn", type: "submit" }, "Entrar");
  const form = h("form", {
    class: "login-card",
    onsubmit: async (event) => {
      event.preventDefault();
      submit.disabled = true;
      msg.textContent = "";
      try {
        onLogin(await api("/auth/login", { method: "POST", body: { username: user.value, password: pass.value } }));
      } catch (err) {
        msg.textContent = err.message;
      } finally {
        submit.disabled = false;
      }
    },
  },
  h("span", { class: "brand", "aria-label": "Ghost Recon" }),
  h("h1", {}, "Consola"),
  h("label", { for: "login-user" }, "Usuario"), user,
  h("label", { for: "login-pass" }, "Contraseña"), pass,
  msg, submit);
  return h("div", { class: "login-page" }, form);
}
```

`static/views/home.js`:

```js
import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { fmtDate, riskChips } from "../lib/format.js";
import { casesTable, dataTable, kpi } from "./components.js";

export async function render() {
  const o = await api("/system/overview");
  const k = o.kpis;
  return h("div", { class: "page" },
    h("h1", {}, "Inicio"),
    h("section", { class: "kpis" },
      kpi(k.cases_active, "Casos activos", `${k.cases_total} en total`),
      kpi(k.audits_sealed, "Auditorías selladas"),
      kpi(k.open_total, "Hallazgos abiertos", riskChips(k.open_by_risk)),
      kpi(k.jobs_active, "Ejecuciones activas", "disponible en H2")),
    h("section", { class: "card" }, h("h2", {}, "Casos recientes"), casesTable(o.recent_cases)),
    h("section", { class: "card" }, h("h2", {}, "Actividad reciente"), dataTable([
      { title: "Fecha", cell: (e) => fmtDate(e.ts) },
      { title: "Caso", cell: (e) => h("a", { href: `#/cases/${encodeURIComponent(e.case_id)}/timeline` }, e.case_name) },
      { title: "Evento", cell: (e) => e.event_type },
      { title: "Descripción", cell: (e) => e.description },
    ], o.recent_events, { empty: "Sin actividad todavía." })));
}
```

`static/views/cases.js`:

```js
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { casesTable, debounce, errorState } from "./components.js";

export async function render() {
  const q = h("input", { type: "search", placeholder: "Filtrar por nombre, ID o carpeta", "aria-label": "Filtrar casos" });
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "open" }, "Abiertos"),
    h("option", { value: "closed" }, "Cerrados"), h("option", { value: "archived" }, "Archivados"));
  const box = h("div");
  async function load() {
    try {
      mount(box, casesTable((await api("/cases", { query: { q: q.value, status: status.value } })).items));
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  q.addEventListener("input", debounce(load, 250));
  status.addEventListener("change", load);
  await load();
  return h("div", { class: "page" }, h("h1", {}, "Casos"), h("div", { class: "filters" }, q, status),
    h("section", { class: "card" }, box));
}
```

`static/views/system.js`:

```js
import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { chip, fmtDate } from "../lib/format.js";
import { dataTable } from "./components.js";

export async function render({ user }) {
  const doc = await api("/system/doctor");
  const parts = [
    h("h1", {}, "Sistema"),
    h("p", { class: "muted" }, `Consola ${doc.console.version} · ${doc.console.host}:${doc.console.port}`),
    h("section", { class: "card" }, h("h2", {}, doc.ok ? "Diagnóstico: todo en orden" : "Diagnóstico: requiere atención"),
      dataTable([
        { title: "Estado", cell: (c) => (c.ok ? chip("OK", "ok") : chip("revisar", "risk-high")) },
        { title: "Comprobación", cell: (c) => c.check },
        { title: "Detalle", cell: (c) => c.detail },
      ], doc.checks)),
  ];
  if (user.role === "admin") {
    const log = await api("/system/audit-log", { query: { limit: 200 } });
    parts.push(h("section", { class: "card" }, h("h2", {}, "Registro de la consola"), dataTable([
      { title: "Fecha", cell: (e) => fmtDate(e.ts) },
      { title: "Usuario", cell: (e) => e.username || "—" },
      { title: "Acción", cell: (e) => e.action },
      { title: "Objetivo", cell: (e) => e.target || "—" },
      { title: "IP", cell: (e) => e.ip || "—" },
    ], log.items, { empty: "Sin registros." })));
  }
  return h("div", { class: "page" }, parts);
}
```

- [ ] **Step 11: Crear `static/views/case.js` provisional (se reemplaza en la Tarea 8)**

```js
import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";

export async function render({ params }) {
  const detail = await api(`/cases/${encodeURIComponent(params[0])}`);
  return h("div", { class: "page" }, h("h1", {}, detail.case.name), h("p", { class: "muted mono" }, detail.case.id));
}
```

- [ ] **Step 12: Crear `static/app.js`**

```js
// Console bootstrap: hash router, session bootstrap and the application shell (top bar + sidebar).
import { api, setCsrf } from "./lib/api.js";
import { h, mount } from "./lib/dom.js";
import * as caseView from "./views/case.js";
import * as cases from "./views/cases.js";
import { errorState } from "./views/components.js";
import * as home from "./views/home.js";
import * as login from "./views/login.js";
import * as system from "./views/system.js";

const state = { user: null };

const ROUTES = [
  { re: /^\/login$/, view: login, public: true },
  { re: /^\/$/, view: home, nav: "home" },
  { re: /^\/cases$/, view: cases, nav: "cases" },
  { re: /^\/cases\/([^/]+)(?:\/([a-z]+))?$/, view: caseView, nav: "cases" },
  { re: /^\/system$/, view: system, nav: "system" },
];

const NAV = [
  { id: "home", label: "Inicio", href: "#/" },
  { id: "cases", label: "Casos", href: "#/cases" },
  { id: "jobs", label: "Ejecuciones", soon: "Disponible en H2" },
  { id: "system", label: "Sistema", href: "#/system" },
];

async function ensureSession() {
  if (state.user) return true;
  try {
    const me = await api("/auth/me");
    state.user = me.user;
    setCsrf(me.csrf);
    return true;
  } catch {
    return false;
  }
}

async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
  } finally {
    state.user = null;
    setCsrf(null);
    window.location.hash = "#/login";
  }
}

function shell(navId) {
  const main = h("main", { class: "main", id: "main", tabindex: "-1" });
  const root = h("div", { class: "shell" },
    h("header", { class: "topbar" },
      h("a", { class: "brand", href: "#/", "aria-label": "Ghost Recon, inicio" }),
      h("input", { class: "search", type: "search", placeholder: "Búsqueda entre casos (disponible en H3)", disabled: true, "aria-label": "Buscar" }),
      h("button", { class: "btn", disabled: true, title: "Disponible en H2" }, "+ Nueva auditoría"),
      h("span", { class: "who" }, `${state.user.username} · ${state.user.role}`),
      h("button", { class: "btn ghost small", onclick: logout }, "Salir")),
    h("nav", { class: "sidebar", "aria-label": "Secciones" }, NAV.map((n) => (n.soon
      ? h("span", { class: "nav-item soon", title: n.soon }, n.label)
      : h("a", { class: n.id === navId ? "nav-item active" : "nav-item", href: n.href, "aria-current": n.id === navId ? "page" : null }, n.label)))),
    main);
  return { root, main };
}

function onLogin(data) {
  state.user = data.user;
  setCsrf(data.csrf);
  window.location.hash = "#/";
}

async function render() {
  const path = window.location.hash.replace(/^#/, "") || "/";
  const route = ROUTES.find((r) => r.re.test(path)) || ROUTES[1];
  const params = (path.match(route.re) || []).slice(1).map((p) => (p === undefined ? undefined : decodeURIComponent(p)));
  const app = document.getElementById("app");
  app.classList.remove("boot");
  if (route.public) {
    mount(app, await route.view.render({ params, onLogin }));
    return;
  }
  if (!(await ensureSession())) {
    window.location.hash = "#/login";
    return;
  }
  const { root, main } = shell(route.nav);
  mount(app, root);
  mount(main, h("p", { class: "muted" }, "Cargando…"));
  try {
    mount(main, await route.view.render({ params, user: state.user }));
  } catch (err) {
    mount(main, errorState(err));
  }
}

window.addEventListener("hashchange", render);
render();
```

- [ ] **Step 13: Crear `ghost-recon/demo/console_demo.py`**

```python
#!/usr/bin/env python3
"""Ghost Recon console demo: seeds an isolated DB with the demo case and starts the console (no LLM, no Hermes).

    python ghost-recon/demo/console_demo.py [--port 9230]

Copies demo/demo-case to a temp folder, builds a sealed A01 (md pack, findings, a criterion) and an open A02,
creates the admin ``demo`` / ``demo-pass-123`` and the viewer ``visor`` / ``visor-pass-123``, and serves the
console on http://localhost:<port>. Use it to try the UI and for H4 acceptance rehearsals.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=9230)
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="gr-console-demo-"))
    os.environ["GHOSTRECON_DB"] = str(tmp / "ghostrecon.db")

    import uvicorn
    from plugins.ghost_recon import runtime
    from plugins.ghost_recon.console.app import create_app
    from plugins.ghost_recon.console.auth import AuthService
    from plugins.ghost_recon.console.settings import ConsoleSettings
    from plugins.ghost_recon.console.store import ConsoleStore
    from plugins.ghost_recon.core import casefolder as cf, service
    from plugins.ghost_recon.core.reports import pack

    case_dir = tmp / "Acme Importaciones"
    shutil.copytree(REPO / "ghost-recon" / "demo" / "demo-case", case_dir)
    store = runtime.store()
    case_id = service.open_case(store, str(case_dir), name="Acme Importaciones")["case"]["id"]
    a1 = service.start_audit(store, case_id, "initial")
    a1_id, a1_folder = a1["audit"]["id"], Path(a1["folder"])
    service.upsert_findings(store, a1_id, [
        {"kind": "exception", "title": "Pagos Zelle a socio sin factura soporte", "amount": 12450.0, "currency": "USD",
         "risk": "high", "confidence": "PROBABLE", "label": "CALCULATION", "counterparty": "Socio B",
         "owner": "Socio B", "next_evidence": "Facturas del socio ene–mar 2026",
         "evidence_refs": ["Bancos/extracto_2026-01.txt", "Bancos/listado_zelle_2026Q1.zip"]},
        {"kind": "anomaly", "title": "Factura de proveedor con fecha posterior al pago", "amount": 3200.0,
         "currency": "USD", "risk": "medium", "confidence": "POSSIBLE", "label": "INFERENCE", "owner": "Fábrica"},
        {"kind": "question", "title": "¿Quién autorizó el acta de diciembre?", "risk": "medium",
         "confidence": "UNRESOLVED", "label": "UNKNOWN", "owner": "Gerencia"},
    ])
    service.add_criterion(store, a1_id, "Gerencia", "El periodo auditado es enero–junio 2026.")
    cf.write_json(a1_folder, "03_Extracted_Data/model.json", {"kpis": {"Ingresos": 182000.0}})
    cf.write_text(a1_folder, "06_Report/report.md", "## 1. Respuesta\n\nResumen del caso demo.\n")
    pack.build_pack(store, a1_id, formats=["md"])
    service.record_run(store, a1_id, "validation", role="A", status="done", summary="recálculo desde crudo OK")
    service.seal_audit(store, a1_id, force=True)
    (case_dir / "Bancos" / "extracto_2026-03.txt").write_text("2026-03-02;ZELLE;Socio B;-1500.00\n", encoding="utf-8")
    service.start_audit(store, case_id, "rerun")

    settings = ConsoleSettings(port=args.port)
    cstore = ConsoleStore.open_default()
    auth = AuthService(cstore, settings)
    auth.add_user("demo", "demo-pass-123", "admin")
    auth.add_user("visor", "visor-pass-123", "viewer")
    print(f"Consola demo en http://localhost:{args.port}\n  admin:  demo / demo-pass-123\n"
          f"  viewer: visor / visor-pass-123\n  datos:  {tmp}", flush=True)
    uvicorn.run(create_app(settings, store, cstore, auth=auth), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 14: Ejecutar las pruebas**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`, incluido `test_static.py`.

- [ ] **Step 15: Smoke manual en navegador** (o con Playwright si está disponible)

Run: `.venv/Scripts/python.exe ghost-recon/demo/console_demo.py --port 9231` en Windows, o `.venv/bin/python …` en Linux/macOS. Abre `http://localhost:9231` y comprueba:
- [ ] la pantalla de login aparece con la marca GHOST RECON; con una contraseña errónea muestra "usuario o contraseña incorrectos";
- [ ] tras entrar como `demo`, Inicio muestra 1 caso activo, 1 auditoría sellada, 3 hallazgos abiertos (1 alto y 2 medios), "Casos recientes" y "Actividad reciente";
- [ ] Casos filtra por texto ("acme" lo muestra; "zzz" muestra el estado vacío);
- [ ] al hacer clic en el caso se abre su encabezado provisional (nombre e ID);
- [ ] Sistema muestra el doctor y, como admin, el registro de la consola, que incluye `login`;
- [ ] "Salir" vuelve al login; tras entrar como `visor`, Sistema no muestra el registro;
- [ ] la consola del navegador no muestra errores de CSP ni de MIME.

Detén el demo con Ctrl+C.

- [ ] **Step 16: Commit**

```bash
git add plugins/ghost_recon/console/static ghost-recon/demo/console_demo.py tests/plugins/ghost_recon/console/test_static.py
git commit -m "feat(ghost-recon): console frontend shell (login, home, cases, system) and demo launcher

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Frontend — Página del caso y sus 7 pestañas

**Files:**
- Modify (reemplazar): `plugins/ghost_recon/console/static/views/case.js`
- Create: `plugins/ghost_recon/console/static/views/case/summary.js`
- Create: `plugins/ghost_recon/console/static/views/case/audits.js`
- Create: `plugins/ghost_recon/console/static/views/case/findings.js`
- Create: `plugins/ghost_recon/console/static/views/case/evidence.js`
- Create: `plugins/ghost_recon/console/static/views/case/criteria.js`
- Create: `plugins/ghost_recon/console/static/views/case/research.js`
- Create: `plugins/ghost_recon/console/static/views/case/timeline.js`

**Interfaces:**
- Consumes:
  - `GET /cases/{id}`, `…/findings`, `…/evidence`, `…/evidence/stats`, `…/criteria`, `…/research`, `…/timeline`;
  - `GET /cases/{id}/audits/{seq}`, `…/reports`, `…/reports/{rid}/download`, `POST …/verify`;
  - los helpers de la Tarea 7.
- Produces: la vista de caso con pestañas en la ruta `#/cases/<id>/<tab>`, donde `tab ∈ {summary, audits, findings, evidence, criteria, research, timeline, jobs}`. Cada módulo de pestaña exporta `async render({ caseId, detail, user }) -> Node`.

- [ ] **Step 1: Reemplazar `static/views/case.js`**

```js
import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { fmtDate, riskChips, sealChip } from "../lib/format.js";
import { emptyState, errorState, kpi } from "./components.js";
import * as audits from "./case/audits.js";
import * as criteria from "./case/criteria.js";
import * as evidence from "./case/evidence.js";
import * as findings from "./case/findings.js";
import * as research from "./case/research.js";
import * as summary from "./case/summary.js";
import * as timeline from "./case/timeline.js";

const TABS = [
  { id: "summary", label: "Resumen", view: summary },
  { id: "audits", label: "Auditorías", view: audits },
  { id: "findings", label: "Hallazgos", view: findings },
  { id: "evidence", label: "Evidencia", view: evidence },
  { id: "criteria", label: "Criterios", view: criteria },
  { id: "research", label: "Investigación", view: research },
  { id: "timeline", label: "Cronología", view: timeline },
  { id: "jobs", label: "Ejecuciones", view: null },
];

function rerender() {
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

async function verifySeals(detail, button) {
  button.disabled = true;
  button.textContent = "Verificando…";
  try {
    for (const audit of detail.audits.filter((a) => a.status === "sealed")) {
      await api(`/cases/${encodeURIComponent(detail.case.id)}/audits/${audit.seq}/verify`, { method: "POST" });
    }
    rerender();
  } catch (err) {
    button.disabled = false;
    button.textContent = "Verificar sellos";
    button.title = `Error: ${err.message}`;
  }
}

function duplicates(stats) {
  return Object.entries(stats || {}).filter(([k]) => k.startsWith("DUP")).reduce((sum, [, v]) => sum + v, 0);
}

export async function render({ params, user }) {
  const [caseId, tabId = "summary"] = params;
  const detail = await api(`/cases/${encodeURIComponent(caseId)}`);
  const c = detail.case;
  const s = detail.summary;
  const tab = TABS.find((t) => t.id === tabId) || TABS[0];
  const verify = h("button", { class: "btn ghost", disabled: s.sealed_count === 0 }, "Verificar sellos");
  verify.addEventListener("click", () => verifySeals(detail, verify));
  const body = h("div", { class: "tab-body" }, h("p", { class: "muted" }, "Cargando…"));
  const page = h("div", { class: "page" },
    h("div", { class: "case-head" },
      h("div", {}, h("h1", {}, c.name),
        h("p", { class: "muted mono" }, `${c.id} · ${c.base_currency} · ${c.language} · ${c.root_path}`)),
      h("div", { class: "actions" },
        h("button", { class: "btn", disabled: true, title: "Disponible en H2" }, "▶ Re-run"),
        h("button", { class: "btn", disabled: true, title: "Disponible en H2" }, "▶ Review"),
        verify,
        h("button", { class: "btn ghost", disabled: true, title: "Disponible en H3" }, "Exportar resultados (.zip)"))),
    h("section", { class: "kpis" },
      kpi(s.audits_count, "Auditorías", sealChip(s.seal_state)),
      kpi(s.open_total, "Hallazgos abiertos", riskChips(s.open_by_risk)),
      kpi(detail.evidence.total || 0, "Evidencia", `${duplicates(detail.evidence)} duplicados`),
      kpi(fmtDate(s.last_activity), "Última actividad")),
    h("nav", { class: "tabs", "aria-label": "Secciones del caso" }, TABS.map((t) => (t.view
      ? h("a", { class: t.id === tab.id ? "tab active" : "tab", href: `#/cases/${encodeURIComponent(c.id)}/${t.id}`,
        "aria-current": t.id === tab.id ? "page" : null }, t.label)
      : h("span", { class: "tab soon", title: "Disponible en H2" }, t.label)))),
    body);
  try {
    body.replaceChildren(tab.view ? await tab.view.render({ caseId: c.id, detail, user })
      : emptyState("Las ejecuciones del caso llegan en H2."));
  } catch (err) {
    body.replaceChildren(errorState(err));
  }
  return page;
}
```

- [ ] **Step 2: Crear `static/views/case/summary.js`**

```js
import { h } from "../../lib/dom.js";
import { fmtDate, label } from "../../lib/format.js";

function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v === null || v === undefined || v === "" ? "—" : v)]));
}

function counts(obj, fmt = (k) => k) {
  return Object.entries(obj || {}).filter(([k]) => k !== "total").map(([k, v]) => `${fmt(k)}: ${v}`).join(" · ");
}

export async function render({ detail }) {
  const c = detail.case;
  const last = detail.summary.last_audit;
  return h("div", { class: "grid-2" },
    h("section", { class: "card" }, h("h2", {}, "Caso"), kv([
      ["ID", h("span", { class: "mono" }, c.id)],
      ["Carpeta de evidencia", h("span", { class: "mono" }, c.root_path)],
      ["Carpeta de resultados", h("span", { class: "mono" }, detail.results_root)],
      ["Estado", c.status], ["Moneda", c.base_currency], ["Idioma", c.language], ["Creado", fmtDate(c.created_at)],
      ["Última auditoría", last ? `${last.seq} · ${label.auditKind(last.kind)} · ${label.auditStatus(last.status)}` : null],
    ])),
    h("section", { class: "card" }, h("h2", {}, "Contenido"), kv([
      ["Evidencia por estado", counts(detail.evidence)],
      ["Hallazgos por tipo", counts(detail.findings.by_kind, label.findingKind)],
      ["Hallazgos por estado", counts(detail.findings.by_status)],
      ["Criterios", String(detail.criteria)],
      ["Notas de investigación", String(detail.research_notes)],
    ])));
}
```

- [ ] **Step 3: Crear `static/views/case/audits.js`**

```js
import { api, downloadUrl } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { chip, fmtBytes, fmtDate, label, sealCheckChip, shortHash } from "../../lib/format.js";
import { dataTable, toggleDetail } from "../components.js";

const CHECK_LABEL = {
  manifest: "manifiesto", evidence_register: "registro de evidencia", model_json: "model.json", report_md: "informe MD",
  report_pdf: "informe PDF", workbook_xlsx: "workbook XLSX", validation: "validación", exceptions_export: "export de excepciones",
};

async function auditDetail(caseId, audit, user) {
  const base = `/cases/${encodeURIComponent(caseId)}/audits/${audit.seq}`;
  const [d, reports] = await Promise.all([api(base), api(`${base}/reports`)]);
  const canDownload = audit.status === "sealed" || user.role === "admin";
  const broken = d.seal_check && !d.seal_check.ok ? d.seal_check.detail : null;
  return h("div", { class: "detail" },
    h("h3", {}, "Completitud"),
    h("div", { class: "checks" }, Object.entries(d.completion.checks).map(([k, ok]) =>
      chip(`${ok ? "✓" : "✗"} ${CHECK_LABEL[k] || k}`, ok ? "ok" : "risk-high"))),
    broken ? h("p", { class: "error" }, `Sello alterado: ${(broken.modified || []).length} modificados, `
      + `${(broken.missing || []).length} faltantes, ${(broken.added || []).length} añadidos.`) : null,
    h("h3", {}, "Entregables"),
    dataTable([
      { title: "Archivo", cell: (r) => (canDownload
        ? h("a", { href: downloadUrl(`${base}/reports/${r.id}/download`), download: r.name }, r.name) : r.name) },
      { title: "Tipo", cell: (r) => `${r.kind} · ${r.format} · ${r.version}` },
      { title: "Tamaño", class: "num", cell: (r) => fmtBytes(r.size) },
      { title: "SHA-256", cell: (r) => h("span", { class: "mono", title: r.sha256 }, shortHash(r.sha256)) },
    ], reports.items, { empty: "Sin entregables registrados." }),
    canDownload ? null : h("p", { class: "muted" }, "Los entregables de auditorías abiertas solo los descarga un admin."));
}

export async function render({ caseId, detail, user }) {
  return h("section", { class: "card" }, dataTable([
    { title: "Auditoría", cell: (a) => h("strong", {}, a.seq) },
    { title: "Tipo", cell: (a) => label.auditKind(a.kind) },
    { title: "Estado", cell: (a) => label.auditStatus(a.status) },
    { title: "Iniciada", cell: (a) => fmtDate(a.started_at) },
    { title: "Sellada", cell: (a) => fmtDate(a.sealed_at) },
    { title: "Sello", cell: (a) => sealCheckChip(a) },
    { title: "Entregables", class: "num", cell: (a) => String(a.reports) },
  ], detail.audits, { empty: "Sin auditorías.", onRow: (a, tr) => toggleDetail(tr, () => auditDetail(caseId, a, user)) }));
}
```

- [ ] **Step 4: Crear `static/views/case/findings.js`**

```js
import { api } from "../../lib/api.js";
import { h, mount } from "../../lib/dom.js";
import { fmtAmount, fmtDate, riskChip } from "../../lib/format.js";
import { dataTable, debounce, errorState, toggleDetail } from "../components.js";

function select(name, options, selected) {
  return h("select", { "aria-label": name }, options.map(([value, text]) => h("option", { value, selected: value === selected }, text)));
}

function change(entry) {
  if (typeof entry.change === "string") return entry.change;
  return Object.entries(entry.change || {}).map(([k, v]) => `${k} → ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
}

function findingDetail(f) {
  const refs = Array.isArray(f.evidence_refs) ? f.evidence_refs : [];
  const history = Array.isArray(f.history) ? f.history : [];
  return h("div", { class: "detail" },
    f.description ? h("p", {}, f.description) : null,
    h("dl", { class: "kv" },
      h("dt", {}, "Siguiente evidencia"), h("dd", {}, f.next_evidence || "—"),
      h("dt", {}, "Quién aporta"), h("dd", {}, f.owner || "—"),
      h("dt", {}, "Contraparte / entidad"), h("dd", {}, [f.counterparty, f.entity].filter(Boolean).join(" · ") || "—"),
      h("dt", {}, "Evidencia"), h("dd", {}, refs.length
        ? h("ul", {}, refs.map((r) => h("li", { class: "mono" }, typeof r === "string" ? r : JSON.stringify(r)))) : "—")),
    h("h3", {}, "Historia entre auditorías"),
    h("ol", { class: "history" }, history.map((e) =>
      h("li", {}, `${fmtDate(e.ts)} · ${e.audit_id ? e.audit_id.split("/").pop() : "—"} · ${change(e)}`))));
}

export async function render({ caseId }) {
  const kind = select("Tipo", [["", "Todos los tipos"], ["exception", "Excepciones"], ["anomaly", "Anomalías"],
    ["finding", "Hallazgos"], ["question", "Preguntas"]], "");
  const risk = select("Riesgo", [["", "Todos los riesgos"], ["critical", "Crítico"], ["high", "Alto"], ["medium", "Medio"],
    ["low", "Bajo"]], "");
  const status = select("Estado", [["", "Todos los estados"], ["open", "Abiertos"], ["closed", "Cerrados"],
    ["downgraded", "Degradados"], ["upgraded", "Elevados"], ["superseded", "Sustituidos"]], "open");
  const q = h("input", { type: "search", placeholder: "Buscar por ID, título, contraparte…", "aria-label": "Buscar hallazgos" });
  const box = h("div");
  async function load() {
    try {
      const data = await api(`/cases/${encodeURIComponent(caseId)}/findings`,
        { query: { kind: kind.value, risk: risk.value, status: status.value, q: q.value } });
      mount(box, dataTable([
        { title: "ID", cell: (f) => h("strong", { class: "mono" }, f.id) },
        { title: "Título", cell: (f) => f.title },
        { title: "Monto", class: "num", cell: (f) => fmtAmount(f.amount, f.currency) },
        { title: "Riesgo", cell: (f) => riskChip(f.risk) },
        { title: "Confianza", cell: (f) => f.confidence },
        { title: "Etiqueta", cell: (f) => f.label },
        { title: "Estado", cell: (f) => f.status },
        { title: "Quién aporta", cell: (f) => f.owner || "—" },
      ], data.items, { empty: "No hay hallazgos con estos filtros.", onRow: (f, tr) => toggleDetail(tr, async () => findingDetail(f)) }));
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  for (const el of [kind, risk, status]) el.addEventListener("change", load);
  q.addEventListener("input", debounce(load, 250));
  await load();
  return h("section", { class: "card" }, h("div", { class: "filters" }, kind, risk, status, q), box);
}
```

- [ ] **Step 5: Crear `static/views/case/evidence.js`**

```js
import { api } from "../../lib/api.js";
import { h, mount } from "../../lib/dom.js";
import { chip, fmtBytes, shortHash } from "../../lib/format.js";
import { dataTable, debounce, errorState } from "../components.js";

const PAGE = 100;

export async function render({ caseId, detail }) {
  const stats = await api(`/cases/${encodeURIComponent(caseId)}/evidence/stats`);
  const status = h("select", { "aria-label": "Estado" }, h("option", { value: "" }, "Todos los estados"),
    Object.keys(stats.statuses).filter((k) => k !== "total").map((k) => h("option", { value: k }, k)));
  const audit = h("select", { "aria-label": "Auditoría" }, h("option", { value: "" }, "Todas las auditorías"),
    detail.audits.filter((a) => a.kind !== "review").map((a) => h("option", { value: a.seq }, `Primera vez en ${a.seq}`)));
  const q = h("input", { type: "search", placeholder: "Buscar por ruta, nombre o hash…", "aria-label": "Buscar evidencia" });
  const box = h("div");
  const more = h("button", { class: "btn ghost", type: "button", hidden: true }, "Cargar más");
  let rows = [];
  let cursor = null;
  const columns = [
    { title: "Ruta", cell: (e) => h("span", { class: "mono" }, e.path) },
    { title: "Tipo", cell: (e) => e.ext || "—" },
    { title: "Tamaño", class: "num", cell: (e) => fmtBytes(e.size) },
    { title: "Estado", cell: (e) => chip(e.status, e.status.startsWith("DUP") ? "risk-medium" : "muted") },
    { title: "Bloque", cell: (e) => e.block },
    { title: "Auditoría", cell: (e) => (e.first_audit_id ? e.first_audit_id.split("/").pop() : "—") },
    { title: "SHA-256", cell: (e) => h("span", { class: "mono", title: e.sha256 }, shortHash(e.sha256)) },
  ];
  async function load(reset) {
    try {
      if (reset) {
        rows = [];
        cursor = null;
      }
      const data = await api(`/cases/${encodeURIComponent(caseId)}/evidence`,
        { query: { status: status.value, audit: audit.value, q: q.value, limit: PAGE, cursor } });
      rows = rows.concat(data.items);
      cursor = data.next_cursor;
      mount(box, h("p", { class: "muted" }, `${rows.length} de ${data.total} archivos`),
        dataTable(columns, rows, { empty: "No hay evidencia con estos filtros." }));
      more.hidden = !cursor;
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  status.addEventListener("change", () => load(true));
  audit.addEventListener("change", () => load(true));
  q.addEventListener("input", debounce(() => load(true), 250));
  more.addEventListener("click", () => load(false));
  await load(true);
  return h("section", { class: "card" },
    h("div", { class: "chips" }, Object.entries(stats.blocks).map(([k, v]) => chip(`${k}: ${v}`, "muted"))),
    h("div", { class: "filters" }, status, audit, q), box, more);
}
```

- [ ] **Step 6: Crear `criteria.js`, `research.js` y `timeline.js`**

`static/views/case/criteria.js`:

```js
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { dataTable } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/criteria`);
  return h("section", { class: "card" }, dataTable([
    { title: "ID", cell: (c) => h("strong", { class: "mono" }, c.id) },
    { title: "Fecha", cell: (c) => c.date || "—" },
    { title: "Autor", cell: (c) => c.author },
    { title: "Texto (literal)", cell: (c) => c.text },
    { title: "Estado", cell: (c) => c.status },
    { title: "Auditoría", cell: (c) => (c.audit_id ? c.audit_id.split("/").pop() : "—") },
  ], data.items, { empty: "Sin criterios registrados." }));
}
```

`static/views/case/research.js`:

```js
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmtDate, safeHref } from "../../lib/format.js";
import { dataTable } from "../components.js";

function source(note) {
  const href = safeHref(note.url);
  const text = note.title || note.url || "—";
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text) : text;
}

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/research`);
  return h("section", { class: "card" }, dataTable([
    { title: "Fecha", cell: (n) => fmtDate(n.created_at) },
    { title: "Acción", cell: (n) => n.action },
    { title: "Consulta", cell: (n) => n.query || "—" },
    { title: "Fuente", cell: source },
    { title: "Extracto", cell: (n) => n.snippet || "—" },
    { title: "Auditoría", cell: (n) => (n.audit_id ? n.audit_id.split("/").pop() : "—") },
  ], data.items, { empty: "Sin notas de investigación." }));
}
```

`static/views/case/timeline.js`:

```js
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmtDate } from "../../lib/format.js";
import { dataTable } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/timeline`);
  return h("section", { class: "card" }, dataTable([
    { title: "Fecha", cell: (e) => fmtDate(e.ts) },
    { title: "Evento", cell: (e) => e.event_type },
    { title: "Auditoría", cell: (e) => (e.audit_id ? e.audit_id.split("/").pop() : "—") },
    { title: "Actor", cell: (e) => e.actor },
    { title: "Descripción", cell: (e) => e.description },
  ], data.items, { empty: "Sin eventos." }));
}
```

- [ ] **Step 7: Pruebas automáticas (regresión)**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`.

- [ ] **Step 8: Smoke manual de la página del caso**

Lanza el demo (Tarea 7, Step 15), entra como `demo`, abre el caso y comprueba:
- [ ] el encabezado muestra nombre, ID, moneda, idioma y carpeta, con Re-run, Review y Exportar deshabilitados con su aviso;
- [ ] los indicadores muestran 2 auditorías con "sin verificar", 3 abiertos y la evidencia con duplicados;
- [ ] **Resumen** muestra las carpetas y los conteos;
- [ ] **Auditorías**: al expandir A01 aparecen los checks de completitud y el informe `.md`, cuya descarga funciona; "Verificar sellos" convierte el sello en "sello OK";
- [ ] **Hallazgos**: el filtro "Abiertos" viene por defecto, el riesgo "Alto" deja solo EXC-01, la búsqueda "zelle" funciona y al expandir se ven la historia, la evidencia y quién aporta;
- [ ] **Evidencia**: aparecen los chips por bloque y los filtros de estado y auditoría ("Primera vez en A02" muestra el archivo nuevo); "Cargar más" aparece solo si hay más de 100 archivos;
- [ ] **Criterios** muestra CRIT-01; **Investigación** muestra el estado vacío; **Cronología** va de lo más reciente a lo más antiguo;
- [ ] la pestaña Ejecuciones aparece deshabilitada;
- [ ] como `visor`, en A02 (abierta) no hay enlaces de descarga y se muestra el aviso;
- [ ] modificar a mano un archivo de `A01_*/06_Report/` y pulsar "Verificar sellos" marca el sello como "sello alterado" con el conteo de modificados;
- [ ] la consola del navegador no muestra errores.

- [ ] **Step 9: Commit**

```bash
git add plugins/ghost_recon/console/static/views
git commit -m "feat(ghost-recon): console case page with summary, audits, findings, evidence, criteria, research and timeline tabs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Configuración, documentación, verificación completa y PR

**Files:**
- Modify: `plugins/ghost_recon/plugin.yaml` (`config_schema.console`)
- Modify: `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (§4.1, §5 y §8: cómo quedó H1)
- Modify: `ghost-recon/COMMANDS.md` (nueva sección 3b)
- Modify: `ghost-recon/README.md` (fila de la consola)
- Modify: `ghost-recon/AGENTS.md` (reglas y "Dónde está cada cosa")
- Modify: `ghost-recon/PLAN.md` (Fase 8 y registro de cambios)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: documentación coherente con el código y un PR integrado a `main`.

- [ ] **Step 1: `plugin.yaml`**

Añade al final de `config_schema:`:

```yaml
  console:
    type: dict
    default: {}
    description: "Consola web (hermes ghostrecon serve): host, port, session_idle_hours, session_max_days, allowed_hosts. Ver ghost-recon/COMMANDS.md §3b."
```

- [ ] **Step 2: Spec**

En `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`:
- §4.1: añade en el árbol las líneas `├── deps.py             dependencias FastAPI: contexto, principal, roles, ApiError`, `├── readmodel.py        lecturas puras para la API (resúmenes de caso, filtros, paginación)` y `├── paths.py            raíz de resultados de un caso y contención de rutas`.
- §5: añade la tabla `console_seal_checks  audit_id PK, ok (0/1), checked_at, checked_by, detail JSON` y la nota "caché de la última verificación de sello por auditoría".
- §8:
  - sustituye "OpenAPI en `/api/docs`, tras el login" por "OpenAPI en `/api/v1/openapi.json`, tras el login (sin Swagger UI: cargaría recursos externos, contra la CSP)";
  - en la viñeta de `verify`, sustituye "en `console_audit_log.detail`" por "en `console_seal_checks` (y la acción queda en `console_audit_log`)".

- [ ] **Step 3: `COMMANDS.md`**

Inserta antes de `## 4. Herramientas del agente (toolset \`ghost_recon\`)`:

````markdown
## 3b. Consola web (sin agente en H1)

```
hermes ghostrecon serve [--host 127.0.0.1] [--port 9230] [--allow-remote]
hermes ghostrecon user add <nombre> --role admin|viewer [--password-stdin]
hermes ghostrecon user list | passwd <nombre> | disable <nombre> | enable <nombre>
hermes ghostrecon token create --user <nombre> --name <etiqueta>     (Bearer; se muestra una sola vez)
hermes ghostrecon token list | token revoke <id>
```

- Escucha en `127.0.0.1:9230`. Desde otra PC se entra por túnel: `ssh -L 9230:127.0.0.1:9230 usuario@maquina` y luego `http://localhost:9230`.
- `serve` no arranca sin un admin activo. Fuera de loopback exige `--allow-remote` y un proxy TLS delante.
- Roles: `viewer` lee y descarga entregables de auditorías selladas; `admin` además descarga los de auditorías abiertas y ve el registro de la consola.
- API: `/api/v1/…`; el esquema está en `/api/v1/openapi.json`, tras el login.
- Configuración: `plugins.entries.ghost-recon.settings.console` en `config.yaml` (`host`, `port`, `session_idle_hours`, `session_max_days`, `allowed_hosts`).
- Demo local sin LLM: `python ghost-recon/demo/console_demo.py`.
- Diseño completo y próximos hitos (lanzar órdenes, exportar ZIP, búsqueda, avisos): `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`.
````

- [ ] **Step 4: `README.md`**

En la tabla "Quiero… / Lee / ejecuta", añade después de la fila "Instalar en la máquina autónoma":

```markdown
| Operar desde el navegador (consola web) | `hermes ghostrecon user add <nombre> --role admin` y `hermes ghostrecon serve` → `http://localhost:9230` (por túnel desde otra PC) · [`COMMANDS.md`](COMMANDS.md) §3b · demo: `python ghost-recon/demo/console_demo.py` |
```

- [ ] **Step 5: `AGENTS.md`**

En "Reglas de edición", añade:

```markdown
- La consola (`plugins/ghost_recon/console/`) **solo escribe tablas `console_*`**; los datos de caso se leen por `core`
  (`Store`, `service`). Todo path que llega del navegador pasa por `console/paths.resolve_within`. En el frontend,
  nada de `innerHTML` con datos: siempre `h()` (`static/lib/dom.js`).
```

En "Dónde está cada cosa", añade:

```markdown
| añadir un endpoint a la consola | `console/routers/<recurso>.py` + `console/readmodel.py` (lógica pura) + `ROUTERS` en `console/app.py` |
| cambiar login, roles o sesiones de la consola | `console/auth.py`, `console/deps.py` (`require`, CSRF) |
| cambiar una pantalla de la consola | `console/static/views/*.js` (pestañas del caso en `views/case/`) y `static/app.css` |
| cambiar colores/logo de la consola | `console/static/theme.css` (variables) |
```

- [ ] **Step 6: `PLAN.md`**

Antes de `---\n\n## 3. Riesgos`, añade:

```markdown
### Fase 8 — Consola web (spec `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`)
- [x] H1 · Base: `hermes ghostrecon serve|user|token`, login/roles/tokens, API de lectura, verificación de sellos cacheada, descargas contenidas, frontend (Inicio, Casos, Caso con 7 pestañas, Sistema), demo `console_demo.py`
- [ ] H2 · Ejecuciones: navegador de carpetas, asistente Nueva auditoría con notas de contexto, motor de jobs desacoplado, vista en vivo, Re-run/Review
- [ ] H3 · Exportación `.zip` verificable, tablas CSV/XLSX, búsqueda entre casos, avisos
- [ ] H4 · Instaladores `--console`/servicio, `CONSOLE.md`, aceptación en la máquina dedicada
```

Y en "## 4. Registro de cambios", añade:

```markdown
- 2026-10-02 · v1.3 · Fase 8 (consola web) diseñada y H1 implementado: servidor propio en loopback (túnel), login con roles admin/viewer y tokens Bearer, API `/api/v1` de solo lectura sobre la BD de casos, caché de verificación de sellos, descargas contenidas en la carpeta de cada auditoría, frontend sin build. Sin cambios al core de Hermes.
```

- [ ] **Step 7: Verificación completa**

Run: `scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py tests/skills/test_authoring_standards.py tests/skills/test_skill_docs_contract.py tests/hermes_cli/test_plugin_cli_registration.py tests/hermes_cli/test_plugin_api_compat.py -q`
Expected: `0 failed`. Los skipped corresponden solo a pruebas de pack completo sin libs opcionales y a pruebas marcadas para otro SO.

Run: `.venv/Scripts/python.exe ghost-recon/demo/smoke_test.py` (o `.venv/bin/python …`)
Expected: `SMOKE TEST OK`. El ciclo del core sigue intacto tras el cambio en `runtime`.

Run: `git diff --stat origin/main...HEAD -- . ':!plugins/ghost_recon' ':!ghost-recon' ':!tests/plugins/ghost_recon'`
Expected: salida vacía, es decir, ningún archivo fuera del vertical.

- [ ] **Step 8: Commit de documentación**

```bash
git add plugins/ghost_recon/plugin.yaml ghost-recon
git commit -m "docs(ghost-recon): console H1 commands, config schema, area rules and plan status

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 9: Integrar con `main` y abrir el PR**

Antes de abrir el PR, escribe `pr_body.md` en el directorio temporal de la sesión (fuera del repo) con estas secciones:
- **Resumen:** el alcance de H1 (lista de la Fase 8 en `PLAN.md`) y el enlace a la spec;
- **Pruebas:** la salida de resumen del Step 7, en cifras reales, y el `SMOKE TEST OK`;
- **Smoke manual:** las casillas marcadas de las Tareas 7 y 8;
- **Alcance:** la salida vacía del `git diff --stat` fuera del vertical, como prueba de que el core no se toca;
- al final, la línea `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

```bash
git fetch origin main
git merge --no-edit origin/main          # main avanza a menudo (sincronizaciones con upstream)
scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_skill_docs_contract.py -q
git push -u origin ghost-recon-console
gh pr create -R SiteOneTech/agent-ghost-recon-forensic-finance --base main --head ghost-recon-console \
  --title "feat(ghost-recon): console H1 — base (serve, login, read API, case pages)" --body-file "$TMPDIR/pr_body.md"
```

Merge con merge commit fijado al SHA verificado (`gh pr merge <n> --merge --match-head-commit <sha>`), después de la verificación y con el visto bueno del operador.
