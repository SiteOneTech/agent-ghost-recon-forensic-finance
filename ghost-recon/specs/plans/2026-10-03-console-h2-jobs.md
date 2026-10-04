# Consola Ghost Recon · H2 (Ejecuciones) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el operador lance y siga las auditorías desde el navegador, sin terminal y sin escribir rutas:
- navegador de carpetas limitado a `case_roots`, revisión previa y asistente «+ Nueva auditoría» en 3 pasos;
- Re-run y Review desde la página del caso, con «Notas adicionales» del operador;
- motor de ejecuciones desacoplado (un `job_runner` por ejecución) con límites, cola, cancelación del árbol de procesos, huérfanos y supervivencia al reinicio del servidor;
- vista de Ejecución en vivo (fases, actividad, «Hasta ahora», resultado), lista de Ejecuciones, pestaña Ejecuciones del caso e Inicio en vivo;
- «Usuarios y tokens» en Sistema y una UI sin nombres de hito ni comandos.

**Architecture:**
- Todo vive en `plugins/ghost_recon/console/`, encima de H1:
  - `fsjail.py` resuelve, lista, busca e inspecciona carpetas dentro de `case_roots`;
  - `commands.py` es la tabla de órdenes: valida, arma el texto `-q` que espera cada skill, el argv exacto y el contexto combinado (§7). La vista previa y el lanzamiento usan la misma función, `plan()`;
  - `events.py` (puro) convierte el `stream-json` del agente en eventos de consola y deduce la fase;
  - `jobs.py` (`JobService`) crea, encola, despacha, cancela y supervisa; `job_runner.py` es el proceso desacoplado que ejecuta el agente; `procs.py` concentra el contacto con los internos de Hermes (lanzador de la instalación, entorno del perfil, desacople) y psutil;
  - routers `fs.py`, `jobs.py` (JSON + SSE) y `users.py`; el frontend añade vistas sin build.
- La fila de `console_jobs` es el único estado compartido entre servidor y runner. Toda escritura de estado es condicional (`expect=`), así que una cancelación o un veredicto de huérfano siempre ganan a una escritura tardía.
- El core de Hermes no cambia.

**Tech Stack:** Python 3.14, FastAPI/Starlette (SSE con `StreamingResponse`) y uvicorn, SQLite (WAL), psutil (dependencia del core), pytest con `scripts/run_tests.sh`, JS en módulos ES nativos y CSS con variables.

**Spec:** `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (léela entera antes de empezar; este plan implementa su hito H2, §13, más las decisiones del propietario recogidas en Global Constraints). Plan anterior, para convenciones: `ghost-recon/specs/plans/2026-10-02-console-h1-base.md`.

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
- Commits: un commit por tarea, en convención `type(scope): …`, terminando con la línea `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Además, en H2:

- **Escrituras permitidas, completas:** tablas `console_*`; el archivo de contexto combinado en `<resultados>/_console/context_<hash>.md` (nunca entre los archivos de evidencia); los eventos `console_job_launched`, `console_job_cancelled` y `console_job_finished` en la cronología del caso mediante `Store.add_event` (spec §6.2 y §9). Nada más.
- **Órdenes:** argv como lista, sin shell, construido solo por `commands.plan()`; la vista previa (`POST /jobs/preview`) y el lanzamiento (`POST /jobs`) llaman a la misma función y el runner ejecuta el argv guardado en la fila, sin reconstruirlo. Argv del agente: `<hermes> -p <perfil> --cli --accept-hooks --skills <skill> chat -q "<orden>" --format stream-json --source ghost-recon-console`.
- **Validación:** carpetas resueltas con `realpath` dentro de `case_roots`; se rechazan vacías, relativas, UNC, con segmento `..` y en otra unidad. Moneda `^[A-Z]{3}$`, idioma `es|en`, nombre ≤ 120 caracteres sin comillas dobles ni saltos de línea, notas ≤ 20 000 caracteres.
- **Límites:** `max_parallel_jobs` (por defecto 2) y una ejecución activa por carpeta o caso; lo demás queda `queued`. Despacho al arrancar, tras cada lanzamiento o cancelación y cada 10 s. Repetir la misma orden sobre una carpeta que ya la tiene activa o en cola → `409 already_active`.
- **Carpetas:** búsqueda con profundidad ≤ 4, ≤ 200 resultados y ≤ 3 s; el listado oculta archivos ocultos o de sistema y la carpeta de resultados (`GhostRecon_Audits`).
- **En vivo:** SSE que sondea el archivo cada 1 s, con latido cada 15 s y reanudación por `Last-Event-ID`.
- **Procesos (spec §4.3):**
  - el ejecutable de Hermes y el del runner salen de `hermes_cli/_launchers.py` (`installation_command` en POSIX, `runtime_command` en Windows), nunca del `PATH` (el `shutil.which` desnudo está prohibido fuera de `hermes_platform/`);
  - el entorno de los hijos sale de `tools/environments/local.py::served_profile_child_env(inherit_credentials=True)`, nunca de `os.environ.copy()`;
  - el desacople sale de `hermes_cli/_subprocess_compat.py::windows_detach_popen_kwargs()`;
  - vigilar y matar procesos se hace con psutil, verificando la identidad (PID + create time) para no tocar nunca un PID reciclado;
  - todo esto vive en `console/procs.py`, el único módulo de H2 que importa internos de Hermes para procesos.
- **Alcance decidido por el propietario:**
  - se añade «Usuarios y tokens» en Sistema (solo admin), reutilizando `AuthService`/`ConsoleStore`, con cada acción en `console_audit_log`; el último admin activo no se puede deshabilitar ni degradar, y un admin no puede deshabilitarse ni cambiarse el rol a sí mismo;
  - la UI no menciona hitos ni comandos: lo de H3 (ZIP, CSV/XLSX, búsqueda entre casos, avisos) aparece deshabilitado con el aviso «Próximamente»; los estados vacíos ofrecen la acción como botón;
  - sin `case_roots`, la consola lo explica en español y nombra el ajuste que hay que pedir; **no** hay editor de configuración (la consola no escribe `config.yaml`);
  - **no** hay subida de evidencia (el operador copia las carpetas con RustDesk/SFTP a una raíz de casos);
  - `notify_target`, exportación y búsqueda entre casos siguen en H3.
- Los datos de despliegue (usuario `ghostrecon`, `HERMES_HOME=/home/ghostrecon/.hermes`, lanzador `<checkout>/.hermes/bin/hermes`, raíz `/home/ghostrecon/GhostRecon/Casos`, dashboard en `http://127.0.0.1:9119`) **se documentan**; ningún valor se escribe en el código.

## Review Focus

1. **Salida `gr_*` truncada.** `stream_json` corta la salida de cada herramienta a 5 000 caracteres, así que el JSON de `gr_case_open` o `gr_swarm_plan` llega roto en casos reales. El normalizador debe seguir resumiendo con el ID del caso, nunca fallar. La prueba vive en la Tarea 3.
2. **Carpetas con espacios, acentos y comillas.** "Caso Logística Norte" debe llegar intacta del navegador al `-q` y al argv que recibe el agente (POSIX y Windows); una comilla doble en una ruta o un nombre debe rechazarse, no romper el texto `-q`. Las pruebas viven en la Tarea 4 (validación y comillas) y en la Tarea 7 (el argv registrado por el agente falso es el de la fila).
3. **Runner muerto mientras el servidor es su padre.** En POSIX un hijo muerto sin `wait()` queda zombi y psutil lo sigue viendo «vivo»: el job nunca pasaría a `orphaned`. La prueba vive en la Tarea 6.
4. **Cancelación contra la escritura final del runner.** Si el runner termina justo cuando se cancela, nunca debe sobrescribir `cancelled` con `failed` o `succeeded`. La prueba vive en la Tarea 5.
5. **Reconexión SSE.** `EventSource` reconecta con `Last-Event-ID`; el stream no debe repetir ni saltarse eventos. La prueba vive en la Tarea 7.

## Mapa de archivos

| Archivo | Acción | Responsabilidad | Tarea |
|---|---|---|---|
| `plugins/ghost_recon/console/settings.py` | Modificar | claves `case_roots`, `max_parallel_jobs`, `dashboard_url` | 1 |
| `plugins/ghost_recon/console/store.py` | Modificar | migraciones versionadas, tabla `console_jobs` y sus métodos | 1 |
| `plugins/ghost_recon/console/fsjail.py` | Crear | jaula de carpetas: raíces, listado, búsqueda, inspección, caso existente | 2 |
| `plugins/ghost_recon/console/events.py` | Crear | `stream-json` → eventos de consola y fases (puro) | 3 |
| `plugins/ghost_recon/console/commands.py` | Crear | tabla de órdenes, validación, `-q`, argv, contexto combinado, comando copiable | 4 |
| `plugins/ghost_recon/console/procs.py` | Crear (T4) y ampliar (T5) | lanzador de la instalación, perfil, entorno, desacople, identidad y árbol con psutil | 4, 5 |
| `plugins/ghost_recon/console/jobfiles.py` | Crear | archivos por ejecución: lectura incremental, eventos, cola del log | 5 |
| `plugins/ghost_recon/console/job_runner.py` | Crear | proceso desacoplado que ejecuta el agente y escribe estado y eventos | 5 |
| `ghost-recon/demo/fake_agent.py` | Crear | agente falso con las formas reales de `stream-json` (pruebas y demo) | 5 |
| `plugins/ghost_recon/console/jobs.py` | Crear | `JobService`: lanzar, encolar, despachar, cancelar, huérfanos, ciclo | 6 |
| `plugins/ghost_recon/console/deps.py` | Modificar | `ConsoleContext.jobs` | 7 |
| `plugins/ghost_recon/console/app.py` | Modificar | `create_app(..., jobs=)`, lifespan del ciclo, routers nuevos | 7, 9 |
| `plugins/ghost_recon/console/readmodel.py` | Modificar | `job_row`, `job_view`, `progress`; Inicio con ejecuciones activas | 7 |
| `plugins/ghost_recon/console/routers/fs.py` | Crear | `GET /fs/roots`, `/fs/list`, `/fs/search`, `/fs/inspect` | 7 |
| `plugins/ghost_recon/console/routers/jobs.py` | Crear | `POST /jobs/preview`, `POST /jobs`, cancelar, listas, detalle, eventos, SSE, log | 7 |
| `plugins/ghost_recon/console/routers/system.py` | Modificar | doctor con las raíces de casos y espacio libre | 7 |
| `ghost-recon/demo/console_demo.py` | Modificar | raíz de casos temporal y agente falso para probar la UI | 7 |
| `tests/plugins/ghost_recon/console/serve_fake.py` | Crear | servidor real con el agente falso para el E2E (no es una prueba) | 8 |
| `plugins/ghost_recon/console/auth.py` | Modificar | errores de cuenta con estado HTTP, `set_role`, actor en los registros de tokens | 9 |
| `plugins/ghost_recon/console/routers/users.py` | Crear | usuarios y tokens (admin) | 9 |
| `plugins/ghost_recon/console/static/app.js` | Modificar | rutas nuevas, navegación, botón «+ Nueva auditoría», limpieza al salir de una vista | 10, 11 |
| `plugins/ghost_recon/console/static/lib/format.js` | Modificar | etiquetas de órdenes y estados, duraciones | 10 |
| `plugins/ghost_recon/console/static/views/components.js` | Reemplazar | estados vacíos con acción, tablas de ejecuciones, campos, diálogos, copiar | 10 |
| `plugins/ghost_recon/console/static/views/launch.js` | Crear | panel de lanzamiento compartido y diálogo Re-run/Review | 10 |
| `plugins/ghost_recon/console/static/views/job.js` | Crear | vista de Ejecución en vivo | 10 |
| `plugins/ghost_recon/console/static/views/jobs.js` | Crear | lista de Ejecuciones | 10 |
| `plugins/ghost_recon/console/static/views/case/jobs.js` | Crear | pestaña Ejecuciones del caso | 10 |
| `plugins/ghost_recon/console/static/views/{home,cases,case}.js` | Modificar | Inicio en vivo, estados vacíos con botón, Re-run/Review, barrido de textos | 10 |
| `plugins/ghost_recon/console/static/app.css` | Modificar | estilos de ejecuciones, diálogos, formularios, asistente y usuarios | 10, 11 |
| `plugins/ghost_recon/console/static/views/wizard.js` | Crear | asistente «+ Nueva auditoría» | 11 |
| `plugins/ghost_recon/console/static/views/users.js` | Crear | Sistema › Usuarios y tokens | 11 |
| `plugins/ghost_recon/console/static/views/system.js` | Modificar | acceso a Usuarios y tokens | 11 |
| `tests/plugins/ghost_recon/console/conftest.py` | Modificar | `case_root`, `demo_case` dentro de la raíz, agente falso, `make_jobs`, `login_on` | 2, 5, 6, 7 |
| `tests/plugins/ghost_recon/console/test_*.py` | Crear | `store_jobs`, `fsjail`, `events`, `commands`, `procs`, `runner`, `jobs`, `api_fs`, `api_jobs`, `jobs_e2e`, `api_users` | 1–9 |
| `ghost-recon/{COMMANDS,AGENTS,PLAN,README}.md`, spec, `plugin.yaml` | Modificar | documentación de H2 y del despliegue | 12 |

---

### Task 0: Entorno de pruebas y línea base

**Files:** ninguno (solo entorno).

- [ ] **Step 1: Comprobar el venv de pruebas del worktree.** Si `.venv/` no existe en la raíz del worktree, constrúyelo:

```bash
python -m pm.build_env --source . --out .venv --group dev --group test
```

Expected: termina con `✓ Installing Python dependencies` y la ruta de `.venv/.../python`.

- [ ] **Step 2: Línea base verde de Ghost Recon**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py -q`
Expected: `0 failed`. Sin `openpyxl` y `reportlab` hay 2 skipped (pack completo); las pruebas marcadas para otro SO también salen como skipped.

---

### Task 1: Ajustes de ejecuciones y migraciones versionadas con `console_jobs`

**Files:**
- Modify: `plugins/ghost_recon/console/settings.py` (reemplazo completo)
- Modify: `plugins/ghost_recon/console/store.py`
- Test: `tests/plugins/ghost_recon/console/test_store_jobs.py`

**Interfaces:**
- Consumes: `core.db.connect`, `core.db.migrate`, `core.db.utcnow`; `ConsoleStore._insert/_one/_all/_update` y `_j` (H1).
- Produces:
  - `ConsoleSettings` gana `case_roots: tuple = ()`, `max_parallel_jobs: int = 2` y `dashboard_url: str = ""` (solo `http(s)`, sin la `/` final). `from_mapping` y `load_settings` mantienen su firma.
  - `store.py`:
    - constantes `CONSOLE_SCHEMA_VERSION = 2`, `CONSOLE_SCHEMA` (la v1 de H1, intacta), `CONSOLE_MIGRATIONS: Dict[int, List[str]]`, `JOB_COMMANDS`, `JOB_STATUSES`, `ACTIVE_STATUSES = ("queued", "running")` y `TERMINAL_STATUSES`;
    - `migrate_console(conn) -> int` aplica la v1 y luego cada migración por encima de la versión guardada (tabla de una fila);
    - `ConsoleStore.create_job(*, command, folder, args, argv, launched_by, context_file=None, case_id=None) -> dict`, `get_job(job_id) -> dict` (`{}` si no existe), `list_jobs(*, statuses=(), case_id="", folder="", limit=200, oldest_first=False) -> list[dict]`, `update_job(job_id, *, expect=(), **fields) -> bool`;
    - las columnas JSON `args`, `argv` y `tokens` vuelven decodificadas.

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_store_jobs.py`:

```python
"""console_jobs and the new console settings: versioned migration from an H1 database, conditional job updates."""
import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings
from plugins.ghost_recon.console.store import ACTIVE_STATUSES, CONSOLE_SCHEMA, CONSOLE_SCHEMA_VERSION, ConsoleStore
from plugins.ghost_recon.core.db import connect, migrate


def test_settings_parse_case_roots_job_limit_and_dashboard_url():
    s = ConsoleSettings.from_mapping({"case_roots": ["/casos", " ", "/casos", "/otros"], "max_parallel_jobs": "3",
                                      "dashboard_url": "http://127.0.0.1:9119/"})
    assert s.case_roots == ("/casos", "/otros")
    assert s.max_parallel_jobs == 3 and s.dashboard_url == "http://127.0.0.1:9119"


def test_invalid_job_settings_fall_back_to_safe_defaults():
    d = ConsoleSettings()
    s = ConsoleSettings.from_mapping({"case_roots": "/casos", "max_parallel_jobs": 0,
                                      "dashboard_url": "javascript:alert(1)"})
    assert (s.case_roots, s.max_parallel_jobs, s.dashboard_url) == ((), d.max_parallel_jobs, "")


def test_an_h1_database_migrates_to_the_current_version_once(gr_env):
    path = gr_env / "h1.db"
    conn = connect(path)
    migrate(conn)
    for stmt in CONSOLE_SCHEMA:  # exactly what H1 created
        conn.execute(stmt)
    conn.execute("INSERT INTO console_schema_version(version) VALUES (1)")
    conn.commit()
    ConsoleStore(conn)
    again = ConsoleStore.open(path)
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "console_jobs" in tables
    versions = [tuple(r) for r in again.conn.execute("SELECT version FROM console_schema_version")]
    assert versions == [(CONSOLE_SCHEMA_VERSION,)]


def test_job_rows_round_trip_argv_and_json_columns(cstore):
    argv = ["/opt/h/.hermes/bin/hermes", "-q", '/new-open-case "/casos/Caso Logística"']
    job = cstore.create_job(command="new-open-case", folder="/casos/Caso Logística", args={"name": "Logística"},
                            argv=argv, launched_by="jean")
    assert job["status"] == "queued" and job["argv"] == argv and job["args"] == {"name": "Logística"}
    cstore.update_job(job["id"], tokens={"total": 15})
    assert cstore.get_job(job["id"])["tokens"] == {"total": 15}
    assert cstore.get_job(job["id"] + 100) == {}


def test_status_updates_only_apply_while_the_expected_status_holds(cstore):
    job = cstore.create_job(command="rerun-case", folder="/c", args={}, argv=["x"], launched_by="jean")
    assert cstore.update_job(job["id"], expect=("queued",), status="running")
    assert cstore.update_job(job["id"], status="cancelled")
    assert not cstore.update_job(job["id"], expect=ACTIVE_STATUSES, status="failed")  # a late writer loses
    assert cstore.get_job(job["id"])["status"] == "cancelled"


def test_job_writes_reject_unknown_fields_statuses_and_orders(cstore):
    job = cstore.create_job(command="review-case", folder="/c", args={}, argv=["x"], launched_by="jean")
    with pytest.raises(ValueError):
        cstore.update_job(job["id"], argv=["y"])
    with pytest.raises(ValueError):
        cstore.update_job(job["id"], status="paused")
    with pytest.raises(ValueError):
        cstore.create_job(command="rm-rf", folder="/c", args={}, argv=["x"], launched_by="jean")


def test_jobs_are_listed_by_status_and_by_case_or_folder(cstore):
    a = cstore.create_job(command="new-open-case", folder="/c/a", args={}, argv=["x"], launched_by="jean")
    b = cstore.create_job(command="rerun-case", folder="/c/b", args={}, argv=["x"], launched_by="jean",
                          case_id="GRC-b")
    cstore.update_job(b["id"], status="succeeded")
    assert [j["id"] for j in cstore.list_jobs()] == [b["id"], a["id"]]
    assert [j["id"] for j in cstore.list_jobs(statuses=ACTIVE_STATUSES)] == [a["id"]]
    both = cstore.list_jobs(case_id="GRC-b", folder="/c/a", oldest_first=True)
    assert [j["id"] for j in both] == [a["id"], b["id"]]
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_store_jobs.py -q`
Expected: FAIL con `ImportError: cannot import name 'ACTIVE_STATUSES' from 'plugins.ghost_recon.console.store'`.

- [ ] **Step 3: Reemplazar `console/settings.py`**

```python
"""Console settings: ``plugins.entries.ghost-recon.settings.console`` in config.yaml, with safe defaults."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Tuple

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def _str_list(value: Any) -> Tuple[str, ...]:
    """Non-empty, stripped, de-duplicated strings of a YAML list; anything else is an empty tuple."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))


def _http_url(value: Any) -> str:
    """An http(s) base URL without its trailing slash, or "" (the console only ever links http(s))."""
    text = str(value or "").strip()
    return text.rstrip("/") if text.lower().startswith(("http://", "https://")) else ""


@dataclass(frozen=True)
class ConsoleSettings:
    host: str = "127.0.0.1"
    port: int = 9230
    session_idle_hours: int = 12
    session_max_days: int = 7
    allowed_hosts: tuple = LOOPBACK_HOSTS
    case_roots: tuple = ()
    max_parallel_jobs: int = 2
    dashboard_url: str = ""

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

        hosts = tuple(h.lower() for h in _str_list(raw.get("allowed_hosts")))
        return cls(host=str(raw.get("host") or d.host), port=positive_int("port", d.port),
                   session_idle_hours=positive_int("session_idle_hours", d.session_idle_hours),
                   session_max_days=positive_int("session_max_days", d.session_max_days),
                   allowed_hosts=tuple(dict.fromkeys(LOOPBACK_HOSTS + hosts)),
                   case_roots=_str_list(raw.get("case_roots")),
                   max_parallel_jobs=positive_int("max_parallel_jobs", d.max_parallel_jobs),
                   dashboard_url=_http_url(raw.get("dashboard_url")))


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

- [ ] **Step 4: Constantes y tipos en `console/store.py`**

Sustituye:

```python
from typing import Any, Dict, List, Optional
```

por:

```python
from typing import Any, Dict, Iterable, List, Optional
```

y sustituye:

```python
CONSOLE_SCHEMA_VERSION = 1
ROLES = ("viewer", "admin")
_JSON_COLS = ("detail", "ref")
_USER_FIELDS = frozenset({"password_hash", "disabled", "last_login_at", "role"})
```

por:

```python
CONSOLE_SCHEMA_VERSION = 2
ROLES = ("viewer", "admin")
JOB_COMMANDS = ("new-open-case", "rerun-case", "review-case")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "orphaned")
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "orphaned")
_JSON_COLS = ("detail", "ref", "args", "argv", "tokens")
_USER_FIELDS = frozenset({"password_hash", "disabled", "last_login_at", "role"})
_JOB_FIELDS = frozenset({"case_id", "context_file", "status", "pid", "pid_started", "runner_pid", "runner_started",
                         "session_id", "exit_code", "started_at", "finished_at", "result_text", "tokens", "error",
                         "phase", "notify_target"})
```

- [ ] **Step 5: Migraciones versionadas**

En `console/store.py`, sustituye la función completa:

```python
def migrate_console(conn: sqlite3.Connection) -> int:
    for stmt in CONSOLE_SCHEMA:
        conn.execute(stmt)
    if conn.execute("SELECT version FROM console_schema_version").fetchone() is None:
        conn.execute("INSERT INTO console_schema_version(version) VALUES (?)", (CONSOLE_SCHEMA_VERSION,))
    conn.commit()
    return CONSOLE_SCHEMA_VERSION
```

por:

```python
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
}


def migrate_console(conn: sqlite3.Connection) -> int:
    """Idempotent and versioned: the v1 baseline, then every migration above the stored version, then the new
    version in the one-row ``console_schema_version`` table."""
    for stmt in CONSOLE_SCHEMA:
        conn.execute(stmt)
    row = conn.execute("SELECT version FROM console_schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO console_schema_version(version) VALUES (1)")
    current = int(row[0]) if row is not None else 1
    for version in sorted(v for v in CONSOLE_MIGRATIONS if v > current):
        for stmt in CONSOLE_MIGRATIONS[version]:
            conn.execute(stmt)
        conn.execute("UPDATE console_schema_version SET version=?", (version,))
    conn.commit()
    return CONSOLE_SCHEMA_VERSION
```

- [ ] **Step 6: Métodos de ejecuciones**

Añade al final de la clase `ConsoleStore` (después de `recent_events`):

```python
    # ---------------------------------------------------------------- jobs
    def create_job(self, *, command: str, folder: str, args: Dict[str, Any], argv: List[str], launched_by: str,
                   context_file: Optional[str] = None, case_id: Optional[str] = None) -> Dict[str, Any]:
        if command not in JOB_COMMANDS:
            raise ValueError(f"orden desconocida: {command}")
        job_id = self._insert(
            "INSERT INTO console_jobs(command, case_id, folder, args, argv, context_file, status, launched_by,"
            " created_at) VALUES (?,?,?,?,?,?,'queued',?,?)",
            (command, case_id, folder, _j(args), _j([str(a) for a in argv]), context_file, launched_by, utcnow()))
        return self.get_job(job_id)

    def get_job(self, job_id: int) -> Dict[str, Any]:
        return self._one("SELECT * FROM console_jobs WHERE id=?", (int(job_id),))

    def list_jobs(self, *, statuses: Iterable[str] = (), case_id: str = "", folder: str = "", limit: int = 200,
                  oldest_first: bool = False) -> List[Dict[str, Any]]:
        """Newest first (oldest first for the dispatcher). ``case_id`` and ``folder`` together match either: a
        case's jobs include the ones launched on its folder before the case existed."""
        where: List[str] = []
        args: List[Any] = []
        statuses = tuple(statuses)
        if statuses:
            where.append(f"status IN ({','.join('?' * len(statuses))})")
            args += statuses
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
```

- [ ] **Step 7: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed` (incluidas las pruebas de H1, en particular `test_store.py`, que sigue viendo una sola fila en `console_schema_version`).

- [ ] **Step 8: Commit**

```bash
git add plugins/ghost_recon/console/settings.py plugins/ghost_recon/console/store.py tests/plugins/ghost_recon/console/test_store_jobs.py
git commit -m "feat(ghost-recon): console job settings and versioned console migrations with console_jobs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `fsjail` — raíces, listado, búsqueda e inspección

**Files:**
- Create: `plugins/ghost_recon/console/fsjail.py`
- Modify: `tests/plugins/ghost_recon/console/conftest.py` (`case_root`, `demo_case` dentro de la raíz, `settings` con `case_roots`)
- Test: `tests/plugins/ghost_recon/console/test_fsjail.py`

**Interfaces:**
- Consumes: `paths.resolve_within`, `paths.case_results_root`; `core.casefolder` (`audits_root`, `read_case_json`, `IGNORED_NAMES`, `IGNORED_PREFIXES`, `OCR_EXTS`); `Store.get_case`, `Store.list_audits`.
- Produces (`console/fsjail.py`):
  - constantes `MAX_SEARCH_DEPTH = 4`, `MAX_SEARCH_RESULTS = 200`, `SEARCH_BUDGET_S = 3.0`, `COUNT_CAP = 2000`, `INSPECT_CAP = 50_000`, `CONTEXT_PREVIEW_CHARS = 20_000`, `MANY_IMAGES = 50`;
  - `class FsJailError(Exception)` con `code` (`bad_path` | `outside_roots` | `not_a_folder` | `bad_query`) y `message`;
  - `folder_key(path) -> str` (comparable; sin mayúsculas en Windows);
  - `configured_roots(raw: Iterable[str]) -> List[Path]` (solo las que existen, resueltas);
  - `resolve(raw: str, roots) -> Path`;
  - `existing_case(store, folder: Path, audits_dirname: str) -> Optional[dict]` con claves `id, name, source ("db"|"case.json"), audits, sealed, last_status, results_root, base_currency, language`;
  - `context_info(folder: Path, roots) -> Optional[dict]` con `path, sha256, size, text, truncated` (ignora un `context.md` que apunte fuera de las raíces);
  - `count_files(folder, skip=(), cap=COUNT_CAP) -> {"files", "capped"}`;
  - `roots_view(roots) -> list[{name, path, free_bytes}]`;
  - `list_dir(raw, roots, *, store, audits_dirname) -> dict` con `path, name, root, parent, breadcrumb, case, files, capped, items[{name, path, case, files, capped}]`;
  - `search(query, roots, *, skip=(), max_depth, limit, budget_s, clock) -> {"items": [{name, path, root}], "truncated", "timed_out"}`;
  - `inspect(raw, roots, *, store, audits_dirname, defaults, active_jobs=()) -> dict` con `path, name, files, capped, size, by_type[{ext, count}], zips, images, context, case, results_root, active_jobs, warnings[{code, text}], suggested_command, defaults{name, currency, lang}`; códigos de aviso: `empty`, `many_images`, `sealed_case`, `active_job`.
- Fixtures de pruebas: `case_root` (`<tmp>/Casos`), `demo_case` (sustituye a la del plugin: el caso demo **dentro** de `case_root`) y `settings` con `case_roots=(case_root,)`.

- [ ] **Step 1: Fixtures de la raíz de casos**

En `tests/plugins/ghost_recon/console/conftest.py`, sustituye la cabecera:

```python
"""Fixtures for the console tests (they build on tests/plugins/ghost_recon/conftest.py: gr_env, store, demo_case)."""
import pytest
from pathlib import Path

from plugins.ghost_recon.console.settings import ConsoleSettings
```

por:

```python
"""Fixtures for the console tests (they build on tests/plugins/ghost_recon/conftest.py: gr_env, store)."""
import shutil
from pathlib import Path

import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings

REPO = Path(__file__).resolve().parents[4]
DEMO = REPO / "ghost-recon" / "demo" / "demo-case"
```

y sustituye la fixture `settings`:

```python
@pytest.fixture
def settings():
    return ConsoleSettings()
```

por:

```python
@pytest.fixture
def case_root(gr_env):
    """The configured case root of the console tests (spec §12 ``case_roots``)."""
    root = gr_env / "Casos"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture
def demo_case(case_root):
    """The demo case copied INSIDE the case root (overrides the plugin-level fixture) so jobs can target it."""
    dest = case_root / "demo-case"
    shutil.copytree(DEMO, dest)
    return dest


@pytest.fixture
def settings(case_root):
    return ConsoleSettings(case_roots=(str(case_root),))
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_fsjail.py`:

```python
"""Folder jail: only paths inside case_roots, never via '..', UNC, relative paths, symlinks or other drives."""
import ctypes
import hashlib
import os
from pathlib import Path

import pytest

from plugins.ghost_recon.console import fsjail
from plugins.ghost_recon.console.fsjail import FsJailError
from plugins.ghost_recon.core import service

AUDITS = "GhostRecon_Audits"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "Raiz"
    (r / "Caso A" / "Bancos").mkdir(parents=True)
    (r / "Caso A" / "Bancos" / "extracto.txt").write_text("x", encoding="utf-8")
    (r / "Nueva B").mkdir()
    for i in range(3):
        (r / "Nueva B" / f"f{i}.csv").write_text("x", encoding="utf-8")
    (r / ".oculta").mkdir()
    return r


def _code(fn, *args, **kwargs):
    with pytest.raises(FsJailError) as err:
        fn(*args, **kwargs)
    return err.value.code


def test_only_absolute_paths_inside_a_root_resolve(root, tmp_path):
    roots = fsjail.configured_roots([str(root)])
    assert fsjail.resolve(str(root / "Caso A"), roots) == (root / "Caso A").resolve()
    outside = tmp_path / "fuera"
    outside.mkdir()
    assert _code(fsjail.resolve, str(outside), roots) == "outside_roots"
    assert _code(fsjail.resolve, str(root / "no-existe"), roots) == "outside_roots"
    assert _code(fsjail.resolve, str(root / "Caso A" / ".." / "Nueva B"), roots) == "bad_path"  # even inside
    assert _code(fsjail.resolve, "Caso A", roots) == "bad_path"
    assert _code(fsjail.resolve, "", roots) == "bad_path"
    assert _code(fsjail.resolve, str(root), []) == "outside_roots"


def test_configured_roots_skip_missing_and_repeated_entries(root, tmp_path):
    assert fsjail.configured_roots([str(root), str(tmp_path / "no-existe"), str(root)]) == [root.resolve()]


@pytest.mark.platforms("posix")
def test_symlink_escaping_a_root_is_rejected_and_not_listed(root, tmp_path, store):
    secret = tmp_path / "secreto"
    secret.mkdir()
    os.symlink(secret, root / "enlace", target_is_directory=True)
    roots = fsjail.configured_roots([str(root)])
    assert _code(fsjail.resolve, str(root / "enlace"), roots) == "outside_roots"
    names = [i["name"] for i in fsjail.list_dir(str(root), roots, store=store, audits_dirname=AUDITS)["items"]]
    assert "enlace" not in names


@pytest.mark.platforms("posix")
def test_a_context_md_that_links_outside_the_roots_is_not_read(root, tmp_path, store):
    secret = tmp_path / "secreto.md"
    secret.write_text("no", encoding="utf-8")
    os.symlink(secret, root / "Nueva B" / "context.md")
    roots = fsjail.configured_roots([str(root)])
    info = fsjail.inspect(str(root / "Nueva B"), roots, store=store, audits_dirname=AUDITS, defaults={})
    assert info["context"] is None


@pytest.mark.platforms("windows")
def test_unc_paths_and_other_drives_are_rejected(root):
    roots = fsjail.configured_roots([str(root)])
    assert _code(fsjail.resolve, r"\\localhost\c$\Windows", roots) == "outside_roots"
    other = next((f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                  if d != root.drive[0].upper() and Path(f"{d}:\\").exists()), "Z:\\")
    assert _code(fsjail.resolve, other, roots) == "outside_roots"


@pytest.mark.platforms("windows")
def test_windows_hidden_folders_are_not_listed(root, store):
    hidden = root / "Sistema"
    hidden.mkdir()
    assert ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2)  # FILE_ATTRIBUTE_HIDDEN
    roots = fsjail.configured_roots([str(root)])
    names = [i["name"] for i in fsjail.list_dir(str(root), roots, store=store, audits_dirname=AUDITS)["items"]]
    assert "Sistema" not in names and "Caso A" in names


def test_listing_marks_cases_counts_files_and_hides_results_and_hidden(root, store):
    case = service.open_case(store, str(root / "Caso A"), name="Caso A")["case"]
    roots = fsjail.configured_roots([str(root)])
    listing = fsjail.list_dir(str(root), roots, store=store, audits_dirname=AUDITS)
    items = {i["name"]: i for i in listing["items"]}
    assert set(items) == {"Caso A", "Nueva B"}
    assert items["Caso A"]["case"]["id"] == case["id"] and items["Nueva B"]["case"] is None
    assert items["Nueva B"]["files"] == 3 and not items["Nueva B"]["capped"]
    inside = fsjail.list_dir(items["Caso A"]["path"], roots, store=store, audits_dirname=AUDITS)
    assert [i["name"] for i in inside["items"]] == ["Bancos"]  # the results folder is not evidence
    assert [c["path"] for c in inside["breadcrumb"]] == [str(root.resolve()), items["Caso A"]["path"]]
    assert inside["parent"] == str(root.resolve()) and listing["parent"] is None


def test_search_is_bounded_in_depth_results_and_time(root):
    (root / "n1" / "n2" / "n3" / "objetivo-4" / "n5" / "objetivo-6").mkdir(parents=True)
    for i in range(fsjail.MAX_SEARCH_RESULTS + 5):
        (root / "Nueva B" / f"lote-{i:03d}").mkdir()
    roots = fsjail.configured_roots([str(root)])
    assert [i["name"] for i in fsjail.search("objetivo", roots)["items"]] == ["objetivo-4"]  # depth 4 is the limit
    many = fsjail.search("lote", roots)
    assert len(many["items"]) == fsjail.MAX_SEARCH_RESULTS and many["truncated"]
    ticks = iter(range(0, 1000, 2))
    slow = fsjail.search("lote", roots, clock=lambda: next(ticks))
    assert slow["timed_out"] and len(slow["items"]) < fsjail.MAX_SEARCH_RESULTS
    assert _code(fsjail.search, "a", roots) == "bad_query"


def test_inspect_counts_types_warns_and_hashes_the_context(root, store):
    folder = root / "Nueva B"
    for i in range(fsjail.MANY_IMAGES):
        (folder / f"foto{i}.png").write_bytes(b"\x89PNG")
    (folder / "lote.zip").write_bytes(b"PK")
    original = "Objetivo: conciliar ñ.\n".encode("utf-8")
    (folder / "context.md").write_bytes(original)
    roots = fsjail.configured_roots([str(root)])
    info = fsjail.inspect(str(folder), roots, store=store, audits_dirname=AUDITS,
                          defaults={"currency": "USD", "lang": "es"})
    assert info["files"] == sum(t["count"] for t in info["by_type"]) == 3 + fsjail.MANY_IMAGES + 2
    assert info["zips"] == 1 and info["images"] == fsjail.MANY_IMAGES
    assert info["context"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert {w["code"] for w in info["warnings"]} == {"many_images"}
    assert info["suggested_command"] == "new-open-case" and info["case"] is None
    assert info["results_root"] == str(folder.resolve() / AUDITS)
    assert info["defaults"] == {"name": "Nueva B", "currency": "USD", "lang": "es"}


def test_inspect_of_a_sealed_case_suggests_rerun_and_flags_active_jobs(seeded, case_root, store):
    roots = fsjail.configured_roots([str(case_root)])
    folder = str(seeded["root"].resolve())
    info = fsjail.inspect(folder, roots, store=store, audits_dirname=AUDITS, defaults={},
                          active_jobs=[{"id": 7, "folder": folder}])
    assert info["case"]["id"] == seeded["case_id"] and info["case"]["sealed"] == 1
    assert info["suggested_command"] == "rerun-case" and info["active_jobs"] == [7]
    assert {"sealed_case", "active_job"} <= {w["code"] for w in info["warnings"]}
```

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_fsjail.py -q`
Expected: FAIL con `ImportError: cannot import name 'fsjail' from 'plugins.ghost_recon.console'`.

- [ ] **Step 4: Crear `console/fsjail.py`**

```python
"""Folder browser for evidence folders, jailed to the configured ``case_roots`` (spec §9 "Rutas").

A path from the browser is rejected when it is empty, relative, UNC or carries a ``..`` segment; otherwise it is
resolved (symlinks followed) and accepted only inside a root. Listings hide hidden/system entries and the results
folder; search is bounded in depth, results and time. Read-only: nothing here writes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from ..core import casefolder as cf
from ..core.db import Store
from .paths import case_results_root, resolve_within

MAX_SEARCH_DEPTH = 4
MAX_SEARCH_RESULTS = 200
SEARCH_BUDGET_S = 3.0
COUNT_CAP = 2000
INSPECT_CAP = 50_000
CONTEXT_PREVIEW_CHARS = 20_000
MANY_IMAGES = 50
_HIDDEN_ATTRS = 0x2 | 0x4  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM; st_file_attributes exists on Windows only
_UNC_RE = re.compile(r"^(\\\\|//)")
_SEGMENT_RE = re.compile(r"[\\/]")


class FsJailError(Exception):
    """A rejected path or query; ``code`` is machine-readable and the message is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def folder_key(path: Any) -> str:
    """Comparable form of a folder path (case-insensitive on Windows)."""
    return os.path.normcase(str(path))


def configured_roots(raw: Iterable[str]) -> List[Path]:
    """Configured roots that exist, resolved; a missing or unreadable root is skipped (the doctor reports it)."""
    roots: List[Path] = []
    for item in raw:
        try:
            path = Path(item).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def resolve(raw: str, roots: Sequence[Path]) -> Path:
    text = str(raw or "").strip()
    if not text or "\x00" in text:
        raise FsJailError("bad_path", "ruta vacía o inválida")
    if _UNC_RE.match(text):
        raise FsJailError("outside_roots", "las rutas de red (UNC) no están permitidas")
    if ".." in _SEGMENT_RE.split(text):
        raise FsJailError("bad_path", "la ruta no puede contener '..'")
    if not Path(text).is_absolute():
        raise FsJailError("bad_path", "la ruta debe ser absoluta")
    path = resolve_within(text, roots)
    if path is None:
        raise FsJailError("outside_roots", "la ruta no existe o está fuera de las carpetas de casos")
    return path


def _root_of(path: Path, roots: Sequence[Path]) -> Path:
    best: Optional[Path] = None
    for root in roots:
        try:
            if os.path.commonpath([folder_key(root), folder_key(path)]) == folder_key(root):
                best = root if best is None or len(str(root)) > len(str(best)) else best
        except ValueError:  # another drive
            continue
    return best or path


def _visible_name(name: str) -> bool:
    return not (name.startswith(".") or name in cf.IGNORED_NAMES or name.startswith(cf.IGNORED_PREFIXES))


def _hidden(entry: os.DirEntry) -> bool:
    if not _visible_name(entry.name):
        return True
    try:
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attrs & _HIDDEN_ATTRS)


def _subfolders(folder: Path, roots: Sequence[Path], skip: Sequence[str]) -> List[Path]:
    """Visible subfolders; a symlinked folder is kept only when it resolves inside a root."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    found: List[Path] = []
    for entry in entries:
        if _hidden(entry) or entry.name in skip:
            continue
        try:
            if not entry.is_dir(follow_symlinks=True):
                continue
            if entry.is_symlink() and resolve_within(entry.path, roots) is None:
                continue
        except OSError:
            continue
        found.append(Path(entry.path))
    return sorted(found, key=lambda p: p.name.casefold())


def count_files(folder: Path, skip: Sequence[str] = (), cap: int = COUNT_CAP) -> Dict[str, Any]:
    """Files under ``folder`` (hidden entries and ``skip`` folders excluded), stopping at ``cap``."""
    total = 0
    for _dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if _visible_name(d) and d not in skip]
        total += sum(1 for f in filenames if _visible_name(f))
        if total >= cap:
            return {"files": cap, "capped": True}
    return {"files": total, "capped": False}


def existing_case(store: Store, folder: Path, audits_dirname: str) -> Optional[Dict[str, Any]]:
    """The case anchored to ``folder``: from the DB, else from its ``case.json`` mirror (a case opened elsewhere);
    None when the folder is not a case yet."""
    case = store.get_case(str(folder))
    if case:
        audits = store.list_audits(case["id"])
        return {"id": case["id"], "name": case["name"], "source": "db", "audits": len(audits),
                "sealed": sum(1 for a in audits if a["status"] == "sealed"),
                "last_status": audits[-1]["status"] if audits else None,
                "results_root": str(case_results_root(case)), "base_currency": case["base_currency"],
                "language": case["language"]}
    mirror = cf.read_case_json(cf.audits_root(folder, audits_dirname)) or {}
    info = mirror.get("case") if isinstance(mirror.get("case"), dict) else None
    if not info:
        return None
    audits = [a for a in mirror.get("audits") or [] if isinstance(a, dict)]
    meta = info.get("meta") if isinstance(info.get("meta"), dict) else {}
    return {"id": info.get("id"), "name": info.get("name") or folder.name, "source": "case.json",
            "audits": len(audits), "sealed": sum(1 for a in audits if a.get("status") == "sealed"),
            "last_status": audits[-1].get("status") if audits else None,
            "results_root": str(cf.audits_root(folder, audits_dirname, meta.get("out_dir"))),
            "base_currency": info.get("base_currency"), "language": info.get("language")}


def context_info(folder: Path, roots: Sequence[Path]) -> Optional[Dict[str, Any]]:
    """The folder's ``context.md`` (hash over the exact bytes), unless it is missing or links outside the roots."""
    path = folder / "context.md"
    if not path.is_file() or resolve_within(path, roots) is None:
        return None
    data = path.read_bytes()
    text = data.decode("utf-8", "replace")
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "text": text[:CONTEXT_PREVIEW_CHARS], "truncated": len(text) > CONTEXT_PREVIEW_CHARS}


def _mark(case: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {"id": case["id"], "name": case["name"], "sealed": case["sealed"]} if case else None


def roots_view(roots: Sequence[Path]) -> List[Dict[str, Any]]:
    view = []
    for root in roots:
        try:
            free: Optional[int] = shutil.disk_usage(root).free
        except OSError:
            free = None
        view.append({"name": root.name or str(root), "path": str(root), "free_bytes": free})
    return view


def list_dir(raw: str, roots: Sequence[Path], *, store: Store, audits_dirname: str) -> Dict[str, Any]:
    folder = resolve(raw, roots)
    if not folder.is_dir():
        raise FsJailError("not_a_folder", "la ruta no es una carpeta")
    root = _root_of(folder, roots)
    breadcrumb = [{"name": root.name or str(root), "path": str(root)}]
    current = root
    for part in (folder.relative_to(root).parts if folder != root else ()):
        current = current / part
        breadcrumb.append({"name": part, "path": str(current)})
    skip = (audits_dirname,)
    items = [{"name": p.name, "path": str(p), "case": _mark(existing_case(store, p, audits_dirname)),
              **count_files(p, skip)} for p in _subfolders(folder, roots, skip)]
    return {"path": str(folder), "name": folder.name or str(folder), "root": str(root),
            "parent": str(folder.parent) if folder != root else None, "breadcrumb": breadcrumb,
            "case": _mark(existing_case(store, folder, audits_dirname)), **count_files(folder, skip), "items": items}


def search(query: str, roots: Sequence[Path], *, skip: Sequence[str] = (), max_depth: int = MAX_SEARCH_DEPTH,
           limit: int = MAX_SEARCH_RESULTS, budget_s: float = SEARCH_BUDGET_S,
           clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Folders whose name contains ``query`` (case-insensitive), breadth-first, at most ``max_depth`` levels below
    a root, ``limit`` results and ``budget_s`` seconds."""
    needle = (query or "").strip().casefold()
    if len(needle) < 2:
        raise FsJailError("bad_query", "escribe al menos 2 caracteres")
    deadline = clock() + budget_s
    items: List[Dict[str, str]] = []
    truncated = timed_out = False
    queue = deque((root, root, 0) for root in roots)
    while queue and not truncated:
        if clock() > deadline:
            timed_out = True
            break
        folder, root, depth = queue.popleft()
        for path in _subfolders(folder, roots, skip):
            if needle in path.name.casefold():
                if len(items) >= limit:
                    truncated = True
                    break
                items.append({"name": path.name, "path": str(path), "root": str(root)})
            if depth + 1 < max_depth:
                queue.append((path, root, depth + 1))
    return {"items": items, "truncated": truncated, "timed_out": timed_out}


def inspect(raw: str, roots: Sequence[Path], *, store: Store, audits_dirname: str, defaults: Mapping[str, str],
            active_jobs: Iterable[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """Pre-launch review of an evidence folder: files by type, ZIPs, size, context.md, existing case, output folder,
    warnings and the order that fits (Re-run when the case already has a sealed audit)."""
    folder = resolve(raw, roots)
    if not folder.is_dir():
        raise FsJailError("not_a_folder", "la ruta no es una carpeta")
    by_type: Dict[str, int] = {}
    files = size = zips = images = 0
    capped = False
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if _visible_name(d) and d != audits_dirname]
        for name in filenames:
            if not _visible_name(name):
                continue
            try:
                size += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
            ext = Path(name).suffix.lower() or "(sin extensión)"
            by_type[ext] = by_type.get(ext, 0) + 1
            files += 1
            if ext == ".zip":
                zips += 1
            if ext in cf.OCR_EXTS:
                images += 1
        if files >= INSPECT_CAP:
            capped = True
            break
    case = existing_case(store, folder, audits_dirname)
    key = folder_key(folder)
    active = [int(j["id"]) for j in active_jobs if folder_key(j["folder"]) == key]
    warnings: List[Dict[str, str]] = []
    if files == 0:
        warnings.append({"code": "empty", "text": "La carpeta no tiene archivos de evidencia."})
    if images >= MANY_IMAGES:
        warnings.append({"code": "many_images", "text": f"Hay {images} imágenes: el OCR tardará."})
    if case and case["sealed"]:
        warnings.append({"code": "sealed_case",
                         "text": "Ya es un caso con una auditoría sellada: usa Re-run para la evidencia nueva."})
    if active:
        warnings.append({"code": "active_job",
                         "text": f"Hay una ejecución activa en esta carpeta (#{active[0]}): la nueva quedará en cola."})
    known = case or {}
    return {"path": str(folder), "name": folder.name, "files": files, "capped": capped, "size": size,
            "by_type": [{"ext": e, "count": n} for e, n in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))],
            "zips": zips, "images": images, "context": context_info(folder, roots), "case": case,
            "results_root": known.get("results_root") or str(cf.audits_root(folder, audits_dirname)),
            "active_jobs": active, "warnings": warnings,
            "suggested_command": "rerun-case" if case and case["sealed"] else "new-open-case",
            "defaults": {"name": known.get("name") or folder.name,
                         "currency": known.get("base_currency") or defaults.get("currency", "USD"),
                         "lang": known.get("language") or defaults.get("lang", "es")}}
```

- [ ] **Step 5: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`. Las pruebas de H1 que usan `seeded` siguen verdes con el caso demo dentro de `Casos/`; en Windows salen skipped las dos pruebas `posix`, y en Linux/macOS las dos `windows`.

- [ ] **Step 6: Commit**

```bash
git add plugins/ghost_recon/console/fsjail.py tests/plugins/ghost_recon/console/conftest.py tests/plugins/ghost_recon/console/test_fsjail.py
git commit -m "feat(ghost-recon): console folder jail for case roots (list, search, inspect)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `events` — normalización de `stream-json` y fases

**Files:**
- Create: `plugins/ghost_recon/console/events.py`
- Test: `tests/plugins/ghost_recon/console/test_events.py`

**Interfaces:**
- Consumes: las formas reales de `hermes_cli/stream_json.py` (cada línea lleva `timestamp` en ms):
  - `{"type": "system", "subtype": "init", "model", "session_id"}` (el `session_id` puede llegar vacío);
  - `{"type": "text", "text"}`;
  - `{"type": "tool_use", "name", "tool_call_id"?, "input"?}`;
  - `{"type": "tool_result", "name", "tool_call_id"?, "output" (≤ 5000 caracteres + "..."), "duration_ms", "is_error"}`;
  - `{"type": "result", "session_id", "exit_code", "text", "tokens": {input, output, total, cache_read, cache_write}, "duration_ms", "error"?}`.
- Produces (`console/events.py`, sin E/S):
  - `PHASES` (tupla ordenada de `(id, etiqueta)`: `case, audit, intake, swarm, findings, research, pack, validation, seal`), `PHASE_LABEL`, `KINDS`, `DETAIL_MAX = 500`;
  - `phase_for(name, args, delegate_phase=None) -> Optional[str]` (tabla de §6.3);
  - `class Normalizer` con `feed_line(line) -> list[dict]`, `feed(obj) -> list[dict]`, `flush() -> list[dict]` (cierra un grupo pendiente de herramientas genéricas), `start_delegation(phase, total)`, y los atributos `seq`, `phase`, `session_id`, `result` (`{session_id, exit_code, text, tokens, duration_ms, error}` o `None`) y la propiedad `text`;
  - evento de consola: `{seq, ts, kind, phase, title, detail, level}` con `kind ∈ KINDS` y `level ∈ {info, warning, error}`.

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_events.py`:

```python
"""stream-json → console events: phases follow the tool table, generic tools are grouped, the agent's text is kept
for the summary only, and truncated or failed tool outputs never break the feed."""
import json
import re

from plugins.ghost_recon.console.events import KINDS, PHASES, Normalizer, phase_for

T0 = 1_790_000_000_000
CASE = {"case": {"id": "GRC-acme-20261003", "name": "Acme"}, "created": True, "corpus_files": 214}
AUDIT = {"audit": {"id": "GRC-acme-20261003/A01", "summary": {"evidence_new": 214}}, "folder": "/x/A01"}


def rec(kind, step=0, **fields):
    return {"type": kind, "timestamp": T0 + step * 1000, **fields}


def call(name, args, output, step, *, is_error=False):
    text = output if isinstance(output, str) else json.dumps(output)
    return [rec("tool_use", step, name=name, tool_call_id=f"c{step}", input=args),
            rec("tool_result", step, name=name, tool_call_id=f"c{step}", output=text, duration_ms=3, is_error=is_error)]


def run(records):
    n = Normalizer()
    events = [e for r in records for e in n.feed_line(json.dumps(r))] + n.flush()
    return n, events


def full_audit():
    """A complete /new-open-case run as the parent agent streams it."""
    return [rec("system", 0, subtype="init", model="m", session_id="s-1"),
            *call("gr_case_open", {"folder": "/x"}, CASE, 1),
            *call("gr_audit_start", {"case_id": "GRC-acme-20261003"}, AUDIT, 2),
            *call("read_file", {"path": "/x/context.md"}, "texto", 3),
            *call("gr_criteria_add", {"audit_id": "a", "author": "G", "text": "t"}, {"id": "CRIT-01"}, 4),
            *call("gr_swarm_plan", {"audit_id": "a", "mode": "extraction"},
                  {"mode": "extraction", "tasks": [{}, {}, {}], "waves": 1}, 5),
            *call("delegate_task", {"tasks": [{}, {}]}, "ok", 6),
            *call("delegate_task", {"tasks": [{}]}, "ok", 7),
            *call("gr_finding_upsert", {"audit_id": "a"}, {"findings": [{"id": "EXC-01"}]}, 8),
            *call("gr_research", {"query": "q"}, {"action": "search"}, 9),
            *call("gr_report_build", {"audit_id": "a"}, {"files": [{}, {}], "warnings": []}, 10),
            *call("gr_swarm_plan", {"audit_id": "a", "mode": "validation"}, {"mode": "validation", "tasks": [{}, {}]}, 11),
            *call("delegate_task", {"tasks": [{}, {}]}, "ok", 12),
            *call("gr_run_record", {"audit_id": "a", "kind": "validation", "role": "A"},
                  {"kind": "validation", "status": "done"}, 13),
            *call("gr_audit_seal", {"audit_id": "a"}, {"sealed": True, "file_count": 40}, 14),
            rec("text", 15, text="Resumen "), rec("text", 15, text="final."),
            rec("result", 16, session_id="s-1", exit_code=0, text="Resumen final.",
                tokens={"input": 10, "output": 5, "total": 15}, duration_ms=99)]


def test_phases_follow_the_tool_table_in_order():
    n, events = run(full_audit())
    assert [e["phase"] for e in events if e["kind"] == "phase"] == [p for p, _ in PHASES]
    assert n.phase == PHASES[-1][0]


def test_events_have_known_kinds_increasing_seq_and_utc_stamps():
    _, events = run(full_audit())
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert {e["kind"] for e in events} <= set(KINDS)
    assert all(e["ts"].endswith("Z") for e in events)


def test_session_tokens_and_text_come_from_the_stream():
    n, events = run(full_audit())
    assert n.session_id == "s-1" and n.result["exit_code"] == 0 and n.result["tokens"]["total"] == 15
    assert n.text == n.result["text"]
    assert events[-1]["kind"] == "result" and events[-1]["level"] == "info"


def test_session_id_falls_back_to_the_result_record():
    n, _ = run([rec("system", 0, subtype="init", model="m", session_id=""),
                rec("result", 1, session_id="s-9", exit_code=0, text="")])
    assert n.session_id == "s-9"


def test_agent_text_is_accumulated_not_emitted():
    n, events = run([rec("text", 0, text="a"), rec("text", 1, text=" b")])
    assert events == [] and n.text == "a b"


def test_consecutive_generic_tools_collapse_into_one_counted_event():
    records = [r for i in range(4) for r in call("read_file", {"path": f"/x/f{i}.txt"}, "x", i)]
    records += call("terminal", {"command": "ls"}, "x", 9, is_error=True)
    _, events = run(records)
    reads = [e for e in events if "read_file" in e["title"]]
    assert len(reads) == 1 and "4" in reads[0]["title"]
    terminal = [e for e in events if "terminal" in e["title"]]
    assert len(terminal) == 1 and terminal[0]["level"] == "warning"


def test_swarm_progress_counts_delegated_blocks_against_the_plan():
    _, events = run(full_audit())
    titles = [e["title"] for e in events if e["kind"] == "tool_result" and e["phase"] == "swarm"]
    progress = [tuple(map(int, m.groups())) for m in (re.search(r"(\d+)/(\d+)", t) for t in titles) if m]
    assert progress == [(2, 3), (3, 3)]  # done = delegated tasks so far, total = tasks in the extraction plan


def test_truncated_gr_output_still_names_the_case_and_the_audit():  # Review Focus 1
    big_case = json.dumps({**CASE, "audits": [{"notes": "x" * 9000}]})[:5000] + "..."
    big_audit = json.dumps({**AUDIT, "inherited_open_findings": [{"d": "y" * 9000}]})[:5000] + "..."
    _, events = run(call("gr_case_open", {"folder": "/x"}, big_case, 1)
                    + call("gr_audit_start", {"case_id": "c"}, big_audit, 2))
    results = [e["title"] for e in events if e["kind"] == "tool_result"]
    assert len(results) == 2 and "GRC-acme-20261003" in results[0] and "A01" in results[1]


def test_blocked_commands_become_warnings_with_the_reason():
    _, events = run(call("terminal", {"command": "pip install x"},
                         '{"error": "BLOCKED: approval required (approvals.single_query_mode: deny)"}', 1))
    assert any(e["level"] == "warning" and "BLOCKED" in (e["detail"] or "") for e in events)


def test_gr_tool_errors_and_refused_seals_are_warnings():
    _, events = run(call("gr_case_open", {}, {"error": "evidence folder not found"}, 1)
                    + call("gr_audit_seal", {}, {"sealed": False, "completion": {"missing": ["report_pdf"]}}, 2))
    warnings = [e for e in events if e["level"] == "warning"]
    assert len(warnings) == 2
    assert "evidence folder not found" in warnings[0]["detail"] and "report_pdf" in warnings[1]["detail"]


def test_failed_run_ends_with_an_error_event():
    _, events = run([rec("result", 0, session_id="s", exit_code=1, text="", error="credentials or agent init failed")])
    assert events[-1]["kind"] == "result" and events[-1]["level"] == "error"
    assert "credentials" in events[-1]["detail"]


def test_unparseable_lines_are_warnings_not_crashes():
    n = Normalizer()
    events = n.feed_line("not json") + n.feed_line('["a list"]') + n.feed_line("   ")
    assert [e["level"] for e in events] == ["warning", "warning"]


def test_reading_the_context_file_marks_the_intake_phase():
    for path in ("/x/context.md", "C:\\x\\GhostRecon_Audits\\_console\\context_ab12cd34ef56.md"):
        assert phase_for("read_file", {"path": path}) == "intake"
    assert phase_for("read_file", {"path": "/x/Bancos/a.txt"}) is None
    assert phase_for("delegate_task", {}, "swarm") == "swarm" and phase_for("terminal", {}) is None
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_events.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console.events'`.

- [ ] **Step 3: Crear `console/events.py`**

```python
"""stream-json → console events, plus the audit phase deduced from the tools the agent calls (spec §6.3). Pure.

Input: the JSONL records of ``hermes … chat -q … --format stream-json`` (hermes_cli/stream_json.py):
``system/init{model, session_id}``, ``text{text}``, ``tool_use{name, tool_call_id?, input?}``,
``tool_result{name, tool_call_id?, output, duration_ms, is_error}`` and ``result{session_id, exit_code, text, tokens,
duration_ms, error?}``, each stamped with ``timestamp`` (ms). Tool output arrives capped at 5000 characters, so a large
``gr_*`` result can be truncated JSON: summaries then fall back to the ids they can still find.

Output: console events ``{seq, ts, kind, phase, title, detail, level}``. The agent's text is accumulated for the
final summary (no chat is rebuilt); consecutive calls of one generic tool are grouped ("read_file ×4"); sub-agent tools
never reach the parent's stream, so swarm progress comes from the parent's ``delegate_task`` results.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

PHASES = (("case", "Caso"), ("audit", "Auditoría"), ("intake", "Intake"), ("swarm", "Enjambre"),
          ("findings", "Modelo y hallazgos"), ("research", "Investigación"), ("pack", "Pack"),
          ("validation", "Validación"), ("seal", "Sello"))
PHASE_LABEL: Dict[str, str] = dict(PHASES)
KINDS = ("phase", "tool_call", "tool_result", "message", "warning", "error", "result")
DETAIL_MAX = 500

Event = Dict[str, Any]

_FIXED_PHASE = {"gr_case_open": "case", "gr_audit_start": "audit", "gr_review_plan": "audit",
                "gr_criteria_add": "intake", "gr_finding_upsert": "findings", "gr_research": "research",
                "gr_report_build": "pack", "gr_audit_seal": "seal"}
_PLAN_PHASE = {"extraction": "swarm", "validation": "validation", "review": "audit"}
_PLAN_WORDS = {"extraction": ("extracción", "bloques"), "validation": ("validación", "validadores"),
               "review": ("revisión", "roles")}
_DELEGATE_TITLE = {"swarm": "Enjambre: {p} bloques", "validation": "Validación: {p} validadores"}
_CALL_TITLE = {"gr_case_open": "Abriendo el caso", "gr_audit_start": "Iniciando la auditoría",
               "gr_review_plan": "Preparando la revisión", "gr_criteria_add": "Registrando un criterio",
               "gr_swarm_plan": "Planificando el trabajo de los sub-agentes",
               "gr_finding_upsert": "Registrando hallazgos", "gr_research": "Investigando en la web",
               "gr_report_build": "Generando el pack de entregables", "gr_run_record": "Registrando una ronda",
               "gr_audit_seal": "Sellando la auditoría"}
_CASE_ID_RE = re.compile(r'"id":\s*"(GRC-[^"/]+)"')
_AUDIT_ID_RE = re.compile(r'"id":\s*"(GRC-[^"]+/[AR]\d+)"')
_REVIEW_ID_RE = re.compile(r'"review_id":\s*"(GRC-[^"]+/R\d+)"')


def _iso(ms: Any) -> str:
    if not isinstance(ms, (int, float)):
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(output: str) -> Dict[str, Any]:
    try:
        data = json.loads(output)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find(pattern: "re.Pattern[str]", text: str) -> str:
    match = pattern.search(text or "")
    return match.group(1) if match else ""


def _seq(audit_id: str) -> str:
    return audit_id.rsplit("/", 1)[-1] if audit_id else ""


def _count(value: Any) -> Optional[int]:
    return len(value) if isinstance(value, list) else None


def _tasks(args: Dict[str, Any]) -> int:
    tasks = args.get("tasks")
    return len(tasks) if isinstance(tasks, list) and tasks else 1


# ------------------------------------------------------------------------------------------------ phase table
def _plan_phase(args: Dict[str, Any], _delegate: Optional[str]) -> Optional[str]:
    return _PLAN_PHASE.get(str(args.get("mode") or "extraction"))


def _run_phase(args: Dict[str, Any], _delegate: Optional[str]) -> Optional[str]:
    return "validation" if args.get("kind") == "validation" else None


def _delegate_phase(_args: Dict[str, Any], delegate: Optional[str]) -> Optional[str]:
    return delegate


def _read_phase(args: Dict[str, Any], _delegate: Optional[str]) -> Optional[str]:
    path = str(args.get("path") or "").replace("\\", "/")
    return "intake" if path.rsplit("/", 1)[-1] == "context.md" or "/_console/context_" in path else None


_DYNAMIC_PHASE: Dict[str, Callable[[Dict[str, Any], Optional[str]], Optional[str]]] = {
    "gr_swarm_plan": _plan_phase, "gr_run_record": _run_phase, "delegate_task": _delegate_phase,
    "read_file": _read_phase}


def phase_for(name: str, args: Dict[str, Any], delegate_phase: Optional[str] = None) -> Optional[str]:
    """Phase a tool call announces (table of spec §6.3), or None when it does not move the audit."""
    if name in _FIXED_PHASE:
        return _FIXED_PHASE[name]
    rule = _DYNAMIC_PHASE.get(name)
    return rule(args, delegate_phase) if rule else None


# ------------------------------------------------------------------------------------------------ gr_* summaries
def _ok(title: str) -> List[Event]:
    return [{"kind": "tool_result", "title": title}]


def _sum_case_open(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    case = data.get("case") if isinstance(data.get("case"), dict) else {}
    case_id = case.get("id") or _find(_CASE_ID_RE, output)
    if not data:
        return _ok(f"Caso {case_id} listo" if case_id else "Caso listo")
    files = data.get("corpus_files")
    verb = "abierto" if data.get("created") else "cargado"
    return _ok(f"Caso {case_id} {verb}" + (f" · {files} archivos" if files is not None else ""))


def _sum_audit_start(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    audit = data.get("audit") if isinstance(data.get("audit"), dict) else {}
    seq = _seq(audit.get("id") or _find(_AUDIT_ID_RE, output))
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    new = summary.get("evidence_new")
    title = f"Auditoría {seq} iniciada" if seq else "Auditoría iniciada"
    return _ok(title + (f" · {new} archivos nuevos" if new is not None else ""))


def _sum_review_plan(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    seq = _seq(data.get("review_id") or _find(_REVIEW_ID_RE, output))
    roles = _count(data.get("delegate_tasks"))
    title = f"Revisión {seq} preparada" if seq else "Revisión preparada"
    return _ok(title + (f" · {roles} roles" if roles else ""))


def _sum_criterion(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    return _ok(f"Criterio {data['id']} registrado" if data.get("id") else "Criterio registrado")


def _sum_plan(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    mode = str(data.get("mode") or args.get("mode") or "extraction")
    tasks = _count(data.get("tasks"))
    n.start_delegation(_PLAN_PHASE.get(mode), tasks or 0)
    noun, unit = _PLAN_WORDS.get(mode, (mode, "tareas"))
    return _ok(f"Plan de {noun} listo" + (f": {tasks} {unit}" if tasks else ""))


def _sum_findings(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    ids = [f.get("id") for f in data.get("findings") or [] if isinstance(f, dict) and f.get("id")]
    if not ids:
        return _ok("Hallazgos registrados")
    more = f" (+{len(ids) - 5})" if len(ids) > 5 else ""
    return _ok(f"Hallazgos registrados: {', '.join(ids[:5])}{more}")


def _sum_research(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    return _ok(f"Investigación web registrada ({data.get('action') or args.get('action') or 'search'})")


def _sum_report(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    files = _count(data.get("files"))
    items = _ok("Pack generado" + (f" · {files} archivos" if files is not None else ""))
    warnings = [str(w) for w in data.get("warnings") or []]
    if warnings:
        items.append({"kind": "warning", "title": "El pack tiene avisos", "detail": "; ".join(warnings[:3]),
                      "level": "warning"})
    return items


def _sum_run(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    kind = data.get("kind") or args.get("kind") or "?"
    return _ok(f"Ronda de {kind} registrada ({data.get('status') or args.get('status') or 'done'})")


def _sum_seal(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    if data.get("sealed") is True:
        count = data.get("file_count")
        return _ok(f"Auditoría sellada · {count} archivos" if count is not None else "Auditoría sellada")
    if data.get("already_sealed"):
        return _ok("La auditoría ya estaba sellada")
    if data.get("sealed") is False:
        missing = [str(m) for m in (data.get("completion") or {}).get("missing") or []]
        return [{"kind": "warning", "title": "No se pudo sellar la auditoría",
                 "detail": f"faltan: {', '.join(missing)}" if missing else None, "level": "warning"}]
    return _ok("Sello registrado")


_SUMMARY: Dict[str, Callable[["Normalizer", str, Dict[str, Any], Dict[str, Any]], List[Event]]] = {
    "gr_case_open": _sum_case_open, "gr_audit_start": _sum_audit_start, "gr_review_plan": _sum_review_plan,
    "gr_criteria_add": _sum_criterion, "gr_swarm_plan": _sum_plan, "gr_finding_upsert": _sum_findings,
    "gr_research": _sum_research, "gr_report_build": _sum_report, "gr_run_record": _sum_run,
    "gr_audit_seal": _sum_seal}


# ------------------------------------------------------------------------------------------------ normalizer
class Normalizer:
    """Stateful and deterministic for a given input. ``feed_line``/``feed`` return the new console events; ``flush``
    closes a pending group of generic tool calls (call it when the stream goes idle and when it ends)."""

    def __init__(self) -> None:
        self.seq = 0
        self.phase: Optional[str] = None
        self.session_id = ""
        self.result: Optional[Dict[str, Any]] = None
        self._text: List[str] = []
        self._group: Optional[Dict[str, Any]] = None
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._delegate_phase: Optional[str] = None
        self._delegate_total = 0
        self._delegate_done = 0
        self._handlers: Dict[str, Callable[[Dict[str, Any]], List[Event]]] = {
            "system": self._on_system, "text": self._on_text, "tool_use": self._on_tool_use,
            "tool_result": self._on_tool_result, "result": self._on_result}

    @property
    def text(self) -> str:
        return "".join(self._text)

    def start_delegation(self, phase: Optional[str], total: int) -> None:
        """A new plan resets the progress that the next ``delegate_task`` results count against."""
        self._delegate_phase, self._delegate_total, self._delegate_done = phase, total, 0

    def feed_line(self, line: str) -> List[Event]:
        line = line.strip()
        if not line:
            return []
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            return self._emit("warning", "Línea no reconocida en la salida del agente", detail=line, level="warning")
        return self.feed(obj)

    def feed(self, obj: Dict[str, Any]) -> List[Event]:
        handler = self._handlers.get(str(obj.get("type")))
        return handler(obj) if handler else []

    def flush(self) -> List[Event]:
        group, self._group = self._group, None
        if not group:
            return []
        title = group["name"] if group["count"] == 1 else f"{group['name']} ×{group['count']}"
        errors = group["errors"]
        return self._emit("tool_call", title, ts=group["ts"], detail=f"{errors} con error" if errors else None,
                          level="warning" if errors else "info")

    # -------------------------------------------------------------------------------------------- internals
    def _emit(self, kind: str, title: str, *, ts: str = "", detail: Any = None, level: str = "info") -> List[Event]:
        self.seq += 1
        text = str(detail).strip() if detail else ""
        if len(text) > DETAIL_MAX:
            text = text[:DETAIL_MAX] + "…"
        return [{"seq": self.seq, "ts": ts, "kind": kind, "phase": self.phase, "title": title,
                 "detail": text or None, "level": level}]

    @staticmethod
    def _key(obj: Dict[str, Any]) -> str:
        return str(obj.get("tool_call_id") or obj.get("name") or "unknown")

    def _on_system(self, obj: Dict[str, Any]) -> List[Event]:
        if obj.get("subtype") != "init":
            return []
        self.session_id = str(obj.get("session_id") or self.session_id)
        model = obj.get("model")
        return self._emit("message", "Agente iniciado", ts=_iso(obj.get("timestamp")),
                          detail=f"modelo {model}" if model else None)

    def _on_text(self, obj: Dict[str, Any]) -> List[Event]:
        self._text.append(str(obj.get("text") or ""))
        return []

    def _on_tool_use(self, obj: Dict[str, Any]) -> List[Event]:
        name = str(obj.get("name") or "unknown")
        args = obj.get("input") if isinstance(obj.get("input"), dict) else {}
        ts = _iso(obj.get("timestamp"))
        self._pending[self._key(obj)] = args
        out: List[Event] = []
        phase = phase_for(name, args, self._delegate_phase)
        if phase and phase != self.phase:
            out += self.flush()
            self.phase = phase
            out += self._emit("phase", PHASE_LABEL[phase], ts=ts)
        if name in _CALL_TITLE:
            return out + self.flush() + self._emit("tool_call", _CALL_TITLE[name], ts=ts)
        if name == "delegate_task":
            return out + self.flush() + self._emit("tool_call", f"Delegando {_tasks(args)} tarea(s) a sub-agentes",
                                                   ts=ts)
        if self._group and self._group["name"] == name:
            self._group["count"] += 1
            return out
        out += self.flush()
        self._group = {"name": name, "count": 1, "errors": 0, "ts": ts}
        return out

    def _on_tool_result(self, obj: Dict[str, Any]) -> List[Event]:
        name = str(obj.get("name") or "unknown")
        args = self._pending.pop(self._key(obj), {})
        output = str(obj.get("output") or "")
        ts = _iso(obj.get("timestamp"))
        failed = bool(obj.get("is_error"))
        if "BLOCKED:" in output:
            return self.flush() + self._emit("warning", "Comando bloqueado por la política de aprobaciones", ts=ts,
                                             detail=output, level="warning")
        if name in _SUMMARY:
            out = self.flush()
            data = _parse(output)
            if failed or data.get("error"):
                return out + self._emit("warning", f"{_CALL_TITLE[name]}: falló", ts=ts,
                                        detail=data.get("error") or output, level="warning")
            for item in _SUMMARY[name](self, output, data, args):
                out += self._emit(item["kind"], item["title"], ts=ts, detail=item.get("detail"),
                                  level=item.get("level", "info"))
            return out
        if name == "delegate_task":
            out = self.flush()
            if failed:
                return out + self._emit("warning", "Los sub-agentes devolvieron un error", ts=ts, detail=output,
                                        level="warning")
            self._delegate_done += _tasks(args)
            done, total = self._delegate_done, self._delegate_total
            progress = f"{done}/{total}" if total else str(done)
            title = _DELEGATE_TITLE.get(self._delegate_phase or "", "Sub-agentes: {p} tareas terminadas")
            return out + self._emit("tool_result", title.format(p=progress), ts=ts)
        if self._group and self._group["name"] == name:
            self._group["errors"] += int(failed)
            return []
        return self._emit("warning", f"{name} falló", ts=ts, detail=output, level="warning") if failed else []

    def _on_result(self, obj: Dict[str, Any]) -> List[Event]:
        out = self.flush()
        if obj.get("session_id"):
            self.session_id = str(obj["session_id"])
        exit_code = int(obj.get("exit_code") or 0)
        error = str(obj.get("error") or "") or None
        self.result = {"session_id": self.session_id, "exit_code": exit_code,
                       "text": str(obj.get("text") or self.text),
                       "tokens": obj.get("tokens") if isinstance(obj.get("tokens"), dict) else {},
                       "duration_ms": obj.get("duration_ms"), "error": error}
        ok = exit_code == 0 and not error
        return out + self._emit("result", "Ejecución terminada" if ok else "La ejecución terminó con error",
                                ts=_iso(obj.get("timestamp")),
                                detail=None if ok else (error or f"código de salida {exit_code}"),
                                level="info" if ok else "error")
```

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_events.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add plugins/ghost_recon/console/events.py tests/plugins/ghost_recon/console/test_events.py
git commit -m "feat(ghost-recon): normalize agent stream-json into console events and audit phases

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `commands` y lanzador — tabla de órdenes, vista previa exacta y contexto combinado

**Files:**
- Create: `plugins/ghost_recon/console/commands.py`
- Create: `plugins/ghost_recon/console/procs.py` (resolución del lanzador; la Tarea 5 añade el control de procesos)
- Test: `tests/plugins/ghost_recon/console/test_commands.py`
- Test: `tests/plugins/ghost_recon/console/test_procs.py`

**Interfaces:**
- Consumes: `fsjail.resolve`, `fsjail.existing_case`, `fsjail.context_info`, `FsJailError`; `core.casefolder.audits_root`; `hermes_cli._launchers.installation_command` / `runtime_command` (firma confirmada: `(repo_root: Path, args=(), *, module="hermes_cli.main", python=None, home=None) -> list[str]`); `hermes_cli._subprocess_compat.IS_WINDOWS`; `hermes_constants.get_hermes_home`, `profile_name_for_home`.
- Produces:
  - `commands.py`:
    - `SOURCE_TAG = "ghost-recon-console"`, `MAX_NAME = 120`, `MAX_NOTES = 20_000`, `LANGS = ("es", "en")`, `CONSOLE_DIR = "_console"`, `NO_ROOTS_MESSAGE`, `MISSING_ROOTS_MESSAGE`;
    - `@dataclass(frozen=True) Order(command, skill, requires, context_arg, options, out)` y `ORDERS: Dict[str, Order]` (las tres órdenes de §6.1);
    - `class CommandError(Exception)` con `status`, `code`, `message`;
    - `@dataclass(frozen=True) LaunchRequest(command, folder, name="", currency="", lang="", out="", notes="")`;
    - `plan(req, *, store, roots, audits_dirname, username, profile_args, hermes) -> dict` con las claves `command, skill, folder, out, case, results_root, original_context ({path, sha256, size} | None), notes, context_file, query, argv, args`;
    - `build_query(order, folder, context_file, opts, out) -> str`, `agent_args(skill, query, profile_args) -> list[str]`;
    - `combined_name(original_sha, notes, username) -> str`, `combined_context_text(plan, username, now) -> str`, `write_combined_context(plan, username, now) -> Path`;
    - `display_command(argv, *, windows=None) -> str` (comando copiable; `None` = el SO del host).
  - `procs.py`: `RUNNER_MODULE = "plugins.ghost_recon.console.job_runner"`, `hermes_root() -> Path`, `hermes_command(args, *, module="hermes_cli.main") -> list[str]`, `runner_command(job_id) -> list[str]`, `profile_args() -> list[str]`.
- Códigos de error de `plan`: `422 unknown_command | invalid_argument | bad_path | not_a_folder`, `403 outside_roots`, `409 no_case_roots | use_rerun | not_a_case | no_sealed_audit`; `write_combined_context`: `409 context_changed`.

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_commands.py`:

```python
"""Order table: each order preloads its skill with the -q text that skill expects, options are validated, the
operator's notes become a combined context file beside the results (never among the evidence), and the copyable
command round-trips through the target shell."""
import hashlib
import shlex

import pytest

from plugins.ghost_recon.console.commands import (CONSOLE_DIR, ORDERS, SOURCE_TAG, CommandError, LaunchRequest,
                                                  display_command, plan, write_combined_context)
from plugins.ghost_recon.console.fsjail import configured_roots
from plugins.ghost_recon.core import service

AUDITS = "GhostRecon_Audits"


def hermes(args):
    return ["HERMES", *args]


@pytest.fixture
def plan_for(store, case_root):
    roots = configured_roots([str(case_root)])

    def _plan(command, folder, **fields):
        return plan(LaunchRequest(command=command, folder=str(folder), **fields), store=store, roots=roots,
                    audits_dirname=AUDITS, username="jean", profile_args=["-p", "default"], hermes=hermes)
    return _plan


@pytest.fixture
def fresh(case_root):
    folder = case_root / "Caso Logística Norte"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto ñ.txt").write_text("x", encoding="utf-8")
    return folder


@pytest.mark.parametrize("command", sorted(ORDERS))
def test_each_order_preloads_its_skill_and_streams_json(plan_for, seeded, fresh, command):
    p = plan_for(command, fresh if command == "new-open-case" else seeded["root"])
    argv = p["argv"]
    assert argv[0] == "HERMES" and all(isinstance(a, str) for a in argv)
    assert argv[argv.index("--skills") + 1] == ORDERS[command].skill
    assert argv.index("chat") > argv.index("--skills") and argv[1:3] == ["-p", "default"]
    assert argv[argv.index("-q") + 1] == p["query"] and p["query"].startswith(f"/{command} ")
    assert argv[argv.index("--format") + 1] == "stream-json" and argv[argv.index("--source") + 1] == SOURCE_TAG


def test_folder_with_spaces_and_accents_is_quoted_intact(plan_for, fresh):  # Review Focus 2
    p = plan_for("new-open-case", fresh)
    assert p["folder"] == str(fresh.resolve()) and f'"{fresh.resolve()}"' in p["query"]


@pytest.mark.platforms("posix")
def test_a_folder_with_a_double_quote_is_rejected(plan_for, case_root):  # Review Focus 2
    folder = case_root / 'Caso "raro"'
    folder.mkdir()
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", folder)
    assert err.value.status == 422


@pytest.mark.parametrize("field,value", [("currency", "US"), ("currency", "usd1"), ("lang", "fr"),
                                         ("name", "a\nb"), ("name", 'Caso "x"'), ("name", "x" * 121)])
def test_invalid_options_are_422(plan_for, fresh, field, value):
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", fresh, **{field: value})
    assert (err.value.status, err.value.code) == (422, "invalid_argument")


def test_valid_options_reach_the_query_normalized(plan_for, fresh):
    p = plan_for("new-open-case", fresh, name="Logística Norte", currency="eur", lang="EN")
    assert '--name "Logística Norte"' in p["query"] and "--currency EUR" in p["query"] and "--lang en" in p["query"]
    assert p["args"]["currency"] == "EUR"


def test_a_sealed_case_refuses_a_new_audit_and_points_to_rerun(plan_for, seeded):
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", seeded["root"])
    assert (err.value.status, err.value.code) == (409, "use_rerun") and "Re-run" in err.value.message


def test_rerun_needs_a_case_and_review_needs_a_sealed_audit(plan_for, fresh, store):
    with pytest.raises(CommandError) as err:
        plan_for("rerun-case", fresh)
    assert err.value.code == "not_a_case"
    service.open_case(store, str(fresh))
    with pytest.raises(CommandError) as err:
        plan_for("review-case", fresh)
    assert err.value.code == "no_sealed_audit"
    assert plan_for("rerun-case", fresh)["case"]["source"] == "db"


def test_folders_outside_the_roots_are_403_and_no_roots_is_409(plan_for, gr_env, store, fresh):
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", gr_env / "db")
    assert (err.value.status, err.value.code) == (403, "outside_roots")
    with pytest.raises(CommandError) as err:
        plan(LaunchRequest("new-open-case", str(fresh)), store=store, roots=[], audits_dirname=AUDITS,
             username="jean", profile_args=[], hermes=hermes)
    assert (err.value.status, err.value.code) == (409, "no_case_roots") and "case_roots" in err.value.message


def test_without_notes_the_original_context_or_nothing_is_passed(plan_for, fresh):
    assert plan_for("new-open-case", fresh)["context_file"] == ""
    (fresh / "context.md").write_bytes(b"Objetivo: conciliar.\n")
    p = plan_for("new-open-case", fresh)
    assert p["context_file"] == str(fresh.resolve() / "context.md") and f'"{p["context_file"]}"' in p["query"]


def test_combined_context_has_the_literal_original_its_hash_and_signed_notes(plan_for, fresh):
    original = "Objetivo: conciliar ñ.\n\nLínea 2\n".encode("utf-8")
    (fresh / "context.md").write_bytes(original)
    p = plan_for("new-open-case", fresh, notes="El socio B aportó USD 5 000 en marzo.")
    path = write_combined_context(p, "jean", "2026-10-03T10:00:00Z")
    text = path.read_bytes().decode("utf-8")
    assert original.decode("utf-8") in text and hashlib.sha256(original).hexdigest() in text
    assert "El socio B aportó USD 5 000 en marzo." in text and "jean" in text and "CRIT-nn" in text
    assert str(path) == p["context_file"] and f'"{path}"' in p["query"]
    assert path.parent == fresh.resolve() / AUDITS / CONSOLE_DIR  # beside the results, never among the evidence


def test_the_combined_file_name_is_stable_so_the_preview_is_exact(plan_for, fresh):
    a = plan_for("new-open-case", fresh, notes="nota")
    b = plan_for("new-open-case", fresh, notes="nota")
    c = plan_for("new-open-case", fresh, notes="otra nota")
    assert a["argv"] == b["argv"] and a["context_file"] != c["context_file"]


def test_a_context_md_changed_after_the_preview_is_refused(plan_for, fresh):
    (fresh / "context.md").write_bytes(b"uno\n")
    p = plan_for("new-open-case", fresh, notes="nota")
    (fresh / "context.md").write_bytes(b"dos\n")
    with pytest.raises(CommandError) as err:
        write_combined_context(p, "jean", "2026-10-03T10:00:00Z")
    assert (err.value.status, err.value.code) == (409, "context_changed")


def test_review_notes_travel_on_a_second_line(plan_for, seeded):
    p = plan_for("review-case", seeded["root"], notes="Reunión con el abogado el lunes.")
    first, second = p["query"].split("\n")
    assert first == f'/review-case "{seeded["root"].resolve()}"' and p["context_file"] in second


def test_display_command_round_trips_through_a_posix_shell():
    argv = ["/opt/h/.hermes/bin/hermes", "-p", "default", "chat", "-q", '/new-open-case "/casos/Caso ñ" --name "A B"']
    assert shlex.split(display_command(argv, windows=False)) == argv


@pytest.mark.platforms("windows")
def test_display_command_round_trips_through_windows_argv_parsing():
    import ctypes
    argv = ["C:\\h\\python.exe", "-q", '/new-open-case "C:\\Casos\\Caso ñ" --name "A B"']
    count = ctypes.c_int()
    to_argv = ctypes.windll.shell32.CommandLineToArgvW
    to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    parsed = to_argv(display_command(argv, windows=True), ctypes.byref(count))
    assert [parsed[i] for i in range(count.value)] == argv
```

`tests/plugins/ghost_recon/console/test_procs.py`:

```python
"""The agent command is bound to this Hermes installation (launcher or runtime command), never to PATH."""
import subprocess

from plugins.ghost_recon.console import procs


def test_hermes_command_starts_this_installation():
    r = subprocess.run(procs.hermes_command(["--version"]), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip()


def test_the_runner_command_targets_the_runner_module_of_this_installation():
    cmd = procs.runner_command(7)
    assert cmd[-1] == "7" and procs.RUNNER_MODULE in " ".join(cmd)
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_commands.py tests/plugins/ghost_recon/console/test_procs.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console.commands'` (y `... console.procs`).

- [ ] **Step 3: Crear `console/procs.py`**

```python
"""Process glue with Hermes for console jobs: the commands that run the agent and the job runner, and how those
processes are spawned, watched and stopped.

Every Hermes-internal import of the job engine lives in this module (spec §4.3). The executable is never looked up on
PATH: ``hermes_cli._launchers`` builds the command bound to the running installation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import List, Sequence

RUNNER_MODULE = "plugins.ghost_recon.console.job_runner"


def hermes_root() -> Path:
    """Root of the running Hermes installation (the directory that holds ``hermes_cli/``)."""
    spec = importlib.util.find_spec("hermes_cli")
    if spec is None or not spec.origin:
        raise RuntimeError("hermes_cli no es importable: la consola debe ejecutarse desde una instalación de Hermes")
    return Path(spec.origin).resolve().parents[1]


def hermes_command(args: Sequence[str], *, module: str = "hermes_cli.main") -> List[str]:
    """argv that runs ``module`` with this installation's interpreter and dependencies.

    POSIX: ``installation_command`` (the PM launcher ``<root>/.hermes/bin/hermes``, an ``exec`` wrapper, when the
    install has one; else the installation-bound runtime command). Windows: always ``runtime_command``, because the
    launcher there can be a ``.cmd`` shim, unsafe as argv[0] with operator-supplied arguments (kanban's rule)."""
    from hermes_cli._launchers import installation_command, runtime_command
    from hermes_cli._subprocess_compat import IS_WINDOWS
    build = runtime_command if IS_WINDOWS else installation_command
    return [str(part) for part in build(hermes_root(), [str(a) for a in args], module=module)]


def runner_command(job_id: int) -> List[str]:
    """argv of the detached runner process of ``job_id``."""
    return hermes_command([str(int(job_id))], module=RUNNER_MODULE)


def profile_args() -> List[str]:
    """``["-p", <profile>]`` for the profile this console serves; ``[]`` for a custom home outside the profile tree.
    Explicit even for ``default``: a bare ``hermes`` would follow the sticky ``active_profile`` file instead."""
    from hermes_constants import get_hermes_home, profile_name_for_home
    name = profile_name_for_home(get_hermes_home())
    return ["-p", name] if name else []
```

- [ ] **Step 4: Crear `console/commands.py`**

```python
"""Orders the console can launch, as a table (spec §6.1): validation, the ``-q`` text each skill expects, the agent
argv and the operator's combined context file (§7). ``plan`` is the single source of both the preview and the launch,
so the preview is exactly what runs."""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..core import casefolder as cf
from ..core.db import Store
from . import fsjail

SOURCE_TAG = "ghost-recon-console"
MAX_NAME = 120
MAX_NOTES = 20_000
LANGS = ("es", "en")
CONSOLE_DIR = "_console"
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_UNSAFE_RE = re.compile(r'["\x00-\x1f\x7f]')
NO_ROOTS_MESSAGE = ("La consola no tiene carpetas de casos configuradas. Pide a quien administra la máquina que añada "
                    "la carpeta de casos en case_roots (config.yaml → plugins.entries.ghost-recon.settings.console) "
                    "y reinicie la consola.")
MISSING_ROOTS_MESSAGE = ("Ninguna de las carpetas de casos configuradas en case_roots existe en esta máquina. Pide a "
                         "quien administra la máquina que la cree o corrija la configuración.")


@dataclass(frozen=True)
class Order:
    command: str
    skill: str
    requires: str       # "not_sealed" | "case" | "sealed"
    context_arg: bool   # the skill takes a context .md as its second argument
    options: bool       # --name / --currency / --lang
    out: bool           # --out


ORDERS: Dict[str, Order] = {
    "new-open-case": Order("new-open-case", "new-open-case", "not_sealed", True, True, True),
    "rerun-case": Order("rerun-case", "rerun-case", "case", True, False, True),
    "review-case": Order("review-case", "review-case", "sealed", False, False, False),
}

_REQUIREMENTS: Dict[str, Tuple[Callable[[Optional[Dict[str, Any]]], bool], str, str]] = {
    "not_sealed": (lambda case: not (case and case["sealed"]), "use_rerun",
                   "Esta carpeta ya es un caso con una auditoría sellada: usa Re-run para la evidencia nueva."),
    "case": (lambda case: bool(case), "not_a_case", "Esta carpeta todavía no es un caso: usa Nueva auditoría."),
    "sealed": (lambda case: bool(case and case["sealed"]), "no_sealed_audit",
               "La revisión necesita al menos una auditoría sellada del caso."),
}


class CommandError(Exception):
    """A launch the console refuses; ``status`` and ``code`` map to the API error envelope."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LaunchRequest:
    command: str
    folder: str
    name: str = ""
    currency: str = ""
    lang: str = ""
    out: str = ""
    notes: str = ""


def _q(text: str) -> str:
    return f'"{text}"'


def _safe(label: str, value: str) -> str:
    if _UNSAFE_RE.search(value):
        raise CommandError(422, "invalid_argument", f"{label}: no puede contener comillas dobles ni saltos de línea")
    return value


def _jail(raw: str, roots: Sequence[Path], label: str) -> Path:
    try:
        path = fsjail.resolve(raw, roots)
    except fsjail.FsJailError as exc:
        raise CommandError(403 if exc.code == "outside_roots" else 422, exc.code, f"{label}: {exc.message}") from exc
    if not path.is_dir():
        raise CommandError(422, "not_a_folder", f"{label}: no es una carpeta")
    _safe(label, str(path))
    return path


def _options(order: Order, req: LaunchRequest) -> Dict[str, str]:
    if not order.options:
        return {}
    name = req.name.strip()
    if len(name) > MAX_NAME:
        raise CommandError(422, "invalid_argument", f"el nombre admite como máximo {MAX_NAME} caracteres")
    currency = req.currency.strip().upper()
    if currency and not CURRENCY_RE.match(currency):
        raise CommandError(422, "invalid_argument", "la moneda debe ser un código ISO-4217 de 3 letras (p. ej. USD)")
    lang = req.lang.strip().lower()
    if lang and lang not in LANGS:
        raise CommandError(422, "invalid_argument", f"el idioma debe ser uno de: {', '.join(LANGS)}")
    return {"name": _safe("nombre", name), "currency": currency, "lang": lang}


def combined_name(original_sha: str, notes: str, username: str) -> str:
    """Same inputs, same name: the preview can show the exact path the launch will write."""
    digest = hashlib.sha256(f"{original_sha}\n{username}\n{notes}".encode("utf-8")).hexdigest()[:12]
    return f"context_{digest}.md"


def build_query(order: Order, folder: Path, context_file: str, opts: Dict[str, str], out: Optional[Path]) -> str:
    """The ``-q`` text with the argument conventions of the order's skill (skills/ghost-recon/<order>/SKILL.md):
    folder first, then the context ``.md`` for the orders that take one, then the flags. ``/review-case`` has no
    context argument, so the operator's notes travel on a second line."""
    parts = [f"/{order.command}", _q(str(folder))]
    if context_file and order.context_arg:
        parts.append(_q(context_file))
    for flag, key in (("--name", "name"), ("--currency", "currency"), ("--lang", "lang")):
        if opts.get(key):
            parts += [flag, _q(opts[key]) if key == "name" else opts[key]]
    if out is not None and order.out:
        parts += ["--out", _q(str(out))]
    query = " ".join(parts)
    if context_file and not order.context_arg:
        query += f"\nContexto adicional del operador (declaraciones, no hechos): {_q(context_file)}"
    return query


def agent_args(skill: str, query: str, profile_args: Sequence[str]) -> List[str]:
    """Hermes arguments of a console job (spec §6.1); ``--format stream-json`` implies ``--quiet``."""
    return [*profile_args, "--cli", "--accept-hooks", "--skills", skill, "chat", "-q", query,
            "--format", "stream-json", "--source", SOURCE_TAG]


def plan(req: LaunchRequest, *, store: Store, roots: Sequence[Path], audits_dirname: str, username: str,
         profile_args: Sequence[str], hermes: Callable[[Sequence[str]], List[str]]) -> Dict[str, Any]:
    """Validate a launch and compute everything it needs. No side effects: the preview calls it as is."""
    order = ORDERS.get(req.command)
    if order is None:
        raise CommandError(422, "unknown_command", f"orden desconocida: {req.command}")
    if not roots:
        raise CommandError(409, "no_case_roots", NO_ROOTS_MESSAGE)
    folder = _jail(req.folder, roots, "carpeta")
    opts = _options(order, req)
    out = _jail(req.out, roots, "carpeta de salida") if order.out and req.out.strip() else None
    case = fsjail.existing_case(store, folder, audits_dirname)
    check, code, message = _REQUIREMENTS[order.requires]
    if not check(case):
        raise CommandError(409, code, message)
    notes = req.notes.strip()
    if len(notes) > MAX_NOTES:
        raise CommandError(422, "invalid_argument", f"las notas admiten como máximo {MAX_NOTES} caracteres")
    results_root = out or (Path(case["results_root"]) if case else cf.audits_root(folder, audits_dirname))
    found = fsjail.context_info(folder, roots)
    original = {k: found[k] for k in ("path", "sha256", "size")} if found else None
    if notes:
        context_file = str(results_root / CONSOLE_DIR / combined_name((original or {}).get("sha256", ""), notes,
                                                                     username))
    else:
        context_file = original["path"] if original and order.context_arg else ""
    query = build_query(order, folder, context_file, opts, out)
    return {"command": order.command, "skill": order.skill, "folder": str(folder), "out": str(out) if out else "",
            "case": case, "results_root": str(results_root), "original_context": original, "notes": notes,
            "context_file": context_file, "query": query,
            "argv": [str(a) for a in hermes(agent_args(order.skill, query, profile_args))],
            "args": {**opts, "out": str(out) if out else ""}}


def combined_context_text(plan_: Dict[str, Any], username: str, now: str) -> str:
    """The combined context of spec §7: the original ``context.md`` verbatim with its hash, then the operator's
    signed notes, declared as statements to record as criteria (never facts)."""
    original = plan_["original_context"]
    if original:
        data = Path(original["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != original["sha256"]:
            raise CommandError(409, "context_changed",
                               "El context.md cambió mientras se preparaba la ejecución: vuelve a revisarlo y lanza otra vez.")
        source = f"Fuente: {original['path']} · SHA-256 {original['sha256']}"
        literal = data.decode("utf-8", "replace")
    else:
        source, literal = "Sin context.md en la carpeta.", ""
    if literal and not literal.endswith("\n"):
        literal += "\n"
    return (f"# Contexto de la ejecución ({plan_['command']}) · consola Ghost Recon\n\n"
            f"## Contexto original\n\n{source}\n\n{literal}\n"
            f"## Notas del operador — {username}, {now}\n\n"
            f"> Declaraciones del operador: registrar como criterio/declaración (CRIT-nn, autor {username}), "
            f"no como hecho.\n\n{plan_['notes']}\n")


def write_combined_context(plan_: Dict[str, Any], username: str, now: str) -> Path:
    """Write the combined context where ``plan`` said (``<results>/_console/``), as exact UTF-8 bytes."""
    path = Path(plan_["context_file"])
    text = combined_context_text(plan_, username, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def display_command(argv: Sequence[str], *, windows: Optional[bool] = None) -> str:
    """Copyable command line: POSIX shell quoting, or the Windows CreateProcess rules."""
    if windows is None:
        from hermes_cli._subprocess_compat import IS_WINDOWS
        windows = IS_WINDOWS
    return subprocess.list2cmdline(list(argv)) if windows else shlex.join(list(argv))
```

- [ ] **Step 5: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_commands.py tests/plugins/ghost_recon/console/test_procs.py -q`
Expected: `0 failed`. En Windows sale skipped la prueba `posix` de la comilla doble (Windows no admite `"` en nombres); en Linux/macOS, la de `CommandLineToArgvW`.

- [ ] **Step 6: Commit**

```bash
git add plugins/ghost_recon/console/commands.py plugins/ghost_recon/console/procs.py tests/plugins/ghost_recon/console/test_commands.py tests/plugins/ghost_recon/console/test_procs.py
git commit -m "feat(ghost-recon): console order table, exact launch preview and combined operator context

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Procesos y `job_runner` con el agente falso

**Files:**
- Modify: `plugins/ghost_recon/console/procs.py` (entorno, desacople, identidad y árbol)
- Create: `plugins/ghost_recon/console/jobfiles.py`
- Create: `plugins/ghost_recon/console/job_runner.py`
- Create: `ghost-recon/demo/fake_agent.py`
- Modify: `tests/plugins/ghost_recon/console/conftest.py` (`wait_until`, `fake_agent`, `module_runner`)
- Test: `tests/plugins/ghost_recon/console/test_runner.py`

**Interfaces:**
- Consumes: `tools.environments.local.served_profile_child_env(base=None, *, target_home=None, inherit_credentials=False) -> dict` (firma confirmada); `hermes_cli._subprocess_compat.windows_detach_popen_kwargs() -> dict`, `windows_detach_flags_without_breakaway() -> int`, `IS_WINDOWS`; psutil; `events.Normalizer`; `ConsoleStore.get_job/update_job` (Tarea 1); `Store.get_case`, `Store.add_event`; `runtime.db_path()`, `runtime.store()`.
- Produces:
  - `procs.py` (además de la Tarea 4): `child_env() -> dict`, `spawn_detached(argv, *, cwd, env, stdout=DEVNULL, stderr=DEVNULL) -> Popen`, `identity(pid) -> Optional[float]` (create time), `alive(pid, started) -> bool` (un zombi o un PID reciclado cuentan como muertos), `kill_tree(pid, started, *, timeout=10.0) -> bool`.
  - `jobfiles.py`: `jobs_dir() -> Path` (`<carpeta de la BD>/console/jobs`, es decir `plugin_data_dir/ghost-recon/console/jobs` dentro de Hermes), `raw_path`, `log_path`, `events_path`, `runner_log_path` (`(base, job_id) -> Path`), `read_lines(path, offset=0, *, final=False) -> (lines, offset)`, `append_events(path, events)`, `read_events(path, after=0, offset=0) -> (events, offset)`, `tail(path, lines=200, max_bytes=256_000) -> str`.
  - `job_runner.py`: `RESULT_TEXT_MAX = 20_000`, `SELF_CHECK = "ghost-recon job runner ok"`, `final_state(returncode, result, stderr_tail) -> dict`, `class Runner(job_id, *, cstore, store, base, poll=1.0)` con `run() -> str` (estado final según la BD), `main(argv=None) -> int`; CLI `python -m plugins.ghost_recon.console.job_runner <job_id> [--poll S] [--self-check]`.
  - `ghost-recon/demo/fake_agent.py`: `--fake-config <json>` + los argumentos de Hermes; comportamiento por defecto y por nombre de carpeta (`steps`, `delay`, `exit_code`, `error`, `hang`, `no_result`, `open_case`, `record_argv`).
  - Fixtures: `wait_until(predicate, timeout=30.0, interval=0.05, message=...)`, `fake_agent(default=None, folders=None) -> hermes_command`, `module_runner(poll=0.05) -> runner_command`.

- [ ] **Step 1: Fixtures del agente falso**

En `tests/plugins/ghost_recon/console/conftest.py`, sustituye:

```python
import shutil
from pathlib import Path
```

por:

```python
import json
import shutil
import sys
import time
from pathlib import Path
```

y sustituye:

```python
DEMO = REPO / "ghost-recon" / "demo" / "demo-case"
```

por:

```python
DEMO = REPO / "ghost-recon" / "demo" / "demo-case"
FAKE_AGENT = REPO / "ghost-recon" / "demo" / "fake_agent.py"
```

Después añade al final del archivo:

```python
@pytest.fixture
def wait_until():
    """Poll ``predicate`` until it returns something truthy (returned) or fail after ``timeout`` seconds."""
    def _wait(predicate, timeout=30.0, interval=0.05, message="condition"):
        deadline = time.monotonic() + timeout
        while True:
            value = predicate()
            if value:
                return value
            assert time.monotonic() < deadline, f"timed out after {timeout} s waiting for {message}"
            time.sleep(interval)
    return _wait


@pytest.fixture
def fake_agent(tmp_path):
    """Factory: writes a fake-agent config and returns the ``hermes_command`` that runs the fake with it."""
    made = []

    def _make(default=None, folders=None):
        config = tmp_path / f"fake-agent-{len(made)}.json"
        config.write_text(json.dumps({"default": default or {}, "folders": folders or {}}), encoding="utf-8")
        made.append(config)
        return lambda args: [sys.executable, str(FAKE_AGENT), "--fake-config", str(config), *args]
    return _make


@pytest.fixture
def module_runner():
    """Factory: the runner as ``python -m`` from the repo root (the production launcher form is covered by
    test_runner.py::test_runner_entry_point_runs_through_this_installation_launcher)."""
    from plugins.ghost_recon.console.procs import RUNNER_MODULE

    def _make(poll=0.05):
        return lambda job_id: [sys.executable, "-m", RUNNER_MODULE, str(job_id), "--poll", str(poll)]
    return _make
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_runner.py`:

```python
"""Job runner with the fake agent: states, session, phase, result and events land in the DB; the stored argv is what
runs; a cancel always wins over the runner's final write; the detached tree dies whole, on each OS."""
import json
import os
import subprocess
import sys
import threading

import pytest

from plugins.ghost_recon.console import jobfiles, procs
from plugins.ghost_recon.console.commands import agent_args
from plugins.ghost_recon.console.events import Normalizer
from plugins.ghost_recon.console.job_runner import SELF_CHECK, Runner
from plugins.ghost_recon.console.procs import RUNNER_MODULE


@pytest.fixture
def evidence(case_root):
    folder = case_root / "Caso Runner"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder


def _job(cstore, folder, hermes, command="new-open-case"):
    folder = folder.resolve()  # what commands.plan stores
    argv = hermes(agent_args(command, f'/{command} "{folder}"', ["-p", "default"]))
    return cstore.create_job(command=command, folder=str(folder), args={}, argv=argv, launched_by="jean")


def _run(cstore, store, job_id):
    return Runner(job_id, cstore=cstore, store=store, base=jobfiles.jobs_dir(), poll=0.05).run()


def _with_agent(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["pid"] else None


def test_runner_records_session_phase_result_events_and_the_case(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent({"steps": 3}))
    assert _run(cstore, store, job["id"]) == "succeeded"
    row = cstore.get_job(job["id"])
    case = store.get_case(str(evidence.resolve()))
    assert row["exit_code"] == 0 and row["case_id"] == case["id"]
    assert row["tokens"]["total"] > 0 and row["result_text"] and row["finished_at"]
    replay = Normalizer()
    for line in jobfiles.raw_path(jobfiles.jobs_dir(), job["id"]).read_text(encoding="utf-8").splitlines():
        replay.feed_line(line)
    assert (row["phase"], row["session_id"]) == (replay.phase, replay.session_id)  # the DB mirrors the stream
    events, _ = jobfiles.read_events(jobfiles.events_path(jobfiles.jobs_dir(), job["id"]))
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)) and events[-1]["kind"] == "result"
    finished = [e for e in store.list_events(case["id"]) if e["event_type"] == "console_job_finished"]
    assert finished and finished[-1]["actor"] == "jean"


def test_a_failed_agent_keeps_its_exit_code_and_error(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent({"exit_code": 3, "error": "proveedor sin cuota"}))
    assert _run(cstore, store, job["id"]) == "failed"
    row = cstore.get_job(job["id"])
    assert row["exit_code"] == 3 and "proveedor sin cuota" in row["error"]


def test_an_agent_without_a_result_record_fails(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent({"no_result": True}))
    assert _run(cstore, store, job["id"]) == "failed"
    assert "resultado final" in cstore.get_job(job["id"])["error"]


def test_the_runner_executes_exactly_the_stored_argv(cstore, store, evidence, fake_agent, tmp_path):
    record = tmp_path / "argv.json"
    job = _job(cstore, evidence, fake_agent({"record_argv": str(record)}))
    _run(cstore, store, job["id"])
    assert json.loads(record.read_text(encoding="utf-8")) == cstore.get_job(job["id"])["argv"][1:]


def test_a_job_cancelled_before_it_starts_never_launches_the_agent(cstore, store, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent())
    cstore.update_job(job["id"], status="cancelled")
    assert _run(cstore, store, job["id"]) == "cancelled"
    assert not jobfiles.raw_path(jobfiles.jobs_dir(), job["id"]).exists()


def test_a_cancel_wins_over_the_runner_final_write(cstore, store, evidence, fake_agent, wait_until):  # Review Focus 4
    job = _job(cstore, evidence, fake_agent({"steps": 400, "delay": 0.05}))
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(status=_run(cstore, store, job["id"])))
    worker.start()
    row = wait_until(lambda: _with_agent(cstore, job["id"]), message="agent started")
    assert cstore.update_job(job["id"], status="cancelled", error="cancelada por jean")
    worker.join(timeout=60)
    assert outcome["status"] == "cancelled"
    final = cstore.get_job(job["id"])
    assert (final["status"], final["error"]) == ("cancelled", "cancelada por jean")
    assert not procs.alive(row["pid"], row["pid_started"])


def test_the_runner_module_runs_a_job_to_completion(cstore, evidence, fake_agent):
    job = _job(cstore, evidence, fake_agent())
    r = subprocess.run([sys.executable, "-m", RUNNER_MODULE, str(job["id"]), "--poll", "0.05"],
                       cwd=procs.hermes_root(), env=procs.child_env(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert cstore.get_job(job["id"])["status"] == "succeeded"


def test_runner_entry_point_runs_through_this_installation_launcher():
    r = subprocess.run(procs.hermes_command(["--self-check"], module=RUNNER_MODULE), env=procs.child_env(),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    assert SELF_CHECK in r.stdout


def test_identity_guards_against_recycled_pids():
    me = os.getpid()
    assert procs.alive(me, procs.identity(me))
    assert not procs.alive(me, procs.identity(me) + 100)
    assert not procs.alive(None, None) and not procs.kill_tree(None, None)


def _hanging_tree(cstore, folder, fake_agent, wait_until):
    """A detached runner whose fake agent spawned a sleeping grandchild; returns (runner Popen, agent, grandchild)."""
    job = _job(cstore, folder, fake_agent({"hang": True}))
    runner = procs.spawn_detached([sys.executable, "-m", RUNNER_MODULE, str(job["id"]), "--poll", "0.05"],
                                  cwd=procs.hermes_root(), env=procs.child_env())
    raw = jobfiles.raw_path(jobfiles.jobs_dir(), job["id"])

    def grandchild():
        lines = raw.read_text(encoding="utf-8").splitlines() if raw.exists() else []
        hang = [json.loads(line) for line in lines if '"tool_call_id": "hang"' in line]
        return hang[0]["input"]["pid"] if hang else None

    pid = wait_until(grandchild, message="the fake agent's grandchild")
    agent = wait_until(lambda: _with_agent(cstore, job["id"]), message="agent pid")["pid"]
    return runner, agent, pid


def _kill_and_check(runner, agent, grandchild, wait_until):
    assert procs.kill_tree(runner.pid, procs.identity(runner.pid))
    wait_until(lambda: not any(procs.alive(p, None) for p in (runner.pid, agent, grandchild)),
               message="the whole tree gone")
    runner.wait(timeout=30)


@pytest.mark.platforms("posix")
def test_the_detached_runner_leads_its_session_and_dies_with_its_tree_posix(cstore, evidence, fake_agent, wait_until):
    runner, agent, grandchild = _hanging_tree(cstore, evidence, fake_agent, wait_until)
    assert os.getsid(runner.pid) == runner.pid  # start_new_session: a server restart cannot signal it
    _kill_and_check(runner, agent, grandchild, wait_until)


@pytest.mark.platforms("windows")
def test_the_detached_runner_dies_with_its_tree_windows(cstore, evidence, fake_agent, wait_until):
    runner, agent, grandchild = _hanging_tree(cstore, evidence, fake_agent, wait_until)
    _kill_and_check(runner, agent, grandchild, wait_until)
```

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_runner.py -q`
Expected: FAIL con `ImportError: cannot import name 'jobfiles' from 'plugins.ghost_recon.console'`.

- [ ] **Step 4: Ampliar `console/procs.py`**

Sustituye:

```python
import importlib.util
from pathlib import Path
from typing import List, Sequence
```

por:

```python
import importlib.util
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
```

y añade al final del archivo:

```python
_IDENTITY_TOLERANCE_S = 0.01


def child_env() -> Dict[str, str]:
    """Environment of the runner and the agent: the served profile's, with its credentials (root AGENTS.md: child
    spawns use ``served_profile_child_env``, never ``os.environ.copy()``)."""
    from tools.environments.local import served_profile_child_env
    return served_profile_child_env(inherit_credentials=True)


def spawn_detached(argv: Sequence[str], *, cwd: Any, env: Dict[str, str], stdout: Any = subprocess.DEVNULL,
                   stderr: Any = subprocess.DEVNULL) -> subprocess.Popen:
    """Start ``argv`` detached from the console's session/console, so stopping the server never takes it down.
    The only per-OS branch of the job engine, and it is Hermes': a new session on POSIX; a new process group, hidden
    console and job breakaway on Windows, retried without breakaway when a job object forbids it."""
    from hermes_cli._subprocess_compat import (IS_WINDOWS, windows_detach_flags_without_breakaway,
                                               windows_detach_popen_kwargs)
    common = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL, "stdout": stdout, "stderr": stderr,
              "close_fds": True}
    try:
        return subprocess.Popen(list(argv), **common, **windows_detach_popen_kwargs())
    except PermissionError:
        if not IS_WINDOWS:
            raise
        return subprocess.Popen(list(argv), **common, creationflags=windows_detach_flags_without_breakaway())


def identity(pid: Any) -> Optional[float]:
    """The process create time, stored beside a PID as its fingerprint; None when the process is gone."""
    import psutil
    try:
        return psutil.Process(int(pid)).create_time()
    except (psutil.Error, TypeError, ValueError):
        return None


def _matching(pid: Any, started: Any):
    import psutil
    if not pid:
        return None
    try:
        proc = psutil.Process(int(pid))
        if started is not None and abs(proc.create_time() - float(started)) > _IDENTITY_TOLERANCE_S:
            return None
    except (psutil.Error, TypeError, ValueError):
        return None
    try:
        if proc.status() == psutil.STATUS_ZOMBIE:
            return None
    except psutil.AccessDenied:
        pass
    except psutil.Error:
        return None
    return proc


def alive(pid: Any, started: Any) -> bool:
    """True while the process that had ``pid`` at ``started`` still runs. A zombie (a dead child nobody has waited
    for yet) and a recycled PID both count as dead."""
    return _matching(pid, started) is not None


def kill_tree(pid: Any, started: Any, *, timeout: float = 10.0) -> bool:
    """Terminate the process and every descendant, snapshotting the tree first so reparented grandchildren are
    included; escalate to kill after half the timeout. False when the identity does not match (nothing signalled)."""
    import psutil
    root = _matching(pid, started)
    if root is None:
        return False
    try:
        tree = root.children(recursive=True) + [root]
    except psutil.Error:
        tree = [root]
    for proc in tree:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _gone, survivors = psutil.wait_procs(tree, timeout=timeout / 2)
    for proc in survivors:
        try:
            proc.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(survivors, timeout=timeout / 2)
    return True
```

- [ ] **Step 5: Crear `console/jobfiles.py`**

```python
"""Per-job files under ``<plugin data>/console/jobs/`` (the folder that holds ``ghostrecon.db``):
``<id>.jsonl`` (agent stdout, stream-json), ``<id>.log`` (agent stderr), ``<id>.events.jsonl`` (normalized console
events, written by the runner) and ``<id>.runner.log`` (the runner's own stderr). Byte offsets make reads incremental."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def jobs_dir() -> Path:
    from .. import runtime
    path = runtime.db_path().parent / "console" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.jsonl"


def log_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.log"


def events_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.events.jsonl"


def runner_log_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.runner.log"


def read_lines(path: Path, offset: int = 0, *, final: bool = False) -> Tuple[List[str], int]:
    """Lines appended after byte ``offset`` and the new offset. A trailing line without its newline stays for the
    next read, unless ``final`` (the writer is gone)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except FileNotFoundError:
        return [], offset
    end = len(data) if final else data.rfind(b"\n") + 1
    if end <= 0:
        return [], offset
    lines = [line.decode("utf-8", "replace") for line in data[:end].splitlines() if line.strip()]
    return lines, offset + end


def append_events(path: Path, events: Iterable[Dict[str, Any]]) -> None:
    payload = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    if payload:
        with open(path, "ab") as fh:
            fh.write(payload.encode("utf-8"))


def read_events(path: Path, after: int = 0, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Console events with ``seq > after`` written after byte ``offset``, and the new offset."""
    lines, new_offset = read_lines(path, offset)
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and int(event.get("seq") or 0) > after:
            events.append(event)
    return events, new_offset


def tail(path: Path, lines: int = 200, max_bytes: int = 256_000) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - max_bytes))
            data = fh.read()
    except FileNotFoundError:
        return ""
    return "\n".join(data.decode("utf-8", "replace").splitlines()[-lines:])
```

- [ ] **Step 6: Crear `console/job_runner.py`**

```python
"""Detached job runner: one process per console job (``python -m plugins.ghost_recon.console.job_runner <id>``).

It runs the agent argv stored in ``console_jobs`` — exactly what the preview showed — with stdout → ``<id>.jsonl`` and
stderr → ``<id>.log``, normalizes the stream into ``<id>.events.jsonl``, keeps ``phase``/``session_id``/``case_id``
current and writes the final state. The console server is never its required parent: the job survives a server
restart and the new server finds it in the DB. Every write is conditional on the row still being ``running``, so a
cancel (or an orphan verdict) always wins; the runner then stops the agent and exits.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.db import Store, utcnow
from . import events, jobfiles, procs
from .store import ACTIVE_STATUSES, ConsoleStore

RESULT_TEXT_MAX = 20_000
SELF_CHECK = "ghost-recon job runner ok"


def final_state(returncode: int, result: Optional[Dict[str, Any]], stderr_tail: str) -> Dict[str, Any]:
    """``succeeded`` only when the process exited 0 and the stream closed with a clean ``result`` record."""
    if result is None:
        hint = f": {stderr_tail}" if stderr_tail else ""
        return {"status": "failed", "exit_code": returncode,
                "error": f"el agente terminó sin emitir el resultado final{hint}"}
    ok = returncode == 0 and int(result.get("exit_code") or 0) == 0 and not result.get("error")
    error = result.get("error") or (None if ok else f"el agente terminó con código {returncode}")
    return {"status": "succeeded" if ok else "failed", "exit_code": returncode, "error": error}


class Runner:
    """Runs one job; ``run`` returns the job's final status as the DB holds it."""

    def __init__(self, job_id: int, *, cstore: ConsoleStore, store: Store, base: Path, poll: float = 1.0):
        self.job_id = int(job_id)
        self.cstore = cstore
        self.store = store
        self.poll = poll
        self.raw = jobfiles.raw_path(base, job_id)
        self.log = jobfiles.log_path(base, job_id)
        self.events = jobfiles.events_path(base, job_id)
        self.norm = events.Normalizer()
        self.offset = 0
        self.reported: Dict[str, Any] = {}

    def _status(self) -> str:
        return self.cstore.get_job(self.job_id).get("status", "missing")

    def _case_id(self, job: Dict[str, Any]) -> Optional[str]:
        case = self.store.get_case(job["folder"])
        return case.get("id") if case else None

    def run(self) -> str:
        job = self.cstore.get_job(self.job_id)
        if not job or job["status"] not in ACTIVE_STATUSES:
            return job.get("status", "missing") if job else "missing"
        if not self.cstore.update_job(self.job_id, expect=ACTIVE_STATUSES, status="running"):
            return self._status()
        self.reported = {k: job.get(k) for k in ("case_id", "phase", "session_id")}
        try:
            with open(self.raw, "ab") as out, open(self.log, "ab") as err:
                agent = subprocess.Popen(job["argv"], stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                         cwd=job["folder"], env=procs.child_env())
        except OSError as exc:
            self._finish(job, {"status": "failed", "exit_code": None, "error": f"no se pudo iniciar el agente: {exc}"})
            return self._status()
        self.cstore.update_job(self.job_id, expect=("running",), pid=agent.pid, pid_started=procs.identity(agent.pid))
        while agent.poll() is None:
            if not self._pump(job, final=False):
                procs.kill_tree(agent.pid, None)
                agent.wait(timeout=30)
                return self._status()
            time.sleep(self.poll)
        self._pump(job, final=True)
        self._finish(job, final_state(agent.returncode, self.norm.result, jobfiles.tail(self.log, lines=5)))
        return self._status()

    def _pump(self, job: Dict[str, Any], *, final: bool) -> bool:
        """Normalize what the agent wrote since the last call and keep phase/session/case current. False when the
        row is no longer ``running`` (cancelled, or declared orphan): the runner must stop."""
        lines, self.offset = jobfiles.read_lines(self.raw, self.offset, final=final)
        new: List[Dict[str, Any]] = [event for line in lines for event in self.norm.feed_line(line)]
        if final or not lines:
            new += self.norm.flush()  # an idle stream closes the pending group of generic tools
        jobfiles.append_events(self.events, new)
        current = {"phase": self.norm.phase, "session_id": self.norm.session_id or None,
                   "case_id": self.reported.get("case_id") or self._case_id(job)}
        changed = {k: v for k, v in current.items() if v and v != self.reported.get(k)}
        if changed:
            self.reported.update(changed)
            return self.cstore.update_job(self.job_id, expect=("running",), **changed)
        return self._status() == "running"

    def _finish(self, job: Dict[str, Any], state: Dict[str, Any]) -> None:
        result = self.norm.result or {}
        fields: Dict[str, Any] = {"status": state["status"], "exit_code": state["exit_code"], "error": state["error"],
                                  "finished_at": utcnow(), "tokens": result.get("tokens") or {}}
        text = (result.get("text") or self.norm.text)[:RESULT_TEXT_MAX]
        case_id = self.reported.get("case_id") or self._case_id(job)
        extra = {"result_text": text, "phase": self.norm.phase, "session_id": self.norm.session_id,
                 "case_id": case_id}
        fields.update({k: v for k, v in extra.items() if v})
        if self.cstore.update_job(self.job_id, expect=("running",), **fields) and case_id:
            verb = "terminó" if state["status"] == "succeeded" else "falló"
            self.store.add_event(case_id, "console_job_finished", f"Ejecución #{self.job_id} ({job['command']}) {verb}",
                                 actor=job["launched_by"], ref={"job_id": self.job_id, "status": state["status"],
                                                                "session_id": self.norm.session_id or None})


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost-recon-job-runner", description="Run one Ghost Recon console job.")
    parser.add_argument("job_id", type=int, nargs="?")
    parser.add_argument("--poll", type=float, default=1.0, help="Seconds between reads of the agent output")
    parser.add_argument("--self-check", action="store_true",
                        help="Check that this interpreter can run console jobs, then exit")
    args = parser.parse_args(argv)
    if args.self_check:
        procs.child_env()
        if procs.identity(os.getpid()) is None:
            print("psutil no puede leer los procesos de esta máquina", file=sys.stderr)
            return 1
        print(SELF_CHECK, flush=True)
        return 0
    if args.job_id is None:
        parser.error("falta job_id")
    from .. import runtime
    status = Runner(args.job_id, cstore=ConsoleStore.open_default(), store=runtime.store(), base=jobfiles.jobs_dir(),
                    poll=args.poll).run()
    return 0 if status in ("succeeded", "cancelled") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Crear `ghost-recon/demo/fake_agent.py`**

```python
#!/usr/bin/env python3
"""Stand-in for ``hermes … chat -q … --format stream-json`` (console tests and demo; no LLM, no keys).

    python ghost-recon/demo/fake_agent.py --fake-config cfg.json <the Hermes arguments the console built>

Emits the real record shapes of ``hermes_cli/stream_json.py`` (system/init, tool_use, tool_result, text, result),
sleeping between steps, and exits with the configured code. The console runs the agent with the case folder as its
working directory, so the config holds a ``default`` behaviour plus overrides keyed by folder name:

    {"default": {"steps": 3, "delay": 0.05}, "folders": {"hang-case": {"hang": true}}}

Keys: ``steps`` (delegated blocks), ``delay`` (seconds per step), ``exit_code``, ``error`` (in the result record),
``hang`` (spawn a sleeping grandchild and wait to be killed), ``no_result`` (exit without the result record),
``open_case`` (really open the case in the Ghost Recon DB on /new-open-case; default true) and ``record_argv`` (path
where the full argv is written as JSON).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL_OUTPUT_CAP = 5000  # the same cap as hermes_cli/stream_json.py


def emit(record: dict) -> None:
    sys.stdout.write(json.dumps({**record, "timestamp": int(time.time() * 1000)}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def tool(name: str, args: dict, output, call_id: str) -> None:
    emit({"type": "tool_use", "name": name, "tool_call_id": call_id, "input": args})
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    emit({"type": "tool_result", "name": name, "tool_call_id": call_id,
          "output": text if len(text) <= TOOL_OUTPUT_CAP else text[:TOOL_OUTPUT_CAP] + "...", "duration_ms": 5,
          "is_error": False})


def behaviour(config_path: str, folder_name: str) -> dict:
    data = json.loads(Path(config_path).read_text(encoding="utf-8")) if config_path else {}
    merged = dict(data.get("default") or {})
    merged.update((data.get("folders") or {}).get(folder_name) or {})
    return merged


def open_case(folder: Path):
    sys.path.insert(0, str(REPO))
    from plugins.ghost_recon import runtime
    from plugins.ghost_recon.core import service
    return service.open_case(runtime.store(), str(folder), audits_dir=str(runtime.setting("audits_dirname")))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-config", default="")
    parser.add_argument("-q", "--query", default="")
    args, _hermes_flags = parser.parse_known_args()
    folder = Path.cwd()
    cfg = behaviour(args.fake_config, folder.name)
    if cfg.get("record_argv"):
        Path(cfg["record_argv"]).write_text(json.dumps(sys.argv, ensure_ascii=False), encoding="utf-8")
    session = f"fake-{os.getpid()}"
    emit({"type": "system", "subtype": "init", "model": "fake/agent", "session_id": session})
    if cfg.get("hang"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        emit({"type": "tool_use", "name": "terminal", "tool_call_id": "hang",
              "input": {"command": "sleep 600", "pid": child.pid}})
        while True:
            time.sleep(0.2)
    steps, delay = int(cfg.get("steps", 3)), float(cfg.get("delay", 0.05))
    if args.query.startswith("/new-open-case") and cfg.get("open_case", True):
        tool("gr_case_open", {"folder": str(folder)}, open_case(folder), "c1")
    tool("read_file", {"path": str(folder / "context.md")}, "contexto", "c2")
    tool("gr_swarm_plan", {"audit_id": "fake", "mode": "extraction"},
         {"mode": "extraction", "tasks": [{"block": f"b{i}"} for i in range(steps)], "waves": 1}, "c3")
    for i in range(steps):
        time.sleep(delay)
        tool("delegate_task", {"tasks": [{"goal": f"bloque {i + 1}"}]}, "ok", f"d{i}")
    emit({"type": "text", "text": "Auditoría simulada "})
    emit({"type": "text", "text": "completada."})
    code = int(cfg.get("exit_code", 0))
    if cfg.get("no_result"):
        return code
    record = {"type": "result", "session_id": session, "exit_code": code, "text": "Auditoría simulada completada.",
              "tokens": {"input": 120, "output": 45, "total": 165, "cache_read": 0, "cache_write": 0},
              "duration_ms": int(steps * delay * 1000)}
    if cfg.get("error"):
        record["error"] = cfg["error"]
    emit(record)
    print(f"\nsession_id: {session}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_runner.py -q`
Expected: `0 failed` (1 skipped: la prueba de árbol del otro SO).

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`.

- [ ] **Step 9: Commit**

```bash
git add plugins/ghost_recon/console/procs.py plugins/ghost_recon/console/jobfiles.py plugins/ghost_recon/console/job_runner.py ghost-recon/demo/fake_agent.py tests/plugins/ghost_recon/console/conftest.py tests/plugins/ghost_recon/console/test_runner.py
git commit -m "feat(ghost-recon): detached console job runner, process identity checks and a fake agent

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `JobService` — límites, cola, cancelación, huérfanos y reinicio

**Files:**
- Create: `plugins/ghost_recon/console/jobs.py`
- Modify: `tests/plugins/ghost_recon/console/conftest.py` (`make_jobs`)
- Test: `tests/plugins/ghost_recon/console/test_jobs.py`

**Interfaces:**
- Consumes: `commands.plan`, `commands.write_combined_context`, `commands.display_command`, `CommandError`, `LaunchRequest` (Tarea 4); `fsjail.configured_roots`, `fsjail.folder_key` (Tarea 2); `procs.*` (Tareas 4 y 5); `jobfiles.jobs_dir`, `jobfiles.runner_log_path`; `ConsoleStore.create_job/get_job/list_jobs/update_job/log`; `Store.get_case`, `Store.add_event`; `runtime.setting`; `auth.Principal`.
- Produces (`console/jobs.py`):
  - `ORPHAN_ERROR` (texto del error de un huérfano);
  - `class JobService(cstore, store, settings, *, hermes_command=None, runner_command=None, tick_seconds=10.0, stream_poll=1.0)` con los atributos `jobs_dir`, `tick_seconds`, `stream_poll` y los métodos:
    - `roots() -> list[Path]`, `audits_dirname() -> str`, `defaults() -> {"currency", "lang"}`;
    - `plan(req, username) -> dict`, `preview(req, username) -> dict` (el plan + `display` + `queue_note`);
    - `launch(req, principal, ip="") -> dict` (fila del job; `409 already_active` si la misma orden ya está activa o en cola en esa carpeta);
    - `dispatch() -> list[int]`, `reconcile() -> list[int]` (ids que pasaron a `orphaned`), `tick()`;
    - `cancel(job_id, principal, ip="") -> dict` (`404 not_found`, `409 not_active`);
    - `active_for_folder(folder) -> list[dict]`, `queue_note(folder) -> Optional[str]`;
    - `start()` (un `tick` y, si `tick_seconds > 0`, el hilo del ciclo) y `stop()`.
  - Fixture `make_jobs(*, hermes=None, runner=None, config=None) -> JobService` (sin hilo: `tick_seconds=0`), que al final detiene los árboles que hayan quedado vivos.

- [ ] **Step 1: Fixture `make_jobs`**

Añade al final de `tests/plugins/ghost_recon/console/conftest.py`:

```python
@pytest.fixture
def make_jobs(cstore, store, settings, fake_agent, module_runner):
    """Factory: a JobService over the test DB with the fake agent and the ``python -m`` runner, no background thread.
    Teardown stops every process tree a test left running."""
    from plugins.ghost_recon.console import procs
    from plugins.ghost_recon.console.jobs import JobService
    from plugins.ghost_recon.console.store import ACTIVE_STATUSES
    made = []

    def _make(*, hermes=None, runner=None, config=None):
        service = JobService(cstore, store, config or settings, hermes_command=hermes or fake_agent(),
                             runner_command=runner or module_runner(), tick_seconds=0, stream_poll=0.05)
        made.append(service)
        return service

    yield _make
    for service in made:
        service.stop()
    for job in cstore.list_jobs(statuses=ACTIVE_STATUSES):
        procs.kill_tree(job["runner_pid"], job["runner_started"])
        procs.kill_tree(job["pid"], job["pid_started"])
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_jobs.py`:

```python
"""JobService: preview = launched argv, one active job per folder or case plus a global limit, queue, cancel,
orphans (also while the server is the runner's parent) and a job that outlives the service that launched it."""
import sys
from dataclasses import replace
from pathlib import Path

import psutil
import pytest

from plugins.ghost_recon.console import procs
from plugins.ghost_recon.console.auth import Principal
from plugins.ghost_recon.console.commands import CommandError, LaunchRequest
from plugins.ghost_recon.console.jobs import JobService
from plugins.ghost_recon.console.store import TERMINAL_STATUSES, ConsoleStore

ADMIN = Principal(1, "jean", "admin", "session")


def sleeper(job_id):
    """Stands in for a runner that stays alive and never writes (limits and queue only)."""
    return [sys.executable, "-c", "import time; time.sleep(120)"]


def _folder(case_root, name):
    folder = case_root / name
    folder.mkdir()
    (folder / "nota.txt").write_text("x", encoding="utf-8")
    return folder


def _done(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["status"] in TERMINAL_STATUSES else None


def _with_agent(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["pid"] else None


def test_the_preview_is_the_argv_the_launch_stores_and_runs(make_jobs, case_root, cstore, wait_until):
    jobs = make_jobs()
    req = LaunchRequest("new-open-case", str(_folder(case_root, "Caso Uno")), notes="El periodo es 2026.")
    preview = jobs.preview(req, "jean")
    job = jobs.launch(req, ADMIN)
    assert job["argv"] == preview["argv"] and preview["display"]
    assert job["context_file"] == preview["context_file"] and Path(job["context_file"]).is_file()
    assert wait_until(lambda: _done(cstore, job["id"]), timeout=60)["status"] == "succeeded"
    assert any(e["action"] == "job_launch" and e["target"] == f"job:{job['id']}" for e in cstore.list_audit_log())


def test_one_active_job_per_folder_and_the_global_limit(make_jobs, settings, seeded, case_root, cstore):
    jobs = make_jobs(runner=sleeper, config=replace(settings, max_parallel_jobs=2))
    rerun = jobs.launch(LaunchRequest("rerun-case", str(seeded["root"])), ADMIN)
    review = jobs.launch(LaunchRequest("review-case", str(seeded["root"])), ADMIN)
    other = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Dos"))), ADMIN)
    third = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Tres"))), ADMIN)

    def status(job):
        return cstore.get_job(job["id"])["status"]

    assert [status(j) for j in (rerun, review, other, third)] == ["running", "queued", "running", "queued"]
    assert "cola" in jobs.queue_note(str(seeded["root"].resolve()))
    row = cstore.get_job(rerun["id"])
    procs.kill_tree(row["runner_pid"], row["runner_started"])
    cstore.update_job(rerun["id"], status="succeeded")  # what the real runner writes when it ends
    jobs.tick()
    assert (status(review), status(third)) == ("running", "queued")  # the folder is free; the global limit is not


def test_the_same_order_twice_on_a_folder_is_409(make_jobs, seeded):
    jobs = make_jobs(runner=sleeper)
    jobs.launch(LaunchRequest("rerun-case", str(seeded["root"])), ADMIN)
    with pytest.raises(CommandError) as err:
        jobs.launch(LaunchRequest("rerun-case", str(seeded["root"])), ADMIN)
    assert (err.value.status, err.value.code) == (409, "already_active")


def test_cancel_a_queued_and_a_running_job(make_jobs, settings, case_root, cstore, fake_agent, wait_until):
    jobs = make_jobs(hermes=fake_agent({"hang": True}), config=replace(settings, max_parallel_jobs=1))
    running = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso A"))), ADMIN)
    queued = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso B"))), ADMIN)
    assert cstore.get_job(queued["id"])["status"] == "queued"
    assert jobs.cancel(queued["id"], ADMIN)["status"] == "cancelled"
    row = wait_until(lambda: _with_agent(cstore, running["id"]), message="agent started")
    assert jobs.cancel(running["id"], ADMIN)["status"] == "cancelled"
    wait_until(lambda: not procs.alive(row["pid"], row["pid_started"])
               and not procs.alive(row["runner_pid"], row["runner_started"]), message="tree stopped")
    with pytest.raises(CommandError) as err:
        jobs.cancel(running["id"], ADMIN)
    assert (err.value.status, err.value.code) == (409, "not_active")
    assert sum(1 for e in cstore.list_audit_log() if e["action"] == "job_cancel") == 2


def test_a_runner_killed_while_the_server_is_its_parent_is_orphaned(make_jobs, case_root, cstore, fake_agent,
                                                                    wait_until):  # Review Focus 3
    jobs = make_jobs(hermes=fake_agent({"hang": True}))
    job = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Huérfano"))), ADMIN)
    row = wait_until(lambda: _with_agent(cstore, job["id"]), message="agent started")
    psutil.Process(row["runner_pid"]).kill()  # dies without a final write; this process has not reaped it yet
    wait_until(lambda: not procs.alive(row["runner_pid"], row["runner_started"]), message="runner gone")
    assert jobs.reconcile() == [job["id"]]
    final = cstore.get_job(job["id"])
    assert final["status"] == "orphaned" and final["error"]
    wait_until(lambda: not procs.alive(row["pid"], row["pid_started"]), message="the agent left behind is stopped")


def test_a_job_outlives_the_service_that_launched_it(make_jobs, case_root, cstore, store, settings, fake_agent,
                                                     module_runner, wait_until):
    first = make_jobs(hermes=fake_agent({"steps": 60, "delay": 0.1}))
    job = first.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Reinicio"))), ADMIN)
    del first  # the "server" goes away without touching its runner
    second = JobService(ConsoleStore.open_default(), store, settings, hermes_command=fake_agent(),
                        runner_command=module_runner(), tick_seconds=0)
    second.start()
    assert second.reconcile() == []  # found again in the DB, not an orphan
    assert wait_until(lambda: _done(cstore, job["id"]), timeout=90)["status"] == "succeeded"
    second.stop()


def test_a_runner_that_cannot_start_fails_the_job(make_jobs, case_root, cstore, tmp_path):
    jobs = make_jobs(runner=lambda job_id: [str(tmp_path / "no-such-runner")])
    job = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Roto"))), ADMIN)
    row = cstore.get_job(job["id"])
    assert row["status"] == "failed" and "no se pudo iniciar" in row["error"]
```

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_jobs.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console.jobs'`.

- [ ] **Step 4: Crear `console/jobs.py`**

```python
"""JobService: create, queue, dispatch, cancel and supervise console jobs (spec §6.2).

Each job runs in its own detached ``job_runner`` process and the ``console_jobs`` row is the only state the server and
the runner share, so a server restart never touches a running audit: the new server finds it in the DB. ``dispatch``
honours one active job per folder or case and ``max_parallel_jobs`` overall; it runs at start-up, after every launch
and cancel, and on each ``tick`` (every ``tick_seconds``), which also reaps finished runner children and declares
``orphaned`` a running job whose runner is gone (stopping the agent it left behind).
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .. import runtime
from ..core import casefolder as cf
from ..core.db import Store, utcnow
from . import commands, fsjail, jobfiles, procs
from .auth import Principal
from .commands import CommandError, LaunchRequest
from .settings import ConsoleSettings
from .store import ACTIVE_STATUSES, ConsoleStore

logger = logging.getLogger(__name__)
ORPHAN_ERROR = "el proceso de la ejecución terminó sin registrar su estado final"


class JobService:
    def __init__(self, cstore: ConsoleStore, store: Store, settings: ConsoleSettings, *,
                 hermes_command: Optional[Callable[[Sequence[str]], List[str]]] = None,
                 runner_command: Optional[Callable[[int], List[str]]] = None, tick_seconds: float = 10.0,
                 stream_poll: float = 1.0):
        self.cstore = cstore
        self.store = store
        self.settings = settings
        self.hermes_command = hermes_command or procs.hermes_command
        self.runner_command = runner_command or procs.runner_command
        self.jobs_dir: Path = jobfiles.jobs_dir()
        self.tick_seconds = tick_seconds
        self.stream_poll = stream_poll
        self._lock = threading.RLock()
        self._children: Dict[int, subprocess.Popen] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ configuration
    def roots(self) -> List[Path]:
        return fsjail.configured_roots(self.settings.case_roots)

    @staticmethod
    def audits_dirname() -> str:
        return str(runtime.setting("audits_dirname") or cf.DEFAULT_AUDITS_DIR)

    @staticmethod
    def defaults() -> Dict[str, str]:
        return {"currency": str(runtime.setting("base_currency") or "USD"),
                "lang": str(runtime.setting("language") or "es")}

    # ------------------------------------------------------------------ orders
    def plan(self, req: LaunchRequest, username: str) -> Dict[str, Any]:
        return commands.plan(req, store=self.store, roots=self.roots(), audits_dirname=self.audits_dirname(),
                             username=username, profile_args=procs.profile_args(), hermes=self.hermes_command)

    def active_for_folder(self, folder: str) -> List[Dict[str, Any]]:
        key = fsjail.folder_key(folder)
        return [j for j in self.cstore.list_jobs(statuses=ACTIVE_STATUSES) if fsjail.folder_key(j["folder"]) == key]

    def queue_note(self, folder: str) -> Optional[str]:
        same = self.active_for_folder(folder)
        if same:
            return f"Hay una ejecución activa en esta carpeta (#{same[-1]['id']}): esta quedará en cola hasta que termine."
        running = self.cstore.list_jobs(statuses=("running",))
        if len(running) >= self.settings.max_parallel_jobs:
            return (f"Ya hay {len(running)} ejecuciones en curso (límite {self.settings.max_parallel_jobs}): "
                    "esta quedará en cola.")
        return None

    def preview(self, req: LaunchRequest, username: str) -> Dict[str, Any]:
        p = self.plan(req, username)
        return {**p, "display": commands.display_command(p["argv"]), "queue_note": self.queue_note(p["folder"])}

    def launch(self, req: LaunchRequest, principal: Principal, ip: str = "") -> Dict[str, Any]:
        with self._lock:
            p = self.plan(req, principal.username)
            for job in self.active_for_folder(p["folder"]):
                if job["command"] == p["command"]:
                    raise CommandError(409, "already_active", "Ya hay una ejecución de esta orden activa o en cola "
                                                              f"para esta carpeta (#{job['id']}).")
            if p["notes"]:
                commands.write_combined_context(p, principal.username, utcnow())
            case_id = p["case"]["id"] if p["case"] and p["case"]["source"] == "db" else None
            job = self.cstore.create_job(command=p["command"], folder=p["folder"], args=p["args"], argv=p["argv"],
                                         launched_by=principal.username, context_file=p["context_file"] or None,
                                         case_id=case_id)
            self.cstore.log("job_launch", user_id=principal.user_id, username=principal.username, ip=ip,
                            target=f"job:{job['id']}", detail={"command": p["command"], "folder": p["folder"],
                                                               "case_id": case_id})
            self._timeline(job, "console_job_launched",
                           f"Ejecución #{job['id']} ({p['command']}) lanzada desde la consola", principal.username)
            self.dispatch()
            return self.cstore.get_job(job["id"])

    def cancel(self, job_id: int, principal: Principal, ip: str = "") -> Dict[str, Any]:
        with self._lock:
            job = self.cstore.get_job(job_id)
            if not job:
                raise CommandError(404, "not_found", f"ejecución no encontrada: {job_id}")
            if job["status"] not in ACTIVE_STATUSES or not self.cstore.update_job(
                    job_id, expect=ACTIVE_STATUSES, status="cancelled", finished_at=utcnow(),
                    error=f"cancelada por {principal.username}"):
                raise CommandError(409, "not_active", "la ejecución ya no está activa")
            current = self.cstore.get_job(job_id)
            procs.kill_tree(current["runner_pid"], current["runner_started"])
            procs.kill_tree(current["pid"], current["pid_started"])  # an agent that outlived its runner
            self.cstore.log("job_cancel", user_id=principal.user_id, username=principal.username, ip=ip,
                            target=f"job:{job_id}", detail={"was": job["status"]})
            self._timeline(current, "console_job_cancelled", f"Ejecución #{job_id} ({job['command']}) cancelada",
                           principal.username)
            self.dispatch()
            return self.cstore.get_job(job_id)

    # ------------------------------------------------------------------ supervision
    def dispatch(self) -> List[int]:
        """Start queued jobs, oldest first, while the limits allow: one active job per folder or case, and
        ``max_parallel_jobs`` running in total."""
        with self._lock:
            self._reap()
            running = self.cstore.list_jobs(statuses=("running",))
            busy = {fsjail.folder_key(j["folder"]) for j in running}
            busy_cases = {j["case_id"] for j in running if j["case_id"]}
            started: List[int] = []
            for job in self.cstore.list_jobs(statuses=("queued",), oldest_first=True, limit=1000):
                if len(running) + len(started) >= self.settings.max_parallel_jobs:
                    break
                key = fsjail.folder_key(job["folder"])
                if key in busy or (job["case_id"] and job["case_id"] in busy_cases):
                    continue
                if self._start_runner(job):
                    started.append(job["id"])
                    busy.add(key)
                    if job["case_id"]:
                        busy_cases.add(job["case_id"])
            return started

    def reconcile(self) -> List[int]:
        """A ``running`` job whose runner process is gone (crash, OOM, killed) becomes ``orphaned``; the agent it
        left behind is stopped, so two agents never work the same folder."""
        with self._lock:
            self._reap()
            orphaned: List[int] = []
            for job in self.cstore.list_jobs(statuses=("running",)):
                if procs.alive(job["runner_pid"], job["runner_started"]):
                    continue
                if self.cstore.update_job(job["id"], expect=("running",), status="orphaned", finished_at=utcnow(),
                                          error=ORPHAN_ERROR):
                    procs.kill_tree(job["pid"], job["pid_started"])
                    self._timeline(job, "console_job_finished",
                                   f"Ejecución #{job['id']} ({job['command']}) terminó sin estado final",
                                   job["launched_by"])
                    orphaned.append(job["id"])
            return orphaned

    def tick(self) -> None:
        self.reconcile()
        self.dispatch()

    def start(self) -> None:
        """Server start-up: find the jobs again in the DB (orphans, queue), then keep ticking in the background."""
        self.tick()
        if self.tick_seconds > 0 and self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="gr-console-jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------------ internals
    def _loop(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            try:
                self.tick()
            except Exception:  # a failed tick must not end supervision; the next one retries
                logger.exception("ghost-recon console: job supervision tick failed")

    def _reap(self) -> None:
        """Wait for runner children that ended, so they never linger as zombies on POSIX."""
        for job_id, proc in list(self._children.items()):
            if proc.poll() is not None:
                del self._children[job_id]

    def _start_runner(self, job: Dict[str, Any]) -> bool:
        log = open(jobfiles.runner_log_path(self.jobs_dir, job["id"]), "ab")
        try:
            proc = procs.spawn_detached(self.runner_command(job["id"]), cwd=procs.hermes_root(),
                                        env=procs.child_env(), stderr=log)
        except OSError as exc:
            self.cstore.update_job(job["id"], expect=("queued",), status="failed", finished_at=utcnow(),
                                   error=f"no se pudo iniciar la ejecución: {exc}")
            return False
        finally:
            log.close()
        # The runner may already have marked the row running; a cancel in between leaves it cancelled.
        if not self.cstore.update_job(job["id"], expect=ACTIVE_STATUSES, status="running", runner_pid=proc.pid,
                                      runner_started=procs.identity(proc.pid), started_at=utcnow()):
            procs.kill_tree(proc.pid, None)
            return False
        self._children[job["id"]] = proc
        return True

    def _case_id(self, job: Dict[str, Any]) -> Optional[str]:
        if job.get("case_id"):
            return job["case_id"]
        case = self.store.get_case(job["folder"])
        return case.get("id") if case else None

    def _timeline(self, job: Dict[str, Any], event_type: str, text: str, actor: str) -> None:
        case_id = self._case_id(job)
        if case_id:
            self.store.add_event(case_id, event_type, text, actor=actor, ref={"job_id": job["id"]})
```

- [ ] **Step 5: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_jobs.py -q`
Expected: `7 passed`.

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add plugins/ghost_recon/console/jobs.py tests/plugins/ghost_recon/console/conftest.py tests/plugins/ghost_recon/console/test_jobs.py
git commit -m "feat(ghost-recon): console job service with limits, queue, cancel, orphans and restart survival

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: API Carpetas y Ejecuciones (JSON + SSE), Inicio en vivo y demo

**Files:**
- Modify: `plugins/ghost_recon/console/deps.py` (`ConsoleContext.jobs`)
- Modify: `plugins/ghost_recon/console/app.py` (`create_app(..., jobs=)`, lifespan, `ROUTERS`)
- Modify: `plugins/ghost_recon/console/readmodel.py` (`job_row`, `job_view`, `progress`, `overview`)
- Create: `plugins/ghost_recon/console/routers/fs.py`
- Create: `plugins/ghost_recon/console/routers/jobs.py`
- Modify: `plugins/ghost_recon/console/routers/system.py` (reemplazo completo: doctor con raíces de casos)
- Modify: `ghost-recon/demo/console_demo.py` (reemplazo completo)
- Modify: `tests/plugins/ghost_recon/console/conftest.py` (`argv_record`, `jobs`, `app`, `login_on`, `login_as`)
- Test: `tests/plugins/ghost_recon/console/test_api_fs.py`
- Test: `tests/plugins/ghost_recon/console/test_api_jobs.py`

**Interfaces:**
- Consumes: `JobService` (Tarea 6), `fsjail` (Tarea 2), `commands.NO_ROOTS_MESSAGE`, `MISSING_ROOTS_MESSAGE`, `CommandError`, `LaunchRequest`, `display_command` (Tarea 4), `procs.profile_args` (Tarea 4), `jobfiles.events_path/read_events/log_path/runner_log_path/tail` (Tarea 5), `events.PHASES/PHASE_LABEL` (Tarea 3); de H1: `require`, `get_ctx`, `client_ip`, `ApiError`, `routers.cases.get_case_or_404`, `readmodel.audit_view/count_by/case_row/_recent_first`.
- Produces:
  - `ConsoleContext.jobs: JobService`; `create_app(settings, store, cstore, *, auth=None, jobs=None)`: el lifespan llama a `jobs.start()` al arrancar (reencuentra ejecuciones, marca huérfanos, despacha la cola y deja el ciclo de 10 s) y a `jobs.stop()` al parar.
  - `readmodel.job_row(store, job) -> dict` (`id, command, status, active, folder, folder_name, case_id, case_name, phase, phase_label, launched_by, created_at, started_at, finished_at, duration_s`), `readmodel.progress(store, case_id) -> Optional[dict]` (`evidence, findings, findings_total, criteria, research_notes`), `readmodel.job_view(store, cstore, job, *, profile_args, dashboard_url) -> dict` (`job_row` + `args, argv, context_file, session_id, exit_code, result_text, tokens, error, phases, resume{terminal, chat_url}, progress, last_audit`); `overview` añade `kpis.jobs_active`, `kpis.jobs_running` y `active_jobs`.
  - Rutas (`/api/v1`):
    - viewer: `GET /fs/roots` (`{items, configured, hint}`), `GET /fs/list?path=`, `GET /fs/search?q=`, `GET /fs/inspect?path=`;
    - admin: `POST /jobs/preview` (plan + `display` + `queue_note`), `POST /jobs` → 202 `{job}`, `POST /jobs/{id}/cancel` → `{job}`;
    - viewer: `GET /jobs?status=&case=&limit=` (`status` = un estado o `active`), `GET /cases/{id}/jobs`, `GET /jobs/{id}` (`job_view` + `display`), `GET /jobs/{id}/events?after=` (`{items, last_seq}`), `GET /jobs/{id}/events/stream` (SSE: `event` con `id: <seq>`, `status`, `end`, latido), `GET /jobs/{id}/log` (`{log, runner_log}`).
    - Errores de la jaula: `403 outside_roots`, `422 bad_path | not_a_folder | bad_query`, `409 no_case_roots`.
  - `GET /system/doctor` añade un check por raíz de casos (`console.case_roots: <ruta>`, con espacio libre) o `console.case_roots` fallido si no hay ninguna; `console` añade `case_roots`, `max_parallel_jobs` y `dashboard_url`.
  - Fixtures: `argv_record`, `jobs` (app por defecto: agente falso rápido; la carpeta `hang-case` se queda colgada), `login_on(app, role="admin")`; `login_as(role)` pasa a usar `login_on`.

- [ ] **Step 1: Fixtures de la app con ejecuciones**

En `tests/plugins/ghost_recon/console/conftest.py`, sustituye:

```python
@pytest.fixture
def app(store, cstore, settings, auth):
    from plugins.ghost_recon.console.app import create_app
    return create_app(settings, store, cstore, auth=auth)
```

por:

```python
@pytest.fixture
def argv_record(tmp_path):
    """Where the default test app's fake agent writes the argv it received (the last run wins)."""
    return tmp_path / "argv.json"


@pytest.fixture
def jobs(make_jobs, fake_agent, argv_record):
    """JobService of the default test app: the fake agent finishes in a fraction of a second, except in a folder
    named ``hang-case``, where it hangs until it is killed."""
    return make_jobs(hermes=fake_agent({"steps": 3, "delay": 0.05, "record_argv": str(argv_record)},
                                       {"hang-case": {"hang": True}}))


@pytest.fixture
def app(store, cstore, settings, auth, jobs):
    from plugins.ghost_recon.console.app import create_app
    return create_app(settings, store, cstore, auth=auth, jobs=jobs)
```

y sustituye la fixture `login_as` completa:

```python
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

por:

```python
@pytest.fixture
def login_on(users):
    """Factory: a logged-in TestClient on any app (tests build their own for custom settings), CSRF header preset."""
    from fastapi.testclient import TestClient
    opened = []

    def _login(app, role: str = "admin"):
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


@pytest.fixture
def login_as(app, login_on):
    """Factory: a logged-in TestClient for 'admin' or 'viewer' on the default test app."""
    return lambda role: login_on(app, role)
```

- [ ] **Step 2: Escribir las pruebas que fallan**

`tests/plugins/ghost_recon/console/test_api_fs.py`:

```python
"""Folder endpoints: viewer-readable, jailed to case_roots, and a plain explanation when no root is configured."""
import hashlib
from dataclasses import replace


def test_roots_list_search_and_inspect_for_a_viewer(login_as, seeded, case_root):
    c = login_as("viewer")
    roots = c.get("/api/v1/fs/roots").json()
    assert [r["path"] for r in roots["items"]] == [str(case_root.resolve())] and roots["configured"]
    assert roots["items"][0]["free_bytes"] > 0
    listing = c.get("/api/v1/fs/list", params={"path": roots["items"][0]["path"]}).json()
    demo = next(i for i in listing["items"] if i["name"] == "demo-case")
    assert demo["case"]["id"] == seeded["case_id"] and demo["case"]["sealed"] == 1 and demo["files"] > 0
    assert [f["path"] for f in c.get("/api/v1/fs/search", params={"q": "DEMO"}).json()["items"]] == [demo["path"]]
    info = c.get("/api/v1/fs/inspect", params={"path": demo["path"]}).json()
    assert info["context"]["sha256"] == hashlib.sha256((seeded["root"] / "context.md").read_bytes()).hexdigest()
    assert info["case"]["id"] == seeded["case_id"] and info["suggested_command"] == "rerun-case"
    assert sum(t["count"] for t in info["by_type"]) == info["files"]


def test_paths_outside_the_roots_or_with_traversal_are_rejected(login_as, gr_env, case_root):
    c = login_as("viewer")
    outside = c.get("/api/v1/fs/list", params={"path": str(gr_env / "db")})
    assert outside.status_code == 403 and outside.json()["error"]["code"] == "outside_roots"
    traversal = c.get("/api/v1/fs/inspect", params={"path": str(case_root) + "/../db"})
    assert traversal.status_code == 422 and traversal.json()["error"]["code"] == "bad_path"
    assert c.get("/api/v1/fs/search", params={"q": "a"}).json()["error"]["code"] == "bad_query"


def test_the_folder_browser_requires_login(client, case_root):
    assert client.get("/api/v1/fs/roots").status_code == 401
    assert client.get("/api/v1/fs/list", params={"path": str(case_root)}).status_code == 401


def test_without_case_roots_the_console_names_the_missing_setting(store, cstore, auth, settings, make_jobs, login_on):
    from plugins.ghost_recon.console.app import create_app
    bare = replace(settings, case_roots=())
    c = login_on(create_app(bare, store, cstore, auth=auth, jobs=make_jobs(config=bare)), "admin")
    roots = c.get("/api/v1/fs/roots").json()
    assert roots["items"] == [] and not roots["configured"] and "case_roots" in roots["hint"]
    listing = c.get("/api/v1/fs/list", params={"path": "/"})
    assert listing.status_code == 409 and listing.json()["error"]["code"] == "no_case_roots"
    preview = c.post("/api/v1/jobs/preview", json={"command": "new-open-case", "folder": "/x"})
    assert preview.status_code == 409 and preview.json()["error"]["code"] == "no_case_roots"
    doctor = c.get("/api/v1/system/doctor").json()
    assert not doctor["ok"] and any(ch["check"] == "console.case_roots" and not ch["ok"] for ch in doctor["checks"])


def test_the_doctor_reports_each_case_root(login_as, case_root):
    body = login_as("viewer").get("/api/v1/system/doctor").json()
    roots = [ch for ch in body["checks"] if ch["check"].startswith("console.case_roots")]
    assert len(roots) == 1 and roots[0]["ok"] and body["console"]["case_roots"] == [str(case_root)]
```

`tests/plugins/ghost_recon/console/test_api_jobs.py`:

```python
"""Job endpoints: role gates, the preview is what runs, live events (JSON and SSE), cancel, log, Home counters."""
import json
from dataclasses import replace

from plugins.ghost_recon.console.events import PHASES
from plugins.ghost_recon.console.store import TERMINAL_STATUSES


def _folder(case_root, name):
    folder = case_root / name
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder


def _finished(client, job_id):
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    return job if job["status"] in TERMINAL_STATUSES else None


def test_a_viewer_cannot_preview_launch_or_cancel(login_as, case_root):
    c = login_as("viewer")
    body = {"command": "new-open-case", "folder": str(_folder(case_root, "Caso Visor"))}
    for url in ("/api/v1/jobs/preview", "/api/v1/jobs", "/api/v1/jobs/1/cancel"):
        r = c.post(url, json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_the_preview_is_exactly_what_the_launch_runs(login_as, case_root, argv_record, store,
                                                     wait_until):  # Review Focus 2
    c = login_as("admin")
    body = {"command": "new-open-case", "folder": str(_folder(case_root, "Caso Logística Norte")),
            "name": "Logística Norte", "currency": "usd", "lang": "es", "notes": "Declaración del gerente."}
    preview = c.post("/api/v1/jobs/preview", json=body).json()
    launched = c.post("/api/v1/jobs", json=body)
    assert launched.status_code == 202
    job = launched.json()["job"]
    assert job["argv"] == preview["argv"] and job["display"] == preview["display"]
    done = wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    assert done["status"] == "succeeded" and done["case_id"]
    assert json.loads(argv_record.read_text(encoding="utf-8")) == job["argv"][1:]  # what the agent received
    evidence = store.list_evidence(done["case_id"])
    assert evidence and not any("_console" in e["path"] or e["path"].startswith("GhostRecon_Audits")
                                for e in evidence)  # the combined context never becomes evidence


def test_events_json_and_sse_agree_and_a_reconnect_resumes(login_as, case_root, wait_until):  # Review Focus 5
    c = login_as("admin")
    folder = str(_folder(case_root, "Caso SSE"))
    job = c.post("/api/v1/jobs", json={"command": "new-open-case", "folder": folder}).json()["job"]
    wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    items = c.get(f"/api/v1/jobs/{job['id']}/events").json()["items"]
    seqs = [e["seq"] for e in items]
    assert seqs == list(range(1, len(seqs) + 1)) and items[-1]["kind"] == "result"
    tail = c.get(f"/api/v1/jobs/{job['id']}/events", params={"after": seqs[-2]}).json()
    assert [e["seq"] for e in tail["items"]] == [seqs[-1]] and tail["last_seq"] == seqs[-1]

    def stream(headers=None):
        with c.stream("GET", f"/api/v1/jobs/{job['id']}/events/stream", headers=headers or {}) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            text = "".join(r.iter_text())
        return [int(line[4:]) for line in text.splitlines() if line.startswith("id: ")], text

    ids, text = stream()
    assert ids == seqs and "event: status" in text and "event: end" in text
    resumed, _ = stream({"Last-Event-ID": str(seqs[2])})
    assert resumed == seqs[3:]


def test_a_finished_job_offers_terminal_and_chat_resume(store, cstore, auth, settings, make_jobs, login_on, case_root,
                                                        wait_until):
    from plugins.ghost_recon.console.app import create_app
    with_chat = replace(settings, dashboard_url="http://127.0.0.1:9119")
    c = login_on(create_app(with_chat, store, cstore, auth=auth, jobs=make_jobs(config=with_chat)), "admin")
    folder = str(_folder(case_root, "Caso Chat"))
    job = c.post("/api/v1/jobs", json={"command": "new-open-case", "folder": folder}).json()["job"]
    done = wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    sid = done["session_id"]
    assert sid and done["resume"]["terminal"].split()[-2:] == ["--resume", sid]
    assert done["resume"]["chat_url"] == f"http://127.0.0.1:9119/chat?resume={sid}"
    assert done["progress"]["evidence"] >= 1 and done["tokens"]["total"] > 0 and done["result_text"]
    assert [p["id"] for p in done["phases"]] == [p for p, _ in PHASES]


def test_home_counts_active_jobs_and_cancel_stops_them(login_as, case_root, wait_until):
    c = login_as("admin")
    job = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                       "folder": str(_folder(case_root, "hang-case"))}).json()["job"]
    wait_until(lambda: c.get(f"/api/v1/jobs/{job['id']}").json()["session_id"], message="agent init")
    overview = c.get("/api/v1/system/overview").json()
    assert overview["kpis"]["jobs_active"] == 1 and [j["id"] for j in overview["active_jobs"]] == [job["id"]]
    cancelled = c.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["job"]["status"] == "cancelled"
    again = c.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_active"
    assert c.get("/api/v1/system/overview").json()["kpis"]["jobs_active"] == 0


def test_job_lists_case_jobs_timeline_and_log(login_as, seeded, store, wait_until):
    c = login_as("admin")
    job = c.post("/api/v1/jobs", json={"command": "rerun-case", "folder": str(seeded["root"])}).json()["job"]
    assert job["case_id"] == seeded["case_id"]
    wait_until(lambda: _finished(c, job["id"]), timeout=60, message="job end")
    assert [j["id"] for j in c.get(f"/api/v1/cases/{seeded['case_id']}/jobs").json()["items"]] == [job["id"]]
    assert c.get("/api/v1/jobs", params={"status": "active"}).json()["items"] == []
    done = c.get("/api/v1/jobs", params={"status": "succeeded", "case": seeded["case_id"]}).json()["items"]
    assert [j["id"] for j in done] == [job["id"]]
    assert c.get("/api/v1/jobs", params={"status": "nope"}).status_code == 422
    assert "session_id: fake-" in c.get(f"/api/v1/jobs/{job['id']}/log").json()["log"]
    kinds = {e["event_type"] for e in store.list_events(seeded["case_id"])}
    assert {"console_job_launched", "console_job_finished"} <= kinds


def test_conflicts_come_back_as_plain_409s(login_as, seeded):
    r = login_as("admin").post("/api/v1/jobs/preview", json={"command": "new-open-case",
                                                             "folder": str(seeded["root"])})
    assert r.status_code == 409 and r.json()["error"]["code"] == "use_rerun" and "Re-run" in r.json()["error"]["message"]


def test_unknown_jobs_are_404(login_as):
    c = login_as("viewer")
    assert c.get("/api/v1/jobs/999").json()["error"]["code"] == "not_found"
    assert c.get("/api/v1/jobs/999/events").status_code == 404
```

- [ ] **Step 3: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_api_fs.py tests/plugins/ghost_recon/console/test_api_jobs.py -q`
Expected: FAIL con `TypeError: create_app() got an unexpected keyword argument 'jobs'`.

- [ ] **Step 4: `ConsoleContext.jobs` en `console/deps.py`**

Sustituye:

```python
from .auth import AuthService, Principal
from .settings import ConsoleSettings
from .store import ConsoleStore
```

por:

```python
from .auth import AuthService, Principal
from .jobs import JobService
from .settings import ConsoleSettings
from .store import ConsoleStore
```

y sustituye:

```python
    cstore: ConsoleStore
    auth: AuthService
```

por:

```python
    cstore: ConsoleStore
    auth: AuthService
    jobs: JobService
```

- [ ] **Step 5: `create_app` con ejecuciones en `console/app.py`**

Sustituye:

```python
import mimetypes
from pathlib import Path
```

por:

```python
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
```

sustituye:

```python
from .deps import ConsoleContext, current_principal
from .routers import audits as audits_routes, auth as auth_routes, cases as cases_routes, system as system_routes
```

por:

```python
from .deps import ConsoleContext, current_principal
from .jobs import JobService
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, fs as fs_routes,
                      jobs as jobs_routes, system as system_routes)
```

sustituye:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes)
```

por:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes)
```

y sustituye:

```python
def create_app(settings: ConsoleSettings, store: Store, cstore: ConsoleStore, *,
               auth: Optional[AuthService] = None) -> FastAPI:
    app = FastAPI(title="Ghost Recon Console", version=CONSOLE_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gr = ConsoleContext(settings=settings, store=store, cstore=cstore,
                                  auth=auth or AuthService(cstore, settings))
```

por:

```python
def create_app(settings: ConsoleSettings, store: Store, cstore: ConsoleStore, *,
               auth: Optional[AuthService] = None, jobs: Optional[JobService] = None) -> FastAPI:
    jobs = jobs or JobService(cstore, store, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        jobs.start()  # find running jobs again, mark orphans, dispatch the queue; then tick in the background
        try:
            yield
        finally:
            jobs.stop()

    app = FastAPI(title="Ghost Recon Console", version=CONSOLE_VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.gr = ConsoleContext(settings=settings, store=store, cstore=cstore,
                                  auth=auth or AuthService(cstore, settings), jobs=jobs)
```

- [ ] **Step 6: Lecturas de ejecuciones en `console/readmodel.py`**

Sustituye la cabecera de imports:

```python
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..core import ids
from ..core.db import Store
from .paths import case_results_root
from .store import ConsoleStore
```

por:

```python
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from ..core import ids
from ..core.db import Store
from . import events
from .paths import case_results_root
from .store import ACTIVE_STATUSES, ConsoleStore
```

sustituye la función `overview` completa:

```python
def overview(store: Store, cstore: ConsoleStore) -> Dict[str, Any]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    risk = {r: sum(row["open_by_risk"].get(r, 0) for row in rows) for r in RISKS}
    return {"kpis": {"cases_total": len(rows), "cases_active": sum(1 for r in rows if r["status"] == "open"),
                     "audits_sealed": sum(r["sealed_count"] for r in rows), "open_by_risk": risk,
                     "open_total": sum(risk.values()), "jobs_active": 0},
            "recent_cases": _recent_first(rows)[:8], "recent_events": cstore.recent_events(15)}
```

por:

```python
def overview(store: Store, cstore: ConsoleStore) -> Dict[str, Any]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    risk = {r: sum(row["open_by_risk"].get(r, 0) for row in rows) for r in RISKS}
    active = [job_row(store, j) for j in cstore.list_jobs(statuses=ACTIVE_STATUSES)]
    return {"kpis": {"cases_total": len(rows), "cases_active": sum(1 for r in rows if r["status"] == "open"),
                     "audits_sealed": sum(r["sealed_count"] for r in rows), "open_by_risk": risk,
                     "open_total": sum(risk.values()), "jobs_active": len(active),
                     "jobs_running": sum(1 for j in active if j["status"] == "running")},
            "recent_cases": _recent_first(rows)[:8], "recent_events": cstore.recent_events(15),
            "active_jobs": active}
```

y añade al final del archivo:

```python
def _seconds(start: Optional[str], end: Optional[str]) -> Optional[int]:
    """Seconds between two ISO-8601 UTC stamps (until now when ``end`` is empty)."""
    if not start:
        return None
    try:
        begin = datetime.fromisoformat(start.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
    except ValueError:
        return None
    return max(0, int((finish - begin).total_seconds()))


def job_row(store: Store, job: Dict[str, Any]) -> Dict[str, Any]:
    """A job as the tables and Home's "En curso" list show it."""
    case = store.get_case(job["case_id"]) if job.get("case_id") else {}
    phase = job.get("phase") or ""
    return {"id": job["id"], "command": job["command"], "status": job["status"],
            "active": job["status"] in ACTIVE_STATUSES, "folder": job["folder"],
            "folder_name": Path(job["folder"]).name, "case_id": job.get("case_id"), "case_name": case.get("name"),
            "phase": phase or None, "phase_label": events.PHASE_LABEL.get(phase), "launched_by": job["launched_by"],
            "created_at": job["created_at"], "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "duration_s": _seconds(job.get("started_at"), job.get("finished_at"))}


def progress(store: Store, case_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The "Hasta ahora" counters, read from the case DB; None until the case exists."""
    if not case_id or not store.get_case(case_id):
        return None
    findings = store.list_findings(case_id)
    return {"evidence": store.evidence_stats(case_id).get("total", 0), "findings": count_by(findings, "kind"),
            "findings_total": len(findings), "criteria": len(store.list_criteria(case_id)),
            "research_notes": len(store.list_research_notes(case_id))}


def job_view(store: Store, cstore: ConsoleStore, job: Dict[str, Any], *, profile_args: Sequence[str],
             dashboard_url: str) -> Dict[str, Any]:
    """Everything the Ejecución view shows; ``resume`` appears once the agent reported its session."""
    session = job.get("session_id") or ""
    audits = store.list_audits(job["case_id"]) if job.get("case_id") else []
    resume = None
    if session:
        resume = {"terminal": " ".join(["hermes", *profile_args, "--resume", session]),
                  "chat_url": f"{dashboard_url}/chat?resume={quote(session)}" if dashboard_url else None}
    return {**job_row(store, job), "args": job.get("args") or {}, "argv": job.get("argv") or [],
            "context_file": job.get("context_file"), "session_id": session or None, "exit_code": job.get("exit_code"),
            "result_text": job.get("result_text"), "tokens": job.get("tokens") or {}, "error": job.get("error"),
            "phases": [{"id": key, "label": text} for key, text in events.PHASES], "resume": resume,
            "progress": progress(store, job.get("case_id")),
            "last_audit": audit_view(store, cstore, audits[-1]) if audits else None}
```

- [ ] **Step 7: Crear `console/routers/fs.py`**

```python
"""Folder browser endpoints (viewer): configured case roots, listing, search and pre-launch inspection, all jailed
to ``case_roots`` by ``fsjail``."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query

from .. import fsjail
from ..auth import Principal
from ..commands import MISSING_ROOTS_MESSAGE, NO_ROOTS_MESSAGE
from ..deps import ApiError, ConsoleContext, get_ctx, require
from ..store import ACTIVE_STATUSES

router = APIRouter(tags=["fs"])
_HTTP_STATUS = {"outside_roots": 403}


def _hint(ctx: ConsoleContext) -> str:
    return NO_ROOTS_MESSAGE if not ctx.settings.case_roots else MISSING_ROOTS_MESSAGE


def _roots(ctx: ConsoleContext) -> List:
    roots = ctx.jobs.roots()
    if not roots:
        raise ApiError(409, "no_case_roots", _hint(ctx))
    return roots


def _jailed(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except fsjail.FsJailError as exc:
        raise ApiError(_HTTP_STATUS.get(exc.code, 422), exc.code, exc.message) from exc


@router.get("/fs/roots")
def roots(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    found = ctx.jobs.roots()
    return {"items": fsjail.roots_view(found), "configured": bool(ctx.settings.case_roots),
            "hint": None if found else _hint(ctx)}


@router.get("/fs/list")
def list_folder(path: str = Query(..., min_length=1, max_length=4096), _: Principal = Depends(require("viewer")),
                ctx: ConsoleContext = Depends(get_ctx)):
    return _jailed(fsjail.list_dir, path, _roots(ctx), store=ctx.store, audits_dirname=ctx.jobs.audits_dirname())


@router.get("/fs/search")
def search(q: str = Query(..., max_length=200), _: Principal = Depends(require("viewer")),
           ctx: ConsoleContext = Depends(get_ctx)):
    return _jailed(fsjail.search, q, _roots(ctx), skip=(ctx.jobs.audits_dirname(),))


@router.get("/fs/inspect")
def inspect(path: str = Query(..., min_length=1, max_length=4096), _: Principal = Depends(require("viewer")),
            ctx: ConsoleContext = Depends(get_ctx)):
    return _jailed(fsjail.inspect, path, _roots(ctx), store=ctx.store, audits_dirname=ctx.jobs.audits_dirname(),
                   defaults=ctx.jobs.defaults(), active_jobs=ctx.cstore.list_jobs(statuses=ACTIVE_STATUSES))
```

- [ ] **Step 8: Crear `console/routers/jobs.py`**

```python
"""Job endpoints: preview, launch and cancel (admin); list, detail, events as JSON or SSE, and log (viewer)."""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import commands, jobfiles, procs, readmodel
from ..auth import Principal
from ..commands import CommandError, LaunchRequest
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..store import ACTIVE_STATUSES, JOB_STATUSES, TERMINAL_STATUSES
from .cases import get_case_or_404

router = APIRouter(tags=["jobs"])
HEARTBEAT_S = 15.0
_STATUS_KEYS = ("status", "phase", "session_id", "case_id")


class LaunchBody(BaseModel):
    command: Literal["new-open-case", "rerun-case", "review-case"]
    folder: str = Field(min_length=1, max_length=4096)
    name: str = Field("", max_length=1000)
    currency: str = Field("", max_length=16)
    lang: str = Field("", max_length=16)
    out: str = Field("", max_length=4096)
    notes: str = Field("", max_length=100_000)  # commands.plan enforces MAX_NOTES with a clear message

    def to_request(self) -> LaunchRequest:
        return LaunchRequest(**self.model_dump())


def _api_error(exc: CommandError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message)


def _job_or_404(ctx: ConsoleContext, job_id: int) -> dict:
    job = ctx.cstore.get_job(job_id)
    if not job:
        raise ApiError(404, "not_found", f"ejecución no encontrada: {job_id}")
    return job


def _view(ctx: ConsoleContext, job: dict) -> dict:
    view = readmodel.job_view(ctx.store, ctx.cstore, job, profile_args=procs.profile_args(),
                              dashboard_url=ctx.settings.dashboard_url)
    view["display"] = commands.display_command(view["argv"]) if view["argv"] else ""
    return view


@router.post("/jobs/preview")
def preview(body: LaunchBody, principal: Principal = Depends(require("admin")),
            ctx: ConsoleContext = Depends(get_ctx)):
    try:
        return ctx.jobs.preview(body.to_request(), principal.username)
    except CommandError as exc:
        raise _api_error(exc) from exc


@router.post("/jobs", status_code=202)
def launch(body: LaunchBody, request: Request, principal: Principal = Depends(require("admin")),
           ctx: ConsoleContext = Depends(get_ctx)):
    try:
        job = ctx.jobs.launch(body.to_request(), principal, ip=client_ip(request))
    except CommandError as exc:
        raise _api_error(exc) from exc
    return {"job": _view(ctx, job)}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, request: Request, principal: Principal = Depends(require("admin")),
           ctx: ConsoleContext = Depends(get_ctx)):
    try:
        job = ctx.jobs.cancel(job_id, principal, ip=client_ip(request))
    except CommandError as exc:
        raise _api_error(exc) from exc
    return {"job": _view(ctx, job)}


@router.get("/jobs")
def list_jobs(status: str = "", case: str = "", limit: int = Query(100, ge=1, le=500),
              _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    if status and status != "active" and status not in JOB_STATUSES:
        raise ApiError(422, "invalid_argument", f"estado desconocido: {status}")
    statuses = ACTIVE_STATUSES if status == "active" else ((status,) if status else ())
    folder = get_case_or_404(ctx, case)["root_path"] if case else ""
    rows = ctx.cstore.list_jobs(statuses=statuses, case_id=case, folder=folder, limit=limit)
    return {"items": [readmodel.job_row(ctx.store, j) for j in rows], "next_cursor": None}


@router.get("/cases/{case_id}/jobs")
def case_jobs(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    case = get_case_or_404(ctx, case_id)
    rows = ctx.cstore.list_jobs(case_id=case_id, folder=case["root_path"])
    return {"items": [readmodel.job_row(ctx.store, j) for j in rows]}


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return _view(ctx, _job_or_404(ctx, job_id))


@router.get("/jobs/{job_id}/events")
def job_events(job_id: int, after: int = Query(0, ge=0), _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    _job_or_404(ctx, job_id)
    items, _offset = jobfiles.read_events(jobfiles.events_path(ctx.jobs.jobs_dir, job_id), after=after)
    return {"items": items, "last_seq": items[-1]["seq"] if items else after}


@router.get("/jobs/{job_id}/events/stream")
async def job_stream(job_id: int, request: Request, after: int = Query(0, ge=0),
                     _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """SSE: ``event`` frames whose id is the event's seq (a reconnect resumes after Last-Event-ID), a ``status``
    frame whenever status/phase/session/case change, ``end`` once the job is over and its events are drained, and a
    comment as heartbeat. The events file is polled every ``stream_poll`` seconds (1 s by default)."""
    _job_or_404(ctx, job_id)
    last = request.headers.get("last-event-id", "")
    start = max(after, int(last)) if last.isdigit() else after
    path = jobfiles.events_path(ctx.jobs.jobs_dir, job_id)
    poll = ctx.jobs.stream_poll

    async def frames():
        seq, offset, sent, idle = start, 0, None, 0.0
        while not await request.is_disconnected():
            items, offset = jobfiles.read_events(path, after=seq, offset=offset)
            for event in items:
                seq = event["seq"]
                yield f"id: {seq}\nevent: event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            job = ctx.cstore.get_job(job_id)
            state = {key: job.get(key) for key in _STATUS_KEYS}
            if state != sent:
                sent = state
                yield f"event: status\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
            if job["status"] in TERMINAL_STATUSES and not items:
                yield f"event: end\ndata: {json.dumps({'status': job['status']})}\n\n"
                return
            idle = 0.0 if items else idle + poll
            if idle >= HEARTBEAT_S:
                idle = 0.0
                yield ": keepalive\n\n"
            await asyncio.sleep(poll)

    return StreamingResponse(frames(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.get("/jobs/{job_id}/log")
def job_log(job_id: int, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    _job_or_404(ctx, job_id)
    base = ctx.jobs.jobs_dir
    return {"log": jobfiles.tail(jobfiles.log_path(base, job_id)),
            "runner_log": jobfiles.tail(jobfiles.runner_log_path(base, job_id), lines=50)}
```

- [ ] **Step 9: Reemplazar `console/routers/system.py`**

```python
"""System endpoints: control-panel overview, environment doctor and the console audit log."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from .. import CONSOLE_VERSION, readmodel
from ..auth import Principal
from ..commands import NO_ROOTS_MESSAGE
from ..deps import ConsoleContext, get_ctx, require
from ..settings import ConsoleSettings

router = APIRouter(tags=["system"])


def _approvals_mode() -> str:
    try:
        from hermes_cli.config import cfg_get, load_config_readonly
        return str(cfg_get(load_config_readonly(), "approvals", "single_query_mode", default="deny"))
    except Exception:  # standalone (outside Hermes): Hermes' documented default
        return "deny"


def _case_root_checks(settings: ConsoleSettings) -> List[Dict[str, Any]]:
    """One check per configured case root (exists, free space); no root configured is itself a failed check."""
    if not settings.case_roots:
        return [{"check": "console.case_roots", "ok": False, "detail": NO_ROOTS_MESSAGE}]
    checks = []
    for raw in settings.case_roots:
        path = Path(raw).expanduser()
        try:
            free = shutil.disk_usage(path).free if path.is_dir() else None
        except OSError:
            free = None
        checks.append({"check": f"console.case_roots: {raw}", "ok": free is not None,
                       "detail": f"{free / 1024 ** 3:.1f} GB libres" if free is not None
                       else "la carpeta no existe o no se puede leer"})
    return checks


@router.get("/system/overview")
def overview(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return readmodel.overview(ctx.store, ctx.cstore)


@router.get("/system/doctor")
def doctor(_: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    from ...commands import doctor_report
    report = doctor_report()
    mode = _approvals_mode()
    outcome = "aprobados automáticamente" if mode == "approve" else "bloqueados"
    roots = _case_root_checks(ctx.settings)
    checks = report["checks"] + [{"check": "approvals.single_query_mode", "ok": True,
                                  "detail": f"{mode}: comandos peligrosos en ejecuciones desatendidas {outcome}"}]
    return {"ok": report["ok"] and all(c["ok"] for c in roots), "checks": checks + roots,
            "settings": report["settings"],
            "console": {"version": CONSOLE_VERSION, "host": ctx.settings.host, "port": ctx.settings.port,
                        "case_roots": list(ctx.settings.case_roots), "max_parallel_jobs": ctx.settings.max_parallel_jobs,
                        "dashboard_url": ctx.settings.dashboard_url or None}}


@router.get("/system/audit-log")
def audit_log(limit: int = Query(200, ge=1, le=1000), _: Principal = Depends(require("admin")),
              ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": ctx.cstore.list_audit_log(limit)}
```

- [ ] **Step 10: Reemplazar `ghost-recon/demo/console_demo.py`**

```python
#!/usr/bin/env python3
"""Ghost Recon console demo: seeds an isolated DB and case root and starts the console (no LLM, no Hermes keys).

    python ghost-recon/demo/console_demo.py [--port 9230]

Copies demo/demo-case twice into a temporary case root (``case_roots``): "Acme Importaciones" gets a sealed A01 (md
pack, findings, a criterion) and an open A02; "Logística Norte" stays unaudited for the "+ Nueva auditoría" wizard.
Creates the admin ``demo`` / ``demo-pass-123`` and the viewer ``visor`` / ``visor-pass-123`` and serves the console on
http://localhost:<port>. Jobs launched from the UI run the real job runner with ``fake_agent.py`` instead of Hermes:
they emit the real stream-json shapes, take about ten seconds and succeed. Use it to try the UI and for H4 acceptance
rehearsals.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
DEMO = REPO / "ghost-recon" / "demo" / "demo-case"
FAKE_AGENT = REPO / "ghost-recon" / "demo" / "fake_agent.py"


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
    from plugins.ghost_recon.console.jobs import JobService
    from plugins.ghost_recon.console.procs import RUNNER_MODULE
    from plugins.ghost_recon.console.settings import ConsoleSettings
    from plugins.ghost_recon.console.store import ConsoleStore
    from plugins.ghost_recon.core import casefolder as cf, service
    from plugins.ghost_recon.core.reports import pack

    case_root = tmp / "Casos"
    case_dir = case_root / "Acme Importaciones"
    shutil.copytree(DEMO, case_dir)
    shutil.copytree(DEMO, case_root / "Logística Norte")
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

    settings = ConsoleSettings(port=args.port, case_roots=(str(case_root),))
    cstore = ConsoleStore.open_default()
    auth = AuthService(cstore, settings)
    auth.add_user("demo", "demo-pass-123", "admin")
    auth.add_user("visor", "visor-pass-123", "viewer")
    config = tmp / "fake_agent.json"
    config.write_text(json.dumps({"default": {"steps": 20, "delay": 0.5}}), encoding="utf-8")
    jobs = JobService(cstore, store, settings,
                      hermes_command=lambda a: [sys.executable, str(FAKE_AGENT), "--fake-config", str(config), *a],
                      runner_command=lambda job_id: [sys.executable, "-m", RUNNER_MODULE, str(job_id)])
    print(f"Consola demo en http://localhost:{args.port}\n  admin:  demo / demo-pass-123\n"
          f"  viewer: visor / visor-pass-123\n  casos:  {case_root}\n"
          "  las ejecuciones usan un agente simulado (sin LLM)", flush=True)
    uvicorn.run(create_app(settings, store, cstore, auth=auth, jobs=jobs), host="127.0.0.1", port=args.port,
                log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed` (las de H1 incluidas: la app por defecto de las pruebas ya lleva su `JobService`).

- [ ] **Step 12: Smoke de la demo**

Run: `.venv/Scripts/python.exe ghost-recon/demo/console_demo.py --port 9231` en Windows (o `.venv/bin/python …`). En otra terminal:

```bash
curl -s -c "$TMPDIR/gr.txt" -H "Content-Type: application/json" -d '{"username":"demo","password":"demo-pass-123"}' http://localhost:9231/api/v1/auth/login
curl -s -b "$TMPDIR/gr.txt" http://localhost:9231/api/v1/fs/roots
```

Expected: el login devuelve `{"user": {"username": "demo", ...}, "csrf": ...}` y `fs/roots` lista la carpeta `Casos` temporal. Detén la demo con Ctrl+C.

- [ ] **Step 13: Commit**

```bash
git add plugins/ghost_recon/console/deps.py plugins/ghost_recon/console/app.py plugins/ghost_recon/console/readmodel.py plugins/ghost_recon/console/routers/fs.py plugins/ghost_recon/console/routers/jobs.py plugins/ghost_recon/console/routers/system.py ghost-recon/demo/console_demo.py tests/plugins/ghost_recon/console/conftest.py tests/plugins/ghost_recon/console/test_api_fs.py tests/plugins/ghost_recon/console/test_api_jobs.py
git commit -m "feat(ghost-recon): console folder and job API with live SSE events and active jobs on Home

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: E2E de aceptación con un servidor real

**Files:**
- Create: `tests/plugins/ghost_recon/console/serve_fake.py` (script auxiliar; no es una prueba)
- Test: `tests/plugins/ghost_recon/console/test_jobs_e2e.py`

**Interfaces:**
- Consumes: `create_app(..., jobs=)` y `JobService` (Tareas 6 y 7), `procs.RUNNER_MODULE`, `procs.alive`, `procs.kill_tree`, `procs.hermes_root`, `ghost-recon/demo/fake_agent.py`; fixtures `case_root`, `users`, `cstore`, `wait_until`.
- Produces: el criterio de aceptación de H2 (spec §13) como prueba: lanzar → seguir en vivo → reiniciar el servidor sin perder el job → cancelar → detectar huérfano, contra procesos reales (servidor uvicorn, runner y agente falso).
- `serve_fake.py --port N --case-root DIR --fake-config CFG [--tick S] [--poll S]`: el mismo `create_app` que `serve`, con `case_roots` y el agente falso. Existe porque el `serve` standalone solo lee su configuración del `config.yaml` de Hermes y la consola no admite variables de entorno nuevas para configuración.

- [ ] **Step 1: Crear el servidor auxiliar**

`tests/plugins/ghost_recon/console/serve_fake.py`:

```python
"""Test helper (not a test): a real console server process wired to the fake agent, for the H2 acceptance E2E.

    python tests/plugins/ghost_recon/console/serve_fake.py --port N --case-root DIR --fake-config CFG [--tick S]

Standalone ``ghostrecon serve`` reads its settings only from Hermes' config.yaml (and the console takes no new env vars
for settings), so this builds the same app — ``create_app`` + ``JobService`` + uvicorn — with a case root and the fake
agent. The DB comes from GHOSTRECON_DB, as for every standalone run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
FAKE_AGENT = REPO / "ghost-recon" / "demo" / "fake_agent.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--case-root", required=True)
    parser.add_argument("--fake-config", required=True)
    parser.add_argument("--tick", type=float, default=0.5)
    parser.add_argument("--poll", type=float, default=0.1)
    args = parser.parse_args()

    import uvicorn
    from plugins.ghost_recon import runtime
    from plugins.ghost_recon.console.app import create_app
    from plugins.ghost_recon.console.jobs import JobService
    from plugins.ghost_recon.console.procs import RUNNER_MODULE
    from plugins.ghost_recon.console.settings import ConsoleSettings
    from plugins.ghost_recon.console.store import ConsoleStore

    settings = ConsoleSettings(port=args.port, case_roots=(args.case_root,))
    cstore = ConsoleStore.open_default()
    store = runtime.store()
    jobs = JobService(
        cstore, store, settings,
        hermes_command=lambda a: [sys.executable, str(FAKE_AGENT), "--fake-config", args.fake_config, *a],
        runner_command=lambda job_id: [sys.executable, "-m", RUNNER_MODULE, str(job_id), "--poll", str(args.poll)],
        tick_seconds=args.tick)
    uvicorn.run(create_app(settings, store, cstore, jobs=jobs), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Escribir la prueba E2E**

`tests/plugins/ghost_recon/console/test_jobs_e2e.py`:

```python
"""Acceptance of H2 (spec §13): a real console server process drives the real job runner and the fake agent —
launch, follow live, restart the server without losing the job, cancel, and detect an orphan."""
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import httpx
import psutil
import pytest

from plugins.ghost_recon.console import procs
from plugins.ghost_recon.console.store import TERMINAL_STATUSES

SERVE = Path(__file__).resolve().parent / "serve_fake.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Console:
    """One real server process (serve_fake.py) on its own port, over the test DB."""

    def __init__(self, workdir: Path, case_root: Path, config: Path, tick: float):
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.log_path = workdir / f"server-{self.port}.log"
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVE), "--port", str(self.port), "--case-root", str(case_root),
             "--fake-config", str(config), "--tick", str(tick)],
            cwd=procs.hermes_root(), env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while True:
            try:
                httpx.get(self.base + "/api/v1/auth/me", timeout=2)
                return
            except httpx.TransportError:
                assert self.proc.poll() is None, self.log_path.read_text(encoding="utf-8", errors="replace")
                assert time.monotonic() < deadline, "the console did not start within 60 s"
                time.sleep(0.2)

    @contextlib.contextmanager
    def client(self) -> Iterator[httpx.Client]:
        with httpx.Client(base_url=self.base, timeout=20) as c:
            r = c.post("/api/v1/auth/login", json={"username": "jean", "password": "admin-pass-123"})
            assert r.status_code == 200, r.text
            c.headers["X-GR-CSRF"] = r.json()["csrf"]
            yield c

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=30)
        self._log.close()


@pytest.fixture
def consoles(tmp_path, case_root, users, cstore):
    """Factory: start a real console with a fake-agent config; stops servers and leftover job trees at the end."""
    started = []

    def _start(config: dict, tick: float = 0.5) -> Console:
        path = tmp_path / f"fake-config-{len(started)}.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        console = Console(tmp_path, case_root, path, tick)
        started.append(console)
        return console

    yield _start
    for console in started:
        console.stop()
    for job in cstore.list_jobs():
        procs.kill_tree(job["runner_pid"], job["runner_started"])
        procs.kill_tree(job["pid"], job["pid_started"])


def _folder(case_root, name):
    folder = case_root / name
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder


def _finished(client, job_id):
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    return job if job["status"] in TERMINAL_STATUSES else None


def _with_agent(cstore, job_id):
    row = cstore.get_job(job_id)
    return row if row["pid"] else None


def test_a_job_survives_a_server_restart_and_finishes(consoles, case_root, cstore, wait_until):
    config = {"default": {"steps": 25, "delay": 0.2}}
    first = consoles(config)
    with first.client() as c:
        job = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                           "folder": str(_folder(case_root, "Caso E2E"))}).json()["job"]
        wait_until(lambda: len(c.get(f"/api/v1/jobs/{job['id']}/events").json()["items"]) >= 3,
                   message="live events")
    row = cstore.get_job(job["id"])
    first.stop()
    assert procs.alive(row["runner_pid"], row["runner_started"]), "stopping the server must not stop the runner"
    second = consoles(config)
    with second.client() as c:
        assert c.get(f"/api/v1/jobs/{job['id']}").json()["status"] != "orphaned"
        done = wait_until(lambda: _finished(c, job["id"]), timeout=120, message="job end")
        assert done["status"] == "succeeded" and done["case_id"] and done["progress"]["evidence"] >= 1
        events = c.get(f"/api/v1/jobs/{job['id']}/events").json()["items"]
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1)) and events[-1]["kind"] == "result"
        assert job["id"] in [j["id"] for j in c.get(f"/api/v1/cases/{done['case_id']}/jobs").json()["items"]]


def test_cancel_and_orphan_detection_through_a_real_server(consoles, case_root, cstore, wait_until):
    console = consoles({"default": {"hang": True}})
    with console.client() as c:
        doomed = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                              "folder": str(_folder(case_root, "Caso Cancelar"))}).json()["job"]
        row = wait_until(lambda: _with_agent(cstore, doomed["id"]), message="agent started")
        r = c.post(f"/api/v1/jobs/{doomed['id']}/cancel")
        assert r.status_code == 200 and r.json()["job"]["status"] == "cancelled"
        wait_until(lambda: not procs.alive(row["pid"], row["pid_started"]), message="cancelled agent gone")

        lost = c.post("/api/v1/jobs", json={"command": "new-open-case",
                                            "folder": str(_folder(case_root, "Caso Huérfano"))}).json()["job"]
        row = wait_until(lambda: _with_agent(cstore, lost["id"]), message="agent started")
        psutil.Process(row["runner_pid"]).kill()  # the runner dies without writing its final state
        orphan = wait_until(lambda: _finished(c, lost["id"]), timeout=60, message="orphan verdict")
        assert orphan["status"] == "orphaned" and orphan["error"]
        wait_until(lambda: not procs.alive(row["pid"], row["pid_started"]), message="orphaned agent stopped")
        assert "runner_log" in c.get(f"/api/v1/jobs/{lost['id']}/log").json()
```

- [ ] **Step 3: Ejecutar la prueba**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_jobs_e2e.py -q`
Expected: `2 passed` (cada prueba arranca uno o dos servidores reales; tarda unos 30–60 s).

Si falla el arranque del servidor, el mensaje de la aserción incluye el log del servidor (`server-<puerto>.log`).

- [ ] **Step 4: Suite de la consola completa**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add tests/plugins/ghost_recon/console/serve_fake.py tests/plugins/ghost_recon/console/test_jobs_e2e.py
git commit -m "test(ghost-recon): console jobs acceptance E2E against a real server process

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: API de usuarios y tokens (admin)

**Files:**
- Modify: `plugins/ghost_recon/console/auth.py` (errores de cuenta con estado HTTP, `set_role`, actor en los registros de tokens)
- Create: `plugins/ghost_recon/console/routers/users.py`
- Modify: `plugins/ghost_recon/console/app.py` (`ROUTERS`)
- Modify: `tests/plugins/ghost_recon/console/test_auth.py` (último admin y cambio de rol)
- Test: `tests/plugins/ghost_recon/console/test_api_users.py`

**Interfaces:**
- Consumes: `AuthService.add_user/set_password/set_disabled/create_api_token/revoke_api_token`, `ConsoleStore.list_users/list_tokens/update_user/count_active_admins/log` (H1); `require`, `client_ip`, `ApiError`.
- Produces:
  - `auth.py`: `class AccountError(ValueError)` (`status = 422`, `code = "invalid_argument"`), `UnknownUser(AccountError)` (`404 not_found`), `AccountConflict(AccountError)` (`409 conflict`); siguen siendo `ValueError`, así que el CLI de H1 (que captura `ValueError`) no cambia. `AuthService.set_role(username, role) -> None` (no degrada al último admin activo). `create_api_token(username, name, *, actor=None, ip="")` y `revoke_api_token(token_id, *, actor=None, ip="")`: con `actor`, el registro lleva al admin que actúa (y `detail.user`, el dueño del token).
  - Rutas admin (`/api/v1`): `GET /users`, `POST /users` → 201 (`{username, role, password, password_confirm}`), `POST /users/{u}/password` (`{password, password_confirm}`; cierra sus sesiones), `POST /users/{u}/disable`, `POST /users/{u}/enable`, `POST /users/{u}/role` (`{role}`), `GET /tokens`, `POST /tokens` → 201 (`{username, name}` → `{token, id, prefix, name, username}`; el token en claro solo aparece aquí), `POST /tokens/{id}/revoke`.
  - Códigos: `422 password_mismatch | invalid_argument`, `404 not_found`, `409 conflict | self_action` (un admin no puede deshabilitarse ni cambiarse el rol a sí mismo).
  - Registro (`console_audit_log`, con el admin como `username` y `detail.via = "console"`): `user_add`, `user_passwd`, `user_disable`, `user_enable`, `user_role`, `token_create`, `token_revoke`.

- [ ] **Step 1: Escribir las pruebas que fallan**

En `tests/plugins/ghost_recon/console/test_auth.py`, sustituye:

```python
from plugins.ghost_recon.console.auth import AuthError, AuthService, LoginLocked, hash_password, verify_password
```

por:

```python
from plugins.ghost_recon.console.auth import (AccountConflict, AuthError, AuthService, LoginLocked, hash_password,
                                              verify_password)
```

y añade al final del archivo:

```python
def test_the_last_active_admin_keeps_the_role_and_stays_enabled(svc):
    with pytest.raises(AccountConflict):
        svc.set_role("jean", "viewer")
    with pytest.raises(AccountConflict):
        svc.set_disabled("jean", True)
    svc.add_user("ana", "admin-pass-456", "admin")
    svc.set_role("jean", "viewer")
    assert svc.cstore.get_user("jean")["role"] == "viewer"
```

`tests/plugins/ghost_recon/console/test_api_users.py`:

```python
"""Users and API tokens from Sistema (admin only): the CLI's rules, sessions closed on reset or disable, the raw token
shown once, no self-lockout, and every change in the console audit log with the acting admin."""
from fastapi.testclient import TestClient

from plugins.ghost_recon.console.auth import MIN_PASSWORD


def test_user_and_token_administration_is_admin_only(login_as):
    viewer = login_as("viewer")
    calls = [("GET", "/api/v1/users", None), ("GET", "/api/v1/tokens", None),
             ("POST", "/api/v1/users", {"username": "ana", "role": "viewer", "password": "clave-larga-123",
                                         "password_confirm": "clave-larga-123"}),
             ("POST", "/api/v1/users/jean/disable", None), ("POST", "/api/v1/tokens", {"username": "vera", "name": "x"}),
             ("POST", "/api/v1/tokens/1/revoke", None)]
    for method, url, body in calls:
        r = viewer.request(method, url, json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", url


def test_an_admin_creates_users_with_the_cli_rules(login_as, cstore):
    admin = login_as("admin")
    base = {"username": "ana", "role": "admin", "password": "clave-larga-123"}
    mismatch = admin.post("/api/v1/users", json={**base, "password_confirm": "otra-clave-123"})
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "password_mismatch"
    short = admin.post("/api/v1/users", json={**base, "password": "corta", "password_confirm": "corta"})
    assert short.status_code == 422 and str(MIN_PASSWORD) in short.json()["error"]["message"]
    assert admin.post("/api/v1/users", json={**base, "password_confirm": base["password"]}).status_code == 201
    duplicate = admin.post("/api/v1/users", json={**base, "password_confirm": base["password"]})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "conflict"
    assert "ana" in [u["username"] for u in admin.get("/api/v1/users").json()["items"]]
    entry = next(e for e in cstore.list_audit_log() if e["action"] == "user_add")
    assert (entry["username"], entry["target"], entry["detail"]["role"]) == ("jean", "ana", "admin")


def test_a_password_reset_closes_the_users_sessions(login_as):
    admin, vera = login_as("admin"), login_as("viewer")
    body = {"password": "nueva-clave-123", "password_confirm": "nueva-clave-123"}
    assert admin.post("/api/v1/users/vera/password", json=body).status_code == 200
    assert vera.get("/api/v1/auth/me").status_code == 401
    assert vera.post("/api/v1/auth/login", json={"username": "vera", "password": "nueva-clave-123"}).status_code == 200


def test_disable_enable_and_role_changes_take_effect_and_are_logged(login_as, cstore):
    admin, vera = login_as("admin"), login_as("viewer")
    assert admin.post("/api/v1/users/vera/disable").status_code == 200
    assert vera.get("/api/v1/auth/me").status_code == 401
    assert admin.post("/api/v1/users/vera/enable").status_code == 200
    assert admin.post("/api/v1/users/vera/role", json={"role": "admin"}).status_code == 200
    assert login_as("viewer").get("/api/v1/auth/me").json()["user"]["role"] == "admin"  # vera, now admin
    actions = {e["action"] for e in cstore.list_audit_log() if e["username"] == "jean"}
    assert {"user_disable", "user_enable", "user_role"} <= actions


def test_an_admin_cannot_disable_or_demote_themself(login_as):
    admin = login_as("admin")
    for url, body in (("/api/v1/users/jean/disable", None), ("/api/v1/users/jean/role", {"role": "viewer"})):
        r = admin.post(url, json=body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "self_action", url


def test_a_token_is_shown_once_works_as_bearer_and_can_be_revoked(login_as, app, cstore):
    admin = login_as("admin")
    created = admin.post("/api/v1/tokens", json={"username": "vera", "name": "web-app"})
    assert created.status_code == 201
    raw, token_id = created.json()["token"], created.json()["id"]
    assert raw not in admin.get("/api/v1/tokens").text
    with TestClient(app, base_url="http://localhost") as api:
        bearer = {"Authorization": f"Bearer {raw}"}
        assert api.get("/api/v1/auth/me", headers=bearer).json()["user"]["username"] == "vera"
        assert admin.post(f"/api/v1/tokens/{token_id}/revoke").status_code == 200
        assert api.get("/api/v1/auth/me", headers=bearer).status_code == 401
    assert admin.post(f"/api/v1/tokens/{token_id}/revoke").status_code == 404
    log = cstore.list_audit_log()
    assert any(e["action"] == "token_create" and e["username"] == "jean" and e["detail"]["user"] == "vera" for e in log)
    assert any(e["action"] == "token_revoke" and e["username"] == "jean" for e in log)


def test_unknown_users_are_404(login_as):
    body = {"password": "clave-larga-123", "password_confirm": "clave-larga-123"}
    r = login_as("admin").post("/api/v1/users/nadie/password", json=body)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_api_users.py tests/plugins/ghost_recon/console/test_auth.py -q`
Expected: FAIL con `ImportError: cannot import name 'AccountConflict'` y 404 en `/api/v1/users`.

- [ ] **Step 3: Errores de cuenta en `console/auth.py`**

Sustituye:

```python
def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"la contraseña debe tener al menos {MIN_PASSWORD} caracteres")
```

por:

```python
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
```

- [ ] **Step 4: Reglas de cuentas y `set_role`**

En `console/auth.py`, sustituye el bloque completo:

```python
    def add_user(self, username: str, password: str, role: str) -> Dict:
        username = (username or "").strip().lower()
        if not USERNAME_RE.match(username):
            raise ValueError("usuario: 2-32 caracteres en minúscula (a-z, 0-9, punto, guion o guion bajo)")
        if role not in ROLES:
            raise ValueError(f"rol debe ser uno de {ROLES}")
        _check_password(password)
        return self.cstore.create_user(username, hash_password(password), role)
```

por:

```python
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
```

sustituye:

```python
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
```

por:

```python
    def set_disabled(self, username: str, disabled: bool) -> None:
        user = self._require_user(username)
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
```

- [ ] **Step 5: Actor en los registros de tokens**

En `console/auth.py`, sustituye:

```python
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
```

por:

```python
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
```

y sustituye:

```python
    def revoke_api_token(self, token_id: int) -> bool:
        revoked = self.cstore.revoke_token(token_id)
        if revoked:
            self.cstore.log("token_revoke", target=str(token_id))
        return revoked
```

por:

```python
    def revoke_api_token(self, token_id: int, *, actor: Optional[Principal] = None, ip: str = "") -> bool:
        revoked = self.cstore.revoke_token(token_id)
        if revoked:
            self.cstore.log("token_revoke", user_id=actor.user_id if actor else None,
                            username=actor.username if actor else None, ip=ip or None, target=str(token_id))
        return revoked
```

- [ ] **Step 6: Crear `console/routers/users.py`**

```python
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
```

- [ ] **Step 7: Montar el router en `console/app.py`**

Sustituye:

```python
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, fs as fs_routes,
                      jobs as jobs_routes, system as system_routes)
```

por:

```python
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, fs as fs_routes,
                      jobs as jobs_routes, system as system_routes, users as users_routes)
```

y sustituye:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes)
```

por:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes)
```

- [ ] **Step 8: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`, incluidas `test_cli.py` (el CLI sigue igual: los errores de cuenta siguen siendo `ValueError`) y `test_api_users.py`.

- [ ] **Step 9: Commit**

```bash
git add plugins/ghost_recon/console/auth.py plugins/ghost_recon/console/routers/users.py plugins/ghost_recon/console/app.py tests/plugins/ghost_recon/console/test_auth.py tests/plugins/ghost_recon/console/test_api_users.py
git commit -m "feat(ghost-recon): console user and API token administration API

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend — Ejecuciones, Ejecución en vivo, Re-run/Review y barrido de textos

**Files:**
- Modify (reemplazar): `plugins/ghost_recon/console/static/app.js`
- Modify: `plugins/ghost_recon/console/static/lib/format.js` (añadir al final)
- Modify (reemplazar): `plugins/ghost_recon/console/static/views/components.js`
- Create: `plugins/ghost_recon/console/static/views/launch.js`
- Create: `plugins/ghost_recon/console/static/views/job.js`
- Create: `plugins/ghost_recon/console/static/views/jobs.js`
- Create: `plugins/ghost_recon/console/static/views/case/jobs.js`
- Modify (reemplazar): `plugins/ghost_recon/console/static/views/home.js`, `views/cases.js`, `views/case.js`
- Modify: `plugins/ghost_recon/console/static/app.css`

**Interfaces:**
- Consumes: la API de la Tarea 7 (`/fs/inspect`, `/jobs/preview`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/events`, `/jobs/{id}/events/stream`, `/jobs/{id}/log`, `/jobs/{id}/cancel`, `/cases/{id}/jobs`, `/system/overview`) y los helpers de H1 (`h`, `mount`, `api`, `fmtDate`, `chip`, `sealChip`, `sealCheckChip`, `riskChips`, `label`, `fmtBytes`, `shortHash`).
- Produces:
  - `lib/format.js`: `COMMAND_LABEL`, `JOB_STATUS_OPTIONS`, `jobChip(status)`, `fmtDuration(seconds)`, `secondsSince(iso)`.
  - `views/components.js`: `emptyState(text, ...actions)`, `dataTable` (acepta un nodo como `empty`), `newAuditAction(user)`, `casesTable(rows, user, {empty})`, `jobsTable(rows, {showCase, empty})`, `field(text, control, hint)`, `copyText(text)`, `copyButton(text, label)`, `modal(title, body, {wide}) -> {dialog, close}`; siguen `kpi`, `errorState`, `toggleDetail`, `debounce`.
  - `views/launch.js`: `launchPanel({command, folder, inspect, onLaunched})` y `openLaunchDialog({command, folder, title})`.
  - Vistas: `#/jobs` (lista), `#/jobs/<id>` (Ejecución), pestaña `#/cases/<id>/jobs`; cada `render(ctx)` recibe además `onLeave(fn)` para cerrar `EventSource` y temporizadores al navegar.
  - `app.js`: navegación sin entradas deshabilitadas, «+ Nueva auditoría» enlaza a `#/new` (la ruta llega en la Tarea 11), búsqueda deshabilitada con «Próximamente».
- Sin pruebas Python nuevas: la lógica vive en el servidor y está probada; aquí se verifica en el navegador (Step 13) y con la búsqueda de textos prohibidos (Step 12).

- [ ] **Step 1: Ayudas de formato**

Añade al final de `static/lib/format.js`:

```js
export const COMMAND_LABEL = { "new-open-case": "Nueva auditoría", "rerun-case": "Re-run", "review-case": "Review" };
const JOB_STATUS = {
  queued: ["en cola", "info"],
  running: ["en curso", "info"],
  succeeded: ["terminada", "ok"],
  failed: ["fallida", "risk-high"],
  cancelled: ["cancelada", "muted"],
  orphaned: ["interrumpida", "risk-medium"],
};
export const JOB_STATUS_OPTIONS = Object.entries(JOB_STATUS).map(([value, [text]]) => [value, text]);

export function jobChip(status) {
  const [text, variant] = JOB_STATUS[status] || [status, "muted"];
  return chip(text, variant, status === "orphaned" ? "El proceso de la ejecución se detuvo sin registrar su final." : undefined);
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return `${hours} h ${minutes} min`;
  return minutes ? `${minutes} min ${total % 60} s` : `${total % 60} s`;
}

export function secondsSince(iso) {
  const start = parse(iso || "");
  return start ? (Date.now() - start.getTime()) / 1000 : null;
}
```

- [ ] **Step 2: Reemplazar `static/views/components.js`**

```js
// Shared view pieces: KPI tiles, tables with expandable rows, empty/error states, the cases and jobs tables, form
// fields, dialogs and copy-to-clipboard.
import { h } from "../lib/dom.js";
import { COMMAND_LABEL, fmtDate, fmtDuration, jobChip, label, riskChips, sealChip } from "../lib/format.js";

export function kpi(value, title, extra) {
  return h("div", { class: "kpi" },
    h("div", { class: "kpi-value" }, value === null || value === undefined ? "—" : String(value)),
    h("div", { class: "kpi-title" }, title),
    extra ? h("div", { class: "kpi-extra" }, extra) : null);
}

/** Empty state: a sentence plus, optionally, the action that fills it (buttons or links; nulls are skipped). */
export function emptyState(text, ...actions) {
  const items = actions.flat().filter(Boolean);
  return h("div", { class: "empty" }, h("p", {}, text), items.length ? h("div", { class: "empty-actions" }, items) : null);
}

export function errorState(err) {
  return h("div", { class: "error", role: "alert" }, `No se pudo cargar: ${(err && err.message) || err}`);
}

/** columns: [{ title, cell(row) -> node|string|array, class? }]; opts: { empty (text or node), onRow(row, tr) }. */
export function dataTable(columns, rows, opts = {}) {
  if (!rows || !rows.length) return opts.empty instanceof Node ? opts.empty : emptyState(opts.empty || "Sin datos.");
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

/** The "+ Nueva auditoría" action for admins; null for viewers. */
export function newAuditAction(user) {
  return user && user.role === "admin" ? h("a", { class: "btn", href: "#/new" }, "+ Nueva auditoría") : null;
}

export function casesTable(rows, user, { empty } = {}) {
  return dataTable([
    { title: "Caso", cell: (r) => h("a", { href: `#/cases/${encodeURIComponent(r.id)}` }, r.name) },
    { title: "Última auditoría", cell: (r) => (r.last_audit
      ? `${r.last_audit.seq} · ${label.auditStatus(r.last_audit.status)} · ${fmtDate(r.last_audit.started_at)}` : "—") },
    { title: "Abiertos", cell: (r) => riskChips(r.open_by_risk) },
    { title: "Sello", cell: (r) => sealChip(r.seal_state) },
    { title: "Última actividad", cell: (r) => fmtDate(r.last_activity) },
  ], rows, { empty: empty || emptyState("Todavía no hay casos.", newAuditAction(user)) });
}

export function jobsTable(rows, { showCase = true, empty = "Sin ejecuciones." } = {}) {
  return dataTable([
    { title: "#", cell: (j) => h("a", { href: `#/jobs/${j.id}` }, `#${j.id}`) },
    { title: "Orden", cell: (j) => COMMAND_LABEL[j.command] || j.command },
    showCase ? { title: "Caso o carpeta", cell: (j) => (j.case_id
      ? h("a", { href: `#/cases/${encodeURIComponent(j.case_id)}` }, j.case_name || j.case_id) : j.folder_name) } : null,
    { title: "Estado", cell: (j) => jobChip(j.status) },
    { title: "Fase", cell: (j) => j.phase_label || "—" },
    { title: "Lanzada por", cell: (j) => j.launched_by },
    { title: "Inicio", cell: (j) => fmtDate(j.started_at || j.created_at) },
    { title: "Duración", class: "num", cell: (j) => fmtDuration(j.duration_s) },
  ].filter(Boolean), rows, { empty });
}

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

let fieldSeq = 0;

/** A labelled form control (the label points at the control). */
export function field(text, control, hint) {
  fieldSeq += 1;
  if (!control.id) control.id = `field-${fieldSeq}`;
  return h("div", { class: "field" }, h("label", { for: control.id }, text), control,
    hint ? h("small", { class: "muted" }, hint) : null);
}

/** Copy to the clipboard; falls back to a hidden textarea where the async clipboard API is unavailable. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = h("textarea", { class: "copy-fallback", readonly: true }, text);
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export function copyButton(text, labelText = "Copiar") {
  const button = h("button", { class: "btn ghost", type: "button" }, labelText);
  button.addEventListener("click", async () => {
    button.textContent = (await copyText(text)) ? "Copiado ✓" : "No se pudo copiar";
    setTimeout(() => { button.textContent = labelText; }, 1800);
  });
  return button;
}

/** A modal <dialog>; closing it (✕, Esc or navigating away) removes it from the page. */
export function modal(title, body, { wide = false } = {}) {
  const close = h("button", { class: "btn ghost small", type: "button", "aria-label": "Cerrar" }, "✕");
  const dialog = h("dialog", { class: wide ? "modal wide" : "modal", "aria-label": title },
    h("div", { class: "modal-head" }, h("h2", {}, title), close), body);
  dialog.addEventListener("close", () => dialog.remove());
  close.addEventListener("click", () => dialog.close());
  window.addEventListener("hashchange", () => dialog.close(), { once: true });
  document.body.append(dialog);
  dialog.showModal();
  return { dialog, close: () => dialog.close() };
}
```

- [ ] **Step 3: Crear `static/views/launch.js`**

```js
// Launch panel shared by the "+ Nueva auditoría" wizard and the Re-run / Review dialogs of the case page: options,
// the original context.md, the operator's notes and the exact command from POST /jobs/preview (the same plan the
// launch stores), then "Lanzar en segundo plano" or "Copiar comando".
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { COMMAND_LABEL, fmtBytes, shortHash } from "../lib/format.js";
import { copyText, debounce, field, modal } from "./components.js";

const MAX_NOTES = 20000;

function problem(text) {
  return h("div", { class: "error", role: "alert" }, text);
}

function contextBlock(context) {
  if (!context) return h("p", { class: "muted" }, "La carpeta no tiene context.md.");
  return h("div", {},
    h("p", { class: "muted" }, `context.md original (solo lectura) · ${fmtBytes(context.size)} · SHA-256 `,
      h("span", { class: "mono", title: context.sha256 }, shortHash(context.sha256))),
    h("pre", { class: "context-text" }, context.truncated ? `${context.text}\n…` : context.text));
}

/** command: new-open-case | rerun-case | review-case; inspect: GET /fs/inspect of the folder; onLaunched(job). */
export function launchPanel({ command, folder, inspect, onLaunched }) {
  const withOptions = command === "new-open-case";
  const defaults = inspect.defaults || {};
  const name = h("input", { type: "text", maxlength: "120", value: defaults.name || "" });
  const currency = h("input", { type: "text", maxlength: "3", class: "short", value: defaults.currency || "USD" });
  const lang = h("select", {}, [["es", "Español"], ["en", "Inglés"]].map(([value, text]) =>
    h("option", { value, selected: value === defaults.lang }, text)));
  const notes = h("textarea", { rows: "6", maxlength: String(MAX_NOTES),
    placeholder: "Declaraciones o criterios del operador. El agente los registra como criterio (CRIT-nn) con tu usuario, nunca como hechos." });
  const counter = h("small", { class: "muted" }, `0 / ${MAX_NOTES}`);
  const cmd = h("pre", { class: "cmd" }, "Preparando el comando…");
  const notice = h("div");
  const launch = h("button", { class: "btn", type: "button", disabled: true }, "Lanzar en segundo plano");
  const copy = h("button", { class: "btn ghost", type: "button", disabled: true }, "Copiar comando");
  let preview = null;

  const body = () => ({ command, folder, notes: notes.value,
    ...(withOptions ? { name: name.value, currency: currency.value, lang: lang.value } : {}) });

  async function refresh() {
    try {
      preview = await api("/jobs/preview", { method: "POST", body: body() });
      cmd.textContent = preview.display;
      mount(notice, preview.queue_note ? h("p", { class: "notice" }, preview.queue_note) : null);
      launch.disabled = false;
      copy.disabled = Boolean(preview.notes);
      copy.title = preview.notes ? "Con notas adicionales, lanza desde la consola: el archivo de contexto se crea al lanzar." : "";
    } catch (err) {
      preview = null;
      cmd.textContent = "—";
      mount(notice, problem(err.message));
      launch.disabled = true;
      copy.disabled = true;
    }
  }

  const later = debounce(refresh, 300);
  for (const el of [name, currency, notes]) el.addEventListener("input", later);
  lang.addEventListener("change", refresh);
  notes.addEventListener("input", () => { counter.textContent = `${notes.value.length} / ${MAX_NOTES}`; });
  launch.addEventListener("click", async () => {
    launch.disabled = true;
    launch.textContent = "Lanzando…";
    try {
      onLaunched((await api("/jobs", { method: "POST", body: body() })).job);
    } catch (err) {
      mount(notice, problem(err.message));
      launch.disabled = false;
      launch.textContent = "Lanzar en segundo plano";
    }
  });
  copy.addEventListener("click", async () => {
    if (!preview) return;
    copy.textContent = (await copyText(preview.display)) ? "Copiado ✓" : "No se pudo copiar";
    setTimeout(() => { copy.textContent = "Copiar comando"; }, 1800);
  });
  refresh();
  return h("div", { class: "launch" },
    withOptions ? h("div", { class: "grid-3" },
      field("Nombre del caso", name), field("Moneda (ISO-4217)", currency), field("Idioma de los entregables", lang)) : null,
    h("h3", {}, "Contexto"),
    contextBlock(inspect.context),
    field("Notas adicionales (opcional)", notes, "Markdown. Se guardan junto a los resultados del caso, nunca entre la evidencia."),
    counter,
    h("h3", {}, "Comando exacto"),
    cmd,
    notice,
    h("div", { class: "actions" }, launch, copy));
}

/** Re-run / Review from the case page: inspects the case folder, then shows the launch panel in a dialog. */
export async function openLaunchDialog({ command, folder, title }) {
  const content = h("div", {}, h("p", { class: "muted" }, "Revisando la carpeta del caso…"));
  const dialog = modal(`${COMMAND_LABEL[command] || command} · ${title}`, content, { wide: true });
  try {
    const inspect = await api("/fs/inspect", { query: { path: folder } });
    const warnings = inspect.warnings.filter((w) => w.code !== "sealed_case");
    mount(content,
      warnings.length ? h("ul", { class: "warnings" }, warnings.map((w) => h("li", {}, w.text))) : null,
      launchPanel({ command, folder: inspect.path, inspect, onLaunched: (job) => {
        dialog.close();
        window.location.hash = `#/jobs/${job.id}`;
      } }));
  } catch (err) {
    mount(content, problem(err.message));
  }
}
```

- [ ] **Step 4: Crear `static/views/job.js`**

```js
// Ejecución: header with its actions, phase bar, live activity feed (SSE), "Hasta ahora" counters and, once it ends,
// the agent's summary, seal state, deliverables, tokens and the technical log.
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { COMMAND_LABEL, fmtDate, fmtDuration, jobChip, label, sealCheckChip, secondsSince } from "../lib/format.js";
import { copyButton, kpi } from "./components.js";

const FEED_MAX = 500;
const FINDING_KINDS = ["exception", "anomaly", "finding", "question"];

function phaseBar(job, seen) {
  return h("ol", { class: "phases", "aria-label": "Fases" }, job.phases.map((p) => {
    const state = p.id === job.phase ? (job.active ? "current" : "done") : seen.has(p.id) ? "done" : "pending";
    return h("li", { class: `phase ${state}`, "aria-current": state === "current" ? "step" : null }, p.label);
  }));
}

function feedItem(e) {
  return h("li", { class: `feed-item kind-${e.kind} level-${e.level}` },
    h("time", { datetime: e.ts }, e.ts ? new Date(e.ts).toLocaleTimeString("es") : ""),
    h("span", { class: "feed-title" }, e.title),
    e.detail ? h("small", { class: "feed-detail" }, e.detail) : null);
}

function counters(progress) {
  if (!progress) return h("p", { class: "muted" }, "Los contadores aparecen en cuanto el agente abre el caso.");
  const f = progress.findings || {};
  const byKind = FINDING_KINDS.filter((k) => f[k]).map((k) => `${f[k]} ${label.findingKind(k)}`).join(" · ");
  return h("div", { class: "kpis" },
    kpi(progress.evidence, "Evidencia registrada"),
    kpi(progress.findings_total, "Hallazgos", byKind || "ninguno"),
    kpi(progress.criteria, "Criterios"),
    kpi(progress.research_notes, "Notas de investigación"));
}

function tokensText(t) {
  if (!t || !t.total) return "—";
  const n = (v) => Number(v || 0).toLocaleString("es");
  return `${n(t.total)} (entrada ${n(t.input)} · salida ${n(t.output)})`;
}

function outcome(job) {
  if (job.active) return null;
  const a = job.last_audit;
  return h("section", { class: "card" }, h("h2", {}, "Resultado"),
    job.error ? h("div", { class: "error" }, job.error) : null,
    job.result_text ? h("pre", { class: "result" }, job.result_text) : h("p", { class: "muted" }, "El agente no dejó un resumen."),
    h("dl", { class: "kv" },
      h("dt", {}, "Última auditoría"), h("dd", {}, a ? [`${a.seq} · ${label.auditStatus(a.status)} `, sealCheckChip(a)] : "—"),
      h("dt", {}, "Entregables"), h("dd", {}, a && job.case_id
        ? h("a", { href: `#/cases/${encodeURIComponent(job.case_id)}/audits` }, `${a.reports} en ${a.seq}`) : "—"),
      h("dt", {}, "Paquete de resultados"), h("dd", {},
        h("button", { class: "btn ghost small", type: "button", disabled: true, title: "Próximamente" }, "Exportar resultados (.zip)")),
      h("dt", {}, "Tokens"), h("dd", {}, tokensText(job.tokens))));
}

function technicalLog(jobId) {
  const pre = h("pre", { class: "log" }, "Cargando…");
  const box = h("details", { class: "card" }, h("summary", {}, "Log técnico"), pre);
  box.addEventListener("toggle", async () => {
    if (!box.open) return;
    try {
      const data = await api(`/jobs/${jobId}/log`);
      pre.textContent = (data.log || "(el agente no escribió en su salida de error)")
        + (data.runner_log ? `\n\n--- runner ---\n${data.runner_log}` : "");
    } catch (err) {
      pre.textContent = `No se pudo cargar: ${err.message}`;
    }
  });
  return box;
}

export async function render({ params, user, onLeave }) {
  const jobId = Number(params[0]);
  let job = await api(`/jobs/${jobId}`);
  const seen = new Set();
  const feed = h("ol", { class: "feed" }, h("li", { class: "feed-empty muted" }, "Esperando la primera actividad del agente…"));
  const head = h("div");
  const bar = h("div");
  const progressBox = h("div");
  const result = h("div");
  const duration = h("span");

  function tick() {
    duration.textContent = fmtDuration(job.active ? secondsSince(job.started_at || job.created_at) : job.duration_s);
  }

  function actions() {
    const items = [];
    if (user.role === "admin" && job.active) {
      const cancel = h("button", { class: "btn danger", type: "button" }, "Cancelar");
      cancel.addEventListener("click", async () => {
        if (!window.confirm("¿Cancelar esta ejecución? La auditoría a medio hacer queda abierta, sin sellar.")) return;
        cancel.disabled = true;
        try {
          job = (await api(`/jobs/${jobId}/cancel`, { method: "POST" })).job;
          paint();
        } catch (err) {
          cancel.disabled = false;
          cancel.title = err.message;
        }
      });
      items.push(cancel);
    }
    items.push(job.resume ? copyButton(job.resume.terminal, "Continuar en terminal")
      : h("button", { class: "btn ghost", type: "button", disabled: true, title: "Aparece cuando el agente informa su sesión." }, "Continuar en terminal"));
    if (job.resume && job.resume.chat_url) {
      items.push(h("a", { class: "btn ghost", href: job.resume.chat_url, target: "_blank", rel: "noopener noreferrer" }, "Continuar en chat"));
    }
    return items;
  }

  function paint() {
    const where = job.case_id
      ? h("a", { href: `#/cases/${encodeURIComponent(job.case_id)}` }, job.case_name || job.case_id) : job.folder_name;
    mount(head, h("div", { class: "case-head" },
      h("div", {}, h("h1", {}, `${COMMAND_LABEL[job.command] || job.command} · #${job.id}`),
        h("p", { class: "muted" }, where, ` · lanzada por ${job.launched_by} el ${fmtDate(job.created_at)} · `,
          jobChip(job.status), " ", duration)),
      h("div", { class: "actions" }, actions())));
    tick();
    mount(bar, phaseBar(job, seen));
    mount(progressBox, counters(job.progress));
    mount(result, outcome(job));
  }

  function addEvents(items) {
    if (!items.length) return;
    const placeholder = feed.querySelector(".feed-empty");
    if (placeholder) placeholder.remove();
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
    for (const e of items) {
      if (e.kind === "phase" && e.phase) seen.add(e.phase);
      feed.append(feedItem(e));
    }
    while (feed.children.length > FEED_MAX) feed.firstElementChild.remove();
    if (atBottom) feed.scrollTop = feed.scrollHeight;
  }

  async function refresh() {
    job = await api(`/jobs/${jobId}`);
    paint();
  }

  const first = await api(`/jobs/${jobId}/events`, { query: { after: 0 } });
  addEvents(first.items);
  paint();
  const timers = [setInterval(tick, 1000)];
  let source = null;
  if (job.active) {
    source = new EventSource(`/api/v1/jobs/${jobId}/events/stream?after=${first.last_seq}`);
    source.addEventListener("event", (msg) => {
      const e = JSON.parse(msg.data);
      addEvents([e]);
      if (e.kind === "phase") mount(bar, phaseBar(job, seen));
    });
    source.addEventListener("status", () => { refresh(); });
    source.addEventListener("end", () => {
      source.close();
      refresh();
    });
    timers.push(setInterval(() => { if (job.active) refresh(); }, 5000));
  }
  onLeave(() => {
    timers.forEach(clearInterval);
    if (source) source.close();
  });
  return h("div", { class: "page" }, head, bar,
    h("div", { class: "grid-2" },
      h("section", { class: "card" }, h("h2", {}, "Actividad"), feed),
      h("section", { class: "card" }, h("h2", {}, "Hasta ahora"), progressBox)),
    result, technicalLog(jobId));
}
```

- [ ] **Step 5: Crear `static/views/jobs.js` y `static/views/case/jobs.js`**

`static/views/jobs.js`:

```js
// Ejecuciones: every console job, newest first, filterable by status and case; refreshes while any is active.
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { JOB_STATUS_OPTIONS } from "../lib/format.js";
import { emptyState, errorState, jobsTable, newAuditAction } from "./components.js";

const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);

export async function render({ user, onLeave }) {
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "active" }, "Activas (en cola o en curso)"),
    JOB_STATUS_OPTIONS.map(([value, text]) => h("option", { value }, capitalize(text))));
  const cases = (await api("/cases")).items;
  const caseFilter = h("select", { "aria-label": "Caso" }, h("option", { value: "" }, "Todos los casos"),
    cases.map((c) => h("option", { value: c.id }, c.name)));
  const box = h("div");
  let active = false;
  async function load() {
    try {
      const data = await api("/jobs", { query: { status: status.value, case: caseFilter.value } });
      active = data.items.some((j) => j.active);
      const filtered = Boolean(status.value || caseFilter.value);
      mount(box, jobsTable(data.items, { empty: filtered ? "No hay ejecuciones con estos filtros."
        : emptyState("Todavía no se ha lanzado ninguna ejecución.", newAuditAction(user)) }));
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  status.addEventListener("change", load);
  caseFilter.addEventListener("change", load);
  await load();
  const timer = setInterval(() => { if (active) load(); }, 5000);
  onLeave(() => clearInterval(timer));
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Ejecuciones"), newAuditAction(user)),
    h("div", { class: "filters" }, status, caseFilter),
    h("section", { class: "card" }, box));
}
```

`static/views/case/jobs.js`:

```js
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { jobsTable } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/jobs`);
  return h("section", { class: "card" }, jobsTable(data.items, {
    showCase: false, empty: "Este caso todavía no tiene ejecuciones lanzadas desde la consola. Usa Re-run o Review arriba." }));
}
```

- [ ] **Step 6: Reemplazar `static/views/home.js`**

```js
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { fmtDate, riskChips } from "../lib/format.js";
import { casesTable, dataTable, emptyState, jobsTable, kpi, newAuditAction } from "./components.js";

export async function render({ user, onLeave }) {
  const kpis = h("section", { class: "kpis" });
  const running = h("div");
  function paint(o) {
    const k = o.kpis;
    const queued = k.jobs_active - k.jobs_running;
    mount(kpis,
      kpi(k.cases_active, "Casos activos", `${k.cases_total} en total`),
      kpi(k.audits_sealed, "Auditorías selladas"),
      kpi(k.open_total, "Hallazgos abiertos", riskChips(k.open_by_risk)),
      kpi(k.jobs_active, "Ejecuciones activas", queued > 0 ? `${queued} en cola` : null));
    mount(running, jobsTable(o.active_jobs, { empty: emptyState("No hay ejecuciones en curso.", newAuditAction(user)) }));
  }
  const o = await api("/system/overview");
  paint(o);
  const timer = setInterval(async () => {
    try {
      paint(await api("/system/overview"));
    } catch {
      // keep the last figures on screen; the next refresh retries
    }
  }, 10000);
  onLeave(() => clearInterval(timer));
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Inicio"), newAuditAction(user)),
    kpis,
    h("section", { class: "card" }, h("h2", {}, "En curso"), running),
    h("section", { class: "card" }, h("h2", {}, "Casos recientes"), casesTable(o.recent_cases, user)),
    h("section", { class: "card" }, h("h2", {}, "Actividad reciente"), dataTable([
      { title: "Fecha", cell: (e) => fmtDate(e.ts) },
      { title: "Caso", cell: (e) => h("a", { href: `#/cases/${encodeURIComponent(e.case_id)}/timeline` }, e.case_name) },
      { title: "Evento", cell: (e) => e.event_type },
      { title: "Descripción", cell: (e) => e.description },
    ], o.recent_events, { empty: "Sin actividad todavía." })));
}
```

- [ ] **Step 7: Reemplazar `static/views/cases.js`**

```js
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { casesTable, debounce, errorState, newAuditAction } from "./components.js";

export async function render({ user }) {
  const q = h("input", { type: "search", placeholder: "Filtrar por nombre, ID o carpeta", "aria-label": "Filtrar casos" });
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "open" }, "Abiertos"),
    h("option", { value: "closed" }, "Cerrados"), h("option", { value: "archived" }, "Archivados"));
  const box = h("div");
  async function load() {
    try {
      const items = (await api("/cases", { query: { q: q.value, status: status.value } })).items;
      const filtered = Boolean(q.value || status.value);
      mount(box, casesTable(items, user, filtered ? { empty: "Ningún caso coincide con los filtros." } : {}));
    } catch (err) {
      mount(box, errorState(err));
    }
  }
  q.addEventListener("input", debounce(load, 250));
  status.addEventListener("change", load);
  await load();
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Casos"), newAuditAction(user)),
    h("div", { class: "filters" }, q, status),
    h("section", { class: "card" }, box));
}
```

- [ ] **Step 8: Reemplazar `static/views/case.js`**

```js
import { api } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { fmtDate, riskChips, sealChip } from "../lib/format.js";
import { errorState, kpi } from "./components.js";
import * as audits from "./case/audits.js";
import * as criteria from "./case/criteria.js";
import * as evidence from "./case/evidence.js";
import * as findings from "./case/findings.js";
import * as jobs from "./case/jobs.js";
import * as research from "./case/research.js";
import * as summary from "./case/summary.js";
import * as timeline from "./case/timeline.js";
import { openLaunchDialog } from "./launch.js";

const TABS = [
  { id: "summary", label: "Resumen", view: summary },
  { id: "audits", label: "Auditorías", view: audits },
  { id: "findings", label: "Hallazgos", view: findings },
  { id: "evidence", label: "Evidencia", view: evidence },
  { id: "criteria", label: "Criterios", view: criteria },
  { id: "research", label: "Investigación", view: research },
  { id: "timeline", label: "Cronología", view: timeline },
  { id: "jobs", label: "Ejecuciones", view: jobs },
];

function rerender() {
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

// The re-render below rebuilds the page, so verification errors are handed over to the next render().
let verifyErrors = [];

async function verifySeals(detail, button) {
  button.disabled = true;
  button.textContent = "Verificando…";
  verifyErrors = [];
  for (const audit of detail.audits.filter((a) => a.status === "sealed")) {
    try {
      await api(`/cases/${encodeURIComponent(detail.case.id)}/audits/${audit.seq}/verify`, { method: "POST" });
    } catch (err) {
      verifyErrors.push(`${audit.seq}: ${err.message}`);
    }
  }
  rerender();
}

function verifyNotice() {
  const errors = verifyErrors;
  verifyErrors = [];
  return errors.length
    ? h("div", { class: "error", role: "alert" }, `No se pudo verificar el sello (${errors.join("; ")}). El estado mostrado puede no estar al día.`)
    : null;
}

function duplicates(stats) {
  return Object.entries(stats || {}).filter(([k]) => k.startsWith("DUP")).reduce((sum, [, v]) => sum + v, 0);
}

function launchButton(text, command, theCase, user, blocked) {
  const reason = user.role !== "admin" ? "Solo los administradores lanzan ejecuciones." : blocked;
  const button = h("button", { class: "btn", type: "button", disabled: Boolean(reason), title: reason || null }, text);
  button.addEventListener("click", () => openLaunchDialog({ command, folder: theCase.root_path, title: theCase.name }));
  return button;
}

export async function render({ params, user }) {
  const [caseId, tabId = "summary"] = params;
  const detail = await api(`/cases/${encodeURIComponent(caseId)}`);
  const c = detail.case;
  const s = detail.summary;
  const tab = TABS.find((t) => t.id === tabId) || TABS[0];
  const verify = h("button", { class: "btn ghost", disabled: s.sealed_count === 0 }, "Verificar sellos");
  verify.addEventListener("click", () => verifySeals(detail, verify));
  const notice = verifyNotice();
  const body = h("div", { class: "tab-body" }, h("p", { class: "muted" }, "Cargando…"));
  const page = h("div", { class: "page" },
    h("div", { class: "case-head" },
      h("div", {}, h("h1", {}, c.name),
        h("p", { class: "muted mono" }, `${c.id} · ${c.base_currency} · ${c.language} · ${c.root_path}`)),
      h("div", { class: "actions" },
        launchButton("▶ Re-run", "rerun-case", c, user, null),
        launchButton("▶ Review", "review-case", c, user, s.sealed_count === 0 ? "La revisión necesita una auditoría sellada." : null),
        verify,
        h("button", { class: "btn ghost", disabled: true, title: "Próximamente" }, "Exportar resultados (.zip)"))),
    notice,
    h("section", { class: "kpis" },
      kpi(s.audits_count, "Auditorías", sealChip(s.seal_state)),
      kpi(s.open_total, "Hallazgos abiertos", riskChips(s.open_by_risk)),
      kpi(detail.evidence.total || 0, "Evidencia", `${duplicates(detail.evidence)} duplicados`),
      kpi(fmtDate(s.last_activity), "Última actividad")),
    h("nav", { class: "tabs", "aria-label": "Secciones del caso" }, TABS.map((t) =>
      h("a", { class: t.id === tab.id ? "tab active" : "tab", href: `#/cases/${encodeURIComponent(c.id)}/${t.id}`,
        "aria-current": t.id === tab.id ? "page" : null }, t.label))),
    body);
  try {
    body.replaceChildren(await tab.view.render({ caseId: c.id, detail, user }));
  } catch (err) {
    body.replaceChildren(errorState(err));
  }
  return page;
}
```

- [ ] **Step 9: Reemplazar `static/app.js`**

```js
// Console bootstrap: hash router, session bootstrap and the application shell (top bar + sidebar).
import { api, setCsrf } from "./lib/api.js";
import { h, mount } from "./lib/dom.js";
import * as caseView from "./views/case.js";
import * as cases from "./views/cases.js";
import { errorState } from "./views/components.js";
import * as home from "./views/home.js";
import * as job from "./views/job.js";
import * as jobs from "./views/jobs.js";
import * as login from "./views/login.js";
import * as system from "./views/system.js";

const state = { user: null };
let leaving = [];

const ROUTES = [
  { re: /^\/login$/, view: login, public: true },
  { re: /^\/$/, view: home, nav: "home" },
  { re: /^\/cases$/, view: cases, nav: "cases" },
  { re: /^\/cases\/([^/]+)(?:\/([a-z]+))?$/, view: caseView, nav: "cases" },
  { re: /^\/jobs$/, view: jobs, nav: "jobs" },
  { re: /^\/jobs\/(\d+)$/, view: job, nav: "jobs" },
  { re: /^\/system$/, view: system, nav: "system" },
];

const NAV = [
  { id: "home", label: "Inicio", href: "#/" },
  { id: "cases", label: "Casos", href: "#/cases" },
  { id: "jobs", label: "Ejecuciones", href: "#/jobs" },
  { id: "system", label: "Sistema", href: "#/system" },
];

/** Views register cleanups (EventSource, timers) that run when the user navigates away. */
function onLeave(fn) {
  leaving.push(fn);
}

function leave() {
  const fns = leaving;
  leaving = [];
  for (const fn of fns) fn();
}

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
  } catch (err) {
    // 401: the session is already gone, so leaving is honest. Anything else: the cookie may still be valid.
    if (err.status !== 401) {
      document.getElementById("main").prepend(h("div", { class: "error", role: "alert" },
        `No se pudo cerrar la sesión: ${err.message}. Sigues con la sesión abierta.`));
      return;
    }
  }
  state.user = null;
  setCsrf(null);
  window.location.hash = "#/login";
}

function shell(navId) {
  const main = h("main", { class: "main", id: "main", tabindex: "-1" });
  const admin = state.user.role === "admin";
  const root = h("div", { class: "shell" },
    h("header", { class: "topbar" },
      h("a", { class: "brand", href: "#/", "aria-label": "Ghost Recon, inicio" }),
      h("input", { class: "search", type: "search", placeholder: "Buscar entre casos", disabled: true, title: "Próximamente", "aria-label": "Buscar entre casos" }),
      admin ? h("a", { class: "btn", href: "#/new" }, "+ Nueva auditoría")
        : h("button", { class: "btn", disabled: true, title: "Solo los administradores lanzan auditorías." }, "+ Nueva auditoría"),
      h("span", { class: "who" }, `${state.user.username} · ${state.user.role}`),
      h("button", { class: "btn ghost small", onclick: logout }, "Salir")),
    h("nav", { class: "sidebar", "aria-label": "Secciones" }, NAV.map((n) =>
      h("a", { class: n.id === navId ? "nav-item active" : "nav-item", href: n.href, "aria-current": n.id === navId ? "page" : null }, n.label))),
    main);
  return { root, main };
}

function onLogin(data) {
  state.user = data.user;
  setCsrf(data.csrf);
  window.location.hash = "#/";
}

async function render() {
  leave();
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
    mount(main, await route.view.render({ params, user: state.user, onLeave }));
  } catch (err) {
    mount(main, errorState(err));
  }
}

window.addEventListener("hashchange", render);
render();
```

- [ ] **Step 10: Estilos en `static/app.css`**

Sustituye:

```css
.nav-item:hover:not(.soon) { color: #fff; }
.nav-item.soon { opacity: .5; cursor: not-allowed; }
```

por:

```css
.nav-item:hover { color: #fff; }
```

sustituye:

```css
.tab.active { color: var(--gr-text); font-weight: 700; border-bottom-color: var(--gr-primary); }
.tab.soon { opacity: .5; cursor: not-allowed; }
```

por:

```css
.tab.active { color: var(--gr-text); font-weight: 700; border-bottom-color: var(--gr-primary); }
```

y añade al final del archivo:

```css
/* page heads, empty states with an action, notices */
.page-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.page-head h1 { margin: 0; }
.empty p { margin: 0 0 10px; }
.empty-actions { display: flex; justify-content: center; gap: 8px; }
a.btn { display: inline-block; text-decoration: none; }
.btn.danger { background: var(--gr-risk-high); color: var(--gr-primary-text); }
.notice { padding: 8px 12px; border-radius: var(--gr-radius); background: var(--gr-info-bg); color: var(--gr-info); margin: 8px 0; }
.warnings { margin: 0 0 12px; padding: 8px 12px 8px 28px; border-radius: var(--gr-radius);
  background: var(--gr-risk-medium-bg); color: var(--gr-risk-medium); }

/* forms and the launch panel */
.field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.field label { font-weight: 600; font-size: 13px; }
.field input, .field select, .field textarea { font: inherit; padding: 7px 9px; border: 1px solid var(--gr-input-border);
  border-radius: var(--gr-radius); background: var(--gr-surface); color: var(--gr-text); }
.field textarea { resize: vertical; min-height: 110px; }
.field input.short { max-width: 90px; text-transform: uppercase; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
pre.cmd, pre.log, pre.result, pre.context-text { font-family: var(--gr-mono); font-size: 12.5px; white-space: pre-wrap;
  word-break: break-word; background: var(--gr-row-detail); border: 1px solid var(--gr-border);
  border-radius: var(--gr-radius); padding: 10px 12px; margin: 6px 0 10px; max-height: 360px; overflow: auto; }
pre.result { font-family: var(--gr-font); font-size: 14px; }
.copy-fallback { position: fixed; left: -9999px; top: 0; }

/* dialogs */
dialog.modal { border: 0; border-radius: 10px; padding: 18px 20px; width: min(640px, calc(100vw - 32px));
  max-height: calc(100vh - 48px); overflow: auto; background: var(--gr-surface); color: var(--gr-text); }
dialog.modal.wide { width: min(920px, calc(100vw - 32px)); }
dialog.modal::backdrop { background: rgba(16, 24, 38, .55); }
.modal-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.modal-head h2 { margin: 0; font-size: 17px; }

/* job view: phase bar and activity feed */
.phases { display: flex; flex-wrap: wrap; gap: 6px; list-style: none; margin: 0 0 16px; padding: 0; }
.phase { padding: 5px 10px; border-radius: 14px; font-size: 12.5px; font-weight: 600; background: var(--gr-risk-low-bg);
  color: var(--gr-muted); }
.phase.done { background: var(--gr-ok-bg); color: var(--gr-ok); }
.phase.current { background: var(--gr-info-bg); color: var(--gr-info); outline: 2px solid var(--gr-info); }
.feed { list-style: none; margin: 0; padding: 0; max-height: 460px; overflow-y: auto; }
.feed-item { display: grid; grid-template-columns: 72px 1fr; gap: 2px 10px; padding: 6px 4px; border-bottom: 1px solid var(--gr-row-border); }
.feed-item time { color: var(--gr-muted); font-variant-numeric: tabular-nums; font-size: 12px; }
.feed-item .feed-detail { grid-column: 2; color: var(--gr-muted); white-space: pre-wrap; word-break: break-word; }
.feed-item.kind-phase .feed-title { font-weight: 700; }
.feed-item.level-warning .feed-title { color: var(--gr-risk-medium); }
.feed-item.level-error .feed-title { color: var(--gr-risk-high); }
.feed-empty { padding: 12px 4px; }
details.card > summary { cursor: pointer; font-weight: 600; }
```

- [ ] **Step 11: Regresión de la suite**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed` (incluida `test_static.py`, que sirve los módulos con MIME de módulo).

Si Node está instalado (la máquina dedicada no lo necesita), comprueba además la sintaxis de los módulos:

```bash
for f in plugins/ghost_recon/console/static/app.js plugins/ghost_recon/console/static/lib/*.js plugins/ghost_recon/console/static/views/*.js plugins/ghost_recon/console/static/views/case/*.js; do node --input-type=module --check < "$f" || echo "ERROR: $f"; done
```

Expected: sin salida.

- [ ] **Step 12: Barrido de textos**

Run: `grep -rnE "Disponible en|disponible en|\bH[1-4]\b|/new-open-case|/rerun-case|/review-case|desde la consola en" plugins/ghost_recon/console/static`
Expected: sin salida. La UI no nombra hitos ni comandos (el texto `-q` con la orden solo aparece como dato del servidor en «Comando exacto»).

- [ ] **Step 13: Smoke manual en navegador** (o con Playwright si está disponible)

Run: `.venv/Scripts/python.exe ghost-recon/demo/console_demo.py --port 9231` (o `.venv/bin/python …`). Abre `http://localhost:9231`, entra como `demo` y comprueba:
- [ ] la barra lateral muestra Inicio · Casos · Ejecuciones · Sistema, todas activas; la búsqueda superior aparece deshabilitada con el aviso «Próximamente»;
- [ ] Inicio muestra «Ejecuciones activas: 0» y, en «En curso», «No hay ejecuciones en curso.» con el botón «+ Nueva auditoría»;
- [ ] en el caso «Acme Importaciones», «▶ Re-run» abre un diálogo con el `context.md` (y su SHA-256), «Notas adicionales» con contador y el «Comando exacto»; escribir notas deshabilita «Copiar comando» con su explicación;
- [ ] «Lanzar en segundo plano» lleva a `#/jobs/<id>`: la barra de fases avanza, el feed se llena sin recargar, «Hasta ahora» muestra la evidencia y, al terminar (~10 s), aparecen el resumen, la última auditoría con su sello, los tokens y «Continuar en terminal» copia `hermes -p … --resume fake-…`;
- [ ] mientras corre, Inicio muestra «Ejecuciones activas: 1» y la fila en «En curso»; «Ejecuciones» la lista y filtra por estado y caso;
- [ ] «Cancelar» en una ejecución en curso pide confirmación y deja el estado «cancelada»;
- [ ] la pestaña «Ejecuciones» del caso lista sus ejecuciones; «Exportar resultados (.zip)» está deshabilitado con «Próximamente»;
- [ ] como `visor`: no hay «Cancelar», Re-run y Review están deshabilitados con «Solo los administradores lanzan ejecuciones.», y «+ Nueva auditoría» de la barra superior está deshabilitado;
- [ ] la consola del navegador no muestra errores de CSP ni de JS (el 401 de `/auth/me` antes del login y los 4xx de validación que provoques salen como «Failed to load resource»: son esperados).

Detén la demo con Ctrl+C.

- [ ] **Step 14: Commit**

```bash
git add plugins/ghost_recon/console/static
git commit -m "feat(ghost-recon): console live job views, re-run/review dialogs and friendlier copy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Frontend — asistente «+ Nueva auditoría» y Usuarios y tokens

**Files:**
- Create: `plugins/ghost_recon/console/static/views/wizard.js`
- Create: `plugins/ghost_recon/console/static/views/users.js`
- Modify: `plugins/ghost_recon/console/static/views/system.js` (acceso a Usuarios y tokens)
- Modify: `plugins/ghost_recon/console/static/app.js` (rutas `#/new` y `#/system/users`)
- Modify: `plugins/ghost_recon/console/static/app.css`

**Interfaces:**
- Consumes: `GET /fs/roots|list|search|inspect` (Tarea 7), `launchPanel` (Tarea 10), `GET/POST /users…` y `/tokens…` (Tarea 9); `components.dataTable/emptyState/errorState/debounce/field/modal/copyButton`, `format.chip/fmtBytes/fmtDate/shortHash/COMMAND_LABEL`.
- Produces:
  - `#/new`: asistente en 3 pasos (§10.5). Paso 1, carpeta: raíces → navegación con miga de pan, búsqueda (≥ 2 caracteres) y, por carpeta, la marca «nueva» o «caso existente» (sellado o no) y su número de archivos. Paso 2, revisión previa: archivos, tamaño, ZIP, imágenes, `context.md` con su hash, caso existente, carpeta de salida, archivos por tipo y avisos; si la carpeta ya es un caso sellado, el asistente pasa a Re-run y lo explica. Paso 3: `launchPanel`. Sin `case_roots`, el asistente explica qué ajuste falta y a quién pedirlo.
  - `#/system/users` (solo admin): usuarios (crear con confirmación de contraseña, restablecer contraseña, habilitar/deshabilitar, cambiar rol; los botones sobre el propio usuario aparecen deshabilitados con su motivo) y tokens (crear —el token en claro se muestra una sola vez, con botón para copiarlo—, listar, revocar).
- Sin pruebas Python nuevas (ver Tarea 10); verificación en navegador (Step 7).

- [ ] **Step 1: Crear `static/views/wizard.js`**

```js
// "+ Nueva auditoría" in three steps: pick an evidence folder inside the case roots, review what it holds, then set
// the options and context notes and launch (the launch panel shows the exact command first).
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { chip, COMMAND_LABEL, fmtBytes, shortHash } from "../lib/format.js";
import { dataTable, debounce, emptyState, errorState } from "./components.js";
import { launchPanel } from "./launch.js";

const STEPS = ["Carpeta", "Revisión previa", "Opciones y lanzamiento"];

function stepper(current) {
  return h("ol", { class: "steps" }, STEPS.map((text, i) =>
    h("li", { class: i === current ? "current" : i < current ? "done" : null, "aria-current": i === current ? "step" : null },
      `${i + 1}. ${text}`)));
}

function caseMark(entry) {
  if (!entry.case) return chip("nueva", "info");
  return entry.case.sealed ? chip("caso existente · sellado", "ok", entry.case.id) : chip("caso existente", "muted", entry.case.id);
}

function filesText(entry) {
  return `${entry.capped ? "más de " : ""}${entry.files} archivos`;
}

function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v === null || v === undefined || v === "" ? "—" : v)]));
}

function back(onclick) {
  return h("button", { class: "btn ghost", type: "button", onclick }, "← Atrás");
}

export async function render({ user }) {
  const title = h("h1", {}, "Nueva auditoría");
  if (user.role !== "admin") {
    return h("div", { class: "page" }, title, emptyState("Solo los administradores lanzan auditorías."));
  }
  const roots = await api("/fs/roots");
  if (!roots.items.length) {
    return h("div", { class: "page" }, title, h("section", { class: "card" },
      h("h2", {}, "Falta configurar las carpetas de casos"),
      h("p", {}, roots.hint),
      h("p", { class: "muted" }, "Las evidencias se copian primero (por RustDesk o SFTP) a esa carpeta de la máquina dedicada; "
        + "la consola solo muestra lo que está dentro de las carpetas configuradas.")));
  }
  const page = h("div", { class: "page" });
  const search = h("input", { type: "search", placeholder: "Buscar una carpeta por nombre…", "aria-label": "Buscar carpetas" });
  const box = h("div");
  const stepOne = h("section", { class: "card" }, h("div", { class: "filters" }, search), box);
  let browsing = null; // folder shown in step 1; null = the list of roots

  function folderRow(entry, { root = false } = {}) {
    const open = h("button", { class: "open", type: "button", onclick: () => browse(entry.path) }, entry.name);
    return h("li", { class: "folder" }, open,
      entry.case !== undefined ? caseMark(entry) : null,
      entry.files !== undefined ? h("span", { class: "meta" }, filesText(entry)) : null,
      root && entry.free_bytes ? h("span", { class: "meta" }, `${fmtBytes(entry.free_bytes)} libres`) : null,
      root ? null : h("button", { class: "btn small", type: "button", onclick: () => review(entry.path) }, "Elegir"));
  }

  function crumbs(list) {
    const items = [h("button", { type: "button", onclick: () => browse(null) }, "Carpetas de casos")];
    for (const c of list) items.push(h("span", { class: "sep" }, "›"), h("button", { type: "button", onclick: () => browse(c.path) }, c.name));
    return h("nav", { class: "crumbs", "aria-label": "Ruta" }, items);
  }

  async function browse(path) {
    browsing = path;
    mount(page, title, stepper(0), stepOne);
    mount(box, h("p", { class: "muted" }, "Cargando…"));
    if (!path) {
      mount(box, h("p", { class: "muted" }, "Elige la carpeta de casos y, dentro, la carpeta de evidencia del caso."),
        h("ul", { class: "folders" }, roots.items.map((r) => folderRow(r, { root: true }))));
      return;
    }
    try {
      const data = await api("/fs/list", { query: { path } });
      const here = data.path !== data.root
        ? h("div", { class: "here" }, h("span", {}, `Carpeta actual: ${data.name} · ${filesText(data)}`), caseMark(data),
          h("button", { class: "btn", type: "button", onclick: () => review(data.path) }, "Elegir esta carpeta"))
        : null;
      mount(box, crumbs(data.breadcrumb), here,
        data.items.length ? h("ul", { class: "folders" }, data.items.map((e) => folderRow(e))) : emptyState("No hay subcarpetas."));
    } catch (err) {
      mount(box, errorState(err));
    }
  }

  search.addEventListener("input", debounce(async () => {
    const q = search.value.trim();
    if (q.length < 2) {
      browse(browsing);
      return;
    }
    try {
      const data = await api("/fs/search", { query: { q } });
      const note = data.truncated ? "Hay más resultados: afina la búsqueda."
        : data.timed_out ? "La búsqueda se detuvo a los 3 segundos: afina el nombre." : data.items.length === 1 ? "1 resultado" : `${data.items.length} resultados`;
      mount(box, h("p", { class: "muted" }, note),
        data.items.length ? h("ul", { class: "folders" }, data.items.map((e) => folderRow(e))) : emptyState("Ninguna carpeta coincide."));
    } catch (err) {
      mount(box, errorState(err));
    }
  }, 300));

  async function review(path) {
    const content = h("div", {}, h("p", { class: "muted" }, "Revisando la carpeta…"));
    mount(page, title, stepper(1), content);
    let info;
    try {
      info = await api("/fs/inspect", { query: { path } });
    } catch (err) {
      mount(content, errorState(err), h("div", { class: "wizard-actions" }, back(() => browse(browsing))));
      return;
    }
    const command = info.suggested_command;
    const c = info.case;
    mount(content,
      h("section", { class: "card" }, h("h2", {}, info.name), kv([
        ["Carpeta", h("span", { class: "mono" }, info.path)],
        ["Archivos", `${info.capped ? "más de " : ""}${info.files} · ${fmtBytes(info.size)}`],
        ["ZIP", String(info.zips)],
        ["Imágenes", String(info.images)],
        ["context.md", info.context ? h("span", { class: "mono", title: info.context.sha256 }, `sí · SHA-256 ${shortHash(info.context.sha256)}`) : "no"],
        ["Caso", c ? `${c.name} (${c.id}) · ${c.audits} auditorías, ${c.sealed} selladas` : "nuevo"],
        ["Carpeta de salida", h("span", { class: "mono" }, info.results_root)],
      ])),
      h("section", { class: "card" }, h("h2", {}, "Archivos por tipo"), dataTable([
        { title: "Tipo", cell: (r) => r.ext },
        { title: "Archivos", class: "num", cell: (r) => String(r.count) },
      ], info.by_type.slice(0, 25), { empty: "Sin archivos." })),
      info.warnings.some((w) => w.code !== "sealed_case")
        ? h("ul", { class: "warnings" }, info.warnings.filter((w) => w.code !== "sealed_case").map((w) => h("li", {}, w.text))) : null,
      command === "rerun-case"
        ? h("p", { class: "notice" }, "Esta carpeta ya es un caso con una auditoría sellada: se lanzará un Re-run, que incorpora la evidencia nueva sin tocar lo sellado.")
        : null,
      h("div", { class: "wizard-actions" }, back(() => browse(browsing)),
        h("button", { class: "btn", type: "button", onclick: () => configure(info, command) },
          command === "rerun-case" ? "Continuar con Re-run" : "Continuar")));
  }

  function configure(info, command) {
    mount(page, title, stepper(2), h("section", { class: "card" },
      h("h2", {}, `${COMMAND_LABEL[command]} · ${info.name}`),
      launchPanel({ command, folder: info.path, inspect: info, onLaunched: (job) => { window.location.hash = `#/jobs/${job.id}`; } }),
      h("div", { class: "wizard-actions" }, back(() => review(info.path)))));
  }

  await browse(null);
  return page;
}
```

- [ ] **Step 2: Crear `static/views/users.js`**

```js
// Sistema › Usuarios y tokens (admin): accounts, password resets, enable/disable, roles and API tokens. The server
// applies the same rules as the CLI; your own account cannot be disabled or demoted from here.
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { chip, fmtDate } from "../lib/format.js";
import { copyButton, dataTable, emptyState, field, modal } from "./components.js";

function passwordPair() {
  const pass = h("input", { type: "password", autocomplete: "new-password", minlength: "10", required: true });
  const again = h("input", { type: "password", autocomplete: "new-password", minlength: "10", required: true });
  return { pass, again, fields: [field("Contraseña (mínimo 10 caracteres)", pass), field("Repite la contraseña", again)] };
}

function problem(text) {
  return h("div", { class: "error", role: "alert" }, text);
}

export async function render({ user }) {
  const title = h("div", { class: "page-head" }, h("h1", {}, "Usuarios y tokens"), h("a", { class: "btn ghost", href: "#/system" }, "← Sistema"));
  if (user.role !== "admin") {
    return h("div", { class: "page" }, title, emptyState("Solo los administradores gestionan usuarios y tokens."));
  }
  const msg = h("div");
  const usersBox = h("div");
  const tokensBox = h("div");

  async function act(fn) {
    try {
      await fn();
      await reload();
    } catch (err) {
      mount(msg, problem(err.message));
    }
  }

  function resetDialog(username) {
    const { pass, again, fields } = passwordPair();
    const error = h("div");
    const form = h("form", {}, h("p", { class: "muted" }, `Las sesiones abiertas de ${username} se cerrarán.`), fields, error,
      h("div", { class: "actions" }, h("button", { class: "btn", type: "submit" }, "Guardar contraseña")));
    const dialog = modal(`Restablecer contraseña · ${username}`, form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api(`/users/${encodeURIComponent(username)}/password`, { method: "POST", body: { password: pass.value, password_confirm: again.value } });
        dialog.close();
        await reload();
      } catch (err) {
        mount(error, problem(err.message));
      }
    });
  }

  function rowActions(u) {
    const self = u.username === user.username;
    const reset = h("button", { class: "btn ghost small", type: "button", onclick: () => resetDialog(u.username) }, "Restablecer contraseña");
    const toggle = h("button", { class: "btn ghost small", type: "button", disabled: self,
      title: self ? "No puedes deshabilitar tu propio usuario." : null }, u.disabled ? "Habilitar" : "Deshabilitar");
    toggle.addEventListener("click", () => {
      if (!u.disabled && !window.confirm(`¿Deshabilitar a ${u.username}? Sus sesiones se cerrarán.`)) return;
      act(() => api(`/users/${encodeURIComponent(u.username)}/${u.disabled ? "enable" : "disable"}`, { method: "POST" }));
    });
    const other = u.role === "admin" ? "viewer" : "admin";
    const role = h("button", { class: "btn ghost small", type: "button", disabled: self,
      title: self ? "No puedes cambiar tu propio rol." : null }, other === "admin" ? "Hacer admin" : "Hacer viewer");
    role.addEventListener("click", () => act(() => api(`/users/${encodeURIComponent(u.username)}/role`, { method: "POST", body: { role: other } })));
    return h("div", { class: "actions" }, reset, toggle, role);
  }

  function usersTable(items) {
    return dataTable([
      { title: "Usuario", cell: (u) => h("strong", {}, u.username) },
      { title: "Rol", cell: (u) => u.role },
      { title: "Estado", cell: (u) => (u.disabled ? chip("deshabilitado", "muted") : chip("activo", "ok")) },
      { title: "Último acceso", cell: (u) => fmtDate(u.last_login_at) },
      { title: "Acciones", cell: rowActions },
    ], items, { empty: "Sin usuarios." });
  }

  function newUserForm() {
    const username = h("input", { type: "text", autocomplete: "off", maxlength: "32", required: true });
    const role = h("select", {}, h("option", { value: "viewer" }, "viewer (solo lectura)"), h("option", { value: "admin" }, "admin"));
    const { pass, again, fields } = passwordPair();
    const form = h("form", { class: "inline-form" }, field("Usuario", username), field("Rol", role), fields,
      h("button", { class: "btn", type: "submit" }, "Crear usuario"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      act(async () => {
        await api("/users", { method: "POST", body: { username: username.value, role: role.value, password: pass.value, password_confirm: again.value } });
        form.reset();
      });
    });
    return form;
  }

  function tokensTable(items) {
    return dataTable([
      { title: "ID", class: "num", cell: (t) => String(t.id) },
      { title: "Nombre", cell: (t) => t.name },
      { title: "Usuario", cell: (t) => t.username },
      { title: "Token", cell: (t) => h("span", { class: "mono" }, `grt_${t.prefix}_…`) },
      { title: "Creado", cell: (t) => fmtDate(t.created_at) },
      { title: "Último uso", cell: (t) => fmtDate(t.last_used_at) },
      { title: "Estado", cell: (t) => (t.revoked ? chip("revocado", "muted") : chip("activo", "ok")) },
      { title: "", cell: (t) => (t.revoked ? null : h("button", { class: "btn ghost small", type: "button", onclick: () => {
        if (window.confirm(`¿Revocar el token «${t.name}»? Quien lo use dejará de tener acceso.`)) {
          act(() => api(`/tokens/${t.id}/revoke`, { method: "POST" }));
        }
      } }, "Revocar")) },
    ], items, { empty: "Sin tokens de API." });
  }

  function newTokenForm(users) {
    const owner = h("select", {}, users.filter((u) => !u.disabled).map((u) => h("option", { value: u.username }, u.username)));
    const name = h("input", { type: "text", maxlength: "80", required: true, placeholder: "p. ej. web-app" });
    const form = h("form", { class: "inline-form" }, field("Usuario", owner), field("Nombre del token", name),
      h("button", { class: "btn", type: "submit" }, "Crear token"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      act(async () => {
        const created = await api("/tokens", { method: "POST", body: { username: owner.value, name: name.value } });
        form.reset();
        modal("Token creado", h("div", {},
          h("p", {}, "Cópialo ahora: no se volverá a mostrar. Se envía en la cabecera «Authorization: Bearer <token>»."),
          h("p", { class: "token-once" }, created.token),
          copyButton(created.token, "Copiar token")));
      });
    });
    return form;
  }

  async function reload() {
    mount(msg);
    const [users, tokens] = await Promise.all([api("/users"), api("/tokens")]);
    mount(usersBox, usersTable(users.items));
    mount(tokensBox, tokensTable(tokens.items), h("h3", {}, "Crear token"), newTokenForm(users.items));
  }

  await reload();
  return h("div", { class: "page" }, title, msg,
    h("section", { class: "card" }, h("h2", {}, "Usuarios"), usersBox, h("h3", {}, "Crear usuario"), newUserForm()),
    h("section", { class: "card" }, h("h2", {}, "Tokens de API"), tokensBox));
}
```

- [ ] **Step 3: Acceso desde Sistema**

En `static/views/system.js`, sustituye:

```js
    h("h1", {}, "Sistema"),
```

por:

```js
    h("div", { class: "page-head" }, h("h1", {}, "Sistema"),
      user.role === "admin" ? h("a", { class: "btn ghost", href: "#/system/users" }, "Usuarios y tokens") : null),
```

- [ ] **Step 4: Rutas en `static/app.js`**

Sustituye:

```js
import * as login from "./views/login.js";
import * as system from "./views/system.js";
```

por:

```js
import * as login from "./views/login.js";
import * as system from "./views/system.js";
import * as users from "./views/users.js";
import * as wizard from "./views/wizard.js";
```

y sustituye:

```js
  { re: /^\/system$/, view: system, nav: "system" },
];
```

por:

```js
  { re: /^\/system$/, view: system, nav: "system" },
  { re: /^\/system\/users$/, view: users, nav: "system" },
  { re: /^\/new$/, view: wizard, nav: null },
];
```

- [ ] **Step 5: Estilos**

Añade al final de `static/app.css`:

```css
/* new-audit wizard */
.steps { display: flex; flex-wrap: wrap; gap: 8px; list-style: none; margin: 0 0 16px; padding: 0; }
.steps li { padding: 6px 12px; border-radius: 14px; background: var(--gr-risk-low-bg); color: var(--gr-muted);
  font-weight: 600; font-size: 13px; }
.steps li.current { background: var(--gr-primary); color: var(--gr-primary-text); }
.steps li.done { background: var(--gr-ok-bg); color: var(--gr-ok); }
.crumbs { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-bottom: 10px; }
.crumbs button { background: none; border: 0; color: var(--gr-primary); font: inherit; cursor: pointer; padding: 2px 4px; }
.crumbs .sep { color: var(--gr-muted); }
.here { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 6px 0 12px; }
.folders { list-style: none; margin: 0; padding: 0; }
.folder { display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-bottom: 1px solid var(--gr-row-border); }
.folder button.open { flex: 1; background: none; border: 0; padding: 0; font: inherit; color: var(--gr-text);
  text-align: left; cursor: pointer; }
.folder button.open:hover { color: var(--gr-primary); }
.folder .meta { color: var(--gr-muted); font-size: 12.5px; white-space: nowrap; }
.wizard-actions { display: flex; justify-content: space-between; gap: 8px; margin-top: 12px; }

/* users and tokens */
.inline-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
.inline-form .field { margin-bottom: 0; }
.token-once { font-family: var(--gr-mono); padding: 10px; background: var(--gr-ok-bg); color: var(--gr-ok);
  border-radius: var(--gr-radius); word-break: break-all; }
```

- [ ] **Step 6: Regresión y barrido de textos**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`. Si Node está instalado, repite la comprobación de sintaxis de la Tarea 10, Step 11 (sin salida).

Run: `grep -rnE "Disponible en|disponible en|\bH[1-4]\b|/new-open-case|/rerun-case|/review-case|desde la consola en" plugins/ghost_recon/console/static`
Expected: sin salida.

- [ ] **Step 7: Smoke manual en navegador** (o con Playwright si está disponible)

Lanza la demo (Tarea 10, Step 13), entra como `demo` y comprueba:
- [ ] «+ Nueva auditoría» abre el paso 1 con la carpeta de casos y su espacio libre; dentro aparecen «Acme Importaciones» (caso existente · sellado) y «Logística Norte» (nueva), cada una con su número de archivos; la miga de pan vuelve atrás; buscar «norte» encuentra «Logística Norte»;
- [ ] «Elegir» en «Logística Norte» muestra el paso 2: archivos, ZIP, `context.md` con su hash, «Caso: nuevo», la carpeta de salida y los archivos por tipo;
- [ ] «Continuar» muestra el paso 3 con nombre, moneda e idioma, el `context.md`, las notas y el comando exacto; cambiar la moneda a «eu» muestra el error de validación y deshabilita «Lanzar»; «Lanzar en segundo plano» lleva a la vista de la ejecución, que termina con el caso abierto;
- [ ] el asistente sobre «Acme Importaciones» explica que se lanzará un Re-run y el botón dice «Continuar con Re-run»;
- [ ] Sistema muestra «Usuarios y tokens»: crear un usuario con contraseñas distintas da «las contraseñas no coinciden»; con contraseñas iguales aparece en la tabla; «Restablecer contraseña» funciona; «Deshabilitar» y «Hacer viewer» sobre `demo` están deshabilitados con su motivo;
- [ ] «Crear token» muestra el token una sola vez con «Copiar token»; la tabla solo muestra `grt_<prefijo>_…`; «Revocar» lo marca revocado; el registro de la consola (Sistema) muestra `user_add`, `token_create` y `token_revoke` con el usuario `demo`;
- [ ] como `visor`, `#/new` y `#/system/users` muestran que la acción es solo para administradores;
- [ ] la consola del navegador no muestra errores de CSP ni de JS (el 401 de `/auth/me` antes del login y los 4xx de validación que provoques salen como «Failed to load resource»: son esperados).

Detén la demo con Ctrl+C.

- [ ] **Step 8: Commit**

```bash
git add plugins/ghost_recon/console/static
git commit -m "feat(ghost-recon): console new-audit wizard and users and tokens screen

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Documentación, verificación completa, R1 en la máquina real y PR

**Files:**
- Modify: `ghost-recon/COMMANDS.md` (sección 3b completa)
- Modify: `ghost-recon/AGENTS.md` (reglas y "Dónde está cada cosa")
- Modify: `ghost-recon/PLAN.md` (Fase 8 y registro de cambios)
- Modify: `ghost-recon/README.md` (fila de la consola)
- Modify: `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (lo que H2 refinó)
- Modify: `plugins/ghost_recon/plugin.yaml` (`config_schema.console`)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: documentación coherente con el código, las notas de despliegue de la máquina dedicada, el estado de H2 en `PLAN.md` y un PR integrado a `main`. El Step 8 lo ejecuta el **controlador** en la máquina real, no el implementador.

- [ ] **Step 1: `plugin.yaml`**

En `plugins/ghost_recon/plugin.yaml`, sustituye:

```yaml
    description: "Consola web (hermes ghostrecon serve): host, port, session_idle_hours, session_max_days, allowed_hosts. Ver ghost-recon/COMMANDS.md §3b."
```

por:

```yaml
    description: "Consola web (hermes ghostrecon serve): host, port, session_idle_hours, session_max_days, allowed_hosts, case_roots (carpetas de evidencia visibles; obligatoria para lanzar), max_parallel_jobs (por defecto 2), dashboard_url (enlace «Continuar en chat»). Ver ghost-recon/COMMANDS.md §3b."
```

- [ ] **Step 2: `COMMANDS.md`**

Sustituye la sección completa `## 3b. Consola web (sin agente en H1)`, desde su título hasta la línea anterior a `## 4. Herramientas del agente (toolset \`ghost_recon\`)`, por:

````markdown
## 3b. Consola web

```
hermes ghostrecon serve [--host 127.0.0.1] [--port 9230] [--allow-remote]
hermes ghostrecon user add <nombre> [--role admin|viewer] [--password-stdin]
hermes ghostrecon user list | passwd <nombre> [--password-stdin] | disable <nombre> | enable <nombre>
hermes ghostrecon token create --user <nombre> --name <etiqueta>     (Bearer; se muestra una sola vez)
hermes ghostrecon token list | token revoke <id>
```

- Escucha en `127.0.0.1:9230`. Desde otra PC se entra por túnel: `ssh -L 9230:127.0.0.1:9230 usuario@maquina` y luego `http://localhost:9230`.
- `serve` no arranca sin un admin activo: el primero se crea con `user add … --role admin`; los demás usuarios y los tokens también se gestionan desde **Sistema › Usuarios y tokens**. Fuera de loopback exige `--allow-remote` y un proxy TLS delante.
- `--role` es opcional (por defecto `viewer`). `user passwd <nombre> --password-stdin` lee la nueva contraseña de stdin (una línea), igual que `user add`.
- `--allow-remote` con `0.0.0.0` o una IP de Tailscale también exige listar ese nombre o IP en `allowed_hosts`; si no, la consola responde 400 `bad_host`.
- Seguridad de la cookie: la sesión usa una cookie `gr_session_<puerto>` (una por consola) HttpOnly y SameSite=Strict, pero, como cualquier cookie de localhost, también se envía a otros puertos locales. En una PC compartida usa el túnel SSH hacia un puerto local dedicado y pulsa «Salir» al terminar.
- Roles: `viewer` lee, sigue las ejecuciones y descarga entregables de auditorías selladas; `admin` además lanza y cancela ejecuciones, descarga entregables de auditorías abiertas, gestiona usuarios y tokens y ve el registro de la consola.
- **Ejecuciones desde la consola** («+ Nueva auditoría» y, en la página del caso, «▶ Re-run» y «▶ Review»):
  - el navegador de carpetas solo ve las carpetas de `case_roots`; la evidencia se copia antes a una de ellas (RustDesk/SFTP). La consola no sube archivos;
  - cada ejecución corre `<hermes> -p <perfil> --cli --accept-hooks --skills <orden> chat -q "/<orden> …" --format stream-json --source ghost-recon-console` en su propio proceso (`job_runner`), así que sobrevive a cerrar el navegador y a reiniciar la consola. La vista previa muestra exactamente esa orden;
  - las «Notas adicionales» se guardan en `<carpeta de resultados>/_console/context_<hash>.md`, con el `context.md` original literal y su SHA-256; el agente las registra como criterio del operador (`CRIT-nn`), nunca como hecho. El `context.md` original no se toca;
  - límites: una ejecución activa por carpeta o caso y `max_parallel_jobs` en total (por defecto 2); lo demás queda en cola y arranca solo;
  - «Cancelar» detiene el agente y todo lo que lanzó; la auditoría a medio hacer queda abierta, sin sellar, y el siguiente Re-run la continúa. Una ejecución cuyo proceso desaparece sin cerrar queda «interrumpida» (huérfana) y su agente se detiene;
  - «Continuar en terminal» copia `hermes -p <perfil> --resume <session_id>`; con `dashboard_url`, «Continuar en chat» abre la sesión en el dashboard;
  - archivos de cada ejecución en `<plugin-data>/ghost-recon/console/jobs/`: `<id>.jsonl` (salida del agente), `<id>.log` (errores del agente), `<id>.events.jsonl` (actividad) y `<id>.runner.log`.
- API: `/api/v1/…`; el esquema está en `/api/v1/openapi.json`, tras el login.
- Configuración: `plugins.entries.ghost-recon.settings.console` en `config.yaml` (la consola no la edita):

```yaml
plugins:
  entries:
    ghost-recon:
      settings:
        console:
          case_roots: [/home/ghostrecon/GhostRecon/Casos]   # obligatoria para lanzar
          max_parallel_jobs: 2
          dashboard_url: http://127.0.0.1:9119               # opcional: «Continuar en chat»
          # además: host, port, session_idle_hours, session_max_days, allowed_hosts
```

- **Máquina dedicada (Linux):** la consola corre como servicio systemd con el usuario `ghostrecon` y `HERMES_HOME=/home/ghostrecon/.hermes`. El agente y el runner se lanzan con el lanzador de la instalación (`<checkout>/.hermes/bin/hermes`), nunca con lo que haya en el `PATH`. La unidad necesita `KillMode=process`: con el valor por defecto (`control-group`), `systemctl restart` mataría también las auditorías en curso. Si `config.yaml` fija `max_concurrent_sessions`, ese límite también cuenta las ejecuciones de la consola (una que no cabe queda «fallida», con el motivo en el log técnico).
- Demo local sin LLM (agente simulado y carpeta de casos temporal): `python ghost-recon/demo/console_demo.py`.
- Diseño completo y próximos hitos (exportación `.zip`, tablas CSV/XLSX, búsqueda entre casos, avisos): `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`.
````

- [ ] **Step 3: `README.md`**

Sustituye la fila:

```markdown
| Operar desde el navegador (consola web) | `hermes ghostrecon user add <nombre> --role admin` y `hermes ghostrecon serve` → `http://localhost:9230` (por túnel desde otra PC) · [`COMMANDS.md`](COMMANDS.md) §3b · demo: `python ghost-recon/demo/console_demo.py` |
```

por:

```markdown
| Operar desde el navegador (consola web): lanzar auditorías, seguirlas en vivo y consultar casos | `case_roots` en `config.yaml`, `hermes ghostrecon user add <nombre> --role admin` y `hermes ghostrecon serve` → `http://localhost:9230` (por túnel desde otra PC) · [`COMMANDS.md`](COMMANDS.md) §3b · demo: `python ghost-recon/demo/console_demo.py` |
```

- [ ] **Step 4: `AGENTS.md`**

En "Reglas de edición", sustituye:

```markdown
- La consola (`plugins/ghost_recon/console/`) **solo escribe tablas `console_*`**; los datos de caso se leen por `core`
  (`Store`, `service`). Todo path que llega del navegador pasa por `console/paths.resolve_within`. En el frontend,
  nada de `innerHTML` con datos: siempre `h()` (`static/lib/dom.js`).
```

por:

```markdown
- La consola (`plugins/ghost_recon/console/`) **solo escribe** sus tablas `console_*`, el archivo de contexto combinado
  (`<resultados>/_console/context_<hash>.md`) y los eventos `console_job_*` de la cronología del caso (con
  `Store.add_event`); los datos de caso se leen por `core` (`Store`, `service`). Toda carpeta que llega del navegador
  pasa por `console/fsjail.resolve` (dentro de `case_roots`) y toda descarga por `console/paths.resolve_within`. En el
  frontend, nada de `innerHTML` con datos: siempre `h()` (`static/lib/dom.js`).
- Procesos de la consola: lo que toca internos de Hermes para lanzar, vigilar o detener ejecuciones vive solo en
  `console/procs.py` (lanzador de la instalación, entorno del perfil, desacople, árbol con psutil e identidad PID +
  create time). La orden (`commands.py`), las fases (`events.py`) y los límites (`jobs.py`) son Python probado; el JS
  solo pinta. Toda escritura de estado de un job es condicional (`update_job(..., expect=...)`).
- La UI no nombra hitos ni comandos: lo que aún no existe aparece deshabilitado con el aviso «Próximamente».
```

y, en "Dónde está cada cosa", añade al final de la tabla:

```markdown
| cambiar una orden lanzable o su texto `-q` | `console/commands.py` (`ORDERS`, `build_query`) + la skill de la orden |
| cambiar cómo se deducen las fases o el feed de una ejecución | `console/events.py` (`PHASES`, `_FIXED_PHASE`, `_SUMMARY`) |
| cambiar límites, cola, cancelación o huérfanos | `console/jobs.py` (`JobService`) y `console/job_runner.py` |
| cambiar qué carpetas ve el navegador de la consola | `console/fsjail.py` y `case_roots` en la configuración |
```

- [ ] **Step 5: `PLAN.md`**

Sustituye:

```markdown
- [ ] H2 · Ejecuciones: navegador de carpetas, asistente Nueva auditoría con notas de contexto, motor de jobs desacoplado, vista en vivo, Re-run/Review
  - Pendientes de la revisión final de H1 (antes de tocar el esquema):
    - migraciones versionadas de `console_*` con tabla de versión de una fila
    - lock en la contabilidad del bloqueo de login
    - `touch_session` best-effort y cabeceras de seguridad en los 500
    - prueba E2E real con `HERMES_HOME` temporal + `config.yaml`
    - purga de sesiones vencidas
- [ ] H3 · Exportación `.zip` verificable, tablas CSV/XLSX, búsqueda entre casos, avisos, verificación de hash al descargar entregables de auditorías selladas (409 `hash_mismatch`, registro de descargas denegadas)
- [ ] H4 · Instaladores `--console`/servicio, `CONSOLE.md`, aceptación en la máquina dedicada
```

por:

```markdown
- [x] H2 · Ejecuciones: navegador de carpetas (`case_roots`), asistente Nueva auditoría con notas de contexto, Re-run/Review desde el caso, motor de jobs desacoplado (límites, cola, cancelación del árbol, huérfanos, supervivencia al reinicio), vista en vivo (SSE), lista de Ejecuciones, Usuarios y tokens en Sistema, migraciones versionadas de `console_*`, UI sin nombres de hito
  - [ ] R1 verificado en la máquina dedicada (plan H2, Tarea 12, Step 8)
- [ ] H3 · Exportación `.zip` verificable, tablas CSV/XLSX, búsqueda entre casos, avisos, verificación de hash al descargar entregables de auditorías selladas (409 `hash_mismatch`, registro de descargas denegadas)
  - Pendientes de la revisión final de H1 que no entraron en H2:
    - lock en la contabilidad del bloqueo de login
    - `touch_session` best-effort y cabeceras de seguridad en los 500
    - prueba E2E real con `HERMES_HOME` temporal + `config.yaml`
    - purga de sesiones vencidas
- [ ] H4 · Instaladores `--console`/servicio (unidad systemd con `KillMode=process`), `CONSOLE.md`, aceptación en la máquina dedicada
```

y, en "## 4. Registro de cambios de este plan", añade al final:

```markdown
- 2026-10-03 · v1.4 · H2 de la consola implementado: navegador de carpetas limitado a `case_roots`, asistente «+ Nueva auditoría» y Re-run/Review con notas del operador (contexto combinado en `_console/`, nunca en la evidencia), orden exacta en la vista previa, un `job_runner` desacoplado por ejecución (límites, cola, cancelación del árbol con psutil, huérfanos, supervivencia al reinicio), vista en vivo por SSE, Usuarios y tokens en Sistema, migraciones versionadas. E2E con agente falso y servidor real. Sin cambios al core de Hermes.
```

- [ ] **Step 6: Spec (lo que H2 refinó)**

En `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (cada cambio es una sustitución exacta):

§3 (alcance). Sustituye:

```text
los avisos, el instalador del servicio y la documentación.
```

por:

```text
los avisos, el instalador del servicio, la administración de usuarios y tokens desde Sistema (además del CLI) y la documentación.
```

y borra la línea:

```text
- una pantalla de administración de usuarios (en v1 se hace por CLI);
```

§4.1 (árbol). Sustituye:

```text
├── job_runner.py     proceso desacoplado: ejecuta el agente, persiste salida y estado, notifica
```

por:

```text
├── job_runner.py     proceso desacoplado: ejecuta el agente, persiste salida y estado, notifica
├── procs.py          procesos con Hermes: lanzador de la instalación, entorno del perfil, desacople, árbol (psutil)
├── jobfiles.py       archivos por ejecución (<id>.jsonl, .log, .events.jsonl, .runner.log), lectura incremental
```

y sustituye:

```text
├── routers/          auth.py system.py fs.py cases.py audits.py jobs.py exports.py search.py
```

por:

```text
├── routers/          auth.py system.py fs.py cases.py audits.py jobs.py users.py exports.py search.py
```

§5 (modelo de datos). Sustituye:

```text
                   (se completa al abrir), folder (absoluta), args JSON (validados), context_file,
                   status (queued|running|succeeded|failed|cancelled|orphaned), pid, runner_pid,
```

por:

```text
                   (se completa al abrir), folder (absoluta), args JSON (validados), argv JSON (la orden
                   exacta que se ejecuta), context_file,
                   status (queued|running|succeeded|failed|cancelled|orphaned), pid, pid_started,
                   runner_pid, runner_started (create time: identidad frente a PID reciclados),
```

y sustituye:

```text
Sesiones y tokens se guardan solo como SHA-256. El token en claro se muestra una única vez.
```

por:

```text
Sesiones y tokens se guardan solo como SHA-256. El token en claro se muestra una única vez.

`console_schema_version` tiene una sola fila; `migrate()` aplica en orden las migraciones por encima de la versión guardada (v1 = tablas de H1, v2 = `console_jobs`).
```

§6.2 (ciclo de vida). Sustituye:

```text
El despacho se reevalúa al arrancar el servidor, al terminar un job y cada 10 s.
```

por:

```text
El despacho se reevalúa al arrancar el servidor, tras cada lanzamiento o cancelación y cada 10 s (el ciclo también recoge los runners terminados). Repetir la misma orden sobre una carpeta que ya la tiene activa o en cola responde `409 already_active`; una orden distinta queda en cola.
```

y sustituye:

```text
   - marca `running` con `runner_pid`;
```

por:

```text
   - el servidor registra `runner_pid` y su create time al lanzarlo; el runner confirma `running` (si encuentra la fila cancelada, sale sin lanzar el agente) y ejecuta el argv guardado en la fila, sin reconstruirlo;
```

y sustituye:

```text
Se comprueba al arrancar el servidor y en cada ciclo de despacho, y se muestra la cola del log.
```

por:

```text
Se comprueba al arrancar el servidor y en cada ciclo de despacho, y se muestra la cola del log. El agente que quedó sin runner se detiene (árbol completo), para que nunca haya dos agentes sobre la misma carpeta.
```

§7 (contexto del operador). Sustituye:

```text
- Al lanzar, si hay notas, la consola escribe `<salidas>/_console/context_<job>.md`.
```

por:

```text
- Al lanzar, si hay notas, la consola escribe `<salidas>/_console/context_<hash>.md` (12 caracteres del SHA-256 de: hash del original, usuario y notas; el nombre no depende del id del job, así que la vista previa muestra exactamente la orden que se ejecutará).
```

y sustituye:

```text
# Contexto de la ejecución <job> (<orden>)
```

por:

```text
# Contexto de la ejecución (<orden>) · consola Ghost Recon
```

y sustituye:

```text
- Ese archivo es el `context_file` que recibe la orden. Si no hay notas, se pasa el `context.md` original tal cual, o nada.
```

por:

```text
- Ese archivo es el `context_file` que recibe la orden. Si no hay notas, se pasa el `context.md` original tal cual, o nada.
- Si el `context.md` cambia entre la vista previa y el lanzamiento, el lanzamiento responde `409 context_changed`.
```

§8 (API). Sustituye:

```text
| Búsqueda | `GET /search?q=&types=case,finding,evidence,criteria&limit=` | viewer |
```

por:

```text
| Búsqueda | `GET /search?q=&types=case,finding,evidence,criteria&limit=` | viewer |
| Usuarios | `GET /users`, `POST /users`, `POST /users/{u}/password`, `POST /users/{u}/enable\|disable`, `POST /users/{u}/role`, `GET /tokens`, `POST /tokens` (el token en claro solo en esta respuesta), `POST /tokens/{id}/revoke` | **admin** (nadie se deshabilita ni se cambia el rol a sí mismo; el último admin activo no se puede deshabilitar ni degradar) |
```

y sustituye:

```text
- Lecturas: la consola abre la BD con `busy_timeout` (≥ 5 s) y solo escribe tablas `console_*`. SQLite en WAL permite leer mientras los agentes escriben.
```

por:

```text
- `GET /jobs/{id}/events/stream` emite `event` (id = seq; al reconectar se reanuda desde `Last-Event-ID`), `status` (cambios de estado, fase, sesión o caso), `end` y un comentario de latido cada 15 s.
- Lecturas: la consola abre la BD con `busy_timeout` (≥ 5 s) y solo escribe tablas `console_*`. SQLite en WAL permite leer mientras los agentes escriben.
```

§10 (punto 8, Sistema). Sustituye:

```text
   - para admin, el registro de auditoría de la consola.
```

por:

```text
   - para admin, el registro de auditoría de la consola y «Usuarios y tokens» (crear, restablecer contraseña, habilitar o deshabilitar, cambiar rol; crear tokens —se muestran una vez— y revocarlos).
```

§13 (hitos). Sustituye:

```text
Es usable por sí solo: lo que depende de un hito posterior aparece deshabilitado, con el texto "disponible en H2/H3". Por ejemplo, la pestaña Ejecuciones y los botones de lanzar y exportar en H1.
```

por:

```text
Es usable por sí solo: lo que depende de un hito posterior aparece deshabilitado con el aviso «Próximamente», sin nombres de hito ni comandos (decisión del propietario en H2).
```

§15 (riesgos). Sustituye:

```text
| R7 | `--source` podría no aceptar un valor libre | Verificar en H2; si no, se usa el valor por defecto y se filtra por `session_id` |
```

por:

```text
| R7 | `--source` podría no aceptar un valor libre | Resuelto en H2: `--source` acepta cualquier valor (`hermes_cli/main.py` lo pone en `HERMES_SESSION_SOURCE`); la consola usa `ghost-recon-console` |
| R8 | Con `KillMode=control-group` (el valor por defecto de systemd), reiniciar el servicio mata las auditorías en curso | La unidad de la consola usa `KillMode=process` (H4 lo fija en el instalador; documentado en `COMMANDS.md` §3b) |
| R9 | `max_concurrent_sessions` en `config.yaml` puede rechazar una ejecución | El runner la marca `failed` con el motivo en el log técnico; documentado en `COMMANDS.md` §3b |
```

- [ ] **Step 7: Verificación completa**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py tests/skills/test_authoring_standards.py tests/skills/test_skill_docs_contract.py tests/hermes_cli/test_plugin_cli_registration.py tests/hermes_cli/test_plugin_api_compat.py -q`
Expected: `0 failed`. Los skipped son solo las pruebas de pack completo sin libs opcionales y las marcadas para otro SO.

Run: `.venv/Scripts/python.exe ghost-recon/demo/smoke_test.py` (o `.venv/bin/python …`)
Expected: `SMOKE TEST OK`. El smoke construye el pack completo, así que necesita las dependencias opcionales del plugin (`openpyxl`, `reportlab`); en un venv sin ellas solo falla el check «pack … without warnings», que no depende de este hito: anótalo en el PR en vez de instalar nada con pip.

Run: `grep -rnE "Disponible en|disponible en|\bH[1-4]\b|/new-open-case|/rerun-case|/review-case|desde la consola en" plugins/ghost_recon/console/static`
Expected: sin salida.

Run: `git diff --stat origin/main...HEAD -- . ':!plugins/ghost_recon' ':!ghost-recon' ':!tests/plugins/ghost_recon'`
Expected: salida vacía (ningún archivo fuera del vertical).

- [ ] **Step 8 (controlador, no implementador): verificar R1 en la máquina dedicada**

Con claves reales y como el usuario `ghostrecon`:
1. Copia un caso pequeño (por ejemplo `ghost-recon/demo/demo-case`) a `/home/ghostrecon/GhostRecon/Casos/R1-mini`.
2. Lánzalo desde la consola: «+ Nueva auditoría» → `R1-mini` → «Lanzar en segundo plano».

Evidencia esperada:
- la ejecución termina `terminada` (`succeeded`) y la barra de fases recorre Caso → … → Sello;
- `<plugin-data>/ghost-recon/console/jobs/<id>.jsonl` contiene, en ese orden, `tool_use` de `gr_case_open`, `gr_audit_start`, `gr_swarm_plan`, `gr_report_build` y `gr_audit_seal`, y un `result` con `exit_code: 0`;
- `hermes -p <perfil> ghostrecon audits /home/ghostrecon/GhostRecon/Casos/R1-mini` muestra `A01 … sealed`.

Si el agente responde sin ejecutar la skill completa, aplica la alternativa de R1: redacta el texto `-q` como «Ejecuta la orden /new-open-case … siguiendo la skill precargada» en `commands.build_query` (con su prueba en `test_commands.py`), repite la verificación y anota el resultado en `PLAN.md` (casilla de R1) y en §15 de la spec.

- [ ] **Step 9: Commit de documentación**

```bash
git add plugins/ghost_recon/plugin.yaml ghost-recon
git commit -m "docs(ghost-recon): console H2 commands, deployment notes, area rules and plan status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 10: Integrar con `main` y abrir el PR**

Antes de abrir el PR, escribe `pr_body.md` en el directorio temporal de la sesión (fuera del repo) con estas secciones:
- **Resumen:** el alcance de H2 (Fase 8 de `PLAN.md`), las decisiones del propietario (Usuarios y tokens en la UI, sin nombres de hito, sin editor de configuración, sin subida de evidencia) y el enlace a la spec y a este plan;
- **Pruebas:** la salida de resumen del Step 7 en cifras reales, `SMOKE TEST OK` y el resultado del E2E (`test_jobs_e2e.py`);
- **Smoke manual:** las casillas marcadas de las Tareas 10 y 11;
- **Despliegue:** `case_roots`, `KillMode=process` y la verificación de R1 pendiente del controlador (Step 8);
- **Alcance:** la salida vacía del `git diff --stat` fuera del vertical;
- al final, la línea `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

```bash
git fetch origin main
git merge --no-edit origin/main          # main avanza a menudo (sincronizaciones con upstream)
bash scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_skill_docs_contract.py -q
git push -u origin ghost-recon-console
gh pr create -R SiteOneTech/agent-ghost-recon-forensic-finance --base main --head ghost-recon-console \
  --title "feat(ghost-recon): console H2 — jobs (folder browser, new audit wizard, live runs, users)" --body-file "$TMPDIR/pr_body.md"
```

Expected: el PR queda abierto con la CI verde; la casilla de R1 de `PLAN.md` se marca cuando el controlador complete el Step 8.

---

## Autorrevisión del plan (cobertura de la spec)

| Requisito H2 | Dónde |
|---|---|
| §6.1 tabla de órdenes, validación, `-q` por skill, argv sin shell, `--source` libre (R7) | Tarea 4 (`commands.py`, `test_commands.py`) |
| §6.1 preview = argv real | Tareas 4, 6 y 7 (`plan()` único; `test_the_preview_is_*`, argv registrado por el agente falso) |
| §6.2 cola y límites (carpeta/caso + `max_parallel_jobs`), despacho al arrancar y cada 10 s | Tarea 6 (`JobService.dispatch/tick/start`) |
| §6.2 runner desacoplado, estados, `session_id`, `phase`, resultado, cronología del caso | Tarea 5 (`job_runner.py`, `test_runner.py`) |
| §6.2 cancelar mata el árbol (psutil) — una prueba por SO | Tareas 5 y 6 (`kill_tree`, pruebas `posix`/`windows`) |
| §6.2 huérfanos al arrancar y en cada ciclo; el servidor nunca es padre necesario | Tareas 6 y 8 (`reconcile`, reinicio real del servidor) |
| §6.3 eventos y fases (tabla), agrupación, texto acumulado, progreso del enjambre | Tarea 3 (`events.py`, `test_events.py`) |
| §6.4 lectura en vivo `events?after=` y SSE | Tarea 7 (`routers/jobs.py`, `test_api_jobs.py`) |
| §7 contexto combinado (original literal + hash + notas firmadas), nunca en la evidencia | Tareas 4 y 7 |
| §8 Carpetas (`/fs/*`) y Ejecuciones (`/jobs*`, `/cases/{id}/jobs`), roles | Tarea 7 |
| §9 rutas (realpath, `..`, symlink, UNC, otra unidad, ocultos, búsqueda acotada) | Tarea 2 (`fsjail.py`, `test_fsjail.py`) |
| §10.5 asistente en 3 pasos | Tareas 10 (panel de lanzamiento) y 11 (`wizard.js`) |
| §10.6 Ejecución (Cancelar, Continuar en terminal/chat, fases, feed, «Hasta ahora», resultado, log) | Tarea 10 (`job.js`) |
| §10.7 Ejecuciones con filtros | Tarea 10 (`jobs.js`) |
| Re-run y Review desde el caso; pestaña Ejecuciones; Inicio en vivo | Tareas 7 y 10 |
| §12 `case_roots`, `max_parallel_jobs`, `dashboard_url` | Tarea 1 (ajustes) y Tarea 12 (documentación) |
| §13 aceptación: E2E con agente falso | Tarea 8 (`test_jobs_e2e.py`) |
| §14 fsjail, órdenes, contexto, jobs E2E, eventos | Tareas 2–8 |
| Decisión B1: Usuarios y tokens en la UI | Tareas 9 (API) y 11 (`users.js`) |
| Decisiones B2–B4: textos, `case_roots` vacío, sin subida | Tareas 10–11 (barrido), Tarea 7 (`hint`), Global Constraints |
| Decisiones C y E: despliegue documentado, R1 en la máquina real | Tarea 12 |
