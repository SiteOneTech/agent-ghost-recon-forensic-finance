# Consola Ghost Recon · H3 (Exportación y extras) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el operador se lleve los resultados de un caso como un `.zip` íntegro y verificable, y que la consola quede completa para el uso diario:
- exportación `.zip` del caso o de una auditoría con `EXPORT_MANIFEST.json`, construida en segundo plano con progreso, ZIP64, SHA-256 y archivo `.sha256`, solo auditorías selladas salvo que un admin incluya las abiertas (marcadas como borrador), nunca la evidencia y bloqueada por un sello roto;
- tablas del caso (Hallazgos, Evidencia, Cronología, Criterios) a CSV y XLSX con los filtros activos;
- búsqueda entre casos en la barra superior, filtro «riesgo abierto» en Casos y «verificado hace X» en los sellos;
- avisos al terminar una ejecución: notificación del navegador y `hermes send` al `notify_target`;
- descarga de entregables comprobada contra el sello (409 `hash_mismatch`) y los pendientes de las revisiones de H1 y H2 (bloqueo de login con candado, `touch_session` sin errores, 500 con cabeceras, purga de sesiones, E2E en un `HERMES_HOME` real, retención de archivos de ejecuciones, SSE que revalida al usuario, despacho robusto, asistente sin callejones sin salida).

**Architecture:**
- Todo vive en `plugins/ghost_recon/console/`, encima de H1 y H2:
  - `integrity.py` decide si un archivo de una auditoría sellada sigue siendo el sellado (SEALED.json + hash registrado) y guarda cada verificación en la caché de sellos; lo usan la descarga de entregables y el ZIP;
  - `exporter.py` elige las auditorías, verifica los sellos, empaqueta solo la carpeta de resultados (sin enlaces simbólicos ni uniones), vuelve a hashear cada archivo sellado al empaquetarlo y escribe el manifiesto; `exports.py` (`ExportService`) encola y construye en un hilo, una exportación a la vez, con su fila en `console_exports`;
  - `tables.py` convierte las filas de las tablas del caso en CSV/XLSX; las filas salen de `readmodel.TABLE_ROWS`, la misma fuente que los endpoints JSON;
  - `search.py` busca entre casos leyendo con `Store`, acotada en tamaño y tiempo;
  - `housekeeping.py` concentra la limpieza periódica (sesiones, ZIP antiguos, archivos de ejecuciones antiguas);
  - el aviso por `hermes send` lo planifica el servidor al lanzar (`console_jobs.notify_argv`, como el argv del agente) y lo envía el runner al terminar.
- La única migración nueva es la v3 de `console_*` (`console_exports` y la columna `notify_argv`), aplicada bajo `BEGIN IMMEDIATE` para que dos procesos que abren la BD a la vez nunca la repitan.
- El core de Hermes no cambia.

**Tech Stack:** Python 3.14, FastAPI/Starlette y uvicorn, SQLite (WAL), `zipfile` (ZIP64), `csv`, openpyxl (dependencia del plugin, importada solo para XLSX), psutil, pytest con `scripts/run_tests.sh`, JS en módulos ES nativos y CSS con variables.

**Spec:** `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (léela entera antes de empezar; este plan implementa su hito H3, §13, más los pendientes de `ghost-recon/PLAN.md` Fase 8 y las decisiones recogidas en Global Constraints). Planes anteriores, para convenciones: `ghost-recon/specs/plans/2026-10-02-console-h1-base.md` y `ghost-recon/specs/plans/2026-10-03-console-h2-jobs.md`.

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

Además, en H3:

- **Escrituras permitidas, completas:** tablas `console_*` (más `console_exports`); el archivo de contexto combinado y los eventos `console_job_*` de H2; el evento `results_exported` en la cronología del caso (con `Store.add_event`, usuario como actor y el SHA-256 del ZIP); los ZIP, sus `.sha256` y nada más en `<plugin-data>/ghost-recon/console/exports/`; y el **borrado** de ZIP vencidos y de archivos de ejecuciones terminadas (`console/jobs/<id>.*` y `<id>/`). Nunca nada dentro de la carpeta de un caso.
- **openpyxl** es `python_dependency` del plugin (`plugin.yaml`), no del core: se importa solo al pedir un XLSX y, si falta, la respuesta es `503 xlsx_unavailable` con un mensaje claro; CSV y todo lo demás siguen funcionando.
- **ZIP (spec §11):**
  - alcance `case` (todas las auditorías) o `audit` (`seq` = `A0n`/`R0n`); por defecto solo auditorías **selladas**; `include_unsealed=true` solo para admin (un viewer recibe 403) y las abiertas van con `"state": "DRAFT"`; mientras el caso tenga una ejecución en cola o en curso, sus auditorías abiertas **nunca** entran;
  - contenido: `case.json`, `corpus_inventory.csv`, `_console/`, las carpetas completas de las auditorías elegidas (las revisiones `reviews/R0n_…` incluidas) y `EXPORT_MANIFEST.json`. Solo se lee la carpeta de resultados del caso; enlaces simbólicos y uniones NTFS nunca se siguen (quedan en `skipped`); cada archivo debe resolver dentro de esa carpeta; una carpeta de resultados que contenga la del caso se rechaza (`409 results_hold_evidence`). **Nunca** la evidencia original;
  - antes de empaquetar se verifica cada sello (y se guarda como verificación del sello); un sello roto bloquea con `409 seal_broken` y el mensaje nombra el archivo; cada archivo sellado se vuelve a hashear al empaquetarlo, así que un cambio durante la construcción también la para; nunca queda un ZIP a medias (`<nombre>.part` y renombrado al final);
  - manifiesto: `{export_id, case_id, case_name, scope, seq, draft, audits:[{id, seq, kind, sealed, state, seal_sha256, verified_at}], excluded:[{id, seq, reason}], skipped:[{path, reason}], files:[{path, size, sha256}], exported_by, exported_at, generator: "Ghost Recon Console <versión>"}`;
  - nombre `GhostRecon_<slug>_<scope>_<YYYYMMDD-HHMM>.zip` en UTC, con `<scope>` = `case` o la secuencia y `-DRAFT` si lleva abiertas; dos exportaciones en el mismo minuto nunca comparten archivo (la segunda lleva `_e<id>`); al lado, `<zip>.sha256` en formato `sha256sum -c` (`<hash>  <nombre>\n`, LF);
  - construcción en segundo plano, una a la vez, con progreso por archivos (`files_done`/`files_total`) y ZIP64; un reinicio del servidor marca como fallidas las exportaciones que quedaron en cola o a medias y borra sus `.part`;
  - retención `export_retention: {count: 20, days: 30}`: se conservan como mucho las últimas `count` y ninguna con más de `days` días; la fila queda como `expired`.
- **Tablas:** `GET /cases/{id}/{table}.csv|.xlsx` con `table ∈ {findings, evidence, timeline, criteria}` y los mismos filtros que su endpoint JSON (hallazgos: `kind`, `risk`, `status`, `q`; evidencia: `status`, `audit`, `q`; sin paginar). CSV en UTF-8 con BOM, coma y CRLF; un texto que empieza por `=`, `+`, `-`, `@`, tabulador o retorno de carro y no es un número sale con un apóstrofo delante. XLSX: una hoja, encabezado en negrita, `creator` «Ghost Recon (www.ghostrecon.ai)», `lastModifiedBy` «Ghost Recon», `title`, `subject`, `description` = `SIGNATURE`, `keywords` y `Application` = `ENGINE` en `docProps/app.xml` (con `core.reports.xlsx.rewrite_app_xml`); un texto que parece fórmula queda como texto.
- **Descargas de entregables:** en una auditoría sellada el archivo se vuelve a hashear y debe coincidir con su entrada en `SEALED.json` y con `reports.sha256`; si no, `409 hash_mismatch`. Toda descarga rechazada (`not_sealed`, `file_missing`, `hash_mismatch`) queda en `console_audit_log` como `report_download_denied`.
- **Búsqueda:** `GET /search?q=&types=case,finding,evidence,criteria&limit=` para viewer; `q` de 2 a 100 caracteres; `limit` de 1 a 50 por tipo (por defecto 10); el recorrido se corta a los 2 s (`timed_out`); solo lee la BD a través de `Store`. `GET /cases?risk=` acepta `any`, `critical`, `high`, `medium` o `low`.
- **Avisos:** en el navegador, con el interruptor «Avisarme al terminar» y el permiso del navegador, mientras la consola está abierta; por gateway, `hermes -p <perfil> send --to <notify_target> --subject "[Ghost Recon]" "<resumen>"` desde el runner cuando la ejecución termina o falla (nunca si se cancela o queda huérfana), sin shell, con 60 s de tiempo máximo, sin cambiar nunca el estado del job; el resumen neutraliza `MEDIA:` y redacta secretos; `notify_target` vacío = sin envío.
- **Ajustes nuevos** (spec §12): `notify_target` (`""`), `export_include_unsealed` (`false`, solo aplica a admins) y `export_retention` (`{count: 20, days: 30}`).
- **Mantenimiento en un solo sitio** (`housekeeping.py`), al arrancar y cada hora: sesiones vencidas o revocadas; ZIP fuera de retención; archivos de ejecuciones terminadas hace más de `export_retention.days` días (nunca de una activa).
- **Pendientes de H1 y H2:** el intento de login cuenta antes de scrypt y bajo un candado; `touch_session`/`touch_token` nunca hacen fallar una lectura; un error no controlado responde 500 con el sobre de error y las cabeceras de seguridad; el SSE vuelve a comprobar quién mira cada `HEARTBEAT_S`; un fallo al lanzar el runner de una ejecución nunca corta el despacho de las demás; el asistente siempre ofrece volver a las carpetas de casos.
- La raíz del repositorio ignora `export*` en `.gitignore`: la Tarea 4 añade `plugins/ghost_recon/console/.gitignore` con `!export*` para que `exporter.py`, `exports.py`, `routers/exports.py` y `static/views/export.js` se versionen. No se toca el `.gitignore` raíz.
- La UI no menciona hitos ni comandos y, al terminar H3, **no queda ningún «Próximamente»**.

## Review Focus

1. **Doble clic en «Exportar».** Dos exportaciones del mismo caso en el mismo minuto producirían el mismo nombre: la segunda sobrescribiría a la primera mientras alguien la descarga y su SHA-256 dejaría de cuadrar. Cada una debe tener su archivo y su hash. La prueba vive en la Tarea 5.
2. **Reinicio del servidor durante una construcción.** Un `systemctl restart` a mitad de un ZIP grande dejaría la fila «building» para siempre y un `.part` huérfano. Al arrancar, esas exportaciones deben quedar fallidas con un motivo claro y sin archivos a medias. La prueba vive en la Tarea 6.
3. **Texto que Excel ejecutaría.** Un título de hallazgo o una línea de OCR que empieza por `=` (`=HYPERLINK(…)`), `+`, `-` o `@` no debe convertirse en fórmula al abrir el CSV o el XLSX; un importe negativo debe seguir siendo un número. La prueba vive en la Tarea 4.
4. **Nombres con acentos y eñes.** «Conciliación año 2026 — señal.md» debe viajar en el ZIP con su nombre UTF-8 (bandera 0x800) y figurar igual en el manifiesto, para abrirse intacto en Windows y macOS. La prueba vive en la Tarea 5.
5. **Un archivo sellado cambia durante la construcción.** El sello pasó la verificación previa, pero alguien toca un entregable antes de empaquetarlo: la exportación debe fallar nombrando el archivo y sin dejar ZIP. La prueba vive en la Tarea 5.

## Mapa de archivos

| Archivo | Acción | Responsabilidad | Tarea |
|---|---|---|---|
| `plugins/ghost_recon/console/settings.py` | Reemplazar | `notify_target`, `export_include_unsealed`, `export_retention` | 1 |
| `plugins/ghost_recon/console/store.py` | Modificar | migración v3 (`console_exports`, `notify_argv`) bajo `BEGIN IMMEDIATE`, filas de exportación, purga de sesiones | 1 |
| `plugins/ghost_recon/console/auth.py` | Modificar | candado del bloqueo con el intento contado antes de scrypt; `touch` sin errores | 2 |
| `plugins/ghost_recon/console/deps.py` | Modificar | `resolve_principal` (T2); `ConsoleContext.exports` (T6) | 2, 6 |
| `plugins/ghost_recon/console/app.py` | Modificar | 500 con sobre y cabeceras (T2); routers (T4, T7); `ExportService` y `Housekeeping` en el lifespan (T6) | 2, 4, 6, 7 |
| `plugins/ghost_recon/console/routers/jobs.py` | Modificar | el SSE revalida al usuario | 2 |
| `plugins/ghost_recon/console/integrity.py` | Crear | sello frente a archivo: verificación cacheada, hashes del sello, bytes verificados | 3 |
| `plugins/ghost_recon/console/downloads.py` | Crear | respuesta de adjunto con `Content-Disposition` | 3 |
| `plugins/ghost_recon/console/routers/audits.py` | Reemplazar | verificación vía `integrity`; descarga comprobada y rechazos registrados | 3 |
| `plugins/ghost_recon/console/readmodel.py` | Modificar | `TableFilters`, `TABLE_ROWS` (T4); `risk` en `list_cases` (T7) | 4, 7 |
| `plugins/ghost_recon/console/routers/cases.py` | Modificar | filas desde `TABLE_ROWS` (T4); filtro `risk` (T7) | 4, 7 |
| `plugins/ghost_recon/console/tables.py` | Crear | tablas a CSV/XLSX | 4 |
| `plugins/ghost_recon/console/routers/exports.py` | Crear (T4) y reemplazar (T6) | tablas (T4); ZIP: vista previa, petición, estado, descarga, `.sha256` (T6) | 4, 6 |
| `plugins/ghost_recon/console/.gitignore` | Crear | reincluir `export*` bajo la consola | 4 |
| `plugins/ghost_recon/console/exporter.py` | Crear | selección, verificación, empaquetado y manifiesto del ZIP | 5 |
| `plugins/ghost_recon/console/exports.py` | Crear | `ExportService`: cola, hilo, filas, auditoría, cronología, recuperación | 6 |
| `plugins/ghost_recon/console/housekeeping.py` | Crear | limpieza periódica en un solo sitio | 6 |
| `plugins/ghost_recon/console/search.py`, `routers/search.py` | Crear | búsqueda entre casos | 7 |
| `plugins/ghost_recon/console/commands.py` | Modificar | `NOTIFY_SUBJECT`, `ORDER_LABELS`, `notify_args` | 8 |
| `plugins/ghost_recon/console/jobs.py` | Modificar | `notify_argv` al lanzar; `_start_runner` robusto | 8 |
| `plugins/ghost_recon/console/job_runner.py` | Modificar | `notify_message` y envío al terminar | 8 |
| `ghost-recon/demo/fake_agent.py` | Modificar | modo `send` (registra su argv) | 8 |
| `tests/plugins/ghost_recon/console/serve_hermes.py` | Crear | `hermes ghostrecon serve` real con el agente falso (no es una prueba) | 9 |
| `plugins/ghost_recon/console/static/lib/{format,api}.js` | Modificar / reemplazar | «verificado hace X»; descargas en página | 10 |
| `plugins/ghost_recon/console/static/views/components.js` | Modificar | `downloadButton`, `tableExport` | 10 |
| `plugins/ghost_recon/console/static/views/{cases,wizard}.js`, `views/case/{findings,evidence,criteria,timeline,audits}.js` | Modificar / reemplazar | filtro de riesgo, CSV/XLSX, entregables, volver a las raíces | 10 |
| `plugins/ghost_recon/console/static/views/export.js`, `views/search.js`, `lib/notices.js` | Crear | diálogo del ZIP, búsqueda superior, avisos | 11 |
| `plugins/ghost_recon/console/static/{app.js,views/case.js,views/job.js,views/case/audits.js}` | Modificar | búsqueda y avisos en la barra; botones ZIP vivos | 11 |
| `plugins/ghost_recon/console/static/app.css` | Modificar | estilos de exportación, búsqueda y avisos | 10, 11 |
| `tests/plugins/ghost_recon/console/test_*.py` | Crear / ampliar | `store_exports`, `hardening`, `download_integrity`, `tables`, `exporter`, `api_exports`, `housekeeping`, `search`, `notify`, `jobs`, `hermes_home_e2e` | 1–9 |
| `ghost-recon/{COMMANDS,AGENTS,PLAN,README}.md`, spec, `plugin.yaml` | Modificar | documentación de H3 | 12 |

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
Expected: `0 failed`. Sin `openpyxl` ni `reportlab` en el venv de pruebas hay skipped del pack completo; las pruebas marcadas para otro SO también salen como skipped.

- [ ] **Step 3: Saber si openpyxl está disponible.** Las pruebas de XLSX usan `pytest.importorskip("openpyxl")` (dependencia del plugin, no del grupo de pruebas del core): sin él salen como skipped y la ruta de 503 se prueba igualmente con un sustituto. No instales nada en el venv con pip.

Run: `.venv/Scripts/python.exe -c "import openpyxl"` (o `.venv/bin/python …`)
Expected: o nada (está) o `ModuleNotFoundError` (no está; anótalo para el PR).

---
### Task 1: Ajustes de H3 y esquema v3 (`console_exports`, `notify_argv`, purga de sesiones)

**Files:**
- Modify (reemplazar): `plugins/ghost_recon/console/settings.py`
- Modify: `plugins/ghost_recon/console/store.py`
- Test: `tests/plugins/ghost_recon/console/test_store_exports.py`

**Interfaces:**
- Consumes: `ConsoleStore._insert/_one/_all/_update`, `_j`, `migrate_console` y `CONSOLE_MIGRATIONS` de H2.
- Produces:
  - `ConsoleSettings` gana `notify_target: str = ""` (un destino de `hermes send --to`, o `""` si falta o no tiene forma válida), `export_include_unsealed: bool = False`, `export_retention_count: int = 20` y `export_retention_days: int = 30` (de `export_retention: {count, days}`). `from_mapping` y `load_settings` mantienen su firma.
  - `store.py`:
    - `CONSOLE_SCHEMA_VERSION = 3`, `EXPORT_SCOPES = ("case", "audit")`, `EXPORT_STATUSES = ("queued", "building", "succeeded", "failed", "expired")`, `EXPORT_PENDING = ("queued", "building")`, `CONSOLE_MIGRATIONS[3]`;
    - `migrate_console(conn) -> int` aplica las migraciones bajo `BEGIN IMMEDIATE` tras releer la versión;
    - `ConsoleStore.purge_sessions(*, now: str, idle_before: str) -> int`;
    - `ConsoleStore.create_job(..., notify_target: Optional[str] = None, notify_argv: Optional[List[str]] = None)`; `notify_argv` vuelve decodificada (lista);
    - `ConsoleStore.create_export(*, case_id, scope, seq, include_unsealed, created_by) -> dict`, `get_export(export_id) -> dict` (`{}` si no existe; `include_unsealed` como bool), `list_exports(*, statuses=(), limit=1000) -> list` (la más nueva primero), `update_export(export_id, *, expect=(), **fields) -> bool` (campos editables: `status`, `files_total`, `files_done`, `size`, `sha256`, `file_name`, `error`, `detail`, `started_at`, `finished_at`; `detail` es JSON).

- [ ] **Step 1: Escribir las pruebas que fallan**

Crea `tests/plugins/ghost_recon/console/test_store_exports.py`:

```python
"""Console schema v3 and the H3 settings: export rows, the job-end notice argv, session purge, and a migration that
two processes can start at once."""
import threading
import time

import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings
from plugins.ghost_recon.console.store import (CONSOLE_MIGRATIONS, CONSOLE_SCHEMA, CONSOLE_SCHEMA_VERSION,
                                               EXPORT_PENDING, ConsoleStore, migrate_console)
from plugins.ghost_recon.core.db import connect, migrate


def test_settings_parse_the_notice_target_and_the_export_options():
    s = ConsoleSettings.from_mapping({"notify_target": " telegram:-1001234567890:17585 ",
                                      "export_include_unsealed": "true",
                                      "export_retention": {"count": "5", "days": 7}})
    assert s.notify_target == "telegram:-1001234567890:17585"
    assert s.export_include_unsealed is True
    assert (s.export_retention_count, s.export_retention_days) == (5, 7)


@pytest.mark.parametrize("target", ["-x", "telegram now", "tele gram", "a" * 201, "telegram\nx", 12])
def test_a_malformed_notice_target_disables_the_notice(target):
    assert ConsoleSettings.from_mapping({"notify_target": target}).notify_target == ""


def test_invalid_export_options_fall_back_to_the_defaults():
    d = ConsoleSettings()
    s = ConsoleSettings.from_mapping({"export_include_unsealed": "quizás", "export_retention": {"count": 0, "days": "x"}})
    assert (s.export_include_unsealed, s.export_retention_count, s.export_retention_days) == (
        d.export_include_unsealed, d.export_retention_count, d.export_retention_days)
    assert ConsoleSettings.from_mapping({"export_retention": [20, 30]}).export_retention_count == d.export_retention_count


def _h2_database(path):
    """A database exactly as H2 left it: schema v2 with one job."""
    conn = connect(path)
    migrate(conn)
    for stmt in CONSOLE_SCHEMA + CONSOLE_MIGRATIONS[2]:
        conn.execute(stmt)
    conn.execute("INSERT INTO console_schema_version(version) VALUES (2)")
    conn.execute("INSERT INTO console_jobs(command, folder, launched_by, created_at) VALUES"
                 " ('rerun-case', '/c', 'jean', '2026-10-03T10:00:00Z')")
    conn.commit()
    return conn


def test_an_h2_database_migrates_to_v3_once_and_keeps_its_jobs(gr_env):
    path = gr_env / "h2.db"
    _h2_database(path).close()
    first = ConsoleStore.open(path)
    again = ConsoleStore.open(path)
    tables = {r[0] for r in again.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "console_exports" in tables
    assert [tuple(r) for r in again.conn.execute("SELECT version FROM console_schema_version")] == [
        (CONSOLE_SCHEMA_VERSION,)]
    job = first.list_jobs()[0]
    assert job["command"] == "rerun-case" and job["notify_argv"] == []


def test_a_second_migrator_waits_for_the_first_and_finds_nothing_to_do(gr_env):
    """The server and a runner can open an H2 database together: the one that loses the race must not repeat a step
    (ALTER TABLE ADD COLUMN fails when run twice)."""
    path = gr_env / "race.db"
    _h2_database(path).close()
    first, second = connect(path), connect(path)
    first.execute("BEGIN IMMEDIATE")  # the first migrator is mid-way
    errors = []

    def migrate_second():
        try:
            migrate_console(second)
        except Exception as exc:  # what the test is about: no "duplicate column name"
            errors.append(exc)

    racer = threading.Thread(target=migrate_second)
    racer.start()
    time.sleep(0.3)  # the second has read version 2 and now waits for the write lock
    for stmt in CONSOLE_MIGRATIONS[3]:
        first.execute(stmt)
    first.execute("UPDATE console_schema_version SET version=3")
    first.commit()
    racer.join(timeout=10)
    assert not racer.is_alive() and errors == []
    assert [tuple(r) for r in second.execute("SELECT version FROM console_schema_version")] == [(3,)]


def test_jobs_keep_the_notice_target_and_argv(cstore):
    job = cstore.create_job(command="rerun-case", folder="/c", args={}, argv=["hermes"], launched_by="jean",
                            notify_target="telegram", notify_argv=["hermes", "send", "--to", "telegram"])
    assert job["notify_target"] == "telegram" and job["notify_argv"] == ["hermes", "send", "--to", "telegram"]
    bare = cstore.create_job(command="rerun-case", folder="/d", args={}, argv=["hermes"], launched_by="jean")
    assert bare["notify_target"] is None and bare["notify_argv"] == []


def test_export_rows_round_trip_and_update_only_while_expected(cstore):
    row = cstore.create_export(case_id="GRC-a", scope="audit", seq="A01", include_unsealed=False, created_by="vera")
    assert (row["status"], row["include_unsealed"], row["seq"]) == ("queued", False, "A01")
    assert cstore.update_export(row["id"], expect=("queued",), status="building", files_total=4)
    assert cstore.update_export(row["id"], status="failed", detail={"code": "seal_broken"})
    assert not cstore.update_export(row["id"], expect=EXPORT_PENDING, status="succeeded")  # a late writer loses
    stored = cstore.get_export(row["id"])
    assert stored["status"] == "failed" and stored["detail"] == {"code": "seal_broken"}
    assert cstore.get_export(row["id"] + 100) == {}


def test_export_writes_reject_unknown_fields_statuses_and_scopes(cstore):
    row = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=True, created_by="jean")
    with pytest.raises(ValueError):
        cstore.update_export(row["id"], case_id="GRC-b")
    with pytest.raises(ValueError):
        cstore.update_export(row["id"], status="paused")
    with pytest.raises(ValueError):
        cstore.create_export(case_id="GRC-a", scope="everything", seq=None, include_unsealed=False, created_by="jean")


def test_exports_are_listed_newest_first_and_by_status(cstore):
    a = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=False, created_by="jean")
    b = cstore.create_export(case_id="GRC-b", scope="case", seq=None, include_unsealed=False, created_by="jean")
    cstore.update_export(a["id"], status="succeeded")
    assert [e["id"] for e in cstore.list_exports()] == [b["id"], a["id"]]
    assert [e["id"] for e in cstore.list_exports(statuses=EXPORT_PENDING)] == [b["id"]]


def test_purge_sessions_drops_revoked_expired_and_idle_ones(cstore):
    user = cstore.create_user("jean", "hash", "admin")

    def session(token, last_seen, expires):
        return cstore.create_session(user_id=user["id"], token_sha256=token, csrf_token="c", expires_at=expires,
                                     ip="", user_agent="", now=last_seen)
    keep = session("keep", "2026-10-04T11:00:00Z", "2026-10-10T00:00:00Z")
    session("idle", "2026-10-03T20:00:00Z", "2026-10-10T00:00:00Z")
    session("expired", "2026-10-04T11:30:00Z", "2026-10-04T11:59:00Z")
    cstore.revoke_session(session("revoked", "2026-10-04T11:00:00Z", "2026-10-10T00:00:00Z"))
    assert cstore.purge_sessions(now="2026-10-04T12:00:00Z", idle_before="2026-10-04T00:00:00Z") == 3
    assert [r[0] for r in cstore.conn.execute("SELECT id FROM console_sessions")] == [keep]
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_store_exports.py -q`
Expected: FAIL con `ImportError: cannot import name 'EXPORT_PENDING' from 'plugins.ghost_recon.console.store'`.

- [ ] **Step 3: Reemplazar `console/settings.py`**

Reemplaza `plugins/ghost_recon/console/settings.py` completo:

```python
"""Console settings: ``plugins.entries.ghost-recon.settings.console`` in config.yaml, with safe defaults."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Tuple

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
# ``hermes send --to`` targets: a platform name, then optional ``:chat[:thread]`` / ``:#channel`` parts. A leading
# letter keeps the value from ever reading as a flag on the send command line.
NOTIFY_TARGET_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*(?::\S+)?")
NOTIFY_TARGET_MAX = 200
_TRUE = ("true", "yes", "on", "1")
_FALSE = ("false", "no", "off", "0")


def _str_list(value: Any) -> Tuple[str, ...]:
    """Non-empty, stripped, de-duplicated strings of a YAML list; anything else is an empty tuple."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))


def _http_url(value: Any) -> str:
    """An http(s) base URL without its trailing slash, or "" (the console only ever links http(s))."""
    text = str(value or "").strip()
    return text.rstrip("/") if text.lower().startswith(("http://", "https://")) else ""


def _positive(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _flag(value: Any, default: bool) -> bool:
    """A YAML boolean, or its usual spellings as text (``hermes config set`` may store "true")."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if value is not None else ""
    return True if text in _TRUE else False if text in _FALSE else default


def _notify_target(value: Any) -> str:
    """A ``hermes send --to`` target, or "" (no notice) when absent or malformed."""
    text = str(value or "").strip()
    return text if len(text) <= NOTIFY_TARGET_MAX and NOTIFY_TARGET_RE.fullmatch(text) else ""


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
    notify_target: str = ""
    export_include_unsealed: bool = False
    export_retention_count: int = 20
    export_retention_days: int = 30

    @classmethod
    def from_mapping(cls, raw: Any) -> "ConsoleSettings":
        """Tolerant parse: unknown keys are ignored, invalid or non-positive numbers fall back to the default."""
        raw = raw if isinstance(raw, Mapping) else {}
        d = cls()
        retention = raw.get("export_retention")
        retention = retention if isinstance(retention, Mapping) else {}
        hosts = tuple(h.lower() for h in _str_list(raw.get("allowed_hosts")))
        return cls(host=str(raw.get("host") or d.host), port=_positive(raw.get("port", d.port), d.port),
                   session_idle_hours=_positive(raw.get("session_idle_hours", d.session_idle_hours),
                                                d.session_idle_hours),
                   session_max_days=_positive(raw.get("session_max_days", d.session_max_days), d.session_max_days),
                   allowed_hosts=tuple(dict.fromkeys(LOOPBACK_HOSTS + hosts)),
                   case_roots=_str_list(raw.get("case_roots")),
                   max_parallel_jobs=_positive(raw.get("max_parallel_jobs", d.max_parallel_jobs),
                                               d.max_parallel_jobs),
                   dashboard_url=_http_url(raw.get("dashboard_url")),
                   notify_target=_notify_target(raw.get("notify_target")),
                   export_include_unsealed=_flag(raw.get("export_include_unsealed"), d.export_include_unsealed),
                   export_retention_count=_positive(retention.get("count", d.export_retention_count),
                                                    d.export_retention_count),
                   export_retention_days=_positive(retention.get("days", d.export_retention_days),
                                                   d.export_retention_days))


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

- [ ] **Step 4: Constantes del esquema v3**

En `plugins/ghost_recon/console/store.py`, sustituye:

```python
"""``console_*`` tables in the Ghost Recon DB: users, sessions, API tokens, audit log and the seal-check cache.
```

por:

```python
"""``console_*`` tables in the Ghost Recon DB: users, sessions, API tokens, audit log, seal-check cache, jobs and
exports.
```

y sustituye:

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

por:

```python
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
```

- [ ] **Step 5: Migración v3 y migrador que nunca repite un paso**

`ALTER TABLE … ADD COLUMN` no se puede ejecutar dos veces, y el servidor, sus runners y el CLI pueden abrir la BD a la vez: el segundo migrador debe esperar al primero y, al releer la versión, no hacer nada.

En `plugins/ghost_recon/console/store.py`, sustituye:

```python
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

por:

```python
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
```

- [ ] **Step 6: Purga de sesiones y aviso planificado en las ejecuciones**

En `plugins/ghost_recon/console/store.py`, sustituye:

```python
    def revoke_user_sessions(self, user_id: int) -> None:
        self._update("UPDATE console_sessions SET revoked=1 WHERE user_id=?", (user_id,))
```

por:

```python
    def revoke_user_sessions(self, user_id: int) -> None:
        self._update("UPDATE console_sessions SET revoked=1 WHERE user_id=?", (user_id,))

    def purge_sessions(self, *, now: str, idle_before: str) -> int:
        """Delete revoked sessions and the ones past their absolute or idle expiry; the number deleted. The stamps
        are ISO-8601 UTC strings in one format, so text order is time order."""
        return self._update("DELETE FROM console_sessions WHERE revoked=1 OR expires_at <= ? OR last_seen_at < ?",
                            (now, idle_before))
```

y sustituye:

```python
    def create_job(self, *, command: str, folder: str, args: Dict[str, Any], argv: List[str], launched_by: str,
                   context_file: Optional[str] = None, case_id: Optional[str] = None) -> Dict[str, Any]:
        if command not in JOB_COMMANDS:
            raise ValueError(f"orden desconocida: {command}")
        job_id = self._insert(
            "INSERT INTO console_jobs(command, case_id, folder, args, argv, context_file, status, launched_by,"
            " created_at) VALUES (?,?,?,?,?,?,'queued',?,?)",
            (command, case_id, folder, _j(args), _j([str(a) for a in argv]), context_file, launched_by, utcnow()))
        return self.get_job(job_id)
```

por:

```python
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
```

- [ ] **Step 7: Filas de exportación**

En `plugins/ghost_recon/console/store.py`, al final de `update_job` (el último método de la clase), sustituye:

```python
        if expect:
            sql += f" AND status IN ({','.join('?' * len(expect))})"
        return self._update(sql, (*values, int(job_id), *expect)) > 0
```

por:

```python
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
```

- [ ] **Step 8: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_store_exports.py tests/plugins/ghost_recon/console/test_store_jobs.py tests/plugins/ghost_recon/console/test_store.py -q`
Expected: `0 failed` (la migración desde una BD de H1 de `test_store_jobs.py` sigue terminando en una sola fila con la versión actual).

Comprobación de que la prueba de la carrera es real: con el `migrate_console` de H2 (sin `BEGIN IMMEDIATE` ni relectura), `test_a_second_migrator_waits_for_the_first_and_finds_nothing_to_do` falla con `OperationalError('duplicate column name: notify_argv')`.

- [ ] **Step 9: Commit**

```bash
git add plugins/ghost_recon/console/settings.py plugins/ghost_recon/console/store.py tests/plugins/ghost_recon/console/test_store_exports.py
git commit -m "feat(ghost-recon): console H3 settings and schema v3 (exports, notice argv, session purge)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 2: Endurecimiento pendiente — bloqueo de login, `touch` sin errores, 500 con cabeceras y SSE que revalida

**Files:**
- Modify: `plugins/ghost_recon/console/auth.py`
- Modify: `plugins/ghost_recon/console/deps.py`
- Modify: `plugins/ghost_recon/console/app.py`
- Modify: `plugins/ghost_recon/console/routers/jobs.py`
- Test: `tests/plugins/ghost_recon/console/test_hardening.py`

**Interfaces:**
- Consumes: `AuthService.login/resolve_session/resolve_bearer`, `_register_failure`, `MAX_FAILURES`, `TOUCH_EVERY` (H1); `routers/jobs.py::job_stream` y `HEARTBEAT_S` (H2).
- Produces:
  - `AuthService._attempts: threading.Lock` (protege `_failures` y `_locked_until`); el intento cuenta **antes** de scrypt, bajo el candado; un login correcto lo borra;
  - `AuthService._touch(write, row_id, ts)`: escribe el último acceso y, ante `sqlite3.Error`, lo registra en debug y sigue;
  - `deps.resolve_principal(request, ctx) -> Optional[Principal]` (Bearer o cookie, sin CSRF); `current_principal` la usa y conserva sus códigos `invalid_token`, `unauthenticated` y `csrf`;
  - `app.INTERNAL_ERROR` y el middleware `guard`, que convierte una excepción no controlada en `500 {"error": {"code": "internal", …}}` con las cabeceras de seguridad;
  - el SSE (`GET /jobs/{id}/events/stream`) vuelve a resolver al usuario cada `HEARTBEAT_S` y, si ya no puede, emite `event: end` con `{"status": "unauthenticated"}` y cierra.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crea `tests/plugins/ghost_recon/console/test_hardening.py`:

```python
"""Hardening left over from H1 and H2: the lockout holds against a burst, last-seen bookkeeping never fails a read,
an unhandled error keeps the envelope and the security headers, and a live stream stops for a user who lost access."""
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from plugins.ghost_recon.console import auth as auth_mod
from plugins.ghost_recon.console.auth import MAX_FAILURES, AuthError, AuthService, LoginLocked, Principal
from plugins.ghost_recon.console.settings import ConsoleSettings

BURST = 12


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def test_a_burst_of_parallel_guesses_is_held_to_the_lockout_window(cstore, monkeypatch):
    svc = AuthService(cstore, ConsoleSettings())
    svc.add_user("jean", "admin-pass-123", "admin")
    checked = []
    real = auth_mod.verify_password

    def slow(password, encoded):  # scrypt latency: every guess of the burst overlaps the others
        checked.append(password)
        time.sleep(0.2)
        return real(password, encoded)

    monkeypatch.setattr(auth_mod, "verify_password", slow)
    start = threading.Barrier(BURST)
    outcomes = []

    def guess(i):
        start.wait()
        try:
            svc.login("jean", f"wrong-guess-{i}", ip="10.0.0.7")
        except LoginLocked:
            outcomes.append("locked")
        except AuthError:
            outcomes.append("refused")

    threads = [threading.Thread(target=guess, args=(i,)) for i in range(BURST)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(checked) == MAX_FAILURES  # only the window's worth of guesses ever reached the password check
    assert outcomes.count("refused") == MAX_FAILURES and outcomes.count("locked") == BURST - MAX_FAILURES


def test_a_busy_database_never_fails_an_authenticated_read(cstore, monkeypatch):
    clock = _Clock()
    svc = AuthService(cstore, ConsoleSettings(), clock=clock)
    svc.add_user("jean", "admin-pass-123", "admin")
    raw, _ = svc.login("jean", "admin-pass-123")
    token, _ = svc.create_api_token("jean", "webapp")
    clock.now += timedelta(minutes=5)  # past the touch interval: both resolutions want to write last-seen

    def locked(*_args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cstore, "touch_session", locked)
    monkeypatch.setattr(cstore, "touch_token", locked)
    assert svc.resolve_session(raw).username == "jean"
    assert svc.resolve_bearer(token).username == "jean"


def test_an_unhandled_error_keeps_the_envelope_and_the_security_headers(app, client):
    def boom():
        raise RuntimeError("C:/casos/secreto/ruta.txt")

    app.add_api_route("/api/v1/_boom", boom)
    r = client.get("/api/v1/_boom")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert "secreto" not in r.text  # the exception text (paths) stays in the server log


def test_a_live_stream_stops_once_its_user_is_disabled(login_as, case_root, auth, jobs, monkeypatch):
    from plugins.ghost_recon.console.routers import jobs as jobs_routes
    monkeypatch.setattr(jobs_routes, "HEARTBEAT_S", 0.3)
    folder = case_root / "hang-case"
    folder.mkdir()
    (folder / "nota.txt").write_text("x", encoding="utf-8")
    admin = login_as("admin")
    job = admin.post("/api/v1/jobs", json={"command": "new-open-case", "folder": str(folder)}).json()["job"]
    viewer = login_as("viewer")
    # The job never ends: the stream can only end because its watcher lost access while it was open. The safety
    # cancel ends it anyway (as "cancelled") if the stream never asks again, so a regression fails instead of hanging.
    threading.Timer(1.0, auth.set_disabled, args=("vera", True)).start()
    safety = threading.Timer(20.0, jobs.cancel, args=(job["id"], Principal(1, "jean", "admin", "session")))
    safety.start()
    with viewer.stream("GET", f"/api/v1/jobs/{job['id']}/events/stream") as r:
        text = "".join(r.iter_text())
    safety.cancel()
    assert "event: status" in text and text.rstrip().endswith('{"status": "unauthenticated"}')
    assert admin.post(f"/api/v1/jobs/{job['id']}/cancel").status_code == 200
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_hardening.py -q`
Expected: FAIL, 4 failed: la ráfaga llega entera a scrypt (`assert 12 == 5`), `sqlite3.OperationalError: database is locked`, `RuntimeError: C:/casos/secreto/ruta.txt` (el 500 sale sin sobre) y el stream termina como `cancelled` por la cancelación de seguridad (en unos 20 s), no como `unauthenticated`.

- [ ] **Step 3: Candado del bloqueo y `touch` sin errores**

En `plugins/ghost_recon/console/auth.py`, sustituye:

```python
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
```

por:

```python
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .settings import ConsoleSettings
from .store import ROLES, ConsoleStore

logger = logging.getLogger(__name__)
```

y sustituye:

```python
        self._failures: Dict[str, List[datetime]] = {}
        self._locked_until: Dict[str, datetime] = {}
        self._last_admin_lock = threading.Lock()  # protects last-admin checks from concurrent demote/disable
```

por:

```python
        self._failures: Dict[str, List[datetime]] = {}
        self._locked_until: Dict[str, datetime] = {}
        self._attempts = threading.Lock()  # serialises the lockout bookkeeping (_failures, _locked_until)
        self._last_admin_lock = threading.Lock()  # protects last-admin checks from concurrent demote/disable
```

y sustituye:

```python
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
```

por:

```python
        keys = [f"u:{uname}", f"ip:{ip}"]
        now = self.clock()
        with self._attempts:
            for key in keys:
                until = self._locked_until.get(key)
                if until and until > now:
                    raise LoginLocked(int((until - now).total_seconds()) + 1)
            # The attempt counts before the slow scrypt check: a burst of parallel guesses is held to the window,
            # instead of every guess passing the lock check while the earlier ones are still hashing.
            self._register_failure(keys, now)
        user = self.cstore.get_user(uname)
        valid = verify_password(password or "", user["password_hash"] if user else _equalising_hash())
        if not (user and valid and not user["disabled"]):
            self.cstore.log("login_failed", username=uname, ip=ip)
            raise AuthError("usuario o contraseña incorrectos")
        with self._attempts:
            for key in keys:
                self._failures.pop(key, None)
                self._locked_until.pop(key, None)
```

y sustituye:

```python
        if idle >= TOUCH_EVERY:
            self.cstore.touch_session(s["id"], _iso(now))
        return Principal(s["user_id"], s["username"], s["role"], "session", s["id"], s["csrf_token"])
```

por:

```python
        if idle >= TOUCH_EVERY:
            self._touch(self.cstore.touch_session, s["id"], _iso(now))
        return Principal(s["user_id"], s["username"], s["role"], "session", s["id"], s["csrf_token"])

    @staticmethod
    def _touch(write: Callable[[int, str], None], row_id: int, ts: str) -> None:
        """Last-seen bookkeeping is best effort: a busy database must never turn an authenticated read into an
        error (the next request retries the write)."""
        try:
            write(row_id, ts)
        except sqlite3.Error as exc:
            logger.debug("ghost-recon console: last-seen update skipped: %s", exc)
```

y sustituye:

```python
        if not t["last_used_at"] or now - _parse(t["last_used_at"]) >= TOUCH_EVERY:
            self.cstore.touch_token(t["id"], _iso(now))
```

por:

```python
        if not t["last_used_at"] or now - _parse(t["last_used_at"]) >= TOUCH_EVERY:
            self._touch(self.cstore.touch_token, t["id"], _iso(now))
```

- [ ] **Step 4: Resolver al usuario sin CSRF, para volver a preguntar**

En `plugins/ghost_recon/console/deps.py`, sustituye:

```python
import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
```

por:

```python
import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
```

y sustituye:

```python
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
```

por:

```python
def _bearer(request: Request) -> Optional[str]:
    authz = request.headers.get("authorization", "")
    return authz[7:].strip() if authz[:7].lower() == "bearer " else None


def resolve_principal(request: Request, ctx: ConsoleContext) -> Optional[Principal]:
    """Who the request acts for right now (Bearer token or session cookie), or None. No CSRF check, so a long-lived
    stream can ask again later."""
    token = _bearer(request)
    if token is not None:
        return ctx.auth.resolve_bearer(token)
    return ctx.auth.resolve_session(request.cookies.get(session_cookie_name(ctx.settings), ""))


def current_principal(request: Request, ctx: ConsoleContext = Depends(get_ctx)) -> Principal:
    """Bearer token (API clients, CSRF-exempt: no cookie involved) or session cookie (browser, CSRF-checked)."""
    principal = resolve_principal(request, ctx)
    if principal is None:
        if _bearer(request) is not None:
            raise ApiError(401, "invalid_token", "token inválido o revocado")
        raise ApiError(401, "unauthenticated", "inicia sesión")
    if (principal.via == "session" and request.method not in SAFE_METHODS
            and not _same(request.headers.get(CSRF_HEADER, ""), principal.csrf or "")):
        raise ApiError(403, "csrf", "falta o no coincide la cabecera anti-CSRF")
    return principal
```

- [ ] **Step 5: Un 500 con sobre y cabeceras**

Con `@app.middleware("http")`, una excepción de una ruta sale de `call_next` y la contesta el `ServerErrorMiddleware` de Starlette **fuera** de este middleware: texto plano y sin CSP ni `no-store`.

En `plugins/ghost_recon/console/app.py`, sustituye:

```python
from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
```

por:

```python
from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
```

y sustituye:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes)
```

por:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes)
INTERNAL_ERROR = {"error": {"code": "internal",
                            "message": "error interno de la consola; el detalle quedó en el log del servidor"}}
logger = logging.getLogger(__name__)
```

y sustituye:

```python
        if host_allowed(request.headers.get("host", ""), settings):
            response = await call_next(request)
        else:
            response = JSONResponse({"error": {"code": "bad_host", "message": "host no permitido"}}, status_code=400)
```

por:

```python
        if not host_allowed(request.headers.get("host", ""), settings):
            response = JSONResponse({"error": {"code": "bad_host", "message": "host no permitido"}}, status_code=400)
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Starlette's last-resort handler answers outside this middleware: plain text, no security headers.
                logger.exception("ghost-recon console: unhandled error on %s %s", request.method, request.url.path)
                response = JSONResponse(INTERNAL_ERROR, status_code=500)
```

- [ ] **Step 6: El SSE vuelve a preguntar quién mira**

En `plugins/ghost_recon/console/routers/jobs.py`, sustituye:

```python
import asyncio
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import commands, jobfiles, procs, readmodel
from ..auth import Principal
from ..commands import CommandError, LaunchRequest
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
```

por:

```python
import asyncio
import json
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import commands, jobfiles, procs, readmodel
from ..auth import Principal
from ..commands import CommandError, LaunchRequest
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require, resolve_principal
```

y sustituye:

```python
    """SSE: ``event`` frames whose id is the event's seq (a reconnect resumes after Last-Event-ID), a ``status``
    frame whenever status/phase/session/case change, ``end`` once the job is over and its events are drained, and a
    comment as heartbeat. The events file is polled every ``stream_poll`` seconds (1 s by default)."""
    _job_or_404(ctx, job_id)
    last = request.headers.get("last-event-id", "")
    start = max(after, int(last)) if last.isascii() and last.isdigit() else after
    path = jobfiles.events_path(ctx.jobs.jobs_dir, job_id)
    poll = ctx.jobs.stream_poll

    async def frames():
        seq, offset, sent, idle = start, 0, None, 0.0
        while not await request.is_disconnected():
```

por:

```python
    """SSE: ``event`` frames whose id is the event's seq (a reconnect resumes after Last-Event-ID), a ``status``
    frame whenever status/phase/session/case change, ``end`` once the job is over and its events are drained, and a
    comment as heartbeat. The events file is polled every ``stream_poll`` seconds (1 s by default). Every
    ``HEARTBEAT_S`` the stream asks again who is watching: a disabled user or a revoked session or token gets
    ``end`` with status ``unauthenticated`` and nothing more."""
    _job_or_404(ctx, job_id)
    last = request.headers.get("last-event-id", "")
    start = max(after, int(last)) if last.isascii() and last.isdigit() else after
    path = jobfiles.events_path(ctx.jobs.jobs_dir, job_id)
    poll = ctx.jobs.stream_poll

    async def frames():
        seq, offset, sent, idle, checked = start, 0, None, 0.0, time.monotonic()
        while not await request.is_disconnected():
            if time.monotonic() - checked >= HEARTBEAT_S:
                checked = time.monotonic()
                if resolve_principal(request, ctx) is None:
                    yield f"event: end\ndata: {json.dumps({'status': 'unauthenticated'})}\n\n"
                    return
```

La vista de Ejecución no cambia: ante `end` cierra el `EventSource` y refresca, y ese refresco recibe 401 y lleva al login.

- [ ] **Step 7: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_hardening.py tests/plugins/ghost_recon/console/test_auth.py tests/plugins/ghost_recon/console/test_api_security.py tests/plugins/ghost_recon/console/test_api_jobs.py -q`
Expected: `0 failed` (el bloqueo de 5 fallos de H1 y los streams de H2 siguen iguales).

- [ ] **Step 8: Commit**

```bash
git add plugins/ghost_recon/console/auth.py plugins/ghost_recon/console/deps.py plugins/ghost_recon/console/app.py plugins/ghost_recon/console/routers/jobs.py tests/plugins/ghost_recon/console/test_hardening.py
git commit -m "fix(ghost-recon): console lockout under a lock, best-effort touch, 500 envelope and SSE re-auth

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 3: Integridad de los entregables al descargarlos (409 `hash_mismatch`)

**Files:**
- Create: `plugins/ghost_recon/console/integrity.py`
- Create: `plugins/ghost_recon/console/downloads.py`
- Modify (reemplazar): `plugins/ghost_recon/console/routers/audits.py`
- Test: `tests/plugins/ghost_recon/console/test_download_integrity.py`

**Interfaces:**
- Consumes: `core.service.verify_audit`, `core.casefolder.read_json/SEALED_FILE`, `ConsoleStore.save_seal_check/log`, `paths.resolve_within`, `routers/cases.get_case_or_404`.
- Produces:
  - `integrity.IntegrityError(code, rel, message)` con `code ∈ {no_seal_manifest, not_in_seal, hash_mismatch}` y `rel` (ruta dentro de la auditoría, se puede mostrar);
  - `integrity.record_seal_check(store, cstore, audit, username) -> {"ok", "detail", "checked_at"}`: verifica el sello y lo guarda en la caché (lo usan `POST …/verify` y el ZIP de la Tarea 5);
  - `integrity.changed_files(detail, limit=5) -> str`: «06_Report/x.md (modificado), …» o el motivo;
  - `integrity.seal_hashes(folder) -> Optional[Dict[str, str]]`, `integrity.relative(folder, path) -> str`, `integrity.expected_hash(sealed, rel) -> str`, `integrity.check(rel, actual, expected, registered="")` y `integrity.verified_bytes(folder, path, *, registered="") -> bytes`;
  - `downloads.content_disposition(filename) -> str` y `downloads.attachment(data, filename, media_type) -> Response`;
  - la descarga de un entregable de una auditoría **sellada** sirve exactamente los bytes comprobados; cada rechazo queda como `report_download_denied` con `{"code", …}`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crea `tests/plugins/ghost_recon/console/test_download_integrity.py`:

```python
"""Deliverables of sealed audits are re-hashed on download: a file that no longer matches its seal is refused by name
(409 hash_mismatch) and every refused download is in the console audit log."""
from pathlib import Path


def _url(seeded, seq):
    return f"/api/v1/cases/{seeded['case_id']}/audits/{seq}"


def _denied(login_as):
    log = login_as("admin").get("/api/v1/system/audit-log").json()["items"]
    return [e for e in log if e["action"] == "report_download_denied"]


def test_a_tampered_sealed_deliverable_is_refused_by_name_and_logged(login_as, seeded, store):
    report = next(r for r in store.list_reports(seeded["a1"]) if r["format"] == "md")
    path = Path(report["path"])
    path.write_bytes(path.read_bytes() + b"\nalterado")
    r = login_as("viewer").get(_url(seeded, "A01") + f"/reports/{report['id']}/download")
    assert r.status_code == 409 and r.json()["error"]["code"] == "hash_mismatch"
    assert path.name in r.json()["error"]["message"]
    denied = _denied(login_as)
    assert denied[0]["username"] == "vera" and denied[0]["detail"]["code"] == "hash_mismatch"
    assert denied[0]["detail"]["file"].endswith(path.name)


def test_a_sealed_deliverable_outside_its_seal_or_without_one_is_refused(login_as, seeded, store):
    extra = seeded["a1_folder"] / "06_Report" / "anexo.md"
    extra.write_text("añadido después del sello\n", encoding="utf-8")  # inside the folder, never sealed
    rid = store.add_report(seeded["a1"], "annex_md", str(extra), "md")
    c = login_as("viewer")
    r = c.get(_url(seeded, "A01") + f"/reports/{rid}/download")
    assert r.status_code == 409 and "anexo.md" in r.json()["error"]["message"]
    (seeded["a1_folder"] / "SEALED.json").unlink()
    original = next(x for x in store.list_reports(seeded["a1"]) if x["format"] == "md")
    assert c.get(_url(seeded, "A01") + f"/reports/{original['id']}/download").status_code == 409
    assert {e["detail"]["reason"] for e in _denied(login_as)} == {"not_in_seal", "no_seal_manifest"}


def test_every_refused_download_is_logged_with_its_reason(login_as, seeded, store):
    open_report = store.list_reports(seeded["a2"])[0]
    viewer = login_as("viewer")
    assert viewer.get(_url(seeded, "A02") + f"/reports/{open_report['id']}/download").status_code == 403
    Path(open_report["path"]).unlink()
    assert login_as("admin").get(_url(seeded, "A02") + f"/reports/{open_report['id']}/download").status_code == 404
    assert sorted(e["detail"]["code"] for e in _denied(login_as)) == ["file_missing", "not_sealed"]


def test_an_intact_sealed_deliverable_downloads_with_its_name(login_as, seeded, store):
    report = next(r for r in store.list_reports(seeded["a1"]) if r["format"] == "md")
    r = login_as("viewer").get(_url(seeded, "A01") + f"/reports/{report['id']}/download")
    assert r.status_code == 200 and r.content == Path(report["path"]).read_bytes()
    assert Path(report["path"]).name in r.headers["content-disposition"]
    assert _denied(login_as) == []
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_download_integrity.py -q`
Expected: FAIL, 3 failed y 1 passed: el entregable alterado se descarga con 200 y ningún rechazo queda en el registro (la descarga intacta ya funcionaba).

- [ ] **Step 3: Crear `console/integrity.py`**

Crea `plugins/ghost_recon/console/integrity.py`:

```python
"""Integrity of sealed results (spec §9 "Descargas", §11 "Integridad").

A file of a sealed audit is trusted only while its bytes still hash to what the seal recorded in ``SEALED.json`` and,
for a deliverable, to the hash registered when the pack was built. Deliverable downloads and the ZIP export both go
through these checks, so a changed file is refused by name instead of leaving the console.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import casefolder as cf, service
from ..core.db import Store
from .store import ConsoleStore

SEAL_DETAIL_KEYS = ("missing", "added", "modified", "file_count", "manifest_sha256", "db_matches", "reason", "sealed")
_CHANGE_WORDS = (("modified", "modificado"), ("missing", "falta"), ("added", "añadido"))
_REASONS = {"read_error": "no se pudo leer la carpeta de la auditoría", "no SEALED.json": "falta SEALED.json"}


class IntegrityError(Exception):
    """A sealed file that cannot be trusted; ``rel`` is its path inside the audit folder (safe to show)."""

    def __init__(self, code: str, rel: str, message: str):
        super().__init__(message)
        self.code = code
        self.rel = rel
        self.message = message


def record_seal_check(store: Store, cstore: ConsoleStore, audit: Dict[str, Any], username: str) -> Dict[str, Any]:
    """Re-hash a sealed audit against its seal and cache the outcome (``console_seal_checks``, the "verificado hace X"
    of the views): ``{"ok", "detail", "checked_at"}``. A folder that cannot be read is a failed check."""
    try:
        result = service.verify_audit(store, audit["id"])
    except (OSError, service.CaseError):
        result = {"ok": False, "reason": "read_error"}  # machine code only: the exception text carries paths
    ok = bool(result.get("ok")) and result.get("db_matches") is not False
    detail = {k: result.get(k) for k in SEAL_DETAIL_KEYS}
    check = cstore.save_seal_check(audit["id"], ok, detail, username)
    return {"ok": ok, "detail": detail, "checked_at": check["checked_at"]}


def changed_files(detail: Dict[str, Any], limit: int = 5) -> str:
    """What a failed seal check found, for a message: "06_Report/x.md (modificado), …" or the reason it failed."""
    parts: List[str] = [f"{rel} ({word})" for key, word in _CHANGE_WORDS for rel in (detail.get(key) or [])]
    if parts:
        more = f" y {len(parts) - limit} más" if len(parts) > limit else ""
        return ", ".join(parts[:limit]) + more
    if detail.get("db_matches") is False:
        return "el hash del sello no coincide con el registrado en la base de datos"
    return _REASONS.get(detail.get("reason") or "", "el sello no se pudo comprobar")


def seal_hashes(folder: Path) -> Optional[Dict[str, str]]:
    """``relative path -> sha256`` as the audit's ``SEALED.json`` recorded them; None when missing or unreadable."""
    record = cf.read_json(Path(folder) / cf.SEALED_FILE)
    files = record.get("files") if isinstance(record, dict) else None
    return files if isinstance(files, dict) else None


def relative(folder: Path, path: Path) -> str:
    """``path`` relative to the audit ``folder`` in the seal's notation (forward slashes)."""
    return Path(path).resolve().relative_to(Path(folder).resolve()).as_posix()


def expected_hash(sealed: Optional[Dict[str, str]], rel: str) -> str:
    """The hash the seal recorded for ``rel``; IntegrityError when there is no readable seal or ``rel`` is not in it."""
    if sealed is None:
        raise IntegrityError("no_seal_manifest", rel, f"no se puede leer el sello (SEALED.json) para comprobar {rel}")
    expected = sealed.get(rel)
    if not expected:
        raise IntegrityError("not_in_seal", rel, f"{rel} no estaba en la auditoría cuando se selló")
    return expected


def check(rel: str, actual: str, expected: str, registered: str = "") -> None:
    """``actual`` must equal the sealed hash and, when given, the hash registered for the deliverable."""
    if actual != expected or (registered and actual != registered):
        raise IntegrityError("hash_mismatch", rel, f"{rel} cambió después de sellar la auditoría")


def verified_bytes(folder: Path, path: Path, *, registered: str = "") -> bytes:
    """The bytes of ``path`` (a file inside the sealed audit ``folder``) only if they pass ``check``. The bytes
    returned are exactly the ones hashed, so nothing can change between the check and the download."""
    rel = relative(folder, path)
    expected = expected_hash(seal_hashes(folder), rel)
    data = Path(path).read_bytes()
    check(rel, hashlib.sha256(data).hexdigest(), expected, registered)
    return data
```

- [ ] **Step 4: Crear `console/downloads.py`**

Crea `plugins/ghost_recon/console/downloads.py`:

```python
"""HTTP attachments of the console: bytes sent with a Content-Disposition the browser saves under the given name."""

from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import Response


def content_disposition(filename: str) -> str:
    """RFC 6266: a plain quoted name when it is URL-safe ASCII, ``filename*=utf-8''…`` otherwise (accents, quotes)."""
    quoted = quote(filename)
    return f"attachment; filename*=utf-8''{quoted}" if quoted != filename else f'attachment; filename="{filename}"'


def attachment(data: bytes, filename: str, media_type: str) -> Response:
    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": content_disposition(filename)})
```

- [ ] **Step 5: Reemplazar `routers/audits.py`**

La verificación pasa a `integrity.record_seal_check` (misma respuesta y mismo registro `seal_verify` que en H1) y la descarga comprueba el entregable antes de servirlo.

Reemplaza `plugins/ghost_recon/console/routers/audits.py` completo:

```python
"""Audit endpoints: detail with completion checks, internal runs, seal verification and deliverable downloads."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from ...core import service
from .. import integrity, readmodel
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..downloads import attachment
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
    check = integrity.record_seal_check(ctx.store, ctx.cstore, audit, principal.username)
    ctx.cstore.log("seal_verify", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=audit["id"], detail={"ok": check["ok"]})
    return {"audit_id": audit["id"], "ok": check["ok"], "checked_at": check["checked_at"], "detail": check["detail"]}


@router.get("/cases/{case_id}/audits/{seq}/reports")
def audit_reports(case_id: str, seq: str, _: Principal = Depends(require("viewer")),
                  ctx: ConsoleContext = Depends(get_ctx)):
    audit = get_audit_or_404(ctx, case_id, seq)
    return {"items": [{"id": r["id"], "kind": r["kind"], "format": r["format"], "version": r["version"],
                       "size": r["size"], "sha256": r["sha256"], "name": Path(r["path"]).name,
                       "created_at": r["created_at"]} for r in ctx.store.list_reports(audit["id"])]}


def _refuse(ctx: ConsoleContext, request: Request, principal: Principal, target: str, status: int, code: str,
            message: str, **detail) -> ApiError:
    """Every refused download is in the console audit log, with who asked and why."""
    ctx.cstore.log("report_download_denied", user_id=principal.user_id, username=principal.username,
                   ip=client_ip(request), target=target, detail={"code": code, **detail})
    return ApiError(status, code, message)


@router.get("/cases/{case_id}/audits/{seq}/reports/{report_id}/download")
def download_report(case_id: str, seq: str, report_id: int, request: Request,
                    principal: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """A deliverable of a sealed audit is re-hashed and served only if it still matches its seal entry and the hash
    the pack registered (409 ``hash_mismatch`` otherwise). Open audits' deliverables are for admins only."""
    audit = get_audit_or_404(ctx, case_id, seq)
    target = f"{audit['id']}#{report_id}"
    sealed = audit["status"] == "sealed"
    if not sealed and not principal.has("admin"):
        raise _refuse(ctx, request, principal, target, 403, "not_sealed",
                      "los entregables de auditorías abiertas solo los descarga un admin")
    report = next((r for r in ctx.store.list_reports(audit["id"]) if r["id"] == report_id), None)
    path = resolve_within(report["path"], [audit["folder"]]) if report else None
    if path is None or not path.is_file():
        raise _refuse(ctx, request, principal, target, 404, "file_missing",
                      "el archivo del entregable no está en la carpeta de la auditoría")
    if sealed:
        try:
            data = integrity.verified_bytes(Path(audit["folder"]), path, registered=report["sha256"] or "")
        except integrity.IntegrityError as exc:
            raise _refuse(ctx, request, principal, target, 409, "hash_mismatch",
                          f"El entregable no coincide con el sello de la auditoría: {exc.message}. "
                          "Verifica los sellos del caso antes de usarlo.", file=exc.rel, reason=exc.code)
    else:
        data = path.read_bytes()
    ctx.cstore.log("report_download", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=target, detail={"file": path.name})
    return attachment(data, path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
```

- [ ] **Step 6: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_download_integrity.py tests/plugins/ghost_recon/console/test_api_audits.py -q`
Expected: `0 failed` (incluidas las pruebas de H1: caché de sellos, archivo ilegible, manifiesto borrado y descargas por rol).

- [ ] **Step 7: Commit**

```bash
git add plugins/ghost_recon/console/integrity.py plugins/ghost_recon/console/downloads.py plugins/ghost_recon/console/routers/audits.py tests/plugins/ghost_recon/console/test_download_integrity.py
git commit -m "feat(ghost-recon): console re-hashes sealed deliverables on download and logs refusals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 4: Tablas del caso a CSV y XLSX con los filtros activos

**Files:**
- Modify: `plugins/ghost_recon/console/readmodel.py`
- Modify: `plugins/ghost_recon/console/routers/cases.py`
- Create: `plugins/ghost_recon/console/tables.py`
- Create: `plugins/ghost_recon/console/routers/exports.py` (solo las tablas; la Tarea 6 lo amplía)
- Create: `plugins/ghost_recon/console/.gitignore`
- Modify: `plugins/ghost_recon/console/app.py` (`ROUTERS`)
- Test: `tests/plugins/ghost_recon/console/test_tables.py`

**Interfaces:**
- Consumes: `readmodel.filter_findings/filter_evidence`, `Store.list_findings/list_evidence/list_events/list_criteria`, `core.SIGNATURE`, `core.ENGINE`, `core.reports.xlsx.rewrite_app_xml`, `core.reports.pack.scan_tool_names` (solo en la prueba), `downloads.attachment`.
- Produces:
  - `readmodel.TableFilters(kind="", risk="", status="", q="", audit="")` (frozen), `findings_rows/evidence_rows/timeline_rows/criteria_rows(store, case_id, f) -> list` y `readmodel.TABLE_ROWS: Dict[str, Callable]`. Los endpoints JSON de `routers/cases.py` leen sus filas de ahí: una exportación siempre tiene lo que muestra la tabla con los mismos filtros;
  - `tables.Column(header, value)`, `tables.Table(title, columns)`, `tables.TABLES` (`findings`, `evidence`, `timeline`, `criteria`), `tables.csv_cell(value)`, `tables.to_csv(table, rows, case) -> bytes`, `tables.load_openpyxl()`, `tables.XlsxUnavailable`, `tables.to_xlsx(table, rows, case) -> bytes`, `tables.WRITERS = {"csv": (to_csv, CSV_MEDIA), "xlsx": (to_xlsx, XLSX_MEDIA)}`, `tables.file_name(case, table, fmt, now=None) -> str` (`GhostRecon_<slug>_<tabla>_<YYYYMMDD-HHMM>.<fmt>`, UTC);
  - `GET /cases/{case_id}/{table}.{fmt}` (viewer): 404 para tabla o formato desconocidos, 503 `xlsx_unavailable` sin openpyxl, `table_export` en el registro con las filas y los filtros usados.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crea `tests/plugins/ghost_recon/console/test_tables.py`:

```python
"""Case tables as CSV/XLSX: the rows and filters of the JSON endpoints, text Excel opens intact (accents, commas,
line breaks) and never runs as a formula, and the Ghost Recon metadata of the pack."""
import csv
import io
import zipfile

import pytest

from plugins.ghost_recon.console import tables
from plugins.ghost_recon.core import ENGINE, service
from plugins.ghost_recon.core.reports.pack import scan_tool_names

TRICKY = 'Pago "Zelle", socio B — señal de alerta\nsegunda línea; ñandú'
FORMULA = '=HYPERLINK("http://ejemplo.invalid","clic")'


def _csv_rows(response):
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM: Excel reads the file as UTF-8
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))


@pytest.fixture
def tricky(store, seeded):
    """Findings whose text breaks naive CSV: quotes, commas, a line break, accents, a formula and a negative amount."""
    service.upsert_findings(store, seeded["a2"], [
        {"kind": "finding", "title": TRICKY, "counterparty": "Socio B, S.A.", "risk": "high", "amount": -1500.0},
        {"kind": "anomaly", "title": FORMULA, "risk": "low"},
    ])
    return {f["title"]: f for f in store.list_findings(seeded["case_id"])}


def test_csv_round_trips_accents_commas_quotes_and_line_breaks(login_as, seeded, tricky):
    r = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/findings.csv")
    assert r.headers["content-type"].startswith("text/csv") and ".csv" in r.headers["content-disposition"]
    row = next(x for x in _csv_rows(r) if x["ID"] == tricky[TRICKY]["id"])
    assert row["Título"] == TRICKY and row["Contraparte"] == "Socio B, S.A."
    assert float(row["Importe"]) == -1500.0  # a number keeps its sign


def test_text_that_looks_like_a_formula_stays_text(login_as, seeded, tricky):
    c = login_as("viewer")
    row = next(x for x in _csv_rows(c.get(f"/api/v1/cases/{seeded['case_id']}/findings.csv"))
               if x["ID"] == tricky[FORMULA]["id"])
    assert row["Título"] == "'" + FORMULA
    assert tables.csv_cell("-12.50") == "-12.50" and tables.csv_cell("@SUM(A1)") == "'@SUM(A1)"


@pytest.mark.parametrize("table,params,key,json_key", [
    ("findings", {"risk": "high"}, "ID", "id"),
    ("findings", {"status": "open", "q": "zelle"}, "ID", "id"),
    ("evidence", {"status": "NEW", "q": "bancos"}, "Ruta", "path"),
    ("evidence", {"audit": "A02"}, "Ruta", "path"),
    ("timeline", {}, "Evento", "event_type"),
    ("criteria", {}, "ID", "id"),
])
def test_a_table_file_holds_exactly_the_rows_of_its_json_endpoint(login_as, seeded, table, params, key, json_key):
    c = login_as("viewer")
    base = f"/api/v1/cases/{seeded['case_id']}/{table}"
    shown = c.get(base, params={**params, "limit": 500}).json()["items"]
    exported = _csv_rows(c.get(f"{base}.csv", params=params))
    assert [r[key] for r in exported] == [str(i[json_key]) for i in shown]


def test_xlsx_opens_with_the_ghost_recon_metadata_and_no_live_formula(login_as, seeded, tricky, tmp_path):
    openpyxl = pytest.importorskip("openpyxl", reason="plugin python_dependency, not in the core test group")
    r = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/findings.xlsx")
    assert r.status_code == 200 and r.headers["content-type"] == tables.XLSX_MEDIA
    path = tmp_path / "t.xlsx"
    path.write_bytes(r.content)
    wb = openpyxl.load_workbook(path)
    assert "Ghost Recon" in wb.properties.creator and "Acme Demo" in wb.properties.title
    with zipfile.ZipFile(path) as zf:
        assert f"<Application>{ENGINE}</Application>" in zf.read("docProps/app.xml").decode("utf-8")
    assert scan_tool_names([path]) == {}  # no library names, like the pack
    cells = {c.value: c for row in wb.active.iter_rows(min_row=2) for c in row if isinstance(c.value, str)}
    assert cells[FORMULA].data_type == "s" and cells[TRICKY].value == TRICKY


def test_xlsx_without_openpyxl_is_a_clear_503_and_csv_still_works(login_as, seeded, monkeypatch):
    def missing():
        raise tables.XlsxUnavailable("Falta openpyxl")
    monkeypatch.setattr(tables, "load_openpyxl", missing)
    c = login_as("viewer")
    r = c.get(f"/api/v1/cases/{seeded['case_id']}/criteria.xlsx")
    assert r.status_code == 503 and r.json()["error"]["code"] == "xlsx_unavailable"
    assert c.get(f"/api/v1/cases/{seeded['case_id']}/criteria.csv").status_code == 200


def test_table_files_need_a_login_a_known_table_and_are_audited(login_as, client, seeded):
    url = f"/api/v1/cases/{seeded['case_id']}"
    assert client.get(f"{url}/findings.csv").status_code == 401
    c = login_as("viewer")
    assert c.get(f"{url}/passwords.csv").status_code == 404 and c.get(f"{url}/findings.pdf").status_code == 404
    assert c.get("/api/v1/cases/GRC-nope-20260101/findings.csv").status_code == 404
    c.get(f"{url}/findings.csv", params={"risk": "high"})
    entry = next(e for e in login_as("admin").get("/api/v1/system/audit-log").json()["items"]
                 if e["action"] == "table_export")
    assert entry["username"] == "vera" and entry["detail"]["filters"] == {"risk": "high"}
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_tables.py -q`
Expected: FAIL con `ImportError: cannot import name 'tables' from 'plugins.ghost_recon.console'`.

- [ ] **Step 3: Una sola fuente para las filas de las tablas**

En `plugins/ghost_recon/console/readmodel.py`, sustituye:

```python
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
```

por:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
```

y sustituye:

```python
def filter_evidence(rows: List[Dict[str, Any]], *, q: str = "") -> List[Dict[str, Any]]:
    needle = q.strip().lower()
    return [e for e in rows if not needle or _matches(e, needle, EVIDENCE_TEXT_FIELDS)]
```

por:

```python
def filter_evidence(rows: List[Dict[str, Any]], *, q: str = "") -> List[Dict[str, Any]]:
    needle = q.strip().lower()
    return [e for e in rows if not needle or _matches(e, needle, EVIDENCE_TEXT_FIELDS)]


@dataclass(frozen=True)
class TableFilters:
    """The filters of the case tables (findings: kind, risk, status, q; evidence: status, audit, q)."""
    kind: str = ""
    risk: str = ""
    status: str = ""
    q: str = ""
    audit: str = ""


def findings_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    return filter_findings(store.list_findings(case_id), kind=f.kind, risk=f.risk, status=f.status, q=f.q)


def evidence_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    rows = store.list_evidence(case_id, status=f.status or None,
                               first_audit_id=f"{case_id}/{f.audit}" if f.audit else None)
    return filter_evidence(rows, q=f.q)


def timeline_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    """Newest first."""
    return sorted(store.list_events(case_id), key=lambda e: (e["ts"], e["id"]), reverse=True)


def criteria_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    return store.list_criteria(case_id)


# One source for the rows of each case table: the JSON endpoints and the CSV/XLSX exports both read through it, so an
# export always holds what the table shows with the same filters.
TABLE_ROWS: Dict[str, Callable[[Store, str, TableFilters], List[Dict[str, Any]]]] = {
    "findings": findings_rows, "evidence": evidence_rows, "timeline": timeline_rows, "criteria": criteria_rows}
```

- [ ] **Step 4: Los endpoints JSON leen de esa fuente**

En `plugins/ghost_recon/console/routers/cases.py`, sustituye:

```python
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
```

por:

```python
    get_case_or_404(ctx, case_id)
    t = service.timeline(ctx.store, case_id)
    return {"items": readmodel.timeline_rows(ctx.store, case_id, readmodel.TableFilters()), "audits": t["audits"],
            "findings_evolution": t["findings_evolution"]}


@router.get("/cases/{case_id}/findings")
def findings(case_id: str, kind: str = "", risk: str = "", status: str = "", q: str = "",
             _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    get_case_or_404(ctx, case_id)
    filters = readmodel.TableFilters(kind=kind, risk=risk, status=status, q=q)
    return {"items": readmodel.findings_rows(ctx.store, case_id, filters)}
```

y sustituye:

```python
    get_case_or_404(ctx, case_id)
    rows = ctx.store.list_evidence(case_id, status=status or None,
                                   first_audit_id=f"{case_id}/{audit}" if audit else None)
    rows = readmodel.filter_evidence(rows, q=q)
    items, next_cursor = readmodel.page(rows, cursor, limit)
```

por:

```python
    get_case_or_404(ctx, case_id)
    rows = readmodel.evidence_rows(ctx.store, case_id, readmodel.TableFilters(status=status, audit=audit, q=q))
    items, next_cursor = readmodel.page(rows, cursor, limit)
```

y sustituye:

```python
    get_case_or_404(ctx, case_id)
    return {"items": ctx.store.list_criteria(case_id)}
```

por:

```python
    get_case_or_404(ctx, case_id)
    return {"items": readmodel.criteria_rows(ctx.store, case_id, readmodel.TableFilters())}
```

- [ ] **Step 5: Crear `console/tables.py`**

openpyxl 3.1 define `ILLEGAL_CHARACTERS_RE` en `openpyxl.cell.cell` (no en `openpyxl.utils.cell`).

Crea `plugins/ghost_recon/console/tables.py`:

```python
"""Case tables as files (spec §11 "Tablas"): findings, evidence, timeline and criteria — the rows of their JSON
endpoints, with the same filters — as CSV (UTF-8 with BOM, so Excel shows the accents) or XLSX (openpyxl, with the
Ghost Recon metadata of the pack). Pure: rows in, bytes out."""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

from ..core import SIGNATURE, ids
from ..core.reports.xlsx import rewrite_app_xml

CSV_MEDIA = "text/csv; charset=utf-8"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_CREATOR = "Ghost Recon (www.ghostrecon.ai)"
# Text a spreadsheet would run as a formula when it opens the CSV (CSV injection); a plain signed number stays as is.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER_RE = re.compile(r"[+-]?\d+(?:[.,]\d+)*")


class XlsxUnavailable(RuntimeError):
    """openpyxl (a python_dependency of the plugin, not of Hermes) is not installed here."""


@dataclass(frozen=True)
class Column:
    header: str
    value: Callable[[Dict[str, Any]], Any]


@dataclass(frozen=True)
class Table:
    title: str  # Spanish: the XLSX sheet and title
    columns: Sequence[Column]


def _f(key: str) -> Callable[[Dict[str, Any]], Any]:
    return lambda row: row.get(key)


def _audit(key: str) -> Callable[[Dict[str, Any]], Any]:
    return lambda row: ids.short_audit(row[key]) if row.get(key) else ""


def _listed(key: str) -> Callable[[Dict[str, Any]], Any]:
    def value(row: Dict[str, Any]) -> str:
        items = row.get(key) or []
        items = items if isinstance(items, list) else [items]
        return "; ".join(i if isinstance(i, str) else json.dumps(i, ensure_ascii=False) for i in items)
    return value


TABLES: Dict[str, Table] = {
    "findings": Table("Hallazgos", (
        Column("ID", _f("id")), Column("Tipo", _f("kind")), Column("Título", _f("title")),
        Column("Descripción", _f("description")), Column("Importe", _f("amount")), Column("Moneda", _f("currency")),
        Column("Riesgo", _f("risk")), Column("Confianza", _f("confidence")), Column("Etiqueta", _f("label")),
        Column("Estado", _f("status")), Column("Contraparte", _f("counterparty")), Column("Entidad", _f("entity")),
        Column("Fecha", _f("date")), Column("Categoría", _f("category")), Column("Quién aporta", _f("owner")),
        Column("Siguiente evidencia", _f("next_evidence")), Column("Evidencia", _listed("evidence_refs")),
        Column("Auditoría", _audit("audit_id")))),
    "evidence": Table("Evidencia", (
        Column("Ruta", _f("path")), Column("Archivo", _f("filename")), Column("Extensión", _f("ext")),
        Column("Tamaño (bytes)", _f("size")), Column("SHA-256", _f("sha256")), Column("MD5", _f("md5")),
        Column("Estado", _f("status")), Column("Bloque", _f("block")), Column("Tipo de documento", _f("doc_type")),
        Column("Fecha del documento", _f("doc_date")), Column("Entidad", _f("entity")),
        Column("Revisión", _f("review_status")), Column("Primera auditoría", _audit("first_audit_id")),
        Column("Dentro de un ZIP", lambda row: "sí" if row.get("zip_member") else "no"))),
    "timeline": Table("Cronología", (
        Column("Fecha", _f("ts")), Column("Evento", _f("event_type")), Column("Auditoría", _audit("audit_id")),
        Column("Actor", _f("actor")), Column("Descripción", _f("description")))),
    "criteria": Table("Criterios", (
        Column("ID", _f("id")), Column("Fecha", _f("date")), Column("Autor", _f("author")),
        Column("Texto (literal)", _f("text")), Column("Estado", _f("status")), Column("Auditoría", _audit("audit_id")))),
}


def csv_cell(value: Any) -> Any:
    """A CSV value: empty for None, JSON for structures, and text that a spreadsheet would read as a formula behind a
    leading apostrophe (OWASP CSV injection), unless it is just a signed number."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.startswith(_FORMULA_START) and not _NUMBER_RE.fullmatch(value):
        return "'" + value
    return value


def to_csv(table: Table, rows: Iterable[Dict[str, Any]], case: Dict[str, Any]) -> bytes:
    """RFC 4180 (comma, CRLF, quoted fields) in UTF-8 with a BOM."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([c.header for c in table.columns])
    writer.writerows([csv_cell(c.value(row)) for c in table.columns] for row in rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def load_openpyxl():
    """Imported only when an XLSX is asked for: without it the console still serves everything else."""
    try:
        import openpyxl
    except ImportError as exc:
        raise XlsxUnavailable("Falta openpyxl, dependencia del plugin Ghost Recon: la exportación a XLSX no está "
                              "disponible en esta instalación (CSV sí lo está).") from exc
    return openpyxl


def to_xlsx(table: Table, rows: Iterable[Dict[str, Any]], case: Dict[str, Any]) -> bytes:
    """One sheet, bold frozen header; Ghost Recon properties and docProps/app.xml, as the pack's workbook."""
    openpyxl = load_openpyxl()
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = table.title
    ws.append([c.header for c in table.columns])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for r, row in enumerate(rows, start=2):
        for col, column in enumerate(table.columns, start=1):
            value = column.value(row)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str):
                value = ILLEGAL_CHARACTERS_RE.sub("", value)  # OCR and chat exports carry control characters
            cell = ws.cell(row=r, column=col, value=value)
            if isinstance(value, str) and value.startswith("="):
                cell.data_type = "s"  # data that looks like a formula is text, never a formula (as in the pack)
    props = wb.properties
    props.creator = XLSX_CREATOR
    props.lastModifiedBy = "Ghost Recon"
    props.title = f"Ghost Recon — {table.title} — {case['name']}"
    props.subject = "Auditoría financiera forense"
    props.description = SIGNATURE
    props.keywords = f"Ghost Recon, forensic audit, {table.title}"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "table.xlsx"
        wb.save(str(path))
        rewrite_app_xml(path)
        return path.read_bytes()


WRITERS: Dict[str, Tuple[Callable[[Table, Iterable[Dict[str, Any]], Dict[str, Any]], bytes], str]] = {
    "csv": (to_csv, CSV_MEDIA), "xlsx": (to_xlsx, XLSX_MEDIA)}


def file_name(case: Dict[str, Any], table: str, fmt: str, now: Optional[datetime] = None) -> str:
    """``GhostRecon_<slug>_<table>_<YYYYMMDD-HHMM>.<fmt>`` (UTC)."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M")
    return f"GhostRecon_{case['slug']}_{table}_{stamp}.{fmt}"
```

- [ ] **Step 6: La ruta de las tablas**

Crea `plugins/ghost_recon/console/routers/exports.py`:

```python
"""Export endpoints (viewer): the case tables as CSV/XLSX with the filters of their JSON endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from .. import readmodel, tables
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..downloads import attachment
from .cases import get_case_or_404

router = APIRouter(tags=["exports"])


@router.get("/cases/{case_id}/{table}.{fmt}")
def table_file(case_id: str, table: str, fmt: str, request: Request, kind: str = "", risk: str = "",
               status: str = "", q: str = "", audit: str = "", principal: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    """``table`` ∈ findings | evidence | timeline | criteria, ``fmt`` ∈ csv | xlsx; every row that matches the filters
    (no pagination)."""
    case = get_case_or_404(ctx, case_id)
    spec, writer = tables.TABLES.get(table), tables.WRITERS.get(fmt)
    if spec is None or writer is None:
        raise ApiError(404, "not_found", f"tabla o formato desconocido: {table}.{fmt}")
    filters = readmodel.TableFilters(kind=kind, risk=risk, status=status, q=q, audit=audit)
    rows = readmodel.TABLE_ROWS[table](ctx.store, case_id, filters)
    write, media_type = writer
    try:
        data = write(spec, rows, case)
    except tables.XlsxUnavailable as exc:
        raise ApiError(503, "xlsx_unavailable", str(exc)) from exc
    ctx.cstore.log("table_export", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=case_id, detail={"table": table, "format": fmt, "rows": len(rows),
                                           "filters": {k: v for k, v in asdict(filters).items() if v}})
    return attachment(data, tables.file_name(case, table, fmt), media_type)
```

En `plugins/ghost_recon/console/app.py`, sustituye:

```python
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, fs as fs_routes,
                      jobs as jobs_routes, system as system_routes, users as users_routes)
```

por:

```python
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, exports as exports_routes,
                      fs as fs_routes, jobs as jobs_routes, system as system_routes, users as users_routes)
```

y sustituye:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes)
```

por:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes,
           exports_routes)
```

- [ ] **Step 7: Versionar los módulos `export*`**

El `.gitignore` raíz del repositorio ignora `export*` (línea `export*`), así que `git add` rechazaría `routers/exports.py` y, más adelante, `exporter.py`, `exports.py` y `static/views/export.js`. Un `.gitignore` en la carpeta de la consola los reincluye sin tocar el raíz.

Crea `plugins/ghost_recon/console/.gitignore`:

```text
# The repository root ignores ``export*`` (local export dumps). Under the console those names are source files
# (exporter.py, exports.py, routers/exports.py, static/views/export.js), so they are tracked.
!export*
```

Run: `git check-ignore -q plugins/ghost_recon/console/routers/exports.py && echo IGNORADO || echo versionable`
Expected: `versionable` (sin el `.gitignore` de la consola diría `IGNORADO`).

- [ ] **Step 8: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_tables.py tests/plugins/ghost_recon/console/test_api_cases.py -q`
Expected: `0 failed`. Sin openpyxl en el venv, `test_xlsx_opens_with_the_ghost_recon_metadata_and_no_live_formula` sale como skipped; la ruta de 503 sí se prueba.

- [ ] **Step 9: Commit**

```bash
git add plugins/ghost_recon/console/readmodel.py plugins/ghost_recon/console/routers/cases.py plugins/ghost_recon/console/tables.py plugins/ghost_recon/console/routers/exports.py plugins/ghost_recon/console/.gitignore plugins/ghost_recon/console/app.py tests/plugins/ghost_recon/console/test_tables.py
git commit -m "feat(ghost-recon): console case tables as CSV (UTF-8 BOM) and XLSX with the active filters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 5: El ZIP de resultados — selección, sellos, empaquetado y manifiesto

**Files:**
- Create: `plugins/ghost_recon/console/exporter.py`
- Test: `tests/plugins/ghost_recon/console/test_exporter.py`

**Interfaces:**
- Consumes: `integrity.record_seal_check/changed_files/seal_hashes/relative/expected_hash/check/IntegrityError` (Tarea 3), `paths.case_results_root/resolve_within`, `commands.CONSOLE_DIR`, `core.casefolder.CASE_JSON/CORPUS_INVENTORY/SEALED_FILE`, `core.ids.short_audit`, `core.db.utcnow`, `CONSOLE_VERSION`.
- Produces:
  - `exporter.ExportError(status, code, message)` con `code ∈ {not_found, results_missing, results_hold_evidence, audit_outside_results, not_sealed, job_running, nothing_to_export, seal_broken}`;
  - `exporter.exports_dir() -> Path` (`<plugin-data>/ghost-recon/console/exports/`, junto a `jobs/`);
  - `exporter.Selection(case, results_root, scope, seq, audits, excluded)` con `.draft`; cada auditoría lleva `"draft": bool`;
  - `exporter.select(store, case, *, scope, seq, include_unsealed, busy) -> Selection` (`busy`: hay una ejecución activa en el caso) y `exporter.selection_view(sel) -> dict` (lo que muestra la vista previa; cada excluida con su `text`);
  - `exporter.plan_entries(sel) -> (entries, skipped)`, `exporter.verify_seals(store, cstore, sel, username) -> {audit_id: checked_at}`, `exporter.zip_name(sel, now) -> str`;
  - `exporter.build(store, cstore, sel, *, export_id, exported_by, dest_dir, now=None, progress=None) -> {"file_name", "path", "size", "sha256", "manifest"}`; `progress(done, total)` se llama tras cada archivo;
  - `exporter.MANIFEST_NAME = "EXPORT_MANIFEST.json"`, `exporter.GENERATOR`, `exporter.EXCLUDED_REASONS`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Las pruebas de enlaces llevan su marca de SO: en POSIX un symlink de archivo y otro de carpeta; en Windows una unión NTFS (`_winapi.CreateJunction`, que no necesita privilegios; los symlinks de Windows sí).

Crea `tests/plugins/ghost_recon/console/test_exporter.py`:

```python
"""The results ZIP (spec §11): the manifest matches the archive and the archive its sidecar, the evidence never goes
in (symlinks and junctions included), a broken seal blocks naming the file, unsealed audits only as DRAFT and never
while a job is active, and a sealed file that changes during the build fails it."""
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.ghost_recon.console import exporter
from plugins.ghost_recon.console.exporter import ExportError

NOW = datetime(2026, 10, 4, 15, 30, tzinfo=timezone.utc)


def _select(store, seeded, **kw):
    options = {"scope": "case", "seq": None, "include_unsealed": False, "busy": False, **kw}
    return exporter.select(store, store.get_case(seeded["case_id"]), **options)


def _build(store, cstore, seeded, dest, export_id=1, **kw):
    return exporter.build(store, cstore, _select(store, seeded, **kw), export_id=export_id, exported_by="vera",
                          dest_dir=dest, now=NOW)


@pytest.fixture
def dest(tmp_path):
    """Where the archives go (tmp_path itself also holds the test DB and the case root)."""
    path = tmp_path / "exports"
    path.mkdir()
    return path


def _open(result):
    zf = zipfile.ZipFile(result["path"])
    return zf, json.loads(zf.read(exporter.MANIFEST_NAME))


def test_the_manifest_lists_every_packed_file_and_the_zip_matches_its_sidecar(store, cstore, seeded, dest):
    result = _build(store, cstore, seeded, dest)
    zf, manifest = _open(result)
    names = [n for n in zf.namelist() if n != exporter.MANIFEST_NAME]
    assert [f["path"] for f in manifest["files"]] == names
    for f in manifest["files"]:
        data = zf.read(f["path"])
        assert (f["size"], f["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
    digest = hashlib.sha256(Path(result["path"]).read_bytes()).hexdigest()
    sidecar = dest / f"{result['file_name']}.sha256"
    assert result["sha256"] == digest
    assert sidecar.read_bytes() == f"{digest}  {result['file_name']}\n".encode("utf-8")  # sha256sum -c format
    a1 = store.get_audit(seeded["a1"])
    assert [(a["id"], a["state"], a["seal_sha256"]) for a in manifest["audits"]] == [(a1["id"], "SEALED",
                                                                                    a1["seal_sha256"])]
    assert manifest["audits"][0]["verified_at"] and manifest["exported_by"] == "vera"
    assert manifest["generator"].startswith("Ghost Recon Console ") and manifest["export_id"] == 1
    assert [e["seq"] for e in manifest["excluded"]] == ["A02"] and manifest["draft"] is False
    assert result["file_name"] == f"GhostRecon_{store.get_case(seeded['case_id'])['slug']}_case_20261004-1530.zip"
    assert not list(dest.glob("*.part"))


def test_the_evidence_never_enters_the_archive(store, cstore, seeded, dest):
    zf, _ = _open(_build(store, cstore, seeded, dest, include_unsealed=True))
    folders = {Path(store.get_audit(a)["folder"]).name for a in (seeded["a1"], seeded["a2"])}
    allowed = ("case.json", "corpus_inventory.csv", exporter.MANIFEST_NAME, "_console/",
               *(f"{name}/" for name in folders))
    assert all(n.startswith(allowed) for n in zf.namelist())
    evidence = {e["path"] for e in store.list_evidence(seeded["case_id"])}
    assert evidence and not evidence & set(zf.namelist())


@pytest.mark.platforms("posix")
def test_symlinks_inside_the_results_folder_are_never_followed_posix(store, cstore, seeded, dest):
    report_dir = seeded["a2_folder"] / "06_Report"
    os.symlink(seeded["root"] / "Bancos" / "extracto_2026-01.txt", report_dir / "extracto.txt")
    console = seeded["a1_folder"].parent / "_console"
    console.mkdir()
    os.symlink(seeded["root"], console / "evidencia", target_is_directory=True)
    zf, manifest = _open(_build(store, cstore, seeded, dest, include_unsealed=True))
    assert not any(n.endswith("extracto.txt") or "/evidencia" in n for n in zf.namelist())
    assert {(s["path"].rsplit("/", 1)[-1], s["reason"]) for s in manifest["skipped"]} == {
        ("extracto.txt", "symlink"), ("evidencia", "symlink")}


@pytest.mark.platforms("windows")
def test_junctions_inside_the_results_folder_are_never_followed_windows(store, cstore, seeded, dest):
    import _winapi
    console = seeded["a1_folder"].parent / "_console"
    console.mkdir()
    _winapi.CreateJunction(str(seeded["root"] / "Bancos"), str(console / "evidencia"))
    zf, manifest = _open(_build(store, cstore, seeded, dest))
    assert not any("evidencia" in n for n in zf.namelist())
    assert manifest["skipped"] == [{"path": "_console/evidencia", "reason": "symlink"}]


def test_a_results_folder_that_holds_the_evidence_is_refused(store, seeded):
    store.update_case(seeded["case_id"], meta={"out_dir": str(seeded["root"])})
    with pytest.raises(ExportError) as refused:
        _select(store, seeded)
    assert refused.value.code == "results_hold_evidence"


def test_a_broken_seal_blocks_the_export_and_names_the_file(store, cstore, seeded, dest):
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    report.write_text(report.read_text(encoding="utf-8") + "\nalterado", encoding="utf-8")
    with pytest.raises(ExportError) as blocked:
        _build(store, cstore, seeded, dest)
    assert blocked.value.code == "seal_broken" and f"06_Report/{report.name}" in blocked.value.message
    assert list(dest.iterdir()) == []
    assert cstore.get_seal_check(seeded["a1"])["ok"] is False  # the views now show the broken seal too


def test_a_sealed_file_changed_during_the_build_fails_it(store, cstore, seeded, dest, monkeypatch):
    """Review Focus: the file changes after the seal check passed and before it is packed."""
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    real = exporter.plan_entries

    def tamper_after_check(sel):
        planned = real(sel)
        report.write_bytes(report.read_bytes() + b"\nalterado durante la exportacion")
        return planned

    monkeypatch.setattr(exporter, "plan_entries", tamper_after_check)
    with pytest.raises(ExportError) as failed:
        _build(store, cstore, seeded, dest)
    assert failed.value.code == "seal_broken" and report.name in failed.value.message
    assert list(dest.iterdir()) == []  # no partial archive is left behind


def test_unsealed_audits_only_on_request_and_marked_draft(store, cstore, seeded, dest):
    result = _build(store, cstore, seeded, dest, include_unsealed=True)
    _, manifest = _open(result)
    states = {a["seq"]: (a["state"], a["sealed"], a["seal_sha256"]) for a in manifest["audits"]}
    assert states["A02"] == ("DRAFT", False, None) and states["A01"][0] == "SEALED"
    assert manifest["draft"] is True and "_case-DRAFT_" in result["file_name"]


def test_an_open_audit_never_goes_in_while_a_job_is_active_on_the_case(store, seeded):
    sel = _select(store, seeded, include_unsealed=True, busy=True)
    assert [a["id"] for a in sel.audits] == [seeded["a1"]]
    assert sel.excluded == [{"id": seeded["a2"], "seq": "A02", "reason": "job_running"}]
    with pytest.raises(ExportError) as busy:
        _select(store, seeded, scope="audit", seq="A02", include_unsealed=True, busy=True)
    assert busy.value.code == "job_running"
    with pytest.raises(ExportError) as unsealed:
        _select(store, seeded, scope="audit", seq="A02")
    assert unsealed.value.code == "not_sealed"


def test_accented_file_names_are_stored_as_utf8_and_match_the_manifest(store, cstore, seeded, dest):
    """Review Focus: Spanish names (accents, ñ) must open intact on Windows and macOS."""
    name = "06_Report/Conciliación año 2026 — señal.md"
    (seeded["a2_folder"] / name).write_text("borrador\n", encoding="utf-8")
    zf, manifest = _open(_build(store, cstore, seeded, dest, scope="audit", seq="A02", include_unsealed=True))
    arc = f"{seeded['a2_folder'].name}/{name}"
    assert arc in zf.namelist() and zf.getinfo(arc).flag_bits & 0x800  # the UTF-8 name flag
    assert arc in [f["path"] for f in manifest["files"]]


def test_two_exports_in_the_same_minute_never_share_a_file(store, cstore, seeded, dest):
    """Review Focus: a double click on "Exportar" builds twice within one minute."""
    first = _build(store, cstore, seeded, dest, export_id=1)
    second = _build(store, cstore, seeded, dest, export_id=2)
    assert first["file_name"] != second["file_name"] and Path(first["path"]).is_file()
    assert _open(first)[1]["export_id"] == 1 and _open(second)[1]["export_id"] == 2
    for result in (first, second):
        assert hashlib.sha256(Path(result["path"]).read_bytes()).hexdigest() == result["sha256"]
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_exporter.py -q`
Expected: FAIL con `ImportError: cannot import name 'exporter' from 'plugins.ghost_recon.console'`.

- [ ] **Step 3: Crear `console/exporter.py`**

Puntos que la implementación cuida (todos con su prueba):
- solo lee `case.json`, `corpus_inventory.csv`, `_console/` y las carpetas de las auditorías elegidas, todo dentro de la carpeta de resultados ya resuelta; `os.walk` nunca entra en un symlink ni en una unión (se filtran en `dirnames`) y un archivo que no resuelve dentro de esa carpeta queda fuera;
- verifica los sellos con `integrity.record_seal_check` (la vista ya muestra «verificado hace X» tras exportar) y, al empaquetar, vuelve a hashear cada archivo sellado contra `SEALED.json`; al final comprueba que no falte ninguno (salvo los omitidos por ser enlaces);
- escribe `<nombre>.part`, lo renombra al terminar y deja `<nombre>.sha256` en bytes (LF también en Windows: `write_text` lo convertiría en CRLF y `sha256sum -c` lo rechazaría);
- `ZipInfo` con la fecha del archivo (nunca anterior a 1980) y `force_zip64` para miembros de 1 GiB o más; `zipfile` marca solo los nombres no ASCII como UTF-8.

Crea `plugins/ghost_recon/console/exporter.py`:

```python
"""ZIP of a case's results (spec §11): what goes in, the seal checks before and while packing, and the manifest.

Only the case's results folder is read (``<case>/<audits_dir>`` or its ``--out``), never the evidence: ``case.json``,
``corpus_inventory.csv``, ``_console/`` and the selected audit folders (reviews included). Symlinks and junctions are
skipped and listed, every file must resolve inside the results folder, and a results folder that holds the case's
evidence folder is refused. Unsealed audits go in only on request and marked DRAFT; while a job is active on the case
its open audits never do. Each selected seal is verified first and every sealed file is hashed again as it is packed,
so a change at any moment fails the export naming the file. The archive is written as ``<name>.part`` and renamed only
once complete, with its SHA-256 beside it in ``<name>.sha256`` (``sha256sum -c`` format).
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from ..core import casefolder as cf, ids
from ..core.db import Store, utcnow
from . import CONSOLE_VERSION, integrity
from .commands import CONSOLE_DIR
from .paths import case_results_root, resolve_within
from .store import ConsoleStore

MANIFEST_NAME = "EXPORT_MANIFEST.json"
GENERATOR = f"Ghost Recon Console {CONSOLE_VERSION}"
ROOT_FILES = (cf.CASE_JSON, cf.CORPUS_INVENTORY)
CHUNK = 1024 * 1024
ZIP64_FORCE_BYTES = 1 << 30  # stream larger members with ZIP64 headers from the start
EXCLUDED_REASONS = {
    "not_sealed": "está abierta (sin sellar): solo entra si un admin incluye las auditorías abiertas",
    "job_running": "hay una ejecución activa en el caso y la auditoría abierta puede estar a medio escribir",
}


class ExportError(Exception):
    """An export the console refuses or stops; ``status`` and ``code`` map to the API error envelope."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def exports_dir() -> Path:
    """``<plugin data>/console/exports/`` (beside ``jobs/``, next to ``ghostrecon.db``)."""
    from .. import runtime
    path = runtime.db_path().parent / "console" / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Selection:
    case: Dict[str, Any]
    results_root: Path
    scope: str
    seq: Optional[str]
    audits: List[Dict[str, Any]]    # the audit rows that go in, each with "draft" (True = not sealed)
    excluded: List[Dict[str, str]]  # {"id", "seq", "reason"}

    @property
    def draft(self) -> bool:
        return any(a["draft"] for a in self.audits)


def results_root_for(case: Dict[str, Any]) -> Path:
    """The case's results folder (resolved): refused when it is missing or when the case's evidence folder lies
    inside it, since then the archive could carry original evidence."""
    root = case_results_root(case)
    if not root.is_dir():
        raise ExportError(409, "results_missing", f"La carpeta de resultados del caso no existe: {root}")
    if resolve_within(case["root_path"], [root]) is not None:
        raise ExportError(409, "results_hold_evidence", "La carpeta de resultados del caso contiene su carpeta de "
                          "evidencia; la evidencia original nunca se exporta, así que la consola no la empaqueta.")
    return root.resolve()


def select(store: Store, case: Dict[str, Any], *, scope: str, seq: Optional[str], include_unsealed: bool,
           busy: bool) -> Selection:
    """Which audits an export takes and why the others stay out. ``busy``: a job is active on the case."""
    root = results_root_for(case)
    audits = store.list_audits(case["id"])
    if scope == "audit":
        audits = [a for a in audits if ids.short_audit(a["id"]) == seq]
        if not audits:
            raise ExportError(404, "not_found", f"auditoría no encontrada: {seq}")
    chosen: List[Dict[str, Any]] = []
    excluded: List[Dict[str, str]] = []
    for audit in audits:
        short = ids.short_audit(audit["id"])
        sealed = audit["status"] == "sealed"
        reason = None if sealed else ("job_running" if busy else (None if include_unsealed else "not_sealed"))
        if reason:
            excluded.append({"id": audit["id"], "seq": short, "reason": reason})
            continue
        if resolve_within(audit["folder"], [root]) is None:
            raise ExportError(409, "audit_outside_results", f"La carpeta de {short} no existe o no está dentro de "
                              "la carpeta de resultados del caso: no se exporta.")
        chosen.append({**audit, "draft": not sealed})
    if not chosen:
        if scope == "audit":
            first = excluded[0]
            raise ExportError(409, first["reason"], f"{first['seq']} no se puede exportar: "
                              f"{EXCLUDED_REASONS[first['reason']]}.")
        raise ExportError(409, "nothing_to_export", "El caso no tiene auditorías que se puedan exportar: ninguna "
                          "está sellada (un admin puede incluir las abiertas, marcadas como borrador).")
    return Selection(case, root, scope, seq if scope == "audit" else None, chosen, excluded)


def selection_view(sel: Selection) -> Dict[str, Any]:
    return {"scope": sel.scope, "seq": sel.seq, "draft": sel.draft, "results_root": str(sel.results_root),
            "audits": [{"id": a["id"], "seq": ids.short_audit(a["id"]), "kind": a["kind"], "status": a["status"],
                        "draft": a["draft"]} for a in sel.audits],
            "excluded": [{**e, "text": EXCLUDED_REASONS[e["reason"]]} for e in sel.excluded]}


@dataclass(frozen=True)
class Entry:
    arcname: str
    path: Path
    audit_folder: Optional[Path] = None      # set for the files of a SEALED audit: they are checked as packed
    seal: Optional[Dict[str, str]] = None    # that audit's SEALED.json hashes


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _arc(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _walk(base: Path, root: Path, skipped: List[Dict[str, str]]) -> Iterator[Path]:
    """Regular files under ``base``, sorted; symlinks and junctions are never followed nor packed, and a file that
    does not resolve inside ``root`` is left out. Both go to ``skipped``."""
    for dirpath, dirnames, filenames in os.walk(base):
        here = Path(dirpath)
        kept = []
        for name in sorted(dirnames):
            if _is_link(here / name):
                skipped.append({"path": _arc(here / name, root), "reason": "symlink"})
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = here / name
            if _is_link(path):
                skipped.append({"path": _arc(path, root), "reason": "symlink"})
            elif resolve_within(path, [root]) is None:
                skipped.append({"path": _arc(path, root), "reason": "outside_results"})
            else:
                yield path


def plan_entries(sel: Selection) -> Tuple[List[Entry], List[Dict[str, str]]]:
    root, skipped, entries = sel.results_root, [], []
    for name in ROOT_FILES:
        path = root / name
        if _is_link(path):
            skipped.append({"path": name, "reason": "symlink"})
        elif path.is_file():
            entries.append(Entry(name, path))
    console = root / CONSOLE_DIR
    if _is_link(console):
        skipped.append({"path": CONSOLE_DIR, "reason": "symlink"})
    elif console.is_dir():
        entries += [Entry(_arc(p, root), p) for p in _walk(console, root, skipped)]
    for audit in sel.audits:
        folder = resolve_within(audit["folder"], [root])
        seal = None if audit["draft"] else integrity.seal_hashes(folder)
        sealed_folder = None if audit["draft"] else folder
        entries += [Entry(_arc(p, root), p, sealed_folder, seal) for p in _walk(folder, root, skipped)]
    return entries, skipped


def verify_seals(store: Store, cstore: ConsoleStore, sel: Selection, username: str) -> Dict[str, str]:
    """Every selected sealed audit re-hashed against its seal (and cached as a seal check). The first broken one
    stops the export, naming what changed. ``{audit_id: checked_at}``."""
    verified: Dict[str, str] = {}
    for audit in sel.audits:
        if audit["draft"]:
            continue
        check = integrity.record_seal_check(store, cstore, audit, username)
        if not check["ok"]:
            raise ExportError(409, "seal_broken", f"El sello de {ids.short_audit(audit['id'])} está roto: "
                              f"{integrity.changed_files(check['detail'])}. No se exportó nada.")
        verified[audit["id"]] = check["checked_at"]
    return verified


def _zip_time(mtime: float) -> Tuple[int, int, int, int, int, int]:
    stamp = max(datetime.fromtimestamp(mtime, timezone.utc), datetime(1980, 1, 1, tzinfo=timezone.utc))
    return stamp.timetuple()[:6]


def _pack(zf: zipfile.ZipFile, entry: Entry) -> Tuple[str, int]:
    """Stream one file into the archive, hashing exactly the bytes written."""
    st = entry.path.stat()
    info = zipfile.ZipInfo(entry.arcname, date_time=_zip_time(st.st_mtime))
    info.compress_type = zipfile.ZIP_DEFLATED
    digest, size = hashlib.sha256(), 0
    with open(entry.path, "rb") as src, zf.open(info, "w", force_zip64=st.st_size >= ZIP64_FORCE_BYTES) as dst:
        while chunk := src.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            dst.write(chunk)
    return digest.hexdigest(), size


def _check_sealed(entry: Entry, sha: str) -> str:
    """The packed bytes of a sealed file must still be the sealed ones; returns its path inside the audit."""
    rel = integrity.relative(entry.audit_folder, entry.path)
    if rel != cf.SEALED_FILE:  # the seal itself: its hash is the audit's seal_sha256, checked by verify_seals
        try:
            integrity.check(rel, sha, integrity.expected_hash(entry.seal, rel))
        except integrity.IntegrityError as exc:
            raise ExportError(409, "seal_broken", f"{entry.arcname} cambió mientras se exportaba ({exc.message}). "
                              "No se exportó nada.") from exc
    return rel


def zip_name(sel: Selection, now: datetime) -> str:
    """``GhostRecon_<slug>_<scope>_<YYYYMMDD-HHMM>.zip`` (UTC); ``<scope>`` is ``case`` or the audit (``A02``), with
    ``-DRAFT`` when unsealed audits go in."""
    scope = (sel.seq or "case") + ("-DRAFT" if sel.draft else "")
    return f"GhostRecon_{sel.case['slug']}_{scope}_{now.strftime('%Y%m%d-%H%M')}.zip"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def build(store: Store, cstore: ConsoleStore, sel: Selection, *, export_id: int, exported_by: str, dest_dir: Path,
          now: Optional[datetime] = None, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Verify, pack and publish the archive. ``{"file_name", "path", "size", "sha256", "manifest"}``; ExportError
    (nothing left behind) when a seal is broken or changes during the build."""
    verified = verify_seals(store, cstore, sel, exported_by)
    entries, skipped = plan_entries(sel)
    dest_dir = Path(dest_dir)
    name = zip_name(sel, now or datetime.now(timezone.utc))
    if (dest_dir / name).exists() or (dest_dir / f"{name}.part").exists():
        name = f"{name[:-4]}_e{export_id}.zip"  # two exports in the same minute never share a file
    final, part = dest_dir / name, dest_dir / f"{name}.part"
    files: List[Dict[str, Any]] = []
    packed: Dict[Path, Set[str]] = {}
    try:
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for done, entry in enumerate(entries, 1):
                sha, size = _pack(zf, entry)
                if entry.audit_folder is not None:
                    packed.setdefault(entry.audit_folder, set()).add(_check_sealed(entry, sha))
                files.append({"path": entry.arcname, "size": size, "sha256": sha})
                if progress:
                    progress(done, len(entries))
            skipped_paths = {s["path"] for s in skipped}
            for folder, rels in packed.items():
                seal = integrity.seal_hashes(folder) or {}
                lost = sorted(rel for rel in set(seal) - rels
                              if _arc(folder / rel, sel.results_root) not in skipped_paths)
                if lost:
                    raise ExportError(409, "seal_broken", f"{_arc(folder / lost[0], sel.results_root)} desapareció "
                                      "mientras se exportaba la auditoría sellada. No se exportó nada.")
            manifest = {
                "export_id": export_id, "case_id": sel.case["id"], "case_name": sel.case["name"], "scope": sel.scope,
                "seq": sel.seq, "draft": sel.draft,
                "audits": [{"id": a["id"], "seq": ids.short_audit(a["id"]), "kind": a["kind"],
                            "sealed": not a["draft"], "state": "DRAFT" if a["draft"] else "SEALED",
                            "seal_sha256": None if a["draft"] else a.get("seal_sha256"),
                            "verified_at": verified.get(a["id"])} for a in sel.audits],
                "excluded": sel.excluded, "skipped": skipped, "files": files,
                "exported_by": exported_by, "exported_at": utcnow(), "generator": GENERATOR}
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        sha = _sha256_file(part)
        os.replace(part, final)
        (dest_dir / f"{name}.sha256").write_bytes(f"{sha}  {name}\n".encode("utf-8"))  # LF on every OS
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return {"file_name": name, "path": final, "size": final.stat().st_size, "sha256": sha, "manifest": manifest}
```

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_exporter.py -q`
Expected: `0 failed`; en Windows la prueba POSIX de symlinks sale como skipped y en Linux/macOS la de uniones NTFS.

- [ ] **Step 5: Commit**

```bash
git add plugins/ghost_recon/console/exporter.py tests/plugins/ghost_recon/console/test_exporter.py
git commit -m "feat(ghost-recon): console results ZIP builder with seal checks, manifest and sha256 sidecar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 6: Exportación en segundo plano, API del ZIP y mantenimiento periódico

**Files:**
- Create: `plugins/ghost_recon/console/exports.py`
- Create: `plugins/ghost_recon/console/housekeeping.py`
- Modify: `plugins/ghost_recon/console/deps.py` (`ConsoleContext.exports`)
- Modify: `plugins/ghost_recon/console/app.py` (`create_app(..., exports=, housekeeping=)` y lifespan)
- Modify (reemplazar): `plugins/ghost_recon/console/routers/exports.py`
- Test: `tests/plugins/ghost_recon/console/test_api_exports.py`
- Test: `tests/plugins/ghost_recon/console/test_housekeeping.py`

**Interfaces:**
- Consumes: `exporter.select/selection_view/build/exports_dir/ExportError` (Tarea 5); `ConsoleStore.create_export/get_export/list_exports/update_export/purge_sessions/list_jobs/get_user/log` (Tarea 1); `fsjail.folder_key`; `jobfiles.raw_path/log_path/events_path/runner_log_path/work_dir`; `Store.add_event`.
- Produces:
  - `exports.ExportService(cstore, store, settings, *, exports_dir=None)` con `.dir`, `busy(case) -> bool`, `selection(case, *, scope, seq, include_unsealed)`, `preview(case, *, scope, seq, include_unsealed) -> dict`, `request(case, *, scope, seq, include_unsealed, principal, ip="") -> row` (rechaza en el acto con `ExportError` lo que nunca se podría construir), `file_path(row) -> Optional[Path]`, `build(export_id) -> row`, `recover() -> List[int]`, `start()` y `stop()`;
  - registro: `export_request` (con IP), `export` (archivo, tamaño, SHA-256) o `export_failed` (`code`, `message`), y `export_download`; cronología del caso: `results_exported` con el SHA-256 del ZIP y el usuario como actor;
  - `housekeeping.Housekeeping(cstore, settings, *, exports_dir, jobs_dir, clock=_utcnow, interval_s=3600.0)` con `run_once() -> {"sessions", "exports", "job_files"}`, `purge_sessions()`, `prune_exports()`, `prune_job_files()`, `start()` (una pasada y luego cada hora) y `stop()`;
  - `create_app(settings, store, cstore, *, auth=None, jobs=None, exports=None, housekeeping=None)`; el lifespan arranca `jobs`, `exports` y `housekeeping` y los para en orden inverso; `ConsoleContext.exports`;
  - rutas (viewer): `GET /cases/{id}/export/preview?scope=&seq=&include_unsealed=`, `POST /cases/{id}/export` (`{scope, seq?, include_unsealed?}` → 202 `{"export_id", "export"}`), `GET /exports/{eid}`, `GET /exports/{eid}/download` (409 `not_ready`, 410 `gone`), `GET /exports/{eid}/sha256`. `include_unsealed=true` de un viewer → 403; si no se indica, vale `export_include_unsealed` solo para un admin.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crea `tests/plugins/ghost_recon/console/test_api_exports.py`:

```python
"""Export API: a background build with progress whose download matches its SHA-256, the role rules of unsealed
audits, the preview of what goes in, a broken seal that fails the build, the audit trail, and builds that a server
restart interrupted."""
import hashlib
from dataclasses import replace

from plugins.ghost_recon.console.exports import ExportService


def _wait_done(c, wait_until, export_id):
    def done():
        row = c.get(f"/api/v1/exports/{export_id}").json()
        return row if row["status"] in ("succeeded", "failed") else None
    return wait_until(done, timeout=60, message="export end")


def _export(c, seeded, **body):
    return c.post(f"/api/v1/cases/{seeded['case_id']}/export", json=body)


def test_a_viewer_exports_the_case_and_downloads_exactly_the_hashed_zip(login_as, seeded, store, wait_until):
    c = login_as("viewer")
    r = _export(c, seeded)
    assert r.status_code == 202 and r.json()["export"]["status"] == "queued"
    row = _wait_done(c, wait_until, r.json()["export_id"])
    assert row["status"] == "succeeded" and row["files_done"] == row["files_total"] > 0
    assert row["detail"]["excluded"][0]["seq"] == "A02"  # open audit: left out by default
    zip_bytes = c.get(f"/api/v1/exports/{row['id']}/download")
    assert zip_bytes.status_code == 200 and zip_bytes.headers["content-type"] == "application/zip"
    assert hashlib.sha256(zip_bytes.content).hexdigest() == row["sha256"]
    sidecar = c.get(f"/api/v1/exports/{row['id']}/sha256").text
    assert sidecar == f"{row['sha256']}  {row['file_name']}\n"
    event = next(e for e in store.list_events(seeded["case_id"]) if e["event_type"] == "results_exported")
    assert event["actor"] == "vera" and event["ref"]["sha256"] == row["sha256"]
    actions = [(e["action"], e["username"]) for e in login_as("admin").get("/api/v1/system/audit-log").json()["items"]]
    assert {("export_request", "vera"), ("export", "vera"), ("export_download", "vera")} <= set(actions)


def test_only_an_admin_includes_unsealed_audits_and_they_come_marked_draft(login_as, seeded, wait_until):
    viewer = login_as("viewer")
    r = _export(viewer, seeded, include_unsealed=True)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert viewer.get(f"/api/v1/cases/{seeded['case_id']}/export/preview",
                      params={"include_unsealed": "true"}).status_code == 403
    admin = login_as("admin")
    row = _wait_done(admin, wait_until, _export(admin, seeded, include_unsealed=True).json()["export_id"])
    assert row["status"] == "succeeded" and row["detail"]["draft"] is True and "-DRAFT_" in row["file_name"]
    assert {a["seq"]: a["state"] for a in row["detail"]["audits"]} == {"A01": "SEALED", "A02": "DRAFT"}


def test_the_configured_default_includes_unsealed_audits_for_admins_only(store, cstore, settings, auth, jobs,
                                                                        login_on, seeded):
    from plugins.ghost_recon.console.app import create_app
    app = create_app(replace(settings, export_include_unsealed=True), store, cstore, auth=auth, jobs=jobs)
    url = f"/api/v1/cases/{seeded['case_id']}/export/preview"
    admin = login_on(app, "admin").get(url).json()
    viewer = login_on(app, "viewer").get(url).json()
    assert admin["include_unsealed"] is True and [a["seq"] for a in admin["audits"]] == ["A01", "A02"]
    assert viewer["include_unsealed"] is False and [a["seq"] for a in viewer["audits"]] == ["A01"]
    assert viewer["can_include_unsealed"] is False and admin["can_include_unsealed"] is True


def test_the_preview_explains_what_stays_out_while_a_job_is_active(login_as, seeded, cstore):
    c = login_as("admin")
    url = f"/api/v1/cases/{seeded['case_id']}/export/preview"
    assert c.get(url, params={"include_unsealed": "true"}).json()["excluded"] == []
    cstore.create_job(command="rerun-case", folder=str(seeded["root"]), args={}, argv=["x"], launched_by="jean",
                      case_id=seeded["case_id"])  # queued: it may start writing at any moment
    preview = c.get(url, params={"include_unsealed": "true"}).json()
    assert [(e["seq"], e["reason"]) for e in preview["excluded"]] == [("A02", "job_running")] and preview["excluded"][0]["text"]
    r = c.post(f"/api/v1/cases/{seeded['case_id']}/export", json={"scope": "audit", "seq": "A02",
                                                                   "include_unsealed": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "job_running"


def test_requests_that_could_never_build_are_refused_at_once(login_as, seeded):
    c = login_as("viewer")
    assert _export(c, seeded, scope="audit").status_code == 422  # no seq
    assert _export(c, seeded, scope="audit", seq="A09").json()["error"]["code"] == "not_found"
    unsealed = _export(c, seeded, scope="audit", seq="A02")
    assert unsealed.status_code == 409 and unsealed.json()["error"]["code"] == "not_sealed"
    assert c.get("/api/v1/exports/999").status_code == 404


def test_a_broken_seal_fails_the_build_naming_the_file(login_as, seeded, wait_until):
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    report.write_text(report.read_text(encoding="utf-8") + "\nalterado", encoding="utf-8")
    c = login_as("viewer")
    row = _wait_done(c, wait_until, _export(c, seeded).json()["export_id"])
    assert row["status"] == "failed" and row["detail"]["code"] == "seal_broken" and report.name in row["error"]
    assert c.get(f"/api/v1/exports/{row['id']}/download").status_code == 410
    log = login_as("admin").get("/api/v1/system/audit-log").json()["items"]
    assert any(e["action"] == "export_failed" and e["detail"]["code"] == "seal_broken" for e in log)


def test_builds_a_restart_interrupted_end_failed_and_leave_no_partial_file(cstore, store, settings, seeded, tmp_path):
    """Review Focus: the server stops while a ZIP is being built."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    building = cstore.create_export(case_id=seeded["case_id"], scope="case", seq=None, include_unsealed=False,
                                    created_by="vera")
    cstore.update_export(building["id"], status="building", files_total=10, files_done=3)
    queued = cstore.create_export(case_id=seeded["case_id"], scope="case", seq=None, include_unsealed=False,
                                  created_by="vera")
    (exports_dir / "GhostRecon_acme_case_20261004-1530.zip.part").write_bytes(b"PK\x03\x04 a medias")
    service = ExportService(cstore, store, settings, exports_dir=exports_dir)
    service.start()  # what the lifespan of a new server calls first
    service.stop()
    for export_id in (building["id"], queued["id"]):
        row = cstore.get_export(export_id)
        assert row["status"] == "failed" and row["detail"] == {"code": "interrupted"} and "reinici" in row["error"]
    assert list(exports_dir.iterdir()) == []
```

Crea `tests/plugins/ghost_recon/console/test_housekeeping.py`:

```python
"""Housekeeping: sessions past their expiry go, results ZIPs keep at most the newest ``count`` and none older than
``days``, and old job files go while active jobs keep theirs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from plugins.ghost_recon.console import jobfiles
from plugins.ghost_recon.console.housekeeping import Housekeeping

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _stamp(**ago):
    return (NOW - timedelta(**ago)).isoformat().replace("+00:00", "Z")


def _keeper(cstore, settings, tmp_path, **retention):
    exports_dir, jobs_dir = tmp_path / "exports", tmp_path / "jobs"
    exports_dir.mkdir(exist_ok=True)
    jobs_dir.mkdir(exist_ok=True)
    config = replace(settings, **retention)
    return Housekeeping(cstore, config, exports_dir=exports_dir, jobs_dir=jobs_dir, clock=lambda: NOW)


def test_sessions_past_their_idle_or_absolute_expiry_and_revoked_ones_go(cstore, settings, tmp_path):
    user = cstore.create_user("jean", "hash", "admin")

    def session(token, seen, expires):
        return cstore.create_session(user_id=user["id"], token_sha256=token, csrf_token="c", expires_at=expires,
                                     ip="", user_agent="", now=seen)
    fresh = session("fresh", _stamp(hours=1), _stamp(days=-6))
    session("idle", _stamp(hours=settings.session_idle_hours + 1), _stamp(days=-6))
    session("expired", _stamp(minutes=5), _stamp(minutes=1))
    cstore.revoke_session(session("revoked", _stamp(minutes=5), _stamp(days=-6)))
    assert _keeper(cstore, settings, tmp_path).purge_sessions() == 3
    assert [r[0] for r in cstore.conn.execute("SELECT id FROM console_sessions")] == [fresh]


def test_exports_keep_the_newest_count_and_nothing_older_than_days(cstore, settings, tmp_path):
    keeper = _keeper(cstore, settings, tmp_path, export_retention_count=2, export_retention_days=30)
    made = {}
    for name, age in (("viejo", {"days": 40}), ("tercero", {"days": 2}), ("segundo", {"days": 1}),
                      ("nuevo", {"minutes": 5})):
        row = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=False,
                                   created_by="vera")
        file_name = f"GhostRecon_a_case_{name}.zip"
        for path in (keeper.exports_dir / file_name, keeper.exports_dir / f"{file_name}.sha256"):
            path.write_bytes(b"x")
        cstore.update_export(row["id"], status="succeeded", file_name=file_name, finished_at=_stamp(**age))
        made[name] = row["id"]
    building = cstore.create_export(case_id="GRC-a", scope="case", seq=None, include_unsealed=False,
                                    created_by="vera")
    cstore.update_export(building["id"], status="building", started_at=_stamp(days=60))
    assert keeper.prune_exports() == 2
    status = {name: cstore.get_export(eid)["status"] for name, eid in made.items()}
    assert status == {"viejo": "expired", "tercero": "expired", "segundo": "succeeded", "nuevo": "succeeded"}
    assert sorted(p.name for p in keeper.exports_dir.iterdir()) == sorted(
        f"GhostRecon_a_case_{n}.zip{s}" for n in ("segundo", "nuevo") for s in ("", ".sha256"))
    assert cstore.get_export(building["id"])["status"] == "building"


def test_old_job_files_go_and_active_jobs_keep_theirs(cstore, settings, tmp_path):
    keeper = _keeper(cstore, settings, tmp_path, export_retention_days=30)
    base = keeper.jobs_dir

    def job(status, finished):
        row = cstore.create_job(command="rerun-case", folder="/c", args={}, argv=["x"], launched_by="jean")
        cstore.update_job(row["id"], status=status, **({"finished_at": finished} if finished else {}))
        for path in (jobfiles.raw_path(base, row["id"]), jobfiles.log_path(base, row["id"]),
                     jobfiles.events_path(base, row["id"]), jobfiles.runner_log_path(base, row["id"])):
            path.write_text("x", encoding="utf-8")
        jobfiles.work_dir(base, row["id"]).mkdir()
        return row["id"]
    old, recent, running = job("succeeded", _stamp(days=40)), job("failed", _stamp(days=1)), job("running", None)
    assert keeper.prune_job_files() == 1
    left = {p.name for p in base.iterdir()}
    assert not any(name.split(".")[0] == str(old) for name in left)
    for kept in (recent, running):
        assert {f"{kept}.jsonl", f"{kept}.log", f"{kept}.events.jsonl", f"{kept}.runner.log", str(kept)} <= left
    assert cstore.get_job(old)["status"] == "succeeded"  # the row and its result stay


def test_the_console_cleans_up_when_it_starts(store, cstore, settings, auth, jobs):
    from plugins.ghost_recon.console.app import create_app
    user = cstore.create_user("old", "hash", "viewer")
    cstore.create_session(user_id=user["id"], token_sha256="gone", csrf_token="c", expires_at="2020-01-02T00:00:00Z",
                          ip="", user_agent="", now="2020-01-01T00:00:00Z")
    with TestClient(create_app(settings, store, cstore, auth=auth, jobs=jobs), base_url="http://localhost"):
        assert cstore.conn.execute("SELECT COUNT(*) FROM console_sessions").fetchone()[0] == 0
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_api_exports.py tests/plugins/ghost_recon/console/test_housekeeping.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'plugins.ghost_recon.console.exports'` y `… 'plugins.ghost_recon.console.housekeeping'`.

- [ ] **Step 3: Crear `console/exports.py`**

Crea `plugins/ghost_recon/console/exports.py`:

```python
"""ExportService: background builds of results ZIPs (spec §11) and their rows in ``console_exports``.

A request is checked at once (``exporter.select``: a refused export never gets a row), then built by one worker
thread, one archive at a time, with per-file progress in its row. The console audit log gets ``export_request`` and
then ``export`` or ``export_failed``; the case timeline gets ``results_exported`` with the ZIP's SHA-256. A build does
not survive a server restart: at start-up every export still queued or building is marked failed and partial files
are removed, so a row never stays "building" forever.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.db import Store, utcnow
from . import exporter, fsjail
from .auth import Principal
from .exporter import ExportError
from .settings import ConsoleSettings
from .store import ACTIVE_STATUSES, EXPORT_PENDING, ConsoleStore

logger = logging.getLogger(__name__)
INTERRUPTED = "La exportación se interrumpió porque la consola se reinició: vuelve a exportar."
INTERNAL = "Error interno al construir el ZIP; el detalle quedó en el log del servidor."
PROGRESS_EVERY_S = 0.5


class ExportService:
    def __init__(self, cstore: ConsoleStore, store: Store, settings: ConsoleSettings, *,
                 exports_dir: Optional[Path] = None):
        self.cstore = cstore
        self.store = store
        self.settings = settings
        self.dir = Path(exports_dir) if exports_dir else exporter.exports_dir()
        self._queue: "queue.Queue[Optional[int]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ requests
    def busy(self, case: Dict[str, Any]) -> bool:
        """A job is queued or running on the case (by case id, or on its folder before the case existed)."""
        key = fsjail.folder_key(case["root_path"])
        return any(j["case_id"] == case["id"] or fsjail.folder_key(j["folder"]) == key
                   for j in self.cstore.list_jobs(statuses=ACTIVE_STATUSES))

    def selection(self, case: Dict[str, Any], *, scope: str, seq: Optional[str],
                  include_unsealed: bool) -> exporter.Selection:
        return exporter.select(self.store, case, scope=scope, seq=seq, include_unsealed=include_unsealed,
                               busy=self.busy(case))

    def preview(self, case: Dict[str, Any], *, scope: str, seq: Optional[str], include_unsealed: bool) -> Dict:
        return exporter.selection_view(self.selection(case, scope=scope, seq=seq, include_unsealed=include_unsealed))

    def request(self, case: Dict[str, Any], *, scope: str, seq: Optional[str], include_unsealed: bool,
                principal: Principal, ip: str = "") -> Dict[str, Any]:
        """Queue an export; ExportError right away when it could never be built."""
        self.selection(case, scope=scope, seq=seq, include_unsealed=include_unsealed)
        row = self.cstore.create_export(case_id=case["id"], scope=scope, seq=seq if scope == "audit" else None,
                                        include_unsealed=include_unsealed, created_by=principal.username)
        self.cstore.log("export_request", user_id=principal.user_id, username=principal.username, ip=ip,
                        target=f"export:{row['id']}", detail={"case_id": case["id"], "scope": scope,
                                                              "seq": row["seq"], "include_unsealed": include_unsealed})
        self._queue.put(row["id"])
        return row

    def file_path(self, row: Dict[str, Any]) -> Optional[Path]:
        """The finished archive of an export, while it is still on disk."""
        if row.get("status") != "succeeded" or not row.get("file_name"):
            return None
        path = self.dir / row["file_name"]
        return path if path.is_file() else None

    # ------------------------------------------------------------------ building
    def build(self, export_id: int) -> Dict[str, Any]:
        row = self.cstore.get_export(export_id)
        if not row or not self.cstore.update_export(export_id, expect=("queued",), status="building",
                                                    started_at=utcnow()):
            return row
        last = [0.0]

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            if done == total or now - last[0] >= PROGRESS_EVERY_S:
                last[0] = now
                self.cstore.update_export(export_id, expect=("building",), files_done=done, files_total=total)

        try:
            case = self.store.get_case(row["case_id"])
            if not case:
                raise ExportError(404, "not_found", "El caso ya no existe.")
            sel = self.selection(case, scope=row["scope"], seq=row["seq"], include_unsealed=row["include_unsealed"])
            result = exporter.build(self.store, self.cstore, sel, export_id=export_id, exported_by=row["created_by"],
                                    dest_dir=self.dir, progress=progress)
        except ExportError as exc:
            self._fail(row, exc.code, exc.message)
        except Exception:
            logger.exception("ghost-recon console: export %s failed", export_id)
            self._fail(row, "internal", INTERNAL)
        else:
            self._succeed(row, case, result)
        return self.cstore.get_export(export_id)

    def _log(self, action: str, row: Dict[str, Any], detail: Dict[str, Any]) -> None:
        user = self.cstore.get_user(row["created_by"])
        self.cstore.log(action, user_id=user.get("id"), username=row["created_by"], target=f"export:{row['id']}",
                        detail={"case_id": row["case_id"], **detail})

    def _succeed(self, row: Dict[str, Any], case: Dict[str, Any], result: Dict[str, Any]) -> None:
        manifest = result["manifest"]
        files = len(manifest["files"])
        detail = {"audits": [{"seq": a["seq"], "state": a["state"]} for a in manifest["audits"]],
                  "excluded": manifest["excluded"], "skipped": manifest["skipped"], "draft": manifest["draft"]}
        self.cstore.update_export(row["id"], expect=("building",), status="succeeded", finished_at=utcnow(),
                                  size=result["size"], sha256=result["sha256"], file_name=result["file_name"],
                                  files_done=files, files_total=files, detail=detail)
        self._log("export", row, {"scope": row["scope"], "seq": row["seq"], "draft": manifest["draft"],
                                  "file": result["file_name"], "size": result["size"], "sha256": result["sha256"]})
        what = row["seq"] or "caso completo"
        draft = ", con auditorías abiertas (borrador)" if manifest["draft"] else ""
        self.store.add_event(case["id"], "results_exported",
                             f"Resultados exportados ({what}{draft}) · ZIP SHA-256 {result['sha256']}",
                             actor=row["created_by"],
                             ref={"export_id": row["id"], "file": result["file_name"], "sha256": result["sha256"],
                                  "scope": row["scope"], "seq": row["seq"], "draft": manifest["draft"]})

    def _fail(self, row: Dict[str, Any], code: str, message: str) -> None:
        self.cstore.update_export(row["id"], expect=EXPORT_PENDING, status="failed", finished_at=utcnow(),
                                  error=message, detail={"code": code})
        self._log("export_failed", row, {"code": code, "message": message})

    # ------------------------------------------------------------------ lifecycle
    def recover(self) -> List[int]:
        """Start-up: an export left queued or building by a previous server never finishes; fail it and remove the
        partial archives."""
        interrupted = [row["id"] for row in self.cstore.list_exports(statuses=EXPORT_PENDING)
                       if self.cstore.update_export(row["id"], expect=EXPORT_PENDING, status="failed",
                                                    finished_at=utcnow(), error=INTERRUPTED,
                                                    detail={"code": "interrupted"})]
        for part in self.dir.glob("*.zip.part"):
            part.unlink(missing_ok=True)
        return interrupted

    def start(self) -> None:
        self.recover()
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="gr-console-exports", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=5)  # a build still running ends with the process; recover() cleans up
            self._thread = None

    def _loop(self) -> None:
        while True:
            export_id = self._queue.get()
            if export_id is None:
                return
            try:
                self.build(export_id)
            except Exception:  # a failed bookkeeping write must not end the worker; the row shows what it reached
                logger.exception("ghost-recon console: export worker error on %s", export_id)
```

- [ ] **Step 4: Crear `console/housekeeping.py`**

Crea `plugins/ghost_recon/console/housekeeping.py`:

```python
"""Periodic clean-up of the console, in one place: expired or revoked sessions, results ZIPs past ``export_retention``
(at most the newest ``count`` finished exports and none older than ``days`` days, spec §11-12) and the per-job files
of jobs that ended more than ``days`` days ago. Runs at start-up and then every ``interval_s``; it never touches an
export that is being built nor the files of a queued or running job."""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from . import jobfiles
from .settings import ConsoleSettings
from .store import TERMINAL_STATUSES, ConsoleStore

logger = logging.getLogger(__name__)
INTERVAL_S = 3600.0
_ALL = 1_000_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    """The console's ISO-8601 UTC form ("2026-10-04T12:00:00Z"): text order is time order."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Housekeeping:
    def __init__(self, cstore: ConsoleStore, settings: ConsoleSettings, *, exports_dir: Path, jobs_dir: Path,
                 clock: Callable[[], datetime] = _utcnow, interval_s: float = INTERVAL_S):
        self.cstore = cstore
        self.settings = settings
        self.exports_dir = Path(exports_dir)
        self.jobs_dir = Path(jobs_dir)
        self.clock = clock
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def run_once(self) -> Dict[str, int]:
        return {"sessions": self.purge_sessions(), "exports": self.prune_exports(),
                "job_files": self.prune_job_files()}

    def purge_sessions(self) -> int:
        now = self.clock()
        return self.cstore.purge_sessions(now=_stamp(now),
                                          idle_before=_stamp(now - timedelta(hours=self.settings.session_idle_hours)))

    def _cutoff(self) -> str:
        return _stamp(self.clock() - timedelta(days=self.settings.export_retention_days))

    def prune_exports(self) -> int:
        """Delete the archives (and their .sha256) past retention; their rows stay, marked ``expired``."""
        cutoff, kept, removed = self._cutoff(), 0, 0
        for row in self.cstore.list_exports(statuses=("succeeded",), limit=_ALL):  # newest first
            if kept < self.settings.export_retention_count and (row["finished_at"] or "") >= cutoff:
                kept += 1
                continue
            if row["file_name"]:
                for name in (row["file_name"], f"{row['file_name']}.sha256"):
                    (self.exports_dir / name).unlink(missing_ok=True)
            removed += self.cstore.update_export(row["id"], expect=("succeeded",), status="expired")
        return removed

    def prune_job_files(self) -> int:
        """Remove ``<id>.jsonl``, ``.log``, ``.events.jsonl``, ``.runner.log`` and the work dir ``<id>/`` of jobs that
        finished before the cutoff. The job rows (status, result, tokens) stay."""
        cutoff, pruned = self._cutoff(), 0
        for job in self.cstore.list_jobs(statuses=TERMINAL_STATUSES, limit=_ALL):
            if not job.get("finished_at") or job["finished_at"] >= cutoff:
                continue
            found = False
            for path in (jobfiles.raw_path(self.jobs_dir, job["id"]), jobfiles.log_path(self.jobs_dir, job["id"]),
                         jobfiles.events_path(self.jobs_dir, job["id"]),
                         jobfiles.runner_log_path(self.jobs_dir, job["id"])):
                if path.exists():
                    path.unlink(missing_ok=True)
                    found = True
            work = jobfiles.work_dir(self.jobs_dir, job["id"])
            if work.is_dir():
                shutil.rmtree(work, ignore_errors=True)
                found = True
            pruned += found
        return pruned

    def start(self) -> None:
        self.run_once()
        if self.interval_s > 0 and self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="gr-console-housekeeping", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.run_once()
            except Exception:  # a failed pass must not end the clean-up; the next one retries
                logger.exception("ghost-recon console: housekeeping pass failed")
```

- [ ] **Step 5: El contexto y el lifespan**

En `plugins/ghost_recon/console/deps.py`, sustituye:

```python
from .auth import AuthService, Principal
from .jobs import JobService
```

por:

```python
from .auth import AuthService, Principal
from .exports import ExportService
from .jobs import JobService
```

y sustituye:

```python
    auth: AuthService
    jobs: JobService
```

por:

```python
    auth: AuthService
    jobs: JobService
    exports: ExportService
```

En `plugins/ghost_recon/console/app.py`, sustituye:

```python
from .auth import AuthService
from .deps import ConsoleContext, current_principal
from .jobs import JobService
```

por:

```python
from .auth import AuthService
from .deps import ConsoleContext, current_principal
from .exports import ExportService
from .housekeeping import Housekeeping
from .jobs import JobService
```

y sustituye:

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

por:

```python
def create_app(settings: ConsoleSettings, store: Store, cstore: ConsoleStore, *,
               auth: Optional[AuthService] = None, jobs: Optional[JobService] = None,
               exports: Optional[ExportService] = None, housekeeping: Optional[Housekeeping] = None) -> FastAPI:
    jobs = jobs or JobService(cstore, store, settings)
    exports = exports or ExportService(cstore, store, settings)
    housekeeping = housekeeping or Housekeeping(cstore, settings, exports_dir=exports.dir, jobs_dir=jobs.jobs_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        jobs.start()  # find running jobs again, mark orphans, dispatch the queue; then tick in the background
        exports.start()  # fail the builds a previous server left unfinished; then build in the background
        housekeeping.start()  # sessions, old ZIPs and old job files: now, then every hour
        try:
            yield
        finally:
            housekeeping.stop()
            exports.stop()
            jobs.stop()

    app = FastAPI(title="Ghost Recon Console", version=CONSOLE_VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.gr = ConsoleContext(settings=settings, store=store, cstore=cstore,
                                  auth=auth or AuthService(cstore, settings), jobs=jobs, exports=exports)
```

- [ ] **Step 6: Reemplazar `routers/exports.py` con las rutas del ZIP**

La ruta de las tablas queda igual que en la Tarea 4, al final del archivo (las rutas `…/export/preview` y `/exports/…` no chocan con `/cases/{case_id}/{table}.{fmt}`).

Reemplaza `plugins/ghost_recon/console/routers/exports.py` completo:

```python
"""Export endpoints (viewer): the results ZIP of a case or an audit (built in the background; unsealed audits only for
an admin) and the case tables as CSV/XLSX with the filters of their JSON endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import readmodel, tables
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..downloads import attachment
from ..exporter import ExportError
from ..store import EXPORT_PENDING
from .cases import get_case_or_404

router = APIRouter(tags=["exports"])
SEQ_PATTERN = r"^[AR]\d{2,3}$"


class ExportBody(BaseModel):
    scope: Literal["case", "audit"] = "case"
    seq: Optional[str] = Field(None, pattern=SEQ_PATTERN)
    include_unsealed: Optional[bool] = None  # None: the configured default (export_include_unsealed), admins only


def _include_unsealed(ctx: ConsoleContext, principal: Principal, asked: Optional[bool]) -> bool:
    if asked is None:
        return ctx.settings.export_include_unsealed and principal.has("admin")
    if asked and not principal.has("admin"):
        raise ApiError(403, "forbidden", "solo un admin exporta auditorías sin sellar")
    return asked


def _scope(scope: str, seq: Optional[str]) -> None:
    if scope == "audit" and not seq:
        raise ApiError(422, "invalid_argument", "falta la auditoría (seq) para exportar una sola auditoría")


def _export_or_404(ctx: ConsoleContext, export_id: int) -> dict:
    row = ctx.cstore.get_export(export_id)
    if not row:
        raise ApiError(404, "not_found", f"exportación no encontrada: {export_id}")
    return row


@router.get("/cases/{case_id}/export/preview")
def export_preview(case_id: str, scope: Literal["case", "audit"] = "case",
                   seq: Optional[str] = Query(None, pattern=SEQ_PATTERN), include_unsealed: Optional[bool] = None,
                   principal: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """What an export would take and why the other audits stay out, without building anything."""
    case = get_case_or_404(ctx, case_id)
    _scope(scope, seq)
    include = _include_unsealed(ctx, principal, include_unsealed)
    try:
        view = ctx.exports.preview(case, scope=scope, seq=seq, include_unsealed=include)
    except ExportError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc
    return {**view, "include_unsealed": include, "can_include_unsealed": principal.has("admin")}


@router.post("/cases/{case_id}/export", status_code=202)
def export_case(case_id: str, body: ExportBody, request: Request, principal: Principal = Depends(require("viewer")),
                ctx: ConsoleContext = Depends(get_ctx)):
    case = get_case_or_404(ctx, case_id)
    _scope(body.scope, body.seq)
    include = _include_unsealed(ctx, principal, body.include_unsealed)
    try:
        row = ctx.exports.request(case, scope=body.scope, seq=body.seq, include_unsealed=include,
                                  principal=principal, ip=client_ip(request))
    except ExportError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc
    return {"export_id": row["id"], "export": row}


@router.get("/exports/{export_id}")
def export_status(export_id: int, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """State, progress (files_done / files_total), size and SHA-256 once built."""
    return _export_or_404(ctx, export_id)


def _finished_file(ctx: ConsoleContext, row: dict):
    if row["status"] in EXPORT_PENDING:
        raise ApiError(409, "not_ready", "el ZIP todavía se está construyendo")
    path = ctx.exports.file_path(row)
    if path is None:
        raise ApiError(410, "gone", "este ZIP no está disponible (falló o se eliminó por antigüedad): vuelve a exportar")
    return path


@router.get("/exports/{export_id}/download")
def export_download(export_id: int, request: Request, principal: Principal = Depends(require("viewer")),
                    ctx: ConsoleContext = Depends(get_ctx)):
    row = _export_or_404(ctx, export_id)
    path = _finished_file(ctx, row)
    ctx.cstore.log("export_download", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=f"export:{export_id}", detail={"case_id": row["case_id"], "file": row["file_name"]})
    return FileResponse(path, filename=row["file_name"], media_type="application/zip")


@router.get("/exports/{export_id}/sha256")
def export_sidecar(export_id: int, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """The ``<zip>.sha256`` beside the archive (``sha256sum -c`` format)."""
    path = _finished_file(ctx, _export_or_404(ctx, export_id))
    sidecar = path.with_name(f"{path.name}.sha256")
    return attachment(sidecar.read_bytes(), sidecar.name, "text/plain; charset=utf-8")


@router.get("/cases/{case_id}/{table}.{fmt}")
def table_file(case_id: str, table: str, fmt: str, request: Request, kind: str = "", risk: str = "",
               status: str = "", q: str = "", audit: str = "", principal: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    """``table`` ∈ findings | evidence | timeline | criteria, ``fmt`` ∈ csv | xlsx; every row that matches the filters
    (no pagination)."""
    case = get_case_or_404(ctx, case_id)
    spec, writer = tables.TABLES.get(table), tables.WRITERS.get(fmt)
    if spec is None or writer is None:
        raise ApiError(404, "not_found", f"tabla o formato desconocido: {table}.{fmt}")
    filters = readmodel.TableFilters(kind=kind, risk=risk, status=status, q=q, audit=audit)
    rows = readmodel.TABLE_ROWS[table](ctx.store, case_id, filters)
    write, media_type = writer
    try:
        data = write(spec, rows, case)
    except tables.XlsxUnavailable as exc:
        raise ApiError(503, "xlsx_unavailable", str(exc)) from exc
    ctx.cstore.log("table_export", user_id=principal.user_id, username=principal.username, ip=client_ip(request),
                   target=case_id, detail={"table": table, "format": fmt, "rows": len(rows),
                                           "filters": {k: v for k, v in asdict(filters).items() if v}})
    return attachment(data, tables.file_name(case, table, fmt), media_type)
```

- [ ] **Step 7: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_api_exports.py tests/plugins/ghost_recon/console/test_housekeeping.py tests/plugins/ghost_recon/console/test_exporter.py tests/plugins/ghost_recon/console/test_tables.py tests/plugins/ghost_recon/console/test_api_security.py -q`
Expected: `0 failed`.

- [ ] **Step 8: Commit**

```bash
git add plugins/ghost_recon/console/exports.py plugins/ghost_recon/console/housekeeping.py plugins/ghost_recon/console/deps.py plugins/ghost_recon/console/app.py plugins/ghost_recon/console/routers/exports.py tests/plugins/ghost_recon/console/test_api_exports.py tests/plugins/ghost_recon/console/test_housekeeping.py
git commit -m "feat(ghost-recon): console background ZIP exports, export API and periodic housekeeping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 7: Búsqueda entre casos y filtro «riesgo abierto» en Casos

**Files:**
- Create: `plugins/ghost_recon/console/search.py`
- Create: `plugins/ghost_recon/console/routers/search.py`
- Modify: `plugins/ghost_recon/console/app.py` (`ROUTERS`)
- Modify: `plugins/ghost_recon/console/readmodel.py` (`list_cases(..., risk=)`)
- Modify: `plugins/ghost_recon/console/routers/cases.py` (`GET /cases?risk=`)
- Test: `tests/plugins/ghost_recon/console/test_search.py`

**Interfaces:**
- Consumes: `Store.list_cases/list_findings/list_evidence/list_criteria`, `readmodel.FINDING_TEXT_FIELDS/EVIDENCE_TEXT_FIELDS/RISKS`, `case_row` (`open_by_risk`, `open_total`).
- Produces:
  - `search.TYPES = ("case", "finding", "evidence", "criteria")`, `MIN_QUERY = 2`, `MAX_QUERY = 100`, `DEFAULT_LIMIT = 10`, `MAX_LIMIT = 50`, `SEARCH_BUDGET_S = 2.0`;
  - `search.search(store, q, *, types=TYPES, limit=DEFAULT_LIMIT, clock=time.monotonic) -> {"q", "items": {tipo: [...]}, "more": {tipo: bool}, "timed_out": bool}`; cada item: `{"type", "case_id", "case_name", "id", "title", "detail", "tab"}` con `tab` = la pestaña del caso que lo muestra (`summary`, `findings`, `evidence`, `criteria`);
  - `GET /search?q=&types=&limit=` (viewer): 422 para `q` corta o larga, `limit` fuera de 1–50 o un tipo desconocido;
  - `readmodel.list_cases(store, cstore, *, q="", status="", risk="")` y `GET /cases?risk=any|critical|high|medium|low` (422 si no).

- [ ] **Step 1: Escribir las pruebas que fallan**

Crea `tests/plugins/ghost_recon/console/test_search.py`:

```python
"""Cross-case search (spec §14 "Búsqueda") and the Casos "riesgo abierto" filter: findings by ID or title and
evidence by name or hash across two cases, nothing outside the DB, bounded and behind the login."""
import shutil
from pathlib import Path

import pytest

from plugins.ghost_recon.console import search as search_mod
from plugins.ghost_recon.core import service

DEMO = Path(__file__).resolve().parents[4] / "ghost-recon" / "demo" / "demo-case"


@pytest.fixture
def two_cases(store, seeded, case_root):
    """``seeded`` (Acme Demo) plus "Beta Holding", a second case with its own EXC-01 and criterion."""
    folder = case_root / "Beta Holding"
    shutil.copytree(DEMO, folder)
    beta = service.open_case(store, str(folder), name="Beta Holding")["case"]["id"]
    audit = service.start_audit(store, beta, "initial")["audit"]["id"]
    service.upsert_findings(store, audit, [{"kind": "exception", "title": "Transferencia sin soporte",
                                            "risk": "critical"}])
    service.add_criterion(store, audit, "Socio A", "Las transferencias internas no son ingresos.")
    return {"acme": seeded["case_id"], "beta": beta, "beta_root": folder}


def _search(c, **params):
    r = c.get("/api/v1/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_findings_are_found_by_id_and_by_title_across_cases(login_as, two_cases):
    c = login_as("viewer")
    by_id = _search(c, q="EXC-01", types="finding")["items"]["finding"]
    assert {(f["case_id"], f["id"]) for f in by_id} == {(two_cases["acme"], "EXC-01"), (two_cases["beta"], "EXC-01")}
    by_title = _search(c, q="sin soporte")["items"]["finding"]
    assert [(f["case_id"], f["tab"]) for f in by_title] == [(two_cases["beta"], "findings")]


def test_evidence_is_found_by_name_and_by_hash(login_as, store, two_cases):
    c = login_as("viewer")
    by_name = _search(c, q="extracto", types="evidence", limit=50)["items"]["evidence"]
    assert {e["case_id"] for e in by_name} == {two_cases["acme"], two_cases["beta"]}
    row = store.list_evidence(two_cases["beta"])[0]
    by_hash = _search(c, q=row["sha256"][:16], types="evidence")["items"]["evidence"]
    assert (two_cases["beta"], row["path"]) in {(e["case_id"], e["title"]) for e in by_hash}


def test_cases_and_criteria_are_found_and_link_to_their_tab(login_as, two_cases):
    found = _search(login_as("viewer"), q="beta holding")["items"]
    assert [(i["id"], i["tab"]) for i in found["case"]] == [(two_cases["beta"], "summary")]
    criteria = _search(login_as("viewer"), q="transferencias internas", types="criteria")["items"]["criteria"]
    assert [(i["case_id"], i["id"], i["tab"]) for i in criteria] == [(two_cases["beta"], "CRIT-01", "criteria")]


def test_nothing_outside_the_database_is_ever_found(login_as, two_cases):
    (two_cases["beta_root"] / "fantasma-xyz.txt").write_text("no inventariado", encoding="utf-8")
    result = _search(login_as("viewer"), q="fantasma-xyz")
    assert all(hits == [] for hits in result["items"].values())


def test_search_is_bounded_and_behind_the_login(client, login_as, two_cases):
    assert client.get("/api/v1/search", params={"q": "extracto"}).status_code == 401
    c = login_as("viewer")
    one = _search(c, q="extracto", limit=1)
    assert all(len(hits) <= 1 for hits in one["items"].values()) and one["more"]["evidence"] is True
    for params in ({"q": "a"}, {"q": "  "}, {"q": "x" * 101}, {"q": "extracto", "limit": 51},
                   {"q": "extracto", "types": "finding,passwords"}):
        assert c.get("/api/v1/search", params=params).status_code == 422


def test_the_scan_stops_at_its_time_budget(store, two_cases):
    ticks = iter(range(0, 1000, 5))  # every call: five more seconds
    result = search_mod.search(store, "extracto", clock=lambda: float(next(ticks)))
    assert result["timed_out"] is True and len({h["case_id"] for h in result["items"]["evidence"]}) <= 1


def test_cases_filter_by_open_risk(login_as, two_cases):
    c = login_as("viewer")

    def ids(risk):
        r = c.get("/api/v1/cases", params={"risk": risk})
        assert r.status_code == 200
        return {row["id"] for row in r.json()["items"]}
    assert ids("critical") == {two_cases["beta"]} and ids("high") == {two_cases["acme"]}
    assert ids("low") == set()  # Acme's low-risk finding is closed
    assert ids("any") == {two_cases["acme"], two_cases["beta"]}
    assert c.get("/api/v1/cases", params={"risk": "extreme"}).status_code == 422
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_search.py -q`
Expected: FAIL con `ImportError: cannot import name 'search' from 'plugins.ghost_recon.console'`.

- [ ] **Step 3: Crear `console/search.py` y su router**

Crea `plugins/ghost_recon/console/search.py`:

```python
"""Search across cases (spec §8 "Búsqueda"): cases, findings, evidence and criteria containing a text, read through the
case ``Store`` (nothing outside the database is ever searched). Bounded: the query has 2–100 characters, each type
returns at most ``limit`` items (``more`` says when there were others) and the scan stops after ``SEARCH_BUDGET_S``
seconds (``timed_out``)."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterator, Sequence

from ..core.db import Store
from .readmodel import EVIDENCE_TEXT_FIELDS, FINDING_TEXT_FIELDS

TYPES = ("case", "finding", "evidence", "criteria")
MIN_QUERY, MAX_QUERY = 2, 100
DEFAULT_LIMIT, MAX_LIMIT = 10, 50
SEARCH_BUDGET_S = 2.0
CASE_TEXT_FIELDS = ("id", "name", "slug", "root_path")
CRITERIA_TEXT_FIELDS = ("id", "text", "author")
TITLE_MAX = 160


def _hit(row: Dict[str, Any], needle: str, fields: Sequence[str]) -> bool:
    return any(needle in str(row.get(k) or "").lower() for k in fields)


def _short(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1] + "…"


def _cases(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    if _hit(case, needle, CASE_TEXT_FIELDS):
        yield {"id": case["id"], "title": case["name"], "detail": case["root_path"], "tab": "summary"}


def _findings(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    for f in store.list_findings(case["id"]):
        if _hit(f, needle, FINDING_TEXT_FIELDS):
            yield {"id": f["id"], "title": _short(f["title"]), "detail": f"{f['kind']} · {f['risk']} · {f['status']}",
                   "tab": "findings"}


def _evidence(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    for e in store.list_evidence(case["id"]):
        if _hit(e, needle, EVIDENCE_TEXT_FIELDS):
            yield {"id": e["sha256"], "title": e["path"], "detail": f"{e['status']} · SHA-256 {e['sha256'][:12]}…",
                   "tab": "evidence"}


def _criteria(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    for c in store.list_criteria(case["id"]):
        if _hit(c, needle, CRITERIA_TEXT_FIELDS):
            yield {"id": c["id"], "title": _short(c["text"]), "detail": c["author"], "tab": "criteria"}


SOURCES: Dict[str, Callable[[Store, Dict[str, Any], str], Iterator[Dict[str, Any]]]] = {
    "case": _cases, "finding": _findings, "evidence": _evidence, "criteria": _criteria}


def search(store: Store, q: str, *, types: Sequence[str] = TYPES, limit: int = DEFAULT_LIMIT,
           clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Results grouped by type; each item carries its case and the case tab that shows it."""
    needle = q.strip().lower()
    deadline = clock() + SEARCH_BUDGET_S
    items: Dict[str, list] = {t: [] for t in types}
    more = {t: False for t in types}
    timed_out = False
    for case in store.list_cases():
        if clock() > deadline:
            timed_out = True
            break
        for kind in types:
            if more[kind]:
                continue
            for hit in SOURCES[kind](store, case, needle):
                if len(items[kind]) >= limit:
                    more[kind] = True
                    break
                items[kind].append({"type": kind, "case_id": case["id"], "case_name": case["name"], **hit})
        if all(more.values()):
            break
    return {"q": q, "items": items, "more": more, "timed_out": timed_out}
```

Crea `plugins/ghost_recon/console/routers/search.py`:

```python
"""Cross-case search (viewer): ``GET /search?q=&types=case,finding,evidence,criteria&limit=``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import search as search_mod
from ..auth import Principal
from ..deps import ApiError, ConsoleContext, get_ctx, require

router = APIRouter(tags=["search"])


@router.get("/search")
def search(q: str = Query(..., min_length=search_mod.MIN_QUERY, max_length=search_mod.MAX_QUERY), types: str = "",
           limit: int = Query(search_mod.DEFAULT_LIMIT, ge=1, le=search_mod.MAX_LIMIT),
           _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    wanted = tuple(dict.fromkeys(t.strip() for t in types.split(",") if t.strip())) or search_mod.TYPES
    unknown = [t for t in wanted if t not in search_mod.TYPES]
    if unknown:
        raise ApiError(422, "invalid_argument", f"tipo desconocido: {', '.join(unknown)} "
                                                f"(válidos: {', '.join(search_mod.TYPES)})")
    if len(q.strip()) < search_mod.MIN_QUERY:
        raise ApiError(422, "invalid_argument", f"escribe al menos {search_mod.MIN_QUERY} caracteres")
    return search_mod.search(ctx.store, q, types=wanted, limit=limit)
```

En `plugins/ghost_recon/console/app.py`, sustituye:

```python
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, exports as exports_routes,
                      fs as fs_routes, jobs as jobs_routes, system as system_routes, users as users_routes)
```

por:

```python
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, exports as exports_routes,
                      fs as fs_routes, jobs as jobs_routes, search as search_routes, system as system_routes,
                      users as users_routes)
```

y sustituye:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes,
           exports_routes)
```

por:

```python
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes,
           exports_routes, search_routes)
```

- [ ] **Step 4: Filtro «riesgo abierto»**

En `plugins/ghost_recon/console/readmodel.py`, sustituye:

```python
def list_cases(store: Store, cstore: ConsoleStore, *, q: str = "", status: str = "") -> List[Dict[str, Any]]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    if status:
        rows = [r for r in rows if r["status"] == status]
```

por:

```python
def list_cases(store: Store, cstore: ConsoleStore, *, q: str = "", status: str = "",
               risk: str = "") -> List[Dict[str, Any]]:
    """``risk``: cases with open findings of that risk; ``any``: with any open finding (spec §10.3 "riesgo abierto")."""
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if risk == "any":
        rows = [r for r in rows if r["open_total"] > 0]
    elif risk:
        rows = [r for r in rows if r["open_by_risk"].get(risk, 0) > 0]
```

En `plugins/ghost_recon/console/routers/cases.py`, sustituye:

```python
@router.get("/cases")
def list_cases(q: str = "", status: str = "", _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    return {"items": readmodel.list_cases(ctx.store, ctx.cstore, q=q, status=status)}
```

por:

```python
@router.get("/cases")
def list_cases(q: str = "", status: str = "", risk: str = "", _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    if risk not in ("", "any", *readmodel.RISKS):
        raise ApiError(422, "invalid_argument", f"riesgo desconocido: {risk} (any, {', '.join(readmodel.RISKS)})")
    return {"items": readmodel.list_cases(ctx.store, ctx.cstore, q=q, status=status, risk=risk)}
```

- [ ] **Step 5: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_search.py tests/plugins/ghost_recon/console/test_api_cases.py -q`
Expected: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add plugins/ghost_recon/console/search.py plugins/ghost_recon/console/routers/search.py plugins/ghost_recon/console/app.py plugins/ghost_recon/console/readmodel.py plugins/ghost_recon/console/routers/cases.py tests/plugins/ghost_recon/console/test_search.py
git commit -m "feat(ghost-recon): console cross-case search and open-risk case filter

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 8: Aviso al terminar (`hermes send`) y un despacho que no se corta

**Files:**
- Modify: `plugins/ghost_recon/console/commands.py`
- Modify: `plugins/ghost_recon/console/jobs.py`
- Modify: `plugins/ghost_recon/console/job_runner.py`
- Modify: `ghost-recon/demo/fake_agent.py` (modo `send`)
- Test: `tests/plugins/ghost_recon/console/test_notify.py`
- Test: `tests/plugins/ghost_recon/console/test_jobs.py` (añadir al final)

**Interfaces:**
- Consumes: `JobService.hermes_command` (el mismo comando inyectable que lanza al agente), `procs.profile_args/child_env`, `ConsoleStore.create_job(..., notify_target=, notify_argv=)` (Tarea 1), `settings.notify_target`, `Runner._finish`, `agent.redact.redact_sensitive_text`.
- Produces:
  - `commands.NOTIFY_SUBJECT = "[Ghost Recon]"`, `commands.ORDER_LABELS` (las mismas etiquetas que `COMMAND_LABEL` en `format.js`) y `commands.notify_args(target, profile_args) -> [*profile_args, "send", "--to", target, "--subject", "[Ghost Recon]"]`;
  - `JobService.launch` guarda `notify_target` y `notify_argv = hermes_command(notify_args(...))` solo si hay `notify_target`; el runner, que no tiene la configuración de Hermes, solo añade el resumen como último argumento;
  - `job_runner.notify_message(job, status, case, last_audit, error) -> str` (puro; empieza por «Ejecución #<id>», sustituye `MEDIA:` por `MEDIA :`, redacta y recorta el motivo) y `job_runner.NOTIFY_TIMEOUT_S = 60`;
  - el runner envía el aviso tras su escritura final **solo** si esa escritura ganó (`succeeded`/`failed`); un fallo del envío (código distinto de 0, ejecutable ausente, tiempo agotado) queda en el log del runner (`<id>.runner.log`) y el job conserva su estado;
  - `JobService._start_runner` trata cualquier excepción al abrir su log o lanzar el runner como fallo de ese job (`failed`, «no se pudo iniciar la ejecución: …») y el despacho sigue con los demás;
  - `fake_agent.py`: con `send` entre sus argumentos y sin `-q` escribe su argv (JSON) en `record_send` de la configuración `default` y sale con `send_exit_code` (0 por defecto).

- [ ] **Step 1: Escribir las pruebas que fallan**

Crea `tests/plugins/ghost_recon/console/test_notify.py`:

```python
"""The job-end notice (spec §6.2, C10): the server plans the ``hermes send`` argv at launch, the runner sends it with a
summary when the job ends, an empty target sends nothing, and a failed notice never changes the job."""
import json
import logging
from dataclasses import replace

from plugins.ghost_recon.console import jobfiles, procs
from plugins.ghost_recon.console.auth import Principal
from plugins.ghost_recon.console.commands import NOTIFY_SUBJECT, LaunchRequest, agent_args, notify_args
from plugins.ghost_recon.console.job_runner import Runner, notify_message

ADMIN = Principal(1, "jean", "admin", "session")
SECRET = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def _folder(case_root, name):
    folder = case_root / name
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    return folder.resolve()


def _job(cstore, folder, hermes, target="telegram"):
    """A job as JobService.launch stores it: the agent argv and the notice argv, both through ``hermes``."""
    argv = hermes(agent_args("new-open-case", f'/new-open-case "{folder}"', ["-p", "default"]))
    notify = hermes(notify_args(target, ["-p", "default"])) if target else []
    return cstore.create_job(command="new-open-case", folder=str(folder), args={}, argv=argv, launched_by="jean",
                             notify_target=target or None, notify_argv=notify)


def _run(cstore, store, job_id):
    return Runner(job_id, cstore=cstore, store=store, base=jobfiles.jobs_dir(), poll=0.05).run()


def test_the_runner_sends_the_planned_notice_with_a_summary(cstore, store, case_root, fake_agent, tmp_path):
    record = tmp_path / "send.json"
    job = _job(cstore, _folder(case_root, "Caso Aviso"), fake_agent({"record_send": str(record)}))
    assert _run(cstore, store, job["id"]) == "succeeded"
    sent = json.loads(record.read_text(encoding="utf-8"))
    assert sent[:-1] == job["notify_argv"][1:]  # exactly the planned argv (the fake drops the interpreter) ...
    assert sent[-6:-1] == ["send", "--to", "telegram", "--subject", NOTIFY_SUBJECT]
    message = sent[-1]  # ... plus the summary as the message
    case = store.get_case(cstore.get_job(job["id"])["case_id"])
    assert message.startswith(f"Ejecución #{job['id']}") and "terminó" in message and case["name"] in message


def test_a_failed_job_is_notified_with_its_reason(cstore, store, case_root, fake_agent, tmp_path):
    record = tmp_path / "send.json"
    hermes = fake_agent({"record_send": str(record), "exit_code": 3, "error": f"401 con la clave {SECRET}"})
    job = _job(cstore, _folder(case_root, "Caso Falla"), hermes)
    assert _run(cstore, store, job["id"]) == "failed"
    message = json.loads(record.read_text(encoding="utf-8"))[-1]
    assert "falló" in message and "401" in message and SECRET not in message  # redacted like every console view


def test_a_notice_that_fails_never_changes_the_job(cstore, store, case_root, fake_agent, tmp_path, caplog):
    job = _job(cstore, _folder(case_root, "Caso Sin Aviso"), fake_agent({"send_exit_code": 1}))
    with caplog.at_level(logging.WARNING):
        assert _run(cstore, store, job["id"]) == "succeeded"
    assert "hermes send exited 1" in caplog.text
    broken = _job(cstore, _folder(case_root, "Caso Sin Ejecutable"), fake_agent())
    cstore.conn.execute("UPDATE console_jobs SET notify_argv=? WHERE id=?",
                        (json.dumps([str(tmp_path / "no-such-hermes")]), broken["id"]))
    cstore.conn.commit()
    assert _run(cstore, store, broken["id"]) == "succeeded"


def test_launch_plans_the_notice_only_when_a_target_is_configured(make_jobs, settings, case_root):
    quiet = make_jobs().launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Mudo"))), ADMIN)
    assert quiet["notify_target"] is None and quiet["notify_argv"] == []
    jobs = make_jobs(config=replace(settings, notify_target="telegram:-1001234567890"))
    loud = jobs.launch(LaunchRequest("new-open-case", str(_folder(case_root, "Caso Ruidoso"))), ADMIN)
    assert loud["notify_target"] == "telegram:-1001234567890"
    assert loud["notify_argv"] == jobs.hermes_command(notify_args("telegram:-1001234567890", procs.profile_args()))


def test_operator_text_never_becomes_an_attachment_directive():
    job = {"id": 7, "command": "rerun-case", "folder": "/casos/MEDIA:/etc/passwd"}
    case = {"id": "GRC-x-20261004", "name": "Caso MEDIA:/home/ghostrecon/.hermes/.env"}
    message = notify_message(job, "failed", case, {"id": "GRC-x-20261004/A02", "status": "open"},
                             "falló al leer MEDIA:C:/secretos.txt")
    assert "MEDIA:" not in message.upper()
    assert message.startswith("Ejecución #7 · Re-run · falló") and "A02 (open)" in message
    no_case = notify_message({**job, "id": 8, "folder": "/casos/MEDIA:informe"}, "succeeded", {}, None, None)
    assert "MEDIA:" not in no_case.upper() and "informe" in no_case  # the folder name, neutralised
```

Añade al final de `tests/plugins/ghost_recon/console/test_jobs.py`:

```python


def test_a_runner_that_cannot_spawn_fails_its_job_and_the_dispatch_goes_on(make_jobs, module_runner, case_root,
                                                                           cstore, wait_until):
    real = module_runner()
    broken = set()

    def runner(job_id):
        if job_id in broken:
            raise RuntimeError("tabla de procesos llena")
        return real(job_id)

    jobs = make_jobs(runner=runner)
    rows = []
    for name in ("Caso Roto", "Caso Sano"):  # queued together: one dispatch pass meets both
        plan = jobs.plan(LaunchRequest("new-open-case", str(_folder(case_root, name))), "jean")
        rows.append(cstore.create_job(command=plan["command"], folder=plan["folder"], args=plan["args"],
                                      argv=plan["argv"], launched_by="jean"))
    broken.add(rows[0]["id"])
    assert jobs.dispatch() == [rows[1]["id"]]
    failed = cstore.get_job(rows[0]["id"])
    assert failed["status"] == "failed" and "tabla de procesos llena" in failed["error"]
    assert wait_until(lambda: _done(cstore, rows[1]["id"]), timeout=60)["status"] == "succeeded"
```

- [ ] **Step 2: Ejecutarlas y ver que fallan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_notify.py tests/plugins/ghost_recon/console/test_jobs.py -q`
Expected: FAIL con `ImportError: cannot import name 'NOTIFY_SUBJECT' from 'plugins.ghost_recon.console.commands'` en `test_notify.py`, y en `test_jobs.py` la prueba nueva falla con `RuntimeError: tabla de procesos llena` (el despacho entero se corta).

- [ ] **Step 3: Los argumentos del aviso**

En `plugins/ghost_recon/console/commands.py`, sustituye:

```python
SOURCE_TAG = "ghost-recon-console"
MAX_NAME = 120
```

por:

```python
SOURCE_TAG = "ghost-recon-console"
NOTIFY_SUBJECT = "[Ghost Recon]"
ORDER_LABELS = {"new-open-case": "Nueva auditoría", "rerun-case": "Re-run", "review-case": "Review"}
MAX_NAME = 120
```

y sustituye:

```python
def agent_args(skill: str, query: str, profile_args: Sequence[str]) -> List[str]:
    """Hermes arguments of a console job (spec §6.1); ``--format stream-json`` implies ``--quiet``."""
    return [*profile_args, "--cli", "--accept-hooks", "--skills", skill, "chat", "-q", query,
            "--format", "stream-json", "--source", SOURCE_TAG]
```

por:

```python
def agent_args(skill: str, query: str, profile_args: Sequence[str]) -> List[str]:
    """Hermes arguments of a console job (spec §6.1); ``--format stream-json`` implies ``--quiet``."""
    return [*profile_args, "--cli", "--accept-hooks", "--skills", skill, "chat", "-q", query,
            "--format", "stream-json", "--source", SOURCE_TAG]


def notify_args(target: str, profile_args: Sequence[str]) -> List[str]:
    """Hermes arguments of the job-end notice (spec §6.2): ``-p <perfil> send --to <destino> --subject "[Ghost
    Recon]"``. The runner appends the summary as the message; no LLM and no running gateway are involved."""
    return [*profile_args, "send", "--to", target, "--subject", NOTIFY_SUBJECT]
```

- [ ] **Step 4: El servidor planifica el aviso y el despacho sobrevive a un runner que no arranca**

En `plugins/ghost_recon/console/jobs.py`, sustituye:

```python
            case_id = p["case"]["id"] if p["case"] and p["case"]["source"] == "db" else None
            job = self.cstore.create_job(command=p["command"], folder=p["folder"], args=p["args"], argv=p["argv"],
                                         launched_by=principal.username, context_file=p["context_file"] or None,
                                         case_id=case_id)
```

por:

```python
            case_id = p["case"]["id"] if p["case"] and p["case"]["source"] == "db" else None
            target = self.settings.notify_target
            # Planned here like the agent argv: the runner has no Hermes config, it only appends the summary.
            notify_argv = self.hermes_command(commands.notify_args(target, procs.profile_args())) if target else []
            job = self.cstore.create_job(command=p["command"], folder=p["folder"], args=p["args"], argv=p["argv"],
                                         launched_by=principal.username, context_file=p["context_file"] or None,
                                         case_id=case_id, notify_target=target or None, notify_argv=notify_argv)
```

y sustituye:

```python
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
```

por:

```python
    def _start_runner(self, job: Dict[str, Any]) -> bool:
        """Spawn the job's detached runner. Whatever fails here (the runner log, the launcher, the process table)
        fails this job only: the dispatch pass goes on with the next one."""
        try:
            with open(jobfiles.runner_log_path(self.jobs_dir, job["id"]), "ab") as log:
                proc = procs.spawn_detached(self.runner_command(job["id"]), cwd=procs.hermes_root(),
                                            env=procs.child_env(), stderr=log)
        except Exception as exc:
            logger.exception("ghost-recon console: job %s could not start", job["id"])
            self.cstore.update_job(job["id"], expect=("queued",), status="failed", finished_at=utcnow(),
                                   error=f"no se pudo iniciar la ejecución: {exc}")
            return False
```

- [ ] **Step 5: El runner envía el aviso**

En `plugins/ghost_recon/console/job_runner.py`, sustituye:

```python
The console server is never its required parent: the job survives a server restart and the new server finds it in the
DB. Every write is conditional on the row still being ``running``, so a cancel (or an orphan verdict) always wins; the
runner then stops the agent and exits.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core.db import Store, utcnow
from . import events, jobfiles, procs
from .store import ACTIVE_STATUSES, ConsoleStore

RESULT_TEXT_MAX = 20_000
SELF_CHECK = "ghost-recon job runner ok"
NO_IDENTITY_ERROR = "no se pudo verificar el proceso del agente al iniciarlo (PID y hora de inicio)"
ESSENTIAL_WRITE_BACKOFF_S = (0.5, 1.0, 2.0, 4.0)
logger = logging.getLogger(__name__)
```

por:

```python
The console server is never its required parent: the job survives a server restart and the new server finds it in the
DB. Every write is conditional on the row still being ``running``, so a cancel (or an orphan verdict) always wins; the
runner then stops the agent and exits. When the job ends (succeeded or failed) and a notice target is configured, the
runner runs the ``hermes send`` argv the server planned, with a short summary; the notice is best effort and never
changes the job.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core import ids
from ..core.db import Store, utcnow
from . import commands, events, jobfiles, procs
from .store import ACTIVE_STATUSES, ConsoleStore

RESULT_TEXT_MAX = 20_000
SELF_CHECK = "ghost-recon job runner ok"
NO_IDENTITY_ERROR = "no se pudo verificar el proceso del agente al iniciarlo (PID y hora de inicio)"
ESSENTIAL_WRITE_BACKOFF_S = (0.5, 1.0, 2.0, 4.0)
NOTIFY_TIMEOUT_S = 60
NOTIFY_ERROR_MAX = 300
_MEDIA_RE = re.compile(r"MEDIA:", re.IGNORECASE)
logger = logging.getLogger(__name__)


def notify_message(job: Dict[str, Any], status: str, case: Dict[str, Any], last_audit: Optional[Dict[str, Any]],
                   error: Optional[str]) -> str:
    """The job-end notice: order, outcome, case and last audit, and the (redacted) reason of a failure. Text the
    operator controls (case and folder names, the agent's error) can never turn into a ``MEDIA:`` attachment of
    ``hermes send``, and the message always starts with a word, never with a flag."""
    verb = "terminó" if status == "succeeded" else "falló"
    order = commands.ORDER_LABELS.get(job["command"], job["command"])
    where = f"{case['name']} ({case['id']})" if case else Path(job["folder"]).name
    lines = [f"Ejecución #{job['id']} · {order} · {verb}", f"Caso: {where}"]
    if last_audit:
        lines.append(f"Última auditoría: {ids.short_audit(last_audit['id'])} ({last_audit['status']})")
    if error:
        from agent.redact import redact_sensitive_text
        lines.append(f"Motivo: {redact_sensitive_text(str(error), force=True)[:NOTIFY_ERROR_MAX]}")
    return _MEDIA_RE.sub("MEDIA :", "\n".join(lines))
```

y sustituye:

```python
        fields.update({k: v for k, v in extra.items() if v})
        if _retrying(lambda: self.cstore.update_job(self.job_id, expect=("running",), **fields)) and case_id:
            verb = "terminó" if state["status"] == "succeeded" else "falló"
            _retrying(lambda: self.store.add_event(
                case_id, "console_job_finished", f"Ejecución #{self.job_id} ({job['command']}) {verb}",
                actor=job["launched_by"], ref={"job_id": self.job_id, "status": state["status"],
                                               "session_id": self.norm.session_id or None}))
```

por:

```python
        fields.update({k: v for k, v in extra.items() if v})
        if not _retrying(lambda: self.cstore.update_job(self.job_id, expect=("running",), **fields)):
            return  # cancelled or declared orphan meanwhile: that verdict stands, and nobody is told otherwise
        if case_id:
            verb = "terminó" if state["status"] == "succeeded" else "falló"
            _retrying(lambda: self.store.add_event(
                case_id, "console_job_finished", f"Ejecución #{self.job_id} ({job['command']}) {verb}",
                actor=job["launched_by"], ref={"job_id": self.job_id, "status": state["status"],
                                               "session_id": self.norm.session_id or None}))
        self._notify(job, state["status"], case_id, state["error"])

    def _notify(self, job: Dict[str, Any], status: str, case_id: Optional[str], error: Optional[str]) -> None:
        """``hermes send`` to the configured target (spec §6.2), with the argv the server planned plus the summary.
        Best effort: a failure goes to the runner log and the job keeps its final state."""
        argv = job.get("notify_argv") or []
        if not argv:
            return
        case = self.store.get_case(case_id) if case_id else {}
        audits = self.store.list_audits(case_id) if case else []
        message = notify_message(job, status, case, audits[-1] if audits else None, error)
        try:
            done = subprocess.run([*argv, message], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, cwd=self.work, env=procs.child_env(),
                                  timeout=NOTIFY_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("ghost-recon job runner: the job-end notice was not sent: %s", exc)
            return
        if done.returncode != 0:
            logger.warning("ghost-recon job runner: hermes send exited %s: %s", done.returncode,
                           done.stdout.decode("utf-8", "replace")[-500:])
```

- [ ] **Step 6: El agente falso también hace de `hermes send`**

En `ghost-recon/demo/fake_agent.py`, sustituye:

```python
where the full argv is written as JSON), ``record_cwd`` (path where the working directory is written) and
``write_relative`` (a file name written with a RELATIVE path, as a careless tool call would).
"""
```

por:

```python
where the full argv is written as JSON), ``record_cwd`` (path where the working directory is written) and
``write_relative`` (a file name written with a RELATIVE path, as a careless tool call would).

It also stands in for ``hermes … send --to … --subject … "<message>"`` (the job-end notice): with ``send`` among the
arguments and no ``-q`` it writes its argv as JSON to the default behaviour's ``record_send`` path and exits with
``send_exit_code`` (default 0).
"""
```

y sustituye:

```python
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-config", default="")
    parser.add_argument("-q", "--query", default="")
    args, _hermes_flags = parser.parse_known_args()
    match = _FOLDER_RE.match(args.query)
```

por:

```python
def send(config_path: str) -> int:
    """``hermes send`` stand-in: records its argv and exits with the configured code."""
    cfg = behaviour(config_path, "")
    if cfg.get("record_send"):
        Path(cfg["record_send"]).write_text(json.dumps(sys.argv, ensure_ascii=False), encoding="utf-8")
    return int(cfg.get("send_exit_code", 0))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-config", default="")
    parser.add_argument("-q", "--query", default="")
    args, hermes_args = parser.parse_known_args()
    if not args.query and "send" in hermes_args:
        return send(args.fake_config)
    match = _FOLDER_RE.match(args.query)
```

- [ ] **Step 7: Ejecutar y ver que pasan**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_notify.py tests/plugins/ghost_recon/console/test_jobs.py tests/plugins/ghost_recon/console/test_runner.py tests/plugins/ghost_recon/console/test_api_jobs.py -q`
Expected: `0 failed` (las pruebas del runner y de la API de H2 siguen iguales: sin `notify_target` no hay aviso).

- [ ] **Step 8: Commit**

```bash
git add plugins/ghost_recon/console/commands.py plugins/ghost_recon/console/jobs.py plugins/ghost_recon/console/job_runner.py ghost-recon/demo/fake_agent.py tests/plugins/ghost_recon/console/test_notify.py tests/plugins/ghost_recon/console/test_jobs.py
git commit -m "feat(ghost-recon): console job-end notice via hermes send and a dispatch that survives a bad spawn

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 9: E2E en un `HERMES_HOME` real (sin `GHOSTRECON_DB`)

**Files:**
- Create: `tests/plugins/ghost_recon/console/serve_hermes.py` (script auxiliar; no es una prueba)
- Test: `tests/plugins/ghost_recon/console/test_hermes_home_e2e.py`

**Interfaces:**
- Consumes: el CLI real de Hermes (`python -m hermes_cli.main ghostrecon user add|serve`), el descubrimiento de plugins (`hermes_cli.plugins.discover_plugins`, `get_plugin_manager()._cli_commands`, igual que `hermes_cli/main.py::_register_plugin_cli_commands`), `procs.hermes_command/runner_command/hermes_root`, `ghost-recon/demo/fake_agent.py` (modo `send` de la Tarea 8), el doctor (`GET /system/doctor`, comprobación `database` con `runtime.db_path()`).
- Produces: la prueba del pendiente de H1 «E2E real con `HERMES_HOME` temporal + `config.yaml`»: con un `config.yaml` que habilita el plugin y fija `plugins.entries.ghost-recon.settings.console` (`case_roots`, `port`, `notify_target`) y **sin** `GHOSTRECON_DB`,
  - `hermes ghostrecon user add` crea el admin en `<home>/plugin-data/ghost-recon/ghostrecon.db`;
  - `hermes ghostrecon serve` (el `cmd_serve` real: preflight, `load_settings`, `create_app`, uvicorn) lee esos ajustes y abre esa misma BD;
  - el runner desacoplado (lanzado con el lanzador real de la instalación) y el agente falso escriben en esa BD: el servidor lee de vuelta `succeeded`, el `case_id` y el caso;
  - el aviso al terminar llega al `send` falso con `--to telegram`.
- `serve_hermes.py` no añade ninguna puerta en el código de producción: carga el plugin como lo hace Hermes, sustituye en ese módulo `procs.hermes_command` por el agente falso **solo** para `hermes_cli.main` (el runner sigue usando el lanzador real) y llama a `hermes_cli.main.main()` con `ghostrecon serve`.

- [ ] **Step 1: Crear el servidor auxiliar**

Hermes carga los plugins de carpeta con el nombre de módulo `hermes_plugins.<slug>`, no `plugins.ghost_recon`: el contexto del plugin (`runtime.bind_context`) solo existe en ese paquete. Por eso el auxiliar encuentra el paquete a partir del manejador que registró `ghostrecon` y no importa `plugins.ghost_recon.console` directamente.

Crea `tests/plugins/ghost_recon/console/serve_hermes.py`:

```python
"""Test helper (not a test): the real ``hermes ghostrecon serve`` of a temporary Hermes home, with the fake agent.

    HERMES_HOME=<home> python tests/plugins/ghost_recon/console/serve_hermes.py --fake-config CFG   (no GHOSTRECON_DB)

Runs Hermes' own CLI entry point (``hermes_cli.main`` with ``ghostrecon serve``): plugin discovery, the plugin's
settings from that home's config.yaml, ``serve``'s preflight, ``create_app`` and uvicorn. One thing differs: the
plugin's ``procs.hermes_command`` is wrapped so ``hermes … chat`` and ``hermes … send`` run the fake agent; the job
runner still starts through this installation's launcher and resolves its database on its own.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
FAKE_AGENT = REPO / "ghost-recon" / "demo" / "fake_agent.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-config", required=True)
    args = parser.parse_args()

    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    discover_plugins()
    # The plugin package as Hermes loaded it, found the way hermes_cli/main.py finds `hermes ghostrecon`.
    handler = get_plugin_manager()._cli_commands["ghostrecon"]["handler_fn"]
    procs = importlib.import_module(f"{handler.__module__.rsplit('.', 1)[0]}.console.procs")
    real = procs.hermes_command

    def hermes_command(hermes_args, *, module="hermes_cli.main"):
        if module != "hermes_cli.main":
            return real(hermes_args, module=module)  # the job runner: this installation's launcher, untouched
        return [sys.executable, str(FAKE_AGENT), "--fake-config", args.fake_config, *hermes_args]

    procs.hermes_command = hermes_command
    from hermes_cli.main import main as hermes_main
    sys.argv = ["hermes", "ghostrecon", "serve"]
    return hermes_main()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Escribir la prueba E2E**

La prueba no abre la BD con `sqlite3` desde el proceso de pytest mientras los procesos de Hermes la tienen abierta en WAL (bajo el runner aislado de `run_tests.sh` eso dio `disk I/O error`): demuestra la BD compartida a través del propio servidor (ruta del doctor + filas que solo el runner y el agente escriben).

Crea `tests/plugins/ghost_recon/console/test_hermes_home_e2e.py`:

```python
"""The console inside a real Hermes home, without GHOSTRECON_DB (spec §4.3, §12): ``hermes ghostrecon user add`` and
``hermes ghostrecon serve`` load the plugin through Hermes' own discovery, read the console settings from that home's
config.yaml and find the database under plugin-data; the detached job runner and the agent write to that same
database, and the job-end notice reaches a fake ``hermes send``."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from plugins.ghost_recon.console import procs

SERVE = Path(__file__).resolve().parent / "serve_hermes.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "GHOSTRECON_DB"}  # the profile alone decides the DB
    env.update(HERMES_HOME=str(home), PYTHONIOENCODING="utf-8")
    return env


@pytest.fixture
def hermes_home(tmp_path):
    home, cases = tmp_path / "hermes-home", tmp_path / "Casos"
    home.mkdir()
    cases.mkdir()
    port = _free_port()
    console = {"case_roots": [str(cases)], "port": port, "notify_target": "telegram"}
    config = {"plugins": {"enabled": ["ghost-recon"], "entries": {"ghost-recon": {"settings": {"console": console}}}}}
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")  # JSON is valid YAML
    return {"home": home, "cases": cases, "port": port, "db": home / "plugin-data" / "ghost-recon" / "ghostrecon.db"}


def _wait(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        assert time.monotonic() < deadline, f"timed out after {timeout} s waiting for {message}"
        time.sleep(0.2)


def _up(base, server, log_path):
    try:
        return httpx.get(base + "/api/v1/auth/me", timeout=2).status_code == 401
    except httpx.TransportError:
        assert server.poll() is None, log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
        return False


def test_serve_and_its_runner_share_the_profile_database(hermes_home, tmp_path):
    env = _env(hermes_home["home"])
    added = subprocess.run([sys.executable, "-m", "hermes_cli.main", "ghostrecon", "user", "add", "jean", "--role",
                            "admin", "--password-stdin"], cwd=procs.hermes_root(), env=env, input="admin-pass-123\n",
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert added.returncode == 0, added.stderr[-3000:]
    assert hermes_home["db"].is_file()  # created under <home>/plugin-data/ghost-recon/
    record, fake = tmp_path / "send.json", tmp_path / "fake.json"
    fake.write_text(json.dumps({"default": {"steps": 2, "delay": 0.05, "record_send": str(record)}}),
                    encoding="utf-8")
    log_path = tmp_path / "serve.log"
    folder = hermes_home["cases"] / "Caso Perfil"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto.txt").write_text("2026-01-02;ZELLE;-10.00\n", encoding="utf-8")
    base = f"http://127.0.0.1:{hermes_home['port']}"
    with open(log_path, "wb") as log:
        server = subprocess.Popen([sys.executable, str(SERVE), "--fake-config", str(fake)], cwd=procs.hermes_root(),
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            _wait(lambda: _up(base, server, log_path), 120, "the console to start")
            with httpx.Client(base_url=base, timeout=30) as c:
                r = c.post("/api/v1/auth/login", json={"username": "jean", "password": "admin-pass-123"})
                assert r.status_code == 200, r.text  # the admin the CLI created, in the same database
                c.headers["X-GR-CSRF"] = r.json()["csrf"]
                doctor = c.get("/api/v1/system/doctor").json()
                assert doctor["console"]["case_roots"] == [str(hermes_home["cases"])]  # from that home's config.yaml
                database = next(x["detail"] for x in doctor["checks"] if x["check"] == "database")
                assert Path(database.split(" · ")[0]).resolve() == hermes_home["db"].resolve()
                job = c.post("/api/v1/jobs", json={"command": "new-open-case", "folder": str(folder)}).json()["job"]
                done = _wait(lambda: (lambda j: j if j["status"] not in ("queued", "running") else None)(
                    c.get(f"/api/v1/jobs/{job['id']}").json()), 180, "the job to end")
                # Only the detached runner writes "succeeded" and the case id, and only the fake agent opens the
                # case: the server reading both back from its database proves all three share it.
                assert done["status"] == "succeeded" and done["case_id"], done
                assert c.get(f"/api/v1/cases/{done['case_id']}").json()["case"]["root_path"] == str(folder.resolve())
            _wait(record.is_file, 60, "the job-end notice")  # sent right after the runner's final write
        finally:
            server.terminate()
            server.wait(timeout=30)
    sent = json.loads(record.read_text(encoding="utf-8"))
    assert sent[sent.index("--to") + 1] == "telegram" and sent[-1].startswith(f"Ejecución #{job['id']}")
```

- [ ] **Step 3: Ejecutarla**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_hermes_home_e2e.py -q`
Expected: `1 passed` en unos 10 s. Si falla al arrancar, el `AssertionError` incluye la cola de `serve.log` (por ejemplo, el plugin no se habilitó o falta el admin).

Comprobación de que la prueba mira lo que dice: si el servidor resolviera otra BD (por ejemplo, con `GHOSTRECON_DB` en su entorno), `serve` ni siquiera arrancaría — su preflight no encuentra el admin que `user add` creó en la BD del perfil — y la prueba fallaría en «the console to start» con ese mensaje en la cola de `serve.log`.

- [ ] **Step 4: Regresión del E2E de H2**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_jobs_e2e.py tests/plugins/ghost_recon/console/test_serve_e2e.py tests/plugins/ghost_recon/console/test_cli.py -q`
Expected: `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add tests/plugins/ghost_recon/console/serve_hermes.py tests/plugins/ghost_recon/console/test_hermes_home_e2e.py
git commit -m "test(ghost-recon): console E2E in a real Hermes home shares the profile DB with the runner

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 10: Frontend — «verificado hace X», filtro de riesgo, CSV/XLSX, descargas en la página y el asistente sin callejón

**Files:**
- Modify: `plugins/ghost_recon/console/static/lib/format.js`
- Modify (reemplazar): `plugins/ghost_recon/console/static/lib/api.js`
- Modify: `plugins/ghost_recon/console/static/views/components.js`
- Modify (reemplazar): `plugins/ghost_recon/console/static/views/case/criteria.js`, `views/case/timeline.js`, `views/cases.js`
- Modify: `plugins/ghost_recon/console/static/views/case/findings.js`, `views/case/evidence.js`, `views/case/audits.js`, `views/wizard.js`
- Modify: `plugins/ghost_recon/console/static/app.css` (añadir al final)

**Interfaces:**
- Consumes: `GET /cases?risk=` (Tarea 7), `GET /cases/{id}/{table}.{csv|xlsx}` (Tarea 4), la descarga de entregables comprobada (Tarea 3: 409 con el archivo nombrado) y `seal_check.checked_at` de las auditorías (H1).
- Produces:
  - `format.js`: `fmtAgo(iso)` («hace un momento», «hace 5 min», «hace 3 h», «hace 2 días») y `sealCheckChip(audit)`, que ahora devuelve el chip más «verificado hace X»;
  - `api.js`: `download(path, query)` (descarga un adjunto con `fetch` y un `blob:` sin salir de la página; un error vuelve como `ApiError`); se conservan `api`, `ApiError`, `setCsrf` y `downloadUrl` (enlace directo, para el ZIP grande de la Tarea 11);
  - `components.js`: `downloadButton(text, path, {query, note, title, small})` y `tableExport(caseId, table, filters)` («Exportar con los filtros activos: CSV · XLSX» y el motivo de un rechazo, p. ej. el 503 sin openpyxl);
  - Casos: selector «Riesgo abierto» (cualquiera, con hallazgos abiertos, crítico, alto, medio, bajo);
  - Hallazgos, Evidencia, Cronología y Criterios: botones CSV/XLSX que descargan con los filtros que tiene la tabla en ese momento;
  - Auditorías: los entregables se descargan con `downloadButton` (un entregable alterado muestra el 409 junto al botón en lugar de abrir una página JSON);
  - Asistente: si una carpeta ya no existe al abrirla, el error lleva «← Carpetas de casos».
- Sin pruebas Python nuevas: la lógica está en el servidor y probada; aquí se verifica en el navegador (Step 11) y con el barrido de textos.

- [ ] **Step 1: «verificado hace X»**

En `plugins/ghost_recon/console/static/lib/format.js`, sustituye:

```js
export function sealCheckChip(audit) {
  if (audit.status !== "sealed") return chip("sin sellar", "muted");
  const check = audit.seal_check;
  if (!check) return chip("sin verificar", "info");
  const title = `verificado ${fmtDate(check.checked_at)} por ${check.checked_by || "—"}`;
  return check.ok ? chip("sello OK", "ok", title) : chip("sello alterado", "risk-high", title);
}
```

por:

```js
/** A sealed audit's seal state plus how long ago it was verified ("verificado hace 5 min"). */
export function sealCheckChip(audit) {
  if (audit.status !== "sealed") return chip("sin sellar", "muted");
  const check = audit.seal_check;
  if (!check) return chip("sin verificar", "info");
  const title = `verificado ${fmtDate(check.checked_at)} por ${check.checked_by || "—"}`;
  return h("span", { class: "seal-check" },
    check.ok ? chip("sello OK", "ok", title) : chip("sello alterado", "risk-high", title),
    h("small", { class: "muted", title }, `verificado ${fmtAgo(check.checked_at)}`));
}

/** Relative time in Spanish: "hace un momento", "hace 5 min", "hace 3 h", "hace 2 días". */
export function fmtAgo(iso) {
  const seconds = secondsSince(iso);
  if (seconds === null) return "—";
  if (seconds < 60) return "hace un momento";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `hace ${hours} h`;
  return `hace ${Math.floor(hours / 24)} días`;
}
```

(`secondsSince` está más abajo en el mismo módulo: las declaraciones de función se elevan.)

- [ ] **Step 2: Descargas sin salir de la página**

Un enlace directo a un adjunto que responde con error (503 sin openpyxl, 409 de un entregable alterado) reemplazaría la consola por una página JSON. `download()` lo pide con `fetch`, guarda el archivo desde un `blob:` (la CSP no lo impide: no es una conexión ni un recurso de la página) y devuelve el error como `ApiError`.

Reemplaza `plugins/ghost_recon/console/static/lib/api.js` completo:

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

/** Same-origin URL of an API path, for plain links (a large ZIP downloads straight to disk this way). */
export function downloadUrl(path) {
  return BASE + path;
}

function apiUrl(path, query) {
  const url = new URL(BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  return url;
}

async function failure(res, path) {
  let err = {};
  try {
    err = ((await res.json()) || {}).error || {};
  } catch {
    // not a JSON envelope: keep the HTTP status text
  }
  if (res.status === 401 && !path.startsWith("/auth/")) window.location.hash = "#/login";
  return new ApiError(res.status, err.code || `http_${res.status}`, err.message || res.statusText, null);
}

function attachmentName(header) {
  const star = /filename\*=utf-8''([^;]+)/i.exec(header || "");
  if (star) return decodeURIComponent(star[1]);
  const plain = /filename="([^"]+)"/i.exec(header || "");
  return plain ? plain[1] : "descarga";
}

/** Download an attachment of the API without leaving the page: an error (e.g. 503 without openpyxl, 409 for a
 *  changed deliverable) comes back as ApiError instead of replacing the console with a JSON page. */
export async function download(path, query) {
  const res = await fetch(apiUrl(path, query), { credentials: "same-origin" });
  if (!res.ok) throw await failure(res, path);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await res.blob());
  link.download = attachmentName(res.headers.get("content-disposition"));
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
}

export async function api(path, { method = "GET", body, query } = {}) {
  const url = apiUrl(path, query);
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

- [ ] **Step 3: Botones de descarga y de exportación de tablas**

En `plugins/ghost_recon/console/static/views/components.js`, sustituye:

```js
import { h } from "../lib/dom.js";
import { COMMAND_LABEL, fmtDate, fmtDuration, jobChip, label, riskChips, sealChip } from "../lib/format.js";
```

por:

```js
import { download } from "../lib/api.js";
import { h } from "../lib/dom.js";
import { COMMAND_LABEL, fmtDate, fmtDuration, jobChip, label, riskChips, sealChip } from "../lib/format.js";
```

y sustituye:

```js
export function debounce(fn, ms) {
```

por:

```js
/** A button that downloads an API attachment in place; a refusal is shown in `note` (or after the button). */
export function downloadButton(text, path, { query = () => ({}), note = null, title = null, small = true } = {}) {
  const status = note || h("span", { class: "download-note", role: "status" });
  const button = h("button", { class: small ? "btn ghost small" : "btn ghost", type: "button", title }, text);
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "";
    status.classList.remove("error");
    try {
      await download(path, query());
    } catch (err) {
      status.textContent = err.message;
      status.classList.add("error");
    } finally {
      button.disabled = false;
    }
  });
  return note ? button : h("span", { class: "download" }, button, status);
}

/** "CSV" / "XLSX" of a case table: what the table shows, with its current filters (`filters()` → query). */
export function tableExport(caseId, table, filters = () => ({})) {
  const note = h("span", { class: "download-note", role: "status" });
  const path = (fmt) => `/cases/${encodeURIComponent(caseId)}/${table}.${fmt}`;
  return h("div", { class: "table-export" }, h("span", { class: "muted" }, "Exportar con los filtros activos:"),
    downloadButton("CSV", path("csv"), { query: filters, note, title: "CSV en UTF-8 (se abre en Excel con acentos)" }),
    downloadButton("XLSX", path("xlsx"), { query: filters, note, title: "Libro de Excel con metadatos Ghost Recon" }),
    note);
}

export function debounce(fn, ms) {
```

- [ ] **Step 4: CSV/XLSX en Criterios y Cronología**

Reemplaza `plugins/ghost_recon/console/static/views/case/criteria.js` completo:

```js
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { dataTable, tableExport } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/criteria`);
  return h("section", { class: "card" }, tableExport(caseId, "criteria"), dataTable([
    { title: "ID", cell: (c) => h("strong", { class: "mono" }, c.id) },
    { title: "Fecha", cell: (c) => c.date || "—" },
    { title: "Autor", cell: (c) => c.author },
    { title: "Texto (literal)", cell: (c) => c.text },
    { title: "Estado", cell: (c) => c.status },
    { title: "Auditoría", cell: (c) => (c.audit_id ? c.audit_id.split("/").pop() : "—") },
  ], data.items, { empty: "Sin criterios registrados." }));
}
```

Reemplaza `plugins/ghost_recon/console/static/views/case/timeline.js` completo:

```js
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { fmtDate } from "../../lib/format.js";
import { dataTable, tableExport } from "../components.js";

export async function render({ caseId }) {
  const data = await api(`/cases/${encodeURIComponent(caseId)}/timeline`);
  return h("section", { class: "card" }, tableExport(caseId, "timeline"), dataTable([
    { title: "Fecha", cell: (e) => fmtDate(e.ts) },
    { title: "Evento", cell: (e) => e.event_type },
    { title: "Auditoría", cell: (e) => (e.audit_id ? e.audit_id.split("/").pop() : "—") },
    { title: "Actor", cell: (e) => e.actor },
    { title: "Descripción", cell: (e) => e.description },
  ], data.items, { empty: "Sin eventos." }));
}
```

- [ ] **Step 5: CSV/XLSX en Hallazgos, con sus filtros**

En `plugins/ghost_recon/console/static/views/case/findings.js`, sustituye:

```js
import { dataTable, debounce, errorState, toggleDetail } from "../components.js";
```

por:

```js
import { dataTable, debounce, errorState, tableExport, toggleDetail } from "../components.js";
```

y sustituye:

```js
  const q = h("input", { type: "search", placeholder: "Buscar por ID, título, contraparte…", "aria-label": "Buscar hallazgos" });
  const box = h("div");
  async function load() {
    try {
      const data = await api(`/cases/${encodeURIComponent(caseId)}/findings`,
        { query: { kind: kind.value, risk: risk.value, status: status.value, q: q.value } });
```

por:

```js
  const q = h("input", { type: "search", placeholder: "Buscar por ID, título, contraparte…", "aria-label": "Buscar hallazgos" });
  const box = h("div");
  const filters = () => ({ kind: kind.value, risk: risk.value, status: status.value, q: q.value });
  async function load() {
    try {
      const data = await api(`/cases/${encodeURIComponent(caseId)}/findings`, { query: filters() });
```

y sustituye:

```js
  return h("section", { class: "card" }, h("div", { class: "filters" }, kind, risk, status, q), box);
```

por:

```js
  return h("section", { class: "card" }, h("div", { class: "filters" }, kind, risk, status, q),
    tableExport(caseId, "findings", filters), box);
```

- [ ] **Step 6: CSV/XLSX en Evidencia, con sus filtros (todas las filas, no solo la página cargada)**

En `plugins/ghost_recon/console/static/views/case/evidence.js`, sustituye:

```js
import { dataTable, debounce, errorState } from "../components.js";
```

por:

```js
import { dataTable, debounce, errorState, tableExport } from "../components.js";
```

y sustituye:

```js
  const box = h("div");
  const more = h("button", { class: "btn ghost", type: "button", hidden: true }, "Cargar más");
```

por:

```js
  const box = h("div");
  const more = h("button", { class: "btn ghost", type: "button", hidden: true }, "Cargar más");
  const filters = () => ({ status: status.value, audit: audit.value, q: q.value });
```

y sustituye:

```js
      const data = await api(`/cases/${encodeURIComponent(caseId)}/evidence`,
        { query: { status: status.value, audit: audit.value, q: q.value, limit: PAGE, cursor } });
```

por:

```js
      const data = await api(`/cases/${encodeURIComponent(caseId)}/evidence`,
        { query: { ...filters(), limit: PAGE, cursor } });
```

y sustituye:

```js
    h("div", { class: "filters" }, status, audit, q), box, more);
```

por:

```js
    h("div", { class: "filters" }, status, audit, q), tableExport(caseId, "evidence", filters), box, more);
```

- [ ] **Step 7: Entregables con descarga comprobada en Auditorías**

En `plugins/ghost_recon/console/static/views/case/audits.js`, sustituye:

```js
import { api, downloadUrl } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { chip, fmtBytes, fmtDate, label, sealCheckChip, shortHash } from "../../lib/format.js";
import { dataTable, toggleDetail } from "../components.js";
```

por:

```js
import { api } from "../../lib/api.js";
import { h } from "../../lib/dom.js";
import { chip, fmtBytes, fmtDate, label, sealCheckChip, shortHash } from "../../lib/format.js";
import { dataTable, downloadButton, toggleDetail } from "../components.js";
```

y sustituye:

```js
      { title: "Archivo", cell: (r) => (canDownload
        ? h("a", { href: downloadUrl(`${base}/reports/${r.id}/download`), download: r.name }, r.name) : r.name) },
```

por:

```js
      // A sealed audit's deliverable is re-hashed on download; a changed file is refused here, by name.
      { title: "Archivo", cell: (r) => (canDownload
        ? downloadButton(r.name, `${base}/reports/${r.id}/download`, { title: "Descargar" }) : r.name) },
```

- [ ] **Step 8: Filtro «riesgo abierto» en Casos**

Las respuestas viejas que llegan tarde se descartan (`latestGuard`), porque ahora hay tres filtros que disparan cargas.

Reemplaza `plugins/ghost_recon/console/static/views/cases.js` completo:

```js
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { latestGuard } from "../lib/latest.js";
import { casesTable, debounce, errorState, newAuditAction } from "./components.js";

const RISK_OPTIONS = [["", "Cualquier riesgo"], ["any", "Con hallazgos abiertos"], ["critical", "Riesgo crítico abierto"],
  ["high", "Riesgo alto abierto"], ["medium", "Riesgo medio abierto"], ["low", "Riesgo bajo abierto"]];

export async function render({ user }) {
  const q = h("input", { type: "search", placeholder: "Filtrar por nombre, ID o carpeta", "aria-label": "Filtrar casos" });
  const status = h("select", { "aria-label": "Estado" },
    h("option", { value: "" }, "Todos los estados"), h("option", { value: "open" }, "Abiertos"),
    h("option", { value: "closed" }, "Cerrados"), h("option", { value: "archived" }, "Archivados"));
  const risk = h("select", { "aria-label": "Riesgo abierto" },
    RISK_OPTIONS.map(([value, text]) => h("option", { value }, text)));
  const box = h("div");
  const guard = latestGuard();
  async function load() {
    const token = guard.next();
    try {
      const items = (await api("/cases", { query: { q: q.value, status: status.value, risk: risk.value } })).items;
      if (!guard.isLatest(token)) return;
      const filtered = Boolean(q.value || status.value || risk.value);
      mount(box, casesTable(items, user, filtered ? { empty: "Ningún caso coincide con los filtros." } : {}));
    } catch (err) {
      if (guard.isLatest(token)) mount(box, errorState(err));
    }
  }
  q.addEventListener("input", debounce(load, 250));
  status.addEventListener("change", load);
  risk.addEventListener("change", load);
  await load();
  return h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", {}, "Casos"), newAuditAction(user)),
    h("div", { class: "filters" }, q, status, risk),
    h("section", { class: "card" }, box));
}
```

- [ ] **Step 9: El asistente nunca deja sin salida**

En `plugins/ghost_recon/console/static/views/wizard.js`, sustituye:

```js
    } catch (err) {
      if (guard.isLatest(token)) mount(box, errorState(err));
    }
  }

  search.addEventListener("input", debounce(async () => {
```

por:

```js
    } catch (err) {
      // Never a dead end: the folder may have been moved or renamed since it was listed.
      if (guard.isLatest(token)) {
        mount(box, errorState(err), h("div", { class: "wizard-actions" },
          h("button", { class: "btn ghost", type: "button", onclick: () => browse(null) }, "← Carpetas de casos")));
      }
    }
  }

  search.addEventListener("input", debounce(async () => {
```

- [ ] **Step 10: Estilos**

Añade al final de `plugins/ghost_recon/console/static/app.css`:

```css

/* table exports, in-page downloads and seal checks */
.table-export { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 10px; font-size: 12.5px; }
.download { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.download-note:empty { display: none; }
.download-note.error { padding: 4px 8px; }
.seal-check { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.seal-check small { font-size: 11.5px; }
```

- [ ] **Step 11: Regresión, sintaxis y smoke en el navegador**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console/test_static.py tests/plugins/ghost_recon/console/test_api_cases.py -q`
Expected: `0 failed`.

Si Node está instalado (la máquina dedicada no lo necesita):

```bash
for f in plugins/ghost_recon/console/static/app.js plugins/ghost_recon/console/static/lib/*.js plugins/ghost_recon/console/static/views/*.js plugins/ghost_recon/console/static/views/case/*.js; do node --input-type=module --check < "$f" || echo "ERROR: $f"; done
```

Expected: sin salida.

Smoke (en navegador o con Playwright MCP). Run: `.venv/Scripts/python.exe ghost-recon/demo/console_demo.py --port 9241` (o `.venv/bin/python …`); abre `http://localhost:9241`, entra como `demo` / `demo-pass-123` y comprueba:
- [ ] Casos: el selector «Riesgo abierto» filtra; «Riesgo crítico abierto» deja la tabla en «Ningún caso coincide con los filtros.» y «Riesgo alto abierto» muestra «Acme Importaciones»;
- [ ] en Acme › Auditorías, tras «Verificar sellos», la columna Sello de A01 muestra «sello OK» y «verificado hace un momento» (el `title` lleva la fecha y quién);
- [ ] al desplegar A01, el entregable es un botón: descarga el `.md`; si añades una línea al archivo en disco (`…/GhostRecon_Audits/A01_*/06_Report/*.md`), el segundo clic muestra junto al botón «El entregable no coincide con el sello de la auditoría: 06_Report/… cambió después de sellar la auditoría…» y la consola sigue en pantalla;
- [ ] Hallazgos con «Riesgo: Alto»: «CSV» descarga `GhostRecon_<slug>_findings_<fecha>.csv` con BOM y solo la fila de riesgo alto; «XLSX» descarga el libro, o, sin openpyxl, muestra «Falta openpyxl, dependencia del plugin…» junto a los botones;
- [ ] Evidencia, Cronología y Criterios muestran «Exportar con los filtros activos: CSV XLSX»;
- [ ] «+ Nueva auditoría»: crea una carpeta en la raíz de casos de la demo, ábrela en el listado tras borrarla en disco: aparece el error y «← Carpetas de casos», que vuelve a las raíces;
- [ ] la consola del navegador no muestra errores de CSP ni de JS (los 4xx/5xx provocados salen como «Failed to load resource»: son esperados).

Detén la demo con Ctrl+C.

- [ ] **Step 12: Commit**

```bash
git add plugins/ghost_recon/console/static
git commit -m "feat(ghost-recon): console seal age, open-risk filter, CSV/XLSX table buttons and in-page downloads

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 11: Frontend — diálogo de exportación, búsqueda en la barra superior y avisos

**Files:**
- Create: `plugins/ghost_recon/console/static/views/export.js`
- Create: `plugins/ghost_recon/console/static/views/search.js`
- Create: `plugins/ghost_recon/console/static/lib/notices.js`
- Modify: `plugins/ghost_recon/console/static/app.js`
- Modify: `plugins/ghost_recon/console/static/views/case.js`, `views/case/audits.js`, `views/job.js`
- Modify: `plugins/ghost_recon/console/static/app.css` (añadir al final)

**Interfaces:**
- Consumes: `GET /cases/{id}/export/preview`, `POST /cases/{id}/export`, `GET /exports/{eid}`, `GET /exports/{eid}/download`, `GET /exports/{eid}/sha256` (Tarea 6); `GET /search` (Tarea 7); `GET /jobs?limit=` (H2); `downloadButton`, `downloadUrl`, `copyButton`, `field`, `modal` (Tarea 10 y H2).
- Produces:
  - `views/export.js`: `openExportDialog({caseId, caseName, audits, user, seq = null})`: alcance (caso completo o una auditoría), casilla «Incluir auditorías abiertas» solo para admin (arranca con el valor configurado que devuelve la vista previa), qué entra y qué queda fuera con su motivo, «Exportar», progreso por archivos, y al terminar nombre, tamaño, SHA-256, «Descargar .zip» (enlace directo: un ZIP grande va al disco sin pasar por memoria), «Descargar .sha256» y «Copiar SHA-256»; un fallo (sello roto) se muestra y deja volver a intentarlo;
  - `views/search.js`: `searchBox()`: búsqueda con 250 ms de espera, resultados agrupados (Casos, Hallazgos, Evidencia, Criterios), cada uno enlazado a la pestaña del caso; Esc limpia; salir del cuadro cierra los resultados;
  - `lib/notices.js`: `noticeToggle()` («Avisarme al terminar», deshabilitado con su motivo si el navegador no puede notificar: hace falta https o localhost), `startWatcher()` y `stopWatcher()`. El vigilante solo consulta si el aviso está activado y permitido; cada 15 s lee las 50 ejecuciones más recientes y avisa de cada una que terminó desde la consulta anterior (también la que empezó y terminó entre dos consultas);
  - el botón «Exportar resultados (.zip)» del encabezado del caso, «ZIP de A0n» en el detalle de cada auditoría (deshabilitado para un viewer en una auditoría abierta) y «Exportar resultados (.zip)» en el resultado de una Ejecución quedan vivos; la barra superior lleva la búsqueda y el interruptor de avisos. **No queda ningún «Próximamente».**

- [ ] **Step 1: El diálogo de exportación**

Crea `plugins/ghost_recon/console/static/views/export.js`:

```js
// Results ZIP dialog: the scope (whole case or one audit), unsealed audits for admins (they go in marked as a draft),
// what goes in and why the rest stays out (GET …/export/preview), then the background build with its progress, the
// SHA-256 and the download.
import { api, downloadUrl } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { chip, fmtBytes, label } from "../lib/format.js";
import { latestGuard } from "../lib/latest.js";
import { copyButton, downloadButton, field, modal } from "./components.js";

const POLL_MS = 1000;
const PENDING = ["queued", "building"];

function problem(text) {
  return h("div", { class: "error", role: "alert" }, text);
}

function planView(view) {
  return h("div", { class: "export-plan" },
    h("h3", {}, "Entra en el ZIP"),
    h("ul", { class: "plan" }, view.audits.map((a) => h("li", {}, `${a.seq} · ${label.auditKind(a.kind)} `,
      a.draft ? chip("BORRADOR: sin sellar", "risk-medium") : chip("sellada: se verifica antes de empaquetar", "ok")))),
    h("p", { class: "muted" }, "Además: case.json, corpus_inventory.csv, los contextos de la consola (_console/) y "
      + "EXPORT_MANIFEST.json con el SHA-256 de cada archivo. La evidencia original nunca se exporta."),
    view.excluded.length ? h("h3", {}, "Queda fuera") : null,
    view.excluded.length ? h("ul", { class: "plan" }, view.excluded.map((e) => h("li", {}, `${e.seq}: ${e.text}`))) : null);
}

function finished(row) {
  return h("div", { class: "export-done" },
    h("p", {}, `Listo: ${row.file_name} · ${fmtBytes(row.size)} · ${row.files_total} archivos`),
    h("p", {}, "SHA-256 del ZIP: ", h("span", { class: "mono" }, row.sha256)),
    h("div", { class: "actions" },
      h("a", { class: "btn", href: downloadUrl(`/exports/${row.id}/download`), download: row.file_name }, "Descargar .zip"),
      downloadButton("Descargar .sha256", `/exports/${row.id}/sha256`, { small: false }),
      copyButton(row.sha256, "Copiar SHA-256")));
}

/** audits: the case's audits ({seq, kind, status}); seq preselects one audit (the per-audit ZIP buttons). */
export function openExportDialog({ caseId, caseName, audits, user, seq = null }) {
  const base = `/cases/${encodeURIComponent(caseId)}`;
  const admin = user.role === "admin";
  const scope = h("select", {}, h("option", { value: "" }, "Caso completo"),
    audits.map((a) => h("option", { value: a.seq, selected: a.seq === seq },
      `Solo ${a.seq} · ${label.auditKind(a.kind)} · ${label.auditStatus(a.status)}`)));
  const unsealed = h("input", { type: "checkbox" });
  const plan = h("div", {}, h("p", { class: "muted" }, "Calculando qué entra en el ZIP…"));
  const status = h("div", { role: "status" });
  const start = h("button", { class: "btn", type: "button", disabled: true }, "Exportar");
  const guard = latestGuard();
  let touched = false; // until the admin changes it, the checkbox shows the configured default
  let timer = null;
  const { dialog } = modal(`Exportar resultados · ${caseName}`, h("div", {},
    field("Alcance", scope),
    admin ? h("label", { class: "check" }, unsealed, "Incluir auditorías abiertas (salen marcadas como borrador)") : null,
    plan, status, h("div", { class: "actions" }, start)), { wide: true });
  dialog.addEventListener("close", () => {
    guard.next();
    clearTimeout(timer);
  });

  const body = () => ({ ...(scope.value ? { scope: "audit", seq: scope.value } : { scope: "case" }),
    ...(admin && touched ? { include_unsealed: unsealed.checked } : {}) });

  async function preview() {
    const token = guard.next();
    start.disabled = true;
    mount(status);
    try {
      const view = await api(`${base}/export/preview`, { query: body() });
      if (!guard.isLatest(token)) return;
      unsealed.checked = view.include_unsealed;
      mount(plan, planView(view));
      start.disabled = false;
    } catch (err) {
      if (guard.isLatest(token)) mount(plan, problem(err.message));
    }
  }

  async function follow(id) {
    let row;
    try {
      row = await api(`/exports/${id}`);
    } catch (err) {
      mount(status, problem(`No se pudo consultar la exportación: ${err.message}`));
      timer = setTimeout(() => follow(id), POLL_MS * 3);
      return;
    }
    if (!dialog.open) return;
    if (PENDING.includes(row.status)) {
      const total = row.files_total || 0;
      mount(status, h("p", {}, row.status === "queued" ? "En cola…" : `Empaquetando: ${row.files_done} de ${total} archivos`),
        h("progress", { max: String(Math.max(total, 1)), value: String(row.files_done || 0) }));
      timer = setTimeout(() => follow(id), POLL_MS);
      return;
    }
    if (row.status === "succeeded") {
      mount(status, finished(row));
      return;
    }
    mount(status, problem(row.error || "La exportación falló."));
    for (const el of [start, scope, unsealed]) el.disabled = false; // fix the cause, then try again
  }

  scope.addEventListener("change", preview);
  unsealed.addEventListener("change", () => {
    touched = true;
    preview();
  });
  start.addEventListener("click", async () => {
    for (const el of [start, scope, unsealed]) el.disabled = true;
    try {
      const created = await api(`${base}/export`, { method: "POST", body: body() });
      follow(created.export_id);
    } catch (err) {
      mount(status, problem(err.message));
      for (const el of [start, scope, unsealed]) el.disabled = false;
    }
  });
  preview();
}
```

- [ ] **Step 2: La búsqueda de la barra superior**

Crea `plugins/ghost_recon/console/static/views/search.js`:

```js
// Top-bar search across cases: results grouped by type, each one a link to the case tab that shows it. Esc clears;
// leaving the box closes the results.
import { api } from "../lib/api.js";
import { h, mount } from "../lib/dom.js";
import { latestGuard } from "../lib/latest.js";
import { debounce } from "./components.js";

const GROUPS = [["case", "Casos"], ["finding", "Hallazgos"], ["evidence", "Evidencia"], ["criteria", "Criterios"]];
const LIMIT = 8;

function results(data) {
  const groups = GROUPS.filter(([type]) => (data.items[type] || []).length);
  if (!groups.length) return h("p", { class: "muted" }, `Nada coincide con «${data.q}».`);
  return [
    groups.map(([type, title]) => h("section", { class: "search-group" }, h("h3", {}, title),
      h("ul", {}, data.items[type].map((item) => h("li", {},
        h("a", { href: `#/cases/${encodeURIComponent(item.case_id)}/${item.tab}` }, item.title),
        h("small", { class: "muted" }, `${item.case_name} · ${item.detail}`)))),
      data.more[type] ? h("p", { class: "muted" }, "Hay más resultados: afina la búsqueda.") : null)),
    data.timed_out ? h("p", { class: "muted" }, "La búsqueda se detuvo antes de recorrer todos los casos: afina el texto.") : null,
  ];
}

export function searchBox() {
  const input = h("input", { class: "search", type: "search", autocomplete: "off", "aria-label": "Buscar entre casos",
    placeholder: "Buscar entre casos: ID, hallazgo, archivo, hash…" });
  const panel = h("div", { class: "search-panel", hidden: true, role: "region", "aria-label": "Resultados de la búsqueda" });
  const wrap = h("div", { class: "search-wrap" }, input, panel);
  const guard = latestGuard();
  const hide = () => { panel.hidden = true; };

  async function run() {
    const q = input.value.trim();
    const token = guard.next();
    if (q.length < 2) {
      hide();
      return;
    }
    panel.hidden = false;
    mount(panel, h("p", { class: "muted" }, "Buscando…"));
    try {
      const data = await api("/search", { query: { q, limit: LIMIT } });
      if (guard.isLatest(token)) mount(panel, results(data));
    } catch (err) {
      if (guard.isLatest(token)) mount(panel, h("p", { class: "error" }, err.message));
    }
  }

  input.addEventListener("input", debounce(run, 250));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      input.value = "";
      guard.next();
      hide();
    }
  });
  input.addEventListener("focus", () => { if (input.value.trim().length >= 2 && panel.childNodes.length) panel.hidden = false; });
  wrap.addEventListener("focusout", (e) => { if (!wrap.contains(e.relatedTarget)) hide(); });
  return wrap;
}
```

- [ ] **Step 3: Los avisos del navegador**

Crea `plugins/ghost_recon/console/static/lib/notices.js`:

```js
// Browser notices when a job ends or fails while the console is open. Opt-in twice: the "Avisarme al terminar"
// toggle (remembered in this browser) and the browser's own permission. One watcher per page polls the newest jobs
// and announces each one that ended since the previous poll (also one that started and ended in between).
import { api } from "./api.js";
import { h } from "./dom.js";
import { COMMAND_LABEL } from "./format.js";

const KEY = "gr.notify";
const POLL_MS = 15000;
const RECENT = 50;
const OUTCOME = { succeeded: "terminó", failed: "falló", cancelled: "se canceló", orphaned: "se interrumpió" };
let known = null; // job id -> whether it was active at the previous poll
let timer = null;

function supported() {
  return "Notification" in window && window.isSecureContext;
}

function wanted() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false; // storage blocked: the toggle cannot be remembered, so notices stay off
  }
}

function remember(on) {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    // storage blocked: the choice lasts until the page reloads
  }
}

function on() {
  return supported() && wanted() && Notification.permission === "granted";
}

function announce(job) {
  const notice = new Notification(`Ghost Recon · ejecución #${job.id} ${OUTCOME[job.status] || job.status}`, {
    body: `${COMMAND_LABEL[job.command] || job.command} · ${job.case_name || job.folder_name}`, tag: `gr-job-${job.id}` });
  notice.onclick = () => {
    window.focus();
    window.location.hash = `#/jobs/${job.id}`;
    notice.close();
  };
}

async function poll() {
  if (!on()) {
    known = null;
    return;
  }
  try {
    const jobs = (await api("/jobs", { query: { limit: RECENT } })).items;
    if (known) {
      for (const job of jobs) if (!job.active && known.get(job.id) !== false) announce(job);
    }
    known = new Map(jobs.map((j) => [j.id, j.active]));
  } catch {
    // signed out or the server restarting: the next poll tries again
  }
}

export function startWatcher() {
  if (timer) return;
  poll();
  timer = setInterval(poll, POLL_MS);
}

export function stopWatcher() {
  clearInterval(timer);
  timer = null;
  known = null;
}

/** The top-bar toggle. Disabled where the browser cannot notify (no https and not localhost). */
export function noticeToggle() {
  const box = h("input", { type: "checkbox" });
  const toggle = h("label", { class: "notify-toggle", title: "Notificación del navegador cuando una ejecución termina o falla (con la consola abierta)." },
    box, "Avisarme al terminar");
  if (!supported()) {
    box.disabled = true;
    toggle.title = "Este navegador no puede avisar aquí: hace falta https o localhost (por ejemplo, el túnel SSH).";
    return toggle;
  }
  box.checked = on();
  box.addEventListener("change", async () => {
    if (box.checked && Notification.permission === "default") await Notification.requestPermission();
    box.checked = box.checked && Notification.permission === "granted";
    remember(box.checked);
    if (!box.checked && Notification.permission === "denied") {
      toggle.title = "El navegador bloqueó los avisos de esta página: permítelos en la configuración del sitio.";
    }
    poll(); // start (or stop) watching right away
  });
  return toggle;
}
```

- [ ] **Step 4: Barra superior: búsqueda y avisos**

En `plugins/ghost_recon/console/static/app.js`, sustituye:

```js
import { api, setCsrf } from "./lib/api.js";
import { h, mount } from "./lib/dom.js";
import * as caseView from "./views/case.js";
```

por:

```js
import { api, setCsrf } from "./lib/api.js";
import { h, mount } from "./lib/dom.js";
import { noticeToggle, startWatcher, stopWatcher } from "./lib/notices.js";
import * as caseView from "./views/case.js";
```

y sustituye:

```js
import * as login from "./views/login.js";
import * as system from "./views/system.js";
```

por:

```js
import * as login from "./views/login.js";
import { searchBox } from "./views/search.js";
import * as system from "./views/system.js";
```

y sustituye:

```js
function signedOut(notice) {
  state.user = null;
  state.notice = notice || null;
  setCsrf(null);
```

por:

```js
function signedOut(notice) {
  state.user = null;
  state.notice = notice || null;
  setCsrf(null);
  stopWatcher();
```

y sustituye:

```js
      h("a", { class: "brand", href: "#/", "aria-label": "Ghost Recon, inicio" }),
      h("input", { class: "search", type: "search", placeholder: "Buscar entre casos", disabled: true, title: "Próximamente", "aria-label": "Buscar entre casos" }),
      admin ? h("a", { class: "btn", href: "#/new" }, "+ Nueva auditoría")
        : h("button", { class: "btn", disabled: true, title: "Solo los administradores lanzan auditorías." }, "+ Nueva auditoría"),
      h("span", { class: "who" }, `${state.user.username} · ${state.user.role}`),
      h("button", { class: "btn ghost small", onclick: logout }, "Salir")),
```

por:

```js
      h("a", { class: "brand", href: "#/", "aria-label": "Ghost Recon, inicio" }),
      searchBox(),
      admin ? h("a", { class: "btn", href: "#/new" }, "+ Nueva auditoría")
        : h("button", { class: "btn", disabled: true, title: "Solo los administradores lanzan auditorías." }, "+ Nueva auditoría"),
      h("span", { class: "who" }, `${state.user.username} · ${state.user.role}`),
      noticeToggle(),
      h("button", { class: "btn ghost small", onclick: logout }, "Salir")),
```

y sustituye:

```js
  const { root, main } = shell(route.nav);
  mount(app, root);
```

por:

```js
  const { root, main } = shell(route.nav);
  mount(app, root);
  startWatcher(); // job-end notices while the console is open (no-op until the operator opts in)
```

- [ ] **Step 5: Botón «Exportar resultados (.zip)» del caso**

En `plugins/ghost_recon/console/static/views/case.js`, sustituye:

```js
import * as timeline from "./case/timeline.js";
import { openLaunchDialog } from "./launch.js";
```

por:

```js
import * as timeline from "./case/timeline.js";
import { openExportDialog } from "./export.js";
import { openLaunchDialog } from "./launch.js";
```

y sustituye:

```js
  const verify = h("button", { class: "btn ghost", disabled: s.sealed_count === 0 }, "Verificar sellos");
  verify.addEventListener("click", () => verifySeals(detail, verify));
```

por:

```js
  const verify = h("button", { class: "btn ghost", disabled: s.sealed_count === 0 }, "Verificar sellos");
  verify.addEventListener("click", () => verifySeals(detail, verify));
  const exportZip = h("button", { class: "btn ghost", type: "button" }, "Exportar resultados (.zip)");
  exportZip.addEventListener("click", () => openExportDialog({ caseId: c.id, caseName: c.name, audits: detail.audits, user }));
```

y sustituye:

```js
        verify,
        h("button", { class: "btn ghost", disabled: true, title: "Próximamente" }, "Exportar resultados (.zip)"))),
```

por:

```js
        verify,
        exportZip)),
```

- [ ] **Step 6: «ZIP de A0n» en cada auditoría**

En `plugins/ghost_recon/console/static/views/case/audits.js`, sustituye:

```js
import { dataTable, downloadButton, toggleDetail } from "../components.js";
```

por:

```js
import { dataTable, downloadButton, toggleDetail } from "../components.js";
import { openExportDialog } from "../export.js";
```

y sustituye:

```js
async function auditDetail(caseId, audit, user) {
  const base = `/cases/${encodeURIComponent(caseId)}/audits/${audit.seq}`;
  const [d, reports] = await Promise.all([api(base), api(`${base}/reports`)]);
  const canDownload = audit.status === "sealed" || user.role === "admin";
  const broken = d.seal_check && !d.seal_check.ok ? d.seal_check.detail : null;
  return h("div", { class: "detail" },
```

por:

```js
function auditZip(detail, audit, user) {
  const blocked = audit.status !== "sealed" && user.role !== "admin"
    ? "Solo se exportan auditorías selladas; un admin puede incluir las abiertas como borrador." : null;
  const button = h("button", { class: "btn ghost small", type: "button", disabled: Boolean(blocked), title: blocked },
    `ZIP de ${audit.seq}`);
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    openExportDialog({ caseId: detail.case.id, caseName: detail.case.name, audits: detail.audits, user, seq: audit.seq });
  });
  return button;
}

async function auditDetail(detail, audit, user) {
  const base = `/cases/${encodeURIComponent(detail.case.id)}/audits/${audit.seq}`;
  const [d, reports] = await Promise.all([api(base), api(`${base}/reports`)]);
  const canDownload = audit.status === "sealed" || user.role === "admin";
  const broken = d.seal_check && !d.seal_check.ok ? d.seal_check.detail : null;
  return h("div", { class: "detail" },
    h("div", { class: "actions" }, auditZip(detail, audit, user)),
```

y sustituye:

```js
export async function render({ caseId, detail, user }) {
```

por:

```js
export async function render({ detail, user }) {
```

y sustituye:

```js
  ], detail.audits, { empty: "Sin auditorías.", onRow: (a, tr) => toggleDetail(tr, () => auditDetail(caseId, a, user)) }));
```

por:

```js
  ], detail.audits, { empty: "Sin auditorías.", onRow: (a, tr) => toggleDetail(tr, () => auditDetail(detail, a, user)) }));
```

- [ ] **Step 7: «Exportar resultados (.zip)» al terminar una ejecución**

En `plugins/ghost_recon/console/static/views/job.js`, sustituye:

```js
import { copyButton, kpi } from "./components.js";
```

por:

```js
import { copyButton, kpi } from "./components.js";
import { openExportDialog } from "./export.js";
```

y sustituye:

```js
function outcome(job) {
  if (job.active) return null;
  const a = job.last_audit;
```

por:

```js
function exportPackage(job, user) {
  if (!job.case_id) return "—";
  const button = h("button", { class: "btn ghost small", type: "button" }, "Exportar resultados (.zip)");
  const note = h("span", { class: "download-note", role: "status" });
  button.addEventListener("click", async () => {
    try {
      const detail = await api(`/cases/${encodeURIComponent(job.case_id)}`);
      openExportDialog({ caseId: job.case_id, caseName: detail.case.name, audits: detail.audits, user });
    } catch (err) {
      note.textContent = err.message;
      note.classList.add("error");
    }
  });
  return [button, note];
}

function outcome(job, user) {
  if (job.active) return null;
  const a = job.last_audit;
```

y sustituye:

```js
      h("dt", {}, "Paquete de resultados"), h("dd", {},
        h("button", { class: "btn ghost small", type: "button", disabled: true, title: "Próximamente" }, "Exportar resultados (.zip)")),
```

por:

```js
      h("dt", {}, "Paquete de resultados"), h("dd", {}, exportPackage(job, user)),
```

y sustituye:

```js
    mount(result, outcome(job));
```

por:

```js
    mount(result, outcome(job, user));
```

- [ ] **Step 8: Estilos**

Añade al final de `plugins/ghost_recon/console/static/app.css`:

```css

/* top-bar search, job-end notices and the export dialog */
.search-wrap { position: relative; flex: 1; max-width: 520px; }
.search-wrap .search { width: 100%; max-width: none; }
.search-panel { position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 20; max-height: 70vh;
  overflow-y: auto; padding: 8px 12px; background: var(--gr-surface); color: var(--gr-text);
  border: 1px solid var(--gr-border); border-radius: var(--gr-radius); box-shadow: 0 8px 24px rgba(16, 24, 38, .18); }
.search-group h3 { margin: 6px 0 4px; font-size: 12px; color: var(--gr-muted); text-transform: uppercase; letter-spacing: .04em; }
.search-group ul { list-style: none; margin: 0 0 6px; padding: 0; }
.search-group li { display: flex; flex-direction: column; gap: 1px; padding: 5px 0; border-bottom: 1px solid var(--gr-row-border); }
.search-group li small { word-break: break-all; }
.notify-toggle { display: inline-flex; align-items: center; gap: 5px; color: var(--gr-sidebar-text); font-size: 12.5px;
  white-space: nowrap; cursor: pointer; }
label.check { display: flex; align-items: center; gap: 8px; margin: 4px 0 10px; }
.plan { margin: 0 0 8px; padding-left: 20px; }
.plan li { margin: 3px 0; }
.export-done { padding: 10px 12px; border-radius: var(--gr-radius); background: var(--gr-ok-bg); margin: 8px 0; }
.export-done .mono { color: var(--gr-text); }
progress { width: 100%; height: 10px; }
@media (max-width: 900px) {
  .search-wrap { order: 5; flex-basis: 100%; max-width: none; }
}
```

- [ ] **Step 9: Regresión, sintaxis y barrido de textos**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon/console -q`
Expected: `0 failed`.

Si Node está instalado, repite la comprobación de sintaxis de la Tarea 10, Step 11 (sin salida).

Run: `grep -rnE "Próximamente|Disponible en|disponible en|\bH[1-4]\b|/new-open-case|/rerun-case|/review-case|desde la consola en" plugins/ghost_recon/console/static`
Expected: sin salida.

- [ ] **Step 10: Smoke en el navegador** (o con Playwright MCP)

Lanza la demo (Tarea 10, Step 11), entra como `demo` y comprueba:
- [ ] la barra superior muestra la búsqueda (activa) y «Avisarme al terminar»; escribir «extracto» lista «EVIDENCIA» con las rutas de `Bancos/…`; «EXC-01» lista el hallazgo con su caso y lleva a `#/cases/<id>/findings`; Esc cierra; «a» (un carácter) no busca;
- [ ] en Acme, «Exportar resultados (.zip)» abre el diálogo: «Entra en el ZIP: A01 · sellada…» y «Queda fuera: A02: está abierta (sin sellar)…»; marcar «Incluir auditorías abiertas» pasa A02 a «BORRADOR: sin sellar»;
- [ ] «Exportar» muestra «Empaquetando: n de m archivos» y luego «Listo: GhostRecon_<slug>_case-DRAFT_<fecha>.zip · … · m archivos» con el SHA-256; «Descargar .zip» guarda un archivo cuyo `sha256sum` coincide con el mostrado; «Descargar .sha256» y «Copiar SHA-256» funcionan; la Cronología del caso tiene `results_exported` con `demo` como actor;
- [ ] con un entregable de A01 alterado en disco, «Exportar» termina en «El sello de A01 está roto: 06_Report/… (modificado). No se exportó nada.» y el botón vuelve a quedar activo;
- [ ] al desplegar A01 en Auditorías aparece «ZIP de A01», que abre el diálogo con «Solo A01» elegido; la vista de una Ejecución terminada tiene «Exportar resultados (.zip)»;
- [ ] avisos: con el permiso concedido (en Playwright, sustituye `window.Notification` por una clase que registre las llamadas y tenga `permission = "granted"`), activa «Avisarme al terminar» y lanza un Re-run de «Logística Norte»: a los ~10 s de terminar (más hasta 15 s de consulta) llega «Ghost Recon · ejecución #n terminó» con «Re-run · Logística Norte»;
- [ ] como `visor` / `visor-pass-123`: el diálogo no tiene la casilla de auditorías abiertas, «ZIP de A02» está deshabilitado con su motivo, y CSV/XLSX y la búsqueda funcionan;
- [ ] la consola del navegador no muestra errores de CSP ni de JS (los 4xx/5xx provocados salen como «Failed to load resource»: son esperados).

Detén la demo con Ctrl+C.

- [ ] **Step 11: Commit**

```bash
git add plugins/ghost_recon/console/static
git commit -m "feat(ghost-recon): console export dialog, top-bar search and job-end browser notices

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 12: Documentación, verificación completa y PR

**Files:**
- Modify: `plugins/ghost_recon/plugin.yaml` (`config_schema.console`)
- Modify: `ghost-recon/COMMANDS.md` (§3b)
- Modify: `ghost-recon/README.md` (fila de la consola)
- Modify: `ghost-recon/AGENTS.md` (reglas y «Dónde está cada cosa»)
- Modify: `ghost-recon/PLAN.md` (Fase 8 y registro de cambios)
- Modify: `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (lo que H3 refinó)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: documentación coherente con el código, H3 marcado en `PLAN.md` (con sus pendientes de H1) y un PR integrado a `main`.

- [ ] **Step 1: `plugin.yaml`**

En `plugins/ghost_recon/plugin.yaml`, sustituye:

```yaml
    description: "Consola web (hermes ghostrecon serve): host, port, session_idle_hours, session_max_days, allowed_hosts, case_roots (carpetas de evidencia visibles; obligatoria para lanzar), max_parallel_jobs (por defecto 2), dashboard_url (enlace «Continuar en chat»). Ver ghost-recon/COMMANDS.md §3b."
```

por:

```yaml
    description: "Consola web (hermes ghostrecon serve): host, port, session_idle_hours, session_max_days, allowed_hosts, case_roots (carpetas de evidencia visibles; obligatoria para lanzar), max_parallel_jobs (por defecto 2), dashboard_url (enlace «Continuar en chat»), notify_target (destino de hermes send al terminar una ejecución; vacío = sin aviso), export_include_unsealed (por defecto false; solo admins), export_retention ({count: 20, days: 30}: ZIP y archivos de ejecuciones). Ver ghost-recon/COMMANDS.md §3b."
```

- [ ] **Step 2: `COMMANDS.md` §3b**

En `ghost-recon/COMMANDS.md`, sustituye:

```markdown
- Roles: `viewer` lee, sigue las ejecuciones y descarga entregables de auditorías selladas; `admin` además lanza y cancela ejecuciones, descarga entregables de auditorías abiertas, gestiona usuarios y tokens y ve el registro de la consola. Nadie se deshabilita ni se cambia el rol a sí mismo, y el último admin activo no se puede deshabilitar ni degradar; esa comprobación está serializada, así que dos admins que actúan a la vez el uno sobre el otro nunca dejan cero admins.
```

por:

```markdown
- Roles: `viewer` lee, sigue las ejecuciones, busca entre casos, descarga entregables de auditorías selladas, exporta tablas (CSV/XLSX) y exporta el `.zip` de las auditorías selladas; `admin` además lanza y cancela ejecuciones, descarga entregables de auditorías abiertas, incluye auditorías abiertas (como borrador) en un `.zip`, gestiona usuarios y tokens y ve el registro de la consola. Nadie se deshabilita ni se cambia el rol a sí mismo, y el último admin activo no se puede deshabilitar ni degradar; esa comprobación está serializada, así que dos admins que actúan a la vez el uno sobre el otro nunca dejan cero admins.
```

y, al final del bloque «Ejecuciones desde la consola» (su última línea es la de los archivos de cada ejecución), sustituye:

```markdown
  - archivos de cada ejecución en `<plugin-data>/ghost-recon/console/jobs/`: `<id>.jsonl` (salida del agente), `<id>.log` (errores del agente), `<id>.events.jsonl` (actividad), `<id>.runner.log` y `<id>/` (directorio de trabajo del agente).
```

por:

```markdown
  - archivos de cada ejecución en `<plugin-data>/ghost-recon/console/jobs/`: `<id>.jsonl` (salida del agente), `<id>.log` (errores del agente), `<id>.events.jsonl` (actividad), `<id>.runner.log` y `<id>/` (directorio de trabajo del agente).
- **Exportar resultados (.zip)** (encabezado del caso, «ZIP de A0n» en cada auditoría y el resultado de una ejecución):
  - el diálogo muestra antes qué entra y qué queda fuera y por qué; por defecto solo auditorías **selladas**; un admin puede incluir las abiertas, que salen marcadas `DRAFT` (y el nombre del ZIP lleva `-DRAFT`); mientras el caso tiene una ejecución en cola o en curso, sus auditorías abiertas nunca entran;
  - el ZIP lleva `case.json`, `corpus_inventory.csv`, `_console/`, las carpetas completas de las auditorías elegidas (las revisiones incluidas) y `EXPORT_MANIFEST.json` (cada archivo con su tamaño y SHA-256; cada auditoría con su sello y la hora de la verificación). Nunca la evidencia original: solo se lee la carpeta de resultados, los enlaces simbólicos y las uniones NTFS no se siguen (quedan listados en `skipped`) y una carpeta de resultados que contenga la del caso se rechaza;
  - antes de empaquetar se verifican todos los sellos y, al empaquetar, cada archivo sellado se vuelve a hashear: un sello roto o un archivo que cambia durante la exportación la detiene y nombra el archivo, sin dejar ZIP;
  - se construye en segundo plano, una exportación a la vez, con progreso por archivos y ZIP64; queda en `<plugin-data>/ghost-recon/console/exports/GhostRecon_<slug>_<case|A0n>_<YYYYMMDD-HHMM>.zip` (hora UTC) con `<zip>.sha256` al lado. Comprobación al recibirlo: `sha256sum -c GhostRecon_….zip.sha256` (en Windows, `Get-FileHash -Algorithm SHA256`);
  - un reinicio de la consola durante una construcción la deja «fallida» (hay que volver a exportar); se conservan como mucho las últimas `export_retention.count` (20) y ninguna con más de `export_retention.days` (30) días;
  - cada exportación queda en el registro de la consola (`export_request`, `export` o `export_failed`, `export_download`) y en la Cronología del caso (`results_exported`, con el SHA-256 del ZIP y el usuario).
- **Tablas a CSV/XLSX:** Hallazgos, Evidencia, Cronología y Criterios descargan lo que muestra la tabla con sus filtros (la Evidencia completa, no solo la página cargada). El CSV va en UTF-8 con BOM, separado por comas: un Excel en español puede abrirlo en una sola columna; en ese caso usa el XLSX o «Datos › Desde texto». Un texto que empieza por `=`, `+`, `-` o `@` sale con un apóstrofo delante para que nunca se ejecute como fórmula. El XLSX lleva los metadatos «Ghost Recon» del pack y necesita `openpyxl` (dependencia del plugin); sin él la consola responde «Falta openpyxl…» y el CSV sigue disponible.
- **Búsqueda entre casos** (barra superior): casos por nombre, ID o carpeta; hallazgos por ID, título o contraparte; evidencia por ruta, nombre o hash; criterios por ID, texto o autor. Cada resultado lleva a la pestaña del caso. Mínimo 2 caracteres, como mucho 10 resultados por tipo y 2 s de recorrido. En **Casos**, el filtro «Riesgo abierto» deja los casos con hallazgos abiertos de ese riesgo.
- **Avisos al terminar una ejecución:**
  - en el navegador: «Avisarme al terminar» (barra superior) más el permiso del navegador, mientras la consola está abierta. Los navegadores solo notifican en `https` o en `localhost`: por eso funciona a través del túnel SSH (`http://localhost:9230`) y no por una IP de Tailscale sin TLS;
  - por gateway: con `notify_target` configurado, el runner ejecuta `hermes -p <perfil> send --to <notify_target> --subject "[Ghost Recon]" "<resumen>"` cuando la ejecución termina o falla (no si se cancela o queda interrumpida). No usa LLM ni necesita el gateway en marcha; un fallo del envío queda en `<id>.runner.log` y nunca cambia el estado de la ejecución.
- **Descargas comprobadas:** el entregable de una auditoría sellada se vuelve a hashear al descargarlo y debe coincidir con `SEALED.json` y con el hash del pack; si no, la consola responde «El entregable no coincide con el sello…» (409 `hash_mismatch`). Toda descarga rechazada queda en el registro como `report_download_denied`.
- **Mantenimiento:** al arrancar y cada hora la consola borra las sesiones vencidas o revocadas, los ZIP fuera de retención y los archivos de las ejecuciones terminadas hace más de `export_retention.days` días (las filas de esas ejecuciones, con su resultado y sus tokens, se conservan).
```

y sustituye:

```markdown
          dashboard_url: http://127.0.0.1:9119               # opcional: «Continuar en chat»
          # además: host, port, session_idle_hours, session_max_days, allowed_hosts
```

por:

```markdown
          dashboard_url: http://127.0.0.1:9119               # opcional: «Continuar en chat»
          notify_target: telegram                            # opcional: hermes send al terminar ("" = sin aviso)
          export_include_unsealed: false                     # valor inicial de la casilla (solo admins)
          export_retention: {count: 20, days: 30}            # ZIP y archivos de ejecuciones antiguos
          # además: host, port, session_idle_hours, session_max_days, allowed_hosts
```

y sustituye:

```markdown
- Diseño completo y próximos hitos (exportación `.zip`, tablas CSV/XLSX, búsqueda entre casos, avisos): `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`.
```

por:

```markdown
- Diseño completo y próximo hito (instaladores con `--console` y servicio, `CONSOLE.md`, aceptación en la máquina dedicada): `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`.
```

- [ ] **Step 3: `README.md`**

En `ghost-recon/README.md`, sustituye:

```markdown
| Operar desde el navegador (consola web): lanzar auditorías, seguirlas en vivo y consultar casos | `case_roots` en `config.yaml`, `hermes ghostrecon user add <nombre> --role admin` y `hermes ghostrecon serve` → `http://localhost:9230` (por túnel desde otra PC) · [`COMMANDS.md`](COMMANDS.md) §3b · demo: `python ghost-recon/demo/console_demo.py` |
```

por:

```markdown
| Operar desde el navegador (consola web): lanzar auditorías, seguirlas en vivo, consultar y buscar casos, exportar tablas y el `.zip` verificable de resultados | `case_roots` en `config.yaml`, `hermes ghostrecon user add <nombre> --role admin` y `hermes ghostrecon serve` → `http://localhost:9230` (por túnel desde otra PC) · [`COMMANDS.md`](COMMANDS.md) §3b · demo: `python ghost-recon/demo/console_demo.py` |
```

- [ ] **Step 4: `AGENTS.md`**

En `ghost-recon/AGENTS.md`, sustituye:

```markdown
- La consola (`plugins/ghost_recon/console/`) **solo escribe** sus tablas `console_*`, el archivo de contexto combinado
  (`<resultados>/_console/context_<hash>.md`) y los eventos `console_job_*` de la cronología del caso (con
  `Store.add_event`); los datos de caso se leen por `core` (`Store`, `service`). Toda carpeta que llega del navegador
  pasa por `console/fsjail.resolve` (dentro de `case_roots`) y toda descarga por `console/paths.resolve_within`. En el
  frontend, nada de `innerHTML` con datos: siempre `h()` (`static/lib/dom.js`).
```

por:

```markdown
- La consola (`plugins/ghost_recon/console/`) **solo escribe** sus tablas `console_*`, el archivo de contexto combinado
  (`<resultados>/_console/context_<hash>.md`), los eventos `console_job_*` y `results_exported` de la cronología del
  caso (con `Store.add_event`) y, bajo `<plugin-data>/ghost-recon/console/`, los ZIP de `exports/` (más su `.sha256`) y
  los archivos de `jobs/`; `housekeeping.py` es el único sitio que los borra. Los datos de caso se leen por `core`
  (`Store`, `service`). Toda carpeta que llega del navegador pasa por `console/fsjail.resolve` (dentro de `case_roots`) y
  toda descarga por `console/paths.resolve_within`. En el frontend, nada de `innerHTML` con datos: siempre `h()`
  (`static/lib/dom.js`).
- Un archivo de una auditoría sellada solo sale de la consola tras `console/integrity.py` (descarga de entregables y ZIP):
  se vuelve a hashear contra `SEALED.json`. El ZIP solo lee la carpeta de resultados y nunca sigue enlaces.
- La raíz del repositorio ignora `export*`; `plugins/ghost_recon/console/.gitignore` los reincluye. Un módulo nuevo de la
  consola cuyo nombre empiece por `export` no necesita nada más.
```

y añade al final de la tabla de «Dónde está cada cosa» (después de la fila de `case_roots`), es decir, sustituye:

```markdown
| cambiar qué carpetas ve el navegador de la consola | `console/fsjail.py` y `case_roots` en la configuración |
```

por:

```markdown
| cambiar qué carpetas ve el navegador de la consola | `console/fsjail.py` y `case_roots` en la configuración |
| cambiar qué entra en el ZIP de resultados o su manifiesto | `console/exporter.py` (`select`, `plan_entries`, `build`); la cola y las filas en `console/exports.py` |
| cambiar las columnas o los formatos de las tablas exportables | `console/tables.py` (`TABLES`, `to_csv`, `to_xlsx`); las filas en `console/readmodel.py` (`TABLE_ROWS`) |
| cambiar la búsqueda entre casos | `console/search.py` (`SOURCES`, límites) |
| cambiar el aviso al terminar una ejecución | `console/commands.py` (`notify_args`) y `console/job_runner.py` (`notify_message`, `_notify`) |
| cambiar la limpieza periódica (sesiones, ZIP, archivos de ejecuciones) | `console/housekeeping.py` |
```

- [ ] **Step 5: `PLAN.md`**

En `ghost-recon/PLAN.md`, sustituye:

```markdown
- [ ] H3 · Exportación `.zip` verificable, tablas CSV/XLSX, búsqueda entre casos, avisos, verificación de hash al descargar entregables de auditorías selladas (409 `hash_mismatch`, registro de descargas denegadas)
  - Pendientes de la revisión final de H1 que no entraron en H2:
    - lock en la contabilidad del bloqueo de login
    - `touch_session` best-effort y cabeceras de seguridad en los 500
    - prueba E2E real con `HERMES_HOME` temporal + `config.yaml`
    - purga de sesiones vencidas
```

por:

```markdown
- [x] H3 · Exportación `.zip` verificable, tablas CSV/XLSX, búsqueda entre casos, avisos, verificación de hash al descargar entregables de auditorías selladas (409 `hash_mismatch`, registro de descargas denegadas)
  - [x] ZIP en segundo plano (ZIP64, progreso, `EXPORT_MANIFEST.json`, `.sha256`, retención), solo selladas salvo borrador de un admin, nunca la evidencia ni una auditoría con ejecución activa, sello roto o cambiado durante la construcción → bloqueo con el archivo nombrado
  - [x] tablas CSV (UTF-8 con BOM, sin fórmulas) y XLSX (metadatos Ghost Recon; 503 claro sin openpyxl) con los filtros activos
  - [x] búsqueda entre casos, filtro «riesgo abierto», «verificado hace X»; avisos del navegador y `hermes send` a `notify_target`
  - Pendientes de la revisión final de H1 que no entraron en H2:
    - [x] lock en la contabilidad del bloqueo de login
    - [x] `touch_session` best-effort y cabeceras de seguridad en los 500
    - [x] prueba E2E real con `HERMES_HOME` temporal + `config.yaml`
    - [x] purga de sesiones vencidas
  - [x] Seguimientos de la revisión de H2: retención de archivos de ejecuciones, SSE que revalida al usuario, despacho que sobrevive a un runner que no arranca, asistente con vuelta a las carpetas de casos
```

y añade al final de la sección «## 4. Registro de cambios de este plan» (detrás de la entrada v1.4, que termina en «servidor real. Sin cambios al core de Hermes.»), es decir, sustituye:

```markdown
servidor real. Sin cambios al core de Hermes.
```

por:

```markdown
servidor real. Sin cambios al core de Hermes.
- 2026-10-04 · v1.5 · H3 de la consola implementado: exportación `.zip` verificable de un caso o una auditoría (manifiesto con SHA-256 por archivo, `.sha256`, solo selladas salvo borrador de un admin, sin evidencia ni enlaces, sellos verificados antes y durante el empaquetado), tablas CSV/XLSX con los filtros activos, búsqueda entre casos, filtro «riesgo abierto», avisos del navegador y `hermes send`, descarga de entregables comprobada contra el sello, esquema v3 de `console_*` y los pendientes de H1/H2 (bloqueo con candado, 500 con cabeceras, purga de sesiones, E2E en un `HERMES_HOME` real). Sin cambios al core de Hermes.
```

- [ ] **Step 6: Spec (lo que H3 refinó)**

En `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md` (cada cambio es una sustitución exacta), sustituye:

```text
├── exporter.py       ZIP de resultados + EXPORT_MANIFEST.json; tablas CSV/XLSX
├── search.py         búsqueda entre casos
```

por:

```text
├── exporter.py       ZIP de resultados: selección, verificación de sellos, empaquetado y EXPORT_MANIFEST.json
├── exports.py        ExportService: cola y construcción en segundo plano, filas console_exports, recuperación
├── tables.py         tablas del caso a CSV (UTF-8 con BOM) y XLSX
├── integrity.py      archivo frente a sello (SEALED.json + hash del pack); caché de verificaciones
├── downloads.py      respuestas de adjunto
├── housekeeping.py   limpieza periódica: sesiones, ZIP vencidos, archivos de ejecuciones antiguas
├── search.py         búsqueda entre casos
```

y sustituye:

```text
                   result_text, tokens JSON, error, phase (última fase deducida), notify_target
console_seal_checks  audit_id PK, ok (0/1), checked_at, checked_by, detail JSON
```

por:

```text
                   result_text, tokens JSON, error, phase (última fase deducida), notify_target,
                   notify_argv JSON (el `hermes send` que el servidor planifica al lanzar)
console_seal_checks  audit_id PK, ok (0/1), checked_at, checked_by, detail JSON
console_exports    id PK, case_id, scope (case|audit), seq, include_unsealed (0/1),
                   status (queued|building|succeeded|failed|expired), files_total, files_done, size, sha256,
                   file_name, error, detail JSON, created_by, created_at, started_at, finished_at
```

y sustituye:

```text
(v1 = tablas de H1, v2 = `console_jobs`).
```

por:

```text
(v1 = tablas de H1, v2 = `console_jobs`, v3 = `console_exports` y `console_jobs.notify_argv`). Las migraciones corren bajo `BEGIN IMMEDIATE` tras releer la versión: el servidor, sus runners y el CLI pueden abrir la BD a la vez sin repetir un `ALTER TABLE`.
```

y sustituye:

```text
| Casos | `GET /cases?q=&status=`, `GET /cases/{id}`, `…/timeline`, `…/findings?kind=&risk=&status=&q=`, `…/findings/{fid}`, `…/evidence?status=&audit=&q=`, `…/evidence/stats`, `…/criteria`, `…/research`, `…/jobs` | viewer |
```

por:

```text
| Casos | `GET /cases?q=&status=&risk=` (`risk` ∈ `any`, `critical`, `high`, `medium`, `low`: con hallazgos abiertos de ese riesgo), `GET /cases/{id}`, `…/timeline`, `…/findings?kind=&risk=&status=&q=`, `…/findings/{fid}`, `…/evidence?status=&audit=&q=`, `…/evidence/stats`, `…/criteria`, `…/research`, `…/jobs` | viewer |
```

y sustituye:

```text
| Exportación | `POST /cases/{id}/export` (`{scope: case\|audit, seq?, include_unsealed?}`) → 202 + `export_id`, `GET /exports/{eid}` (estado, tamaño, sha256), `GET /exports/{eid}/download`; `GET /cases/{id}/{table}.csv\|.xlsx?<filtros>` para `table ∈ {findings, evidence, timeline, criteria}` | viewer (exportar con `include_unsealed=true`: **admin**) |
```

por:

```text
| Exportación | `GET /cases/{id}/export/preview?scope=&seq=&include_unsealed=` (qué entra y qué queda fuera, sin construir), `POST /cases/{id}/export` (`{scope: case\|audit, seq?, include_unsealed?}`) → 202 + `export_id`, `GET /exports/{eid}` (estado, progreso, tamaño, sha256), `GET /exports/{eid}/download`, `GET /exports/{eid}/sha256`; `GET /cases/{id}/{table}.csv\|.xlsx?<filtros>` para `table ∈ {findings, evidence, timeline, criteria}` | viewer (exportar con `include_unsealed=true`: **admin**) |
```

y sustituye:

```text
- **Alcance:** el caso completo o una auditoría (A0n o R0n). Por defecto solo auditorías **selladas**. `include_unsealed=true` (solo admin) añade las abiertas, marcadas `DRAFT` en el manifiesto. Una auditoría con un job en curso nunca se incluye.
```

por:

```text
- **Alcance:** el caso completo o una auditoría (A0n o R0n). Por defecto solo auditorías **selladas**. `include_unsealed=true` (solo admin; sin indicarlo vale `export_include_unsealed`, y solo para admins) añade las abiertas, marcadas `DRAFT` en el manifiesto. Mientras el caso tenga una ejecución en cola o en curso, sus auditorías abiertas nunca se incluyen (una sellada no cambia).
```

y sustituye:

```text
**Nunca** incluye la evidencia original.
```

por:

```text
**Nunca** incluye la evidencia original: solo se lee la carpeta de resultados, los enlaces simbólicos y las uniones NTFS no se siguen (quedan en `skipped` del manifiesto), cada archivo debe resolver dentro de esa carpeta y una carpeta de resultados que contenga la del caso se rechaza.
```

y sustituye:

```text
  - antes de empaquetar se verifica cada sello; un sello roto **bloquea** la exportación y se informa qué archivo cambió;
  - `EXPORT_MANIFEST.json` contiene `{export_id, case_id, scope, audits:[{id, sealed, seal_sha256, verified_at}], files:[{path, size, sha256}], exported_by, exported_at, generator: "Ghost Recon Console <versión>"}`;
  - el SHA-256 del ZIP se calcula al terminar, se muestra en la consola y se guarda junto al ZIP como `.sha256`.
```

por:

```text
  - antes de empaquetar se verifica cada sello (la verificación queda en `console_seal_checks`); un sello roto **bloquea** la exportación y se informa qué archivo cambió. Al empaquetar, cada archivo sellado se vuelve a hashear: un cambio durante la construcción también la detiene. Nunca queda un ZIP a medias (`.part` y renombrado al final);
  - `EXPORT_MANIFEST.json` contiene `{export_id, case_id, case_name, scope, seq, draft, audits:[{id, seq, kind, sealed, state (SEALED|DRAFT), seal_sha256, verified_at}], excluded:[{id, seq, reason}], skipped:[{path, reason}], files:[{path, size, sha256}], exported_by, exported_at, generator: "Ghost Recon Console <versión>"}`;
  - el SHA-256 del ZIP se calcula al terminar, se muestra en la consola y se guarda junto al ZIP como `<zip>.sha256`, en formato `sha256sum -c` (`<hash>  <nombre>`, LF).
```

y sustituye:

```text
- **Nombre y ruta:** `GhostRecon_<slug>_<scope>_<YYYYMMDD-HHMM>.zip` en `plugin_data_dir/ghost-recon/console/exports/`. Las exportaciones grandes se construyen en segundo plano, con ZIP64 y progreso por archivos. Se conservan las últimas 20 o 30 días (configurable).
```

por:

```text
- **Nombre y ruta:** `GhostRecon_<slug>_<scope>_<YYYYMMDD-HHMM>.zip` (hora UTC; `<scope>` es `case` o la secuencia, con `-DRAFT` si lleva auditorías abiertas; si ya existe uno con ese nombre, `_e<export_id>`) en `plugin_data_dir/ghost-recon/console/exports/`. Todas las exportaciones se construyen en segundo plano, una a la vez, con ZIP64 y progreso por archivos; un reinicio de la consola marca como fallidas las que quedaron a medias. Se conservan como mucho las últimas 20 y ninguna de más de 30 días (`export_retention`); la fila queda como `expired`.
```

y sustituye:

```text
- **Tablas:** los CSV salen en UTF-8 con BOM, para que Excel abra bien los acentos. Los XLSX salen con openpyxl y metadatos "Ghost Recon", igual que el pack.
```

por:

```text
- **Tablas:** los CSV salen en UTF-8 con BOM, para que Excel abra bien los acentos; un texto que empieza por `=`, `+`, `-`, `@`, tabulador o retorno de carro (y no es un número) lleva un apóstrofo delante para que nunca se ejecute como fórmula. Los XLSX salen con openpyxl y metadatos "Ghost Recon", igual que el pack; sin openpyxl la consola responde `503 xlsx_unavailable`.
- **Descarga de entregables:** en una auditoría sellada el archivo se vuelve a hashear al descargarlo y debe coincidir con `SEALED.json` y con `reports.sha256`; si no, `409 hash_mismatch`. Toda descarga rechazada queda en `console_audit_log` como `report_download_denied`.
```

y sustituye:

```text
| `export_retention` | `{count: 20, days: 30}` | Limpieza de ZIP antiguos |
```

por:

```text
| `export_retention` | `{count: 20, days: 30}` | Limpieza de ZIP antiguos (como mucho los `count` más recientes y ninguno de más de `days` días) y de los archivos de ejecuciones terminadas hace más de `days` días |
```

y, detrás de la fila R10 (la última de §15), sustituye:

```text
Fijar 100 (fragmento de config, instaladores y comprobación de `/gr-doctor`); hallado en la ejecución R1 |
```

por:

```text
Fijar 100 (fragmento de config, instaladores y comprobación de `/gr-doctor`); hallado en la ejecución R1 |
| R11 | Un Excel en español usa `;` como separador de listas y abre un CSV con comas en una sola columna | El XLSX es el formato recomendado para Excel; documentado en `COMMANDS.md` §3b |
| R12 | Las notificaciones del navegador exigen un contexto seguro (`https` o `localhost`) | Acceso por túnel SSH a `localhost` (C2); el interruptor se deshabilita con el motivo fuera de un contexto seguro |
```

- [ ] **Step 7: Verificación completa**

Run: `bash scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py tests/skills/test_authoring_standards.py tests/skills/test_skill_docs_contract.py tests/hermes_cli/test_plugin_cli_registration.py tests/hermes_cli/test_plugin_api_compat.py -q`
Expected: `0 failed`. Los skipped son solo las pruebas que necesitan `openpyxl`/`reportlab` y las marcadas para otro SO.

Run: `.venv/Scripts/python.exe ghost-recon/demo/smoke_test.py` (o `.venv/bin/python …`)
Expected: `SMOKE TEST OK`. Sin las dependencias opcionales del plugin solo falla el check «pack … without warnings», que no depende de este hito: anótalo en el PR en vez de instalar nada con pip.

Run: `grep -rnE "Próximamente|Disponible en|disponible en|\bH[1-4]\b|/new-open-case|/rerun-case|/review-case|desde la consola en" plugins/ghost_recon/console/static`
Expected: sin salida.

Run: `git status --short --ignored plugins/ghost_recon tests/plugins/ghost_recon ghost-recon | grep '^!!' | grep -v __pycache__`
Expected: sin salida (nada del hito quedó ignorado por el `export*` raíz).

Run: `git diff --stat origin/main...HEAD -- . ':!plugins/ghost_recon' ':!ghost-recon' ':!tests/plugins/ghost_recon'`
Expected: salida vacía (ningún archivo fuera del vertical).

- [ ] **Step 8: Commit de documentación**

```bash
git add plugins/ghost_recon/plugin.yaml ghost-recon
git commit -m "docs(ghost-recon): console H3 exports, tables, search and notices; plan and spec status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Integrar con `main` y abrir el PR**

Antes de abrir el PR, escribe `pr_body.md` en el directorio temporal de la sesión (fuera del repo) con estas secciones:
- **Resumen:** el alcance de H3 (Fase 8 de `PLAN.md`), los pendientes de H1/H2 resueltos y el enlace a la spec y a este plan;
- **Pruebas:** la salida de resumen del Step 7 en cifras reales, `SMOKE TEST OK`, si `openpyxl` estaba en el venv (si no, las pruebas de XLSX salieron como skipped) y el resultado de `test_hermes_home_e2e.py`;
- **Smoke manual:** las casillas marcadas de las Tareas 10 y 11;
- **Despliegue:** `notify_target` (opcional; requiere el gateway configurado para `hermes send`), `export_retention` y la recomendación de XLSX para Excel en español;
- **Alcance:** la salida vacía del `git diff --stat` fuera del vertical;
- al final, la línea `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

```bash
git fetch origin main
git merge --no-edit origin/main          # main avanza a menudo (sincronizaciones con upstream)
bash scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_skill_docs_contract.py -q
git push -u origin ghost-recon-console
gh pr create -R SiteOneTech/agent-ghost-recon-forensic-finance --base main --head ghost-recon-console \
  --title "feat(ghost-recon): console H3 — verifiable ZIP export, CSV/XLSX tables, search and notices" --body-file "$TMPDIR/pr_body.md"
```

Expected: el PR queda abierto con la CI verde.

---
## Autorrevisión del plan (cobertura de la spec)

| Requisito H3 | Dónde |
|---|---|
| §8 Exportación: `POST /cases/{id}/export` → 202 + `export_id`, `GET /exports/{eid}`, `GET /exports/{eid}/download` (más vista previa y `.sha256`) | Tarea 6 (`routers/exports.py`, `test_api_exports.py`) |
| §8 Exportación: `GET /cases/{id}/{table}.csv\|.xlsx` con los filtros de cada tabla | Tarea 4 (`tables.py`, `readmodel.TABLE_ROWS`, `test_tables.py`) |
| §8 Búsqueda `GET /search?q=&types=&limit=` (viewer, acotada) | Tarea 7 (`search.py`, `test_search.py`) |
| §8 «verificado hace X» | Tarea 3 (la verificación cacheada vía `integrity.record_seal_check`, también desde el ZIP) y Tarea 10 (`fmtAgo`, `sealCheckChip`) |
| §9 roles: viewer exporta selladas; `include_unsealed` solo admin (403) | Tarea 6 (`_include_unsealed`, `test_only_an_admin_includes_unsealed_audits_and_they_come_marked_draft`) |
| §9 descargas: evidencia nunca; entregables comprobados (`hash_mismatch`, `report_download_denied`) | Tareas 3 y 5 (`test_download_integrity.py`, `test_the_evidence_never_enters_the_archive`, symlinks/uniones) |
| §9 auditoría: exportaciones en `console_audit_log` y en la cronología | Tarea 6 (`export_request`/`export`/`export_failed`/`export_download`, `results_exported`) |
| §10.3 Casos con filtro «riesgo abierto» | Tareas 7 (API) y 10 (selector) |
| §10.4 tablas exportables con los filtros activos; ZIP propio de cada auditoría | Tareas 10 (`tableExport`) y 11 («ZIP de A0n») |
| §10 barra superior con búsqueda; avisos del navegador | Tarea 11 (`searchBox`, `noticeToggle`, `startWatcher`) |
| §11 alcance, DRAFT, auditoría con ejecución activa, contenido, nunca evidencia | Tarea 5 (`select`, `plan_entries`) y Tarea 6 (`busy`) |
| §11 integridad: sellos antes de empaquetar, archivo nombrado, manifiesto, SHA-256 y `.sha256` | Tarea 5 (`verify_seals`, `_check_sealed`, `build`) |
| §11 nombre, ruta, segundo plano, ZIP64, progreso, retención | Tareas 5 (`zip_name`, `force_zip64`), 6 (`ExportService`, `Housekeeping.prune_exports`) |
| §11 tablas: CSV UTF-8 con BOM; XLSX con metadatos Ghost Recon (503 sin openpyxl) | Tarea 4 |
| §12 `notify_target`, `export_include_unsealed`, `export_retention` | Tarea 1 (ajustes), Tareas 6 y 8 (uso), Tarea 12 (documentación) |
| §13 H3 aceptación: ZIP verifica por hash, sello roto bloquea, evidencia excluida, aviso con `send` falso | Tareas 5 y 6 (hash, bloqueo, exclusión), Tareas 8 y 9 (`send` falso en proceso y con un servidor real) |
| §14 Exportación y Búsqueda | Tareas 4–7 |
| PLAN H3: hash al descargar entregables sellados (409 `hash_mismatch`, descargas denegadas registradas) | Tarea 3 |
| PLAN H1: candado del bloqueo; `touch_session` best-effort y cabeceras en los 500; purga de sesiones; E2E con `HERMES_HOME` real | Tareas 2, 1 + 6 (purga) y 9 |
| Revisión H2: retención de archivos de ejecuciones; SSE que revalida; `_start_runner` robusto; asistente con vuelta | Tareas 6, 2, 8 y 10 |
| Review Focus 1–5 | Tareas 5 (1, 4, 5), 6 (2) y 4 (3) |
| Sin «Próximamente» al terminar | Tarea 11 (barrido) y Tarea 12 (verificación) |
