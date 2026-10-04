# Consola Ghost Recon — diseño

| | |
|---|---|
| Estado | Aprobado en conversación (2-oct-2026), pendiente de revisión de esta spec |
| Autor | Jean C. Garcia (Sitio Uno / Ghost Recon), con Claude Code |
| Alcance | Superficie web propia de Ghost Recon para operar el agente: lanzar `/new-open-case`, `/rerun-case`, `/review-case`, seguirlos en vivo, consultar la BD de casos y exportar los resultados |
| Área | `plugins/ghost_recon/console/` (nuevo), `ghost-recon/` (docs, instaladores). Sin cambios al core de Hermes |

## 1. Objetivo y criterios de éxito

El operador, desde el navegador de su PC, debe poder:

1. elegir una carpeta de evidencia en la máquina dedicada (sin escribir rutas a mano);
2. revisar qué contiene y lanzar la orden correcta con el comando exacto a la vista;
3. seguir la ejecución en vivo mientras el agente audita, aunque cierre el navegador;
4. navegar casos, auditorías, hallazgos, evidencia, criterios, investigación y cronología;
5. descargar el paquete de resultados como `.zip` íntegro y verificable, para llevarlo a mano a la consola que construye los dashboards.

Todo esto sin usar la terminal y sin tocar el core de Hermes.

**Criterio de aceptación global:** el ciclo de `HANDOFF.md §4` se ejecuta íntegro desde la consola en la máquina dedicada, con claves reales: `/new-open-case` sobre el caso demo, luego `/rerun-case` con evidencia nueva, luego `/review-case`, y al final la exportación `.zip` verificada por hash.

## 2. Decisiones (con su porqué)

| # | Decisión | Porqué |
|---|---|---|
| C1 | **Servidor propio** (`hermes ghostrecon serve`), no una pestaña del `hermes dashboard` | El operador quiere tres cosas: un producto con identidad Ghost Recon, una API propia que sirva de base a `ghostrecon-web-app`, y no depender del dashboard. Además prevé más usuarios. El dashboard plugin (opción A del análisis) se descartó por esos motivos, no por viabilidad. |
| C2 | **Escucha en loopback por defecto** (`127.0.0.1:9230`); el acceso remoto se hace por túnel (SSH/Tailscale) | Hay datos financieros de clientes, y así nada queda expuesto en la red. Escuchar en otra interfaz exige `--allow-remote` explícito. |
| C3 | **Login desde el día 1**, con roles `admin` y `viewer` y tokens Bearer | Los otros usuarios y la web app son futuros, pero declarados. Es más barato nacer con identidad que añadirla después. |
| C4 | **Ejecuciones desatendidas**: proceso aparte y separado del servidor, a imagen de los workers de kanban | Una auditoría dura horas y debe sobrevivir al cierre del navegador y al reinicio del servidor. |
| C5 | **Continuidad con el chat**: cada ejecución guarda su `session_id` y la consola ofrece "Continuar en terminal" | Permite conversar con el agente sobre esa auditoría. No hace falta que el dashboard esté arriba. |
| C6 | **El navegador de carpetas solo ve las raíces configuradas** (`case_roots`) | Quien tenga el túnel no debe poder recorrer el disco entero. |
| C7 | **La consola solo lee los datos del caso** y escribe únicamente sus propias tablas, más el archivo de contexto combinado | Ningún número se teclea y las auditorías selladas son inmutables. Los hallazgos los registra el agente con las `gr_*`. |
| C8 | **El contexto del operador es un complemento, no una edición**: el `context.md` original nunca se toca | Así se preserva la procedencia. Lo que escribe el operador es una declaración o criterio (`CRIT-nn`), nunca un hecho. |
| C9 | **Exportación `.zip` de resultados** con manifiesto de hashes; por defecto solo auditorías selladas; nunca la evidencia | El transporte a la consola de dashboards es manual por ahora. El ZIP es la unidad de entrega y mañana irá a un bucket sin rediseño. |
| C10 | **Avisos al terminar**: notificación del navegador, más `hermes send` si se configura un destino | `hermes send` no usa LLM ni necesita el gateway en marcha. El agente no puede enviar mensajes por sí mismo: es una decisión de diseño de Hermes. |
| C11 | **Frontend sin paso de build**: JS en módulos ES + CSS servidos por el propio plugin, sin CDN | La máquina dedicada no necesita Node. Además, ninguna petición sale a terceros (confidencialidad y CSP estricta). La reutilizable es la API, no el frontend. |
| C12 | **La lógica vive en Python**: normalizar eventos, deducir fases, construir el comando, validar | Se prueba con pytest. El JS solo pinta. |
| C13 | **Una consola por perfil de Hermes**: `hermes -p <perfil> ghostrecon serve` | Los perfiles son la unidad de aislamiento (BD, memoria, `.env`). Si en el futuro hay un perfil por cliente, cada uno levanta su consola en su puerto. |
| C14 | **Sin proveedor de memoria externo (Honcho u otro)** en el perfil de Ghost Recon | La memoria de Hermes es una por perfil y no tiene partición por caso, así que mezclaría casos. La "memoria" de Ghost Recon es su BD por caso, determinista y auditable. |

## 3. Alcance

**Dentro (v1):** las cuatro entregas de §13. Son la base técnica, el motor de ejecuciones, el asistente de nueva auditoría con notas de contexto, las vistas de casos, la ejecución en vivo, la exportación `.zip`, las tablas a CSV/XLSX, la búsqueda entre casos, los avisos, el instalador del servicio, la administración de usuarios y tokens desde Sistema (además del CLI) y la documentación.

**Fuera (v1), anotado como posibles iteraciones:**
- editar hallazgos, criterios o casos desde la web (va contra C7);
- subir el ZIP a un bucket;
- programar ejecuciones (cron) desde la consola;
- descargar la evidencia original;
- terminación TLS propia (para eso, túnel o proxy inverso);
- varios perfiles en una sola consola;
- un chat con el agente dentro de la consola: el chat vive en Hermes (C5).

## 4. Arquitectura

```
 PC del operador                      Máquina dedicada (perfil Hermes P)
 ┌──────────────┐  túnel SSH/TS   ┌──────────────────────────────────────────────────────────┐
 │  navegador   │ ───────────────▶│ hermes -p P ghostrecon serve  (uvicorn 127.0.0.1:9230)   │
 └──────────────┘                 │   ├─ /            frontend estático (console/static)     │
                                  │   ├─ /api/v1/...  API (FastAPI, routers por recurso)     │
                                  │   └─ lee: ghostrecon.db (core/Store) · escribe: console_*│
                                  │                    │ lanza (detached)                     │
                                  │                    ▼                                      │
                                  │ python -m plugins.ghost_recon.console.job_runner <job>   │
                                  │   └─ hermes -p P --cli --accept-hooks --skills <skill>    │
                                  │        chat -q "<orden>" --format stream-json --source …  │
                                  │        stdout → jobs/<id>.jsonl · stderr → jobs/<id>.log  │
                                  │   └─ al terminar: estado en console_jobs (+ hermes send)  │
                                  └──────────────────────────────────────────────────────────┘
```

### 4.1 Disposición de archivos

```
plugins/ghost_recon/console/
├── __init__.py
├── app.py            create_app(settings) -> FastAPI: middlewares, routers, estáticos, cabeceras
├── settings.py       lectura de plugins.entries.ghost-recon.settings.console.* con defaults
├── store.py          ConsoleStore: tablas console_* (esquema + migrate) sobre la misma ghostrecon.db
├── auth.py           hash scrypt, sesiones, tokens, dependencia current_principal(role)
├── deps.py             dependencias FastAPI: contexto, principal, roles, ApiError
├── readmodel.py        lecturas puras para la API (resúmenes de caso, filtros, paginación)
├── paths.py            raíz de resultados de un caso y contención de rutas
├── fsjail.py         resolución de rutas dentro de case_roots, listado, búsqueda, inspección previa
├── commands.py       construcción y validación de órdenes (tabla orden → skill/args), contexto combinado
├── jobs.py           JobService: crear, encolar, lanzar, cancelar, huérfanos, límites
├── job_runner.py     proceso desacoplado: ejecuta el agente, persiste salida y estado, notifica
├── procs.py          procesos con Hermes: lanzador de la instalación, entorno del perfil, desacople, árbol (psutil)
├── jobfiles.py       archivos por ejecución (<id>.jsonl, .log, .events.jsonl, .runner.log), lectura incremental
├── events.py         normalización stream-json → eventos de consola + deducción de fases (puro)
├── exporter.py       ZIP de resultados + EXPORT_MANIFEST.json; tablas CSV/XLSX
├── search.py         búsqueda entre casos
├── cli.py            subcomandos serve | user | token (registrados bajo `hermes ghostrecon`)
├── routers/          auth.py system.py fs.py cases.py audits.py jobs.py users.py exports.py search.py
└── static/           index.html, app.js (módulos ES), views/*.js, theme.css (variables), app.css, fonts/
```

`core/` no cambia de contrato. La consola lo usa como librería: `Store`, `service.case_status`, `service.timeline`, `service.completion_report`, `service.verify_audit`, `review.build_chronology` y `casefolder`.

### 4.2 Dependencias

Ninguna nueva. FastAPI y uvicorn ya son dependencias del core de Hermes (`pyproject.toml`). `openpyxl` (export XLSX) ya es `python_dependency` del plugin.

### 4.3 Integración con Hermes

- `hermes ghostrecon serve|user|token` se añaden al CLI que el plugin ya registra con `ctx.register_cli_command("ghostrecon", ...)`.
- Rutas y configuración: `get_hermes_home()` / `plugin_data_dir("ghost-recon")`. Nunca `~/.hermes` literal.
- Procesos hijos:
  - el entorno se construye con `tools/environments/local.py::served_profile_child_env` (regla del `AGENTS.md` raíz), nunca con `os.environ.copy()`;
  - el ejecutable de Hermes se resuelve igual que el despachador de kanban (`hermes_cli/kanban_db_dispatch.py::_resolve_hermes_argv`).
- Desacople del proceso:
  - en POSIX, `start_new_session=True`;
  - en Windows, `hermes_cli/_subprocess_compat.py::windows_detach_flags()`.
- Cancelación: `kill_process_tree` del mismo módulo cuando se tiene el `Popen`, y `psutil` (dependencia del core) cuando solo se tiene el PID guardado en la BD.
- Son rutas internas de Hermes: el plan confirma su firma al empezar cada hito. Si alguna cambia, se adapta la consola; no se añaden shims.

## 5. Modelo de datos (tablas nuevas, misma `ghostrecon.db`)

Todas con prefijo `console_` y gestionadas por `console/store.py` con su propio `migrate()` idempotente. Las tablas de caso no se tocan.

```
console_users      id PK, username UNIQUE, password_hash (scrypt: n,r,p,salt,hash), role (admin|viewer),
                   disabled (0/1), created_at, last_login_at
console_sessions   id PK, user_id FK, token_sha256 UNIQUE, csrf_token, created_at, last_seen_at,
                   expires_at, ip, user_agent, revoked (0/1)
console_tokens     id PK, user_id FK, name, token_sha256 UNIQUE, prefix (8 chars visibles),
                   created_at, last_used_at, revoked (0/1)
console_audit_log  id PK, ts, user_id, username, ip, action (login|login_failed|logout|job_launch|
                   job_cancel|export|user_add|user_disable|token_create|token_revoke|…), target, detail JSON
console_jobs       id PK (int), command (new-open-case|rerun-case|review-case), case_id NULL
                   (se completa al abrir), folder (absoluta), args JSON (validados), argv JSON (la orden
                   exacta que se ejecuta), context_file,
                   status (queued|running|succeeded|failed|cancelled|orphaned), pid, pid_started,
                   runner_pid, runner_started (create time: identidad frente a PID reciclados),
                   session_id, exit_code, launched_by, created_at, started_at, finished_at,
                   result_text, tokens JSON, error, phase (última fase deducida), notify_target
console_seal_checks  audit_id PK, ok (0/1), checked_at, checked_by, detail JSON
```

Sesiones y tokens se guardan solo como SHA-256. El token en claro se muestra una única vez.

`console_schema_version` tiene una sola fila; `migrate()` aplica en orden las migraciones por encima de la versión guardada (v1 = tablas de H1, v2 = `console_jobs`).

caché de la última verificación de sello por auditoría.

## 6. Motor de ejecuciones

### 6.1 Órdenes (tabla, no `if/elif`)

| `command` | Skill precargada | Texto `-q` | Requisitos de validación |
|---|---|---|---|
| `new-open-case` | `new-open-case` | `/new-open-case "<folder>" "<context_file>" [--name "…"] [--currency X] [--lang es\|en] [--out "…"]` | `folder` dentro de `case_roots`. Si la carpeta ya es un caso con una auditoría sellada, el API responde `409` con la sugerencia de usar `rerun-case` (la misma regla que la skill). |
| `rerun-case` | `rerun-case` | `/rerun-case "<folder>" ["<context_file>"] [--out "…"]` | `folder` es un caso conocido (BD o `case.json`). |
| `review-case` | `review-case` | `/review-case "<folder>"`. Con notas: segunda línea `Contexto adicional del operador (declaraciones, no hechos): "<context_file>"` | El caso tiene al menos una auditoría sellada. La skill no tiene argumento de contexto, así que se le pasa como línea adicional; se verifica junto con R1. |

Los argumentos se validan en Python: rutas dentro de `case_roots` y resueltas con `realpath`, moneda ISO-4217 de 3 letras, idioma de una lista, nombre ≤ 120 caracteres sin saltos de línea. El comando se construye como lista de argumentos, sin shell, y `POST /jobs/preview` devuelve exactamente la orden que se ejecutará.

Argv del agente:

```
<hermes> -p <perfil> --cli --accept-hooks --skills <skill> chat -q "<orden>" --format stream-json --source ghost-recon-console
```

- `--format stream-json` implica `--quiet`.
- `--source` etiqueta las sesiones para poder filtrarlas.
- Hay que verificar en el plan que `--source` acepta un valor libre. Si no, se usa el valor por defecto y se registra el `session_id` igualmente.
- **Verificación obligatoria en la máquina real** (riesgo R1): que `--skills <skill>` junto con `-q "<orden>"` ejecuta la skill completa.

### 6.2 Ciclo de vida

```
queued ──(límites ok)──▶ running ──▶ succeeded | failed
   │                        │
   └──(cancelar)──▶ cancelled ◀──(cancelar: mata el árbol de procesos)
running ──(runner muerto sin estado final)──▶ orphaned
```

1. `POST /jobs` valida, escribe el contexto combinado (§7), crea la fila `queued` y llama a `JobService.dispatch()`.
2. `dispatch()` respeta dos límites: **una ejecución activa por caso o carpeta**, y **`max_parallel_jobs` en total** (por defecto 2). Lo que no cabe queda `queued` y se despacha cuando se libera un hueco. El despacho se reevalúa al arrancar el servidor, tras cada lanzamiento o cancelación y cada 10 s (el ciclo también recoge los runners terminados). Repetir la misma orden sobre una carpeta que ya la tiene activa o en cola responde `409 already_active`; una orden distinta queda en cola.
3. El **`job_runner`** es un proceso desacoplado, uno por job. Su trabajo:
   - el servidor registra `runner_pid` y su create time al lanzarlo; el runner confirma `running` (si encuentra la fila cancelada, sale sin lanzar el agente) y ejecuta el argv guardado en la fila, sin reconstruirlo. El runner solo es dueño del job si `runner_pid` es su propio pid o el de su padre (un salto de lanzador, p. ej. el redirector del venv en Windows);
   - lanza el agente con stdout hacia `jobs/<id>.jsonl` y stderr hacia `jobs/<id>.log` (bajo `plugin_data_dir/ghost-recon/console/jobs/`);
   - el directorio de trabajo del agente es `jobs/<id>/`, vacío y propio de la ejecución, nunca la carpeta de evidencia ni la de resultados: Hermes carga `AGENTS.md`/`CLAUDE.md`/`.cursorrules` del directorio de trabajo como instrucciones y resuelve allí las rutas relativas, así que un archivo dejado entre la evidencia nunca manda sobre el agente y una escritura relativa nunca toca la evidencia (la carpeta viaja en el `-q`);
   - lee el `session_id` del evento `system/init`;
   - mientras corre, actualiza `phase` en la BD a partir de los eventos (§6.3);
   - al terminar escribe `exit_code`, `result_text`, `tokens` y `error`, y el estado `succeeded` o `failed`;
   - si hay `notify_target`, ejecuta `hermes -p <perfil> send --to <destino> --subject "[Ghost Recon]" "<resumen>"`;
   - registra el evento en el timeline del caso (`console_job_finished`).
4. **Cancelar** marca `cancelled` y mata el árbol de procesos del runner con `psutil`, a partir del `runner_pid` (§4.3). La auditoría a medio hacer queda abierta, sin sellar. El estado real de la carpeta del caso lo maneja el agente en el siguiente `rerun`.
5. **Huérfanos:** si `runner_pid` ya no existe y la fila sigue `running`, el job pasa a `orphaned`. Se comprueba al arrancar el servidor y en cada ciclo de despacho, y se muestra la cola del log. El agente que quedó sin runner se detiene (árbol completo), para que nunca haya dos agentes sobre la misma carpeta.
6. El servidor nunca es padre necesario del runner. Reiniciarlo no afecta a las ejecuciones en curso, y la consola las reencuentra en la BD.

### 6.3 Eventos y fases (`events.py`, puro)

Entrada: líneas de `stream-json` (`system/init`, `text`, `tool_use{name,input}`, `tool_result{name,output,duration_ms,is_error}`, `result{session_id,exit_code,text,tokens,duration_ms,error}`).

Salida: eventos de consola `{seq, ts, kind, phase?, title, detail?, level}`, donde `kind ∈ {phase, tool_call, tool_result, message, warning, error, result}`.

Las fases se deducen con una tabla:

| Herramienta (y argumento) | Fase |
|---|---|
| `gr_case_open` | Caso |
| `gr_audit_start` / `gr_review_plan` | Auditoría A0n / Revisión R0n |
| `gr_criteria_add`, lectura de `context.md` | Intake |
| `gr_swarm_plan(mode=extraction)`, `delegate_task` posterior | Enjambre (n/m bloques según `tool_result`) |
| `gr_finding_upsert` | Modelo y hallazgos |
| `gr_research` | Investigación |
| `gr_report_build` | Pack |
| `gr_swarm_plan(mode=validation)`, `gr_run_record(kind=validation)` | Validación |
| `gr_audit_seal` | Sello |

- Las `gr_*` se traducen a lenguaje claro a partir de su JSON de salida (p. ej. "Caso GRC-… abierto · 214 archivos · 3 ZIP").
- El resto de herramientas se agrupan ("read_file ×4").
- El texto del agente (`text`) se acumula y solo se muestra como resumen final. **No se reconstruye un chat.**
- Las herramientas de los sub-agentes no viajan en el stream del padre. El progreso del enjambre se deduce de los `tool_result` de `delegate_task` y de las filas `runs` y `findings` de la BD.

### 6.4 Lectura en vivo

`GET /jobs/{id}/events?after=<seq>` lee el `.jsonl` de forma incremental (por desplazamiento), normaliza y devuelve los eventos. `GET /jobs/{id}/events/stream` es SSE sobre lo mismo, sondeando el archivo cada 1 s. Los contadores de "Hasta ahora" salen de la BD del caso (evidencia, hallazgos por tipo, notas de investigación).

## 7. Contexto del operador

- En el paso 3 de "Nueva auditoría" y en los diálogos de Re-run y Review aparecen dos cosas:
  - el `context.md` de la carpeta, si existe (solo lectura, con su SHA-256);
  - un campo **"Notas adicionales"** (Markdown, ≤ 20 000 caracteres).
- Al lanzar, si hay notas, la consola escribe `<salidas>/_console/context_<hash>.md` (12 caracteres del SHA-256 de: hash del original, usuario y notas; el nombre no depende del id del job, así que la vista previa muestra exactamente la orden que se ejecutará). `<salidas>` es `<carpeta>/<audits_dirname>/` o el `--out` indicado; nunca la carpeta de evidencia. El archivo tiene esta forma:

```markdown
# Contexto de la ejecución (<orden>) · consola Ghost Recon
## Contexto original
Fuente: <ruta>/context.md · SHA-256 <hash>      (o "sin context.md en la carpeta")
<contenido literal del original>
## Notas del operador — <usuario>, <fecha UTC>
> Declaraciones del operador: registrar como criterio/declaración (CRIT-nn, autor <usuario>), no como hecho.
<notas>
```

- Ese archivo es el `context_file` que recibe la orden. Si no hay notas, se pasa el `context.md` original tal cual, o nada.
- Si el `context.md` cambia entre la vista previa y el lanzamiento, el lanzamiento responde `409 context_changed`.
- Como vive en la carpeta de resultados del caso, el agente lo referencia desde el manifiesto de la auditoría y queda dentro de lo que se exporta.

## 8. API `/api/v1`

Convenciones:
- JSON; errores `{"error": {"code", "message"}}`; listas `{"items", "next_cursor"}`; fechas ISO-8601 UTC.
- OpenAPI en `/api/v1/openapi.json`, tras el login (sin Swagger UI: cargaría recursos externos, contra la CSP);
- La ruta de auditoría usa el ID de caso y la secuencia corta: `/cases/{case_id}/audits/{seq}` con `seq ∈ A01…, R01…`. El ID completo `<case>/A01` lleva `/`.

| Grupo | Método y ruta | Rol |
|---|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | — |
| Sistema | `GET /system/overview` (indicadores de Inicio y actividad reciente), `GET /system/doctor` (equivalente a `/gr-doctor` + disco libre en las raíces), `GET /system/audit-log` | viewer · viewer · **admin** |
| Carpetas | `GET /fs/roots`, `GET /fs/list?path=`, `GET /fs/search?q=`, `GET /fs/inspect?path=` | viewer |
| Casos | `GET /cases?q=&status=`, `GET /cases/{id}`, `…/timeline`, `…/findings?kind=&risk=&status=&q=`, `…/findings/{fid}`, `…/evidence?status=&audit=&q=`, `…/evidence/stats`, `…/criteria`, `…/research`, `…/jobs` | viewer |
| Auditorías | `GET /cases/{id}/audits/{seq}`, `…/runs`, `POST …/verify`, `GET …/reports`, `GET …/reports/{rid}/download` | viewer |
| Ejecuciones | `POST /jobs/preview`, `POST /jobs` → 202, `POST /jobs/{id}/cancel`, `GET /jobs?status=&case=`, `GET /jobs/{id}`, `GET /jobs/{id}/events?after=`, `GET /jobs/{id}/events/stream` (SSE), `GET /jobs/{id}/log` | **admin** para lanzar y cancelar; viewer para leer |
| Exportación | `POST /cases/{id}/export` (`{scope: case\|audit, seq?, include_unsealed?}`) → 202 + `export_id`, `GET /exports/{eid}` (estado, tamaño, sha256), `GET /exports/{eid}/download`; `GET /cases/{id}/{table}.csv\|.xlsx?<filtros>` para `table ∈ {findings, evidence, timeline, criteria}` | viewer (exportar con `include_unsealed=true`: **admin**) |
| Búsqueda | `GET /search?q=&types=case,finding,evidence,criteria&limit=` | viewer |
| Usuarios | `GET /users`, `POST /users`, `POST /users/{u}/password`, `POST /users/{u}/enable\|disable`, `POST /users/{u}/role`, `GET /tokens`, `POST /tokens` (el token en claro solo en esta respuesta), `POST /tokens/{id}/revoke` | **admin** (nadie se deshabilita ni se cambia el rol a sí mismo; el último admin activo no se puede deshabilitar ni degradar, con la comprobación serializada) |

- `POST /cases/{id}/audits/{seq}/verify` recalcula los hashes del sello y cachea el resultado con su fecha en `console_seal_checks` (y la acción queda en `console_audit_log`). La vista muestra "verificado hace X".
- `GET /jobs/{id}/events/stream` emite `event` (id = seq; al reconectar se reanuda desde `Last-Event-ID`), `status` (cambios de estado, fase, sesión o caso), `end` y un comentario de latido cada 15 s. Lee la fila del job antes que los eventos y termina solo cuando una fila terminal va seguida de una lectura vacía.
- Lecturas: la consola abre la BD con `busy_timeout` (≥ 5 s) y solo escribe tablas `console_*`. SQLite en WAL permite leer mientras los agentes escriben.

## 9. Seguridad

- **Autenticación:**
  - contraseñas con `hashlib.scrypt` (n=2^15, r=8, p=1, sal de 16 B), comparación en tiempo constante;
  - bloqueo progresivo: 5 fallos por usuario o IP bloquean 5 min y cada fallo se registra en `console_audit_log`;
  - sesión con token aleatorio de 32 B en cookie `HttpOnly`, `SameSite=Strict`, `Secure` cuando la petición llega por HTTPS;
  - expiración por inactividad de 12 h y absoluta de 7 días, ambas configurables.
- **CSRF:** toda petición que cambia estado exige la cabecera `X-GR-CSRF`, ligada a la sesión. Los tokens Bearer están exentos porque no usan cookie.
- **Roles:** una dependencia `require(role)` por ruta. `viewer` lee y descarga resultados de auditorías selladas; `admin` hace además todo lo demás.
- **Arranque:**
  - `serve` se niega a arrancar si no existe ningún admin, e indica el comando `hermes ghostrecon user add <nombre> --role admin`;
  - escuchar fuera de loopback exige `--allow-remote`, y entonces muestra un aviso que recomienda proxy TLS o túnel.
- **Rutas (`fsjail.py`):**
  - toda ruta recibida se resuelve con `realpath` (sigue symlinks) y debe cumplir `commonpath([raíz, ruta]) == raíz` para alguna raíz;
  - se rechazan rutas UNC y unidades fuera de las raíces en Windows;
  - el listado omite ocultos y archivos de sistema;
  - la búsqueda tiene profundidad ≤ 4, ≤ 200 resultados y ≤ 3 s.
- **Descargas:** solo archivos dentro de la carpeta de resultados de un caso registrado (`<audits_dir>` o `--out`), resueltos con la misma regla. La evidencia original nunca se descarga.
- **Cabeceras:**
  - `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; base-uri 'none'`;
  - `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`;
  - `Cache-Control: no-store` en `/api/`.
  - No hay recursos externos: las fuentes viajan con el plugin.
- **Host:** se valida la cabecera `Host` contra `localhost`/`127.0.0.1`/el host configurado, para evitar DNS rebinding.
- **Secretos:** la consola nunca muestra valores. `TAVILY_API_KEY` y similares aparecen solo como presente o ausente.
- **Ejecución:**
  - argv sin shell, con argumentos validados;
  - las aprobaciones de comandos peligrosos siguen `approvals.single_query_mode` (por defecto `deny`);
  - la consola muestra en Sistema el modo vigente.
- **Auditoría:** login, logout, fallos, lanzamientos, cancelaciones, exportaciones y gestión de usuarios y tokens quedan en `console_audit_log`. Lanzamientos y exportaciones también entran en el timeline del caso, con el usuario como actor.

## 10. UX/UI

La estructura A fue validada con maquetas el 2-oct-2026. Barra superior: marca, búsqueda global entre casos y botón "+ Nueva auditoría". Barra lateral: **Inicio · Casos · Ejecuciones · Sistema**.

1. **Login:** usuario y contraseña, con un mensaje claro cuando hay bloqueo.
2. **Inicio:**
   - indicadores: casos activos, auditorías selladas, hallazgos abiertos por riesgo, ejecuciones activas;
   - ejecuciones en curso con su fase y tiempo;
   - casos recientes y actividad reciente de todos los casos.
3. **Casos:** tabla con búsqueda y filtros (estado, riesgo abierto); columnas nombre, última auditoría, abiertos por riesgo, sello y última actividad.
4. **Página del caso:**
   - encabezado con ID, carpeta, moneda e idioma, y acciones **Re-run**, **Review**, **Verificar sellos** y **Exportar resultados (.zip)**;
   - indicadores y pestañas **Resumen · Auditorías · Hallazgos · Evidencia · Criterios · Investigación · Cronología · Ejecuciones**;
   - Hallazgos: filtros por tipo, riesgo y estado, más texto; cada fila se expande con su historia entre auditorías, las referencias de evidencia y la siguiente evidencia, con quién la aporta;
   - Auditorías: estado, fechas, sello (verificado hace X), checks de completitud, entregables descargables y ZIP propio;
   - cada tabla puede exportarse a CSV/XLSX con los filtros activos.
5. **+ Nueva auditoría**, en 3 pasos:
   1. carpeta: navegador limitado a las raíces, con miga de pan y búsqueda; cada carpeta lleva la marca "caso existente" o "nueva" y su número de archivos;
   2. revisión previa: archivos por tipo, ZIP, tamaño, `context.md`, caso existente y la carpeta de salida. Avisa cuando corresponde ("muchas imágenes, el OCR tardará"; "ya es un caso sellado, usa Re-run");
   3. opciones (nombre, moneda, idioma), contexto (§7), el comando exacto y **Lanzar en segundo plano** o **Copiar comando**.
6. **Ejecución:**
   - encabezado con la orden, el caso, el estado y la duración, y quién la lanzó;
   - **Cancelar** y **Continuar en terminal**, que copia `hermes -p <perfil> --resume <session_id>`; si hay `dashboard_url` configurada, también un enlace a `…/chat?resume=<id>`;
   - una barra de fases (§6.3), el feed de actividad y los contadores "Hasta ahora";
   - al terminar: el resumen del agente, el estado del sello, los entregables, el ZIP, los tokens consumidos y el log técnico plegable.
7. **Ejecuciones:** la lista de todos los jobs con filtros por estado y caso.
8. **Sistema:**
   - el doctor (BD, dependencias, Tavily presente o ausente, skills, límites de delegación, modo de aprobaciones, disco libre en las raíces);
   - para admin, el registro de auditoría de la consola y «Usuarios y tokens» (crear, restablecer contraseña, habilitar o deshabilitar, cambiar rol; crear tokens —se muestran una vez— y revocarlos).

Detalles transversales:
- **Avisos:** cuando una ejecución termina o falla se muestra una notificación del navegador, si el operador la permitió y la consola está abierta.
- **Tema:** `static/theme.css` define las variables de color, tipografía y logo. Reemplazarlo aplica la identidad de marca sin tocar código.
- **Estados:** cada vista tiene estado vacío, de carga y de error.
- **Pantalla:** pensada para escritorio (≥ 1280 px) y usable en tableta.
- **Accesibilidad básica:** foco visible, contraste AA y etiquetas en los formularios.

## 11. Exportación `.zip`

- **Alcance:** el caso completo o una auditoría (A0n o R0n). Por defecto solo auditorías **selladas**. `include_unsealed=true` (solo admin) añade las abiertas, marcadas `DRAFT` en el manifiesto. Una auditoría con un job en curso nunca se incluye.
- **Contenido:** la carpeta de resultados (`<audits_dir>/` o `--out`). Incluye `case.json`, `corpus_inventory.csv`, las carpetas de auditoría seleccionadas completas y `reviews/`, `_console/` (contextos combinados) y `EXPORT_MANIFEST.json`. **Nunca** incluye la evidencia original.
- **Integridad:**
  - antes de empaquetar se verifica cada sello; un sello roto **bloquea** la exportación y se informa qué archivo cambió;
  - `EXPORT_MANIFEST.json` contiene `{export_id, case_id, scope, audits:[{id, sealed, seal_sha256, verified_at}], files:[{path, size, sha256}], exported_by, exported_at, generator: "Ghost Recon Console <versión>"}`;
  - el SHA-256 del ZIP se calcula al terminar, se muestra en la consola y se guarda junto al ZIP como `.sha256`.
- **Nombre y ruta:** `GhostRecon_<slug>_<scope>_<YYYYMMDD-HHMM>.zip` en `plugin_data_dir/ghost-recon/console/exports/`. Las exportaciones grandes se construyen en segundo plano, con ZIP64 y progreso por archivos. Se conservan las últimas 20 o 30 días (configurable).
- **Trazabilidad:** cada exportación queda en `console_audit_log` y en el timeline del caso (`results_exported`, sha256 del ZIP).
- **Tablas:** los CSV salen en UTF-8 con BOM, para que Excel abra bien los acentos. Los XLSX salen con openpyxl y metadatos "Ghost Recon", igual que el pack.

## 12. Configuración y CLI

Todo vive en `config.yaml` bajo `plugins.entries.ghost-recon.settings.console`. Nada va en `.env`, salvo secretos.

| Clave | Por defecto | Uso |
|---|---|---|
| `case_roots` | `[]` (obligatoria para lanzar) | Raíces visibles para el navegador de carpetas |
| `host` / `port` | `127.0.0.1` / `9230` | Escucha. `--host` y `--port` en el CLI las sobrescriben |
| `max_parallel_jobs` | `2` | Límite global de ejecuciones |
| `notify_target` | `""` | Destino de `hermes send` (p. ej. `telegram`); vacío = sin aviso por gateway |
| `export_include_unsealed` | `false` | Valor por defecto del diálogo de exportación |
| `export_retention` | `{count: 20, days: 30}` | Limpieza de ZIP antiguos |
| `session_idle_hours` / `session_max_days` | `12` / `7` | Expiración de sesiones |
| `dashboard_url` | `""` | Si existe, añade el enlace "Continuar en chat" al dashboard |

CLI (dentro de `hermes [-p perfil] ghostrecon`):

```
serve [--host H] [--port N] [--allow-remote]
user add <nombre> --role admin|viewer      (pide la contraseña dos veces)
user list | user passwd <nombre> | user disable <nombre> | user enable <nombre>
token create --user <nombre> --name <etiqueta>   (muestra el token una sola vez)
token list | token revoke <id>
```

Instaladores: `install.sh --console [--port N] [--case-root RUTA]…` e `install.ps1 -Console …`. Hacen tres cosas:
1. fijan la configuración;
2. guían la creación del admin;
3. registran el servicio: unidad systemd de usuario en Linux, launchd en macOS, tarea programada al iniciar sesión en Windows.

Son idempotentes.

## 13. Entrega por hitos

Cada hito tiene **su propio plan de implementación** (`ghost-recon/specs/plans/`) y se integra por PR desde el worktree `ghost-recon-console`. Es usable por sí solo: lo que depende de un hito posterior aparece deshabilitado con el aviso «Próximamente», sin nombres de hito ni comandos (decisión del propietario en H2).

| Hito | Contenido | Aceptación |
|---|---|---|
| **H1 · Base** | `console_store` y migraciones; auth (usuarios, sesiones, tokens, CSRF, roles, bloqueo); `serve`, `user`, `token`; `create_app` con cabeceras y validación de Host; API de solo lectura (sistema, casos, auditorías, reportes con descarga, verificación de sellos); frontend: login, Inicio, Casos, Página del caso (todas las pestañas) | Con el caso demo sembrado, todas las vistas muestran datos coherentes con la BD; un viewer no puede lanzar; las rutas fuera de la carpeta de resultados se rechazan |
| **H2 · Ejecuciones** | `fsjail` (raíces, listado, búsqueda, inspección); `commands` (tabla de órdenes, preview, contexto combinado); `jobs` y `job_runner` (desacople, límites, cancelación, huérfanos); `events` (normalización y fases); vistas Nueva auditoría, Ejecución y Ejecuciones; Re-run y Review desde el caso | E2E con agente falso: lanzar, seguir en vivo, reiniciar el servidor sin perder el job, cancelar, detectar huérfano; contexto combinado correcto |
| **H3 · Exportación y extras** | ZIP de resultados y manifiesto; tablas CSV/XLSX; búsqueda entre casos; avisos (navegador + `hermes send`) | El ZIP verifica por hash; el sello roto bloquea; la evidencia queda excluida; el aviso llega con un `send` falso |
| **H4 · Operación y docs** | Instaladores con `--console` y servicio; `ghost-recon/CONSOLE.md` (operación, túnel, usuarios, exportación); actualización de `COMMANDS.md`, `ARCHITECTURE.md`, `AGENTS.md`, `PLAN.md` y `README.md`; aceptación en la máquina real | El ciclo de §1 completo desde la consola en la máquina dedicada, con claves reales |

## 14. Pruebas

Se ejecutan con `scripts/run_tests.sh`, con `HERMES_HOME` temporal. Son contratos de comportamiento, sin pruebas que lean código fuente ni que congelen valores.

| Área | Pruebas |
|---|---|
| Store y migraciones | `migrate()` idempotente; esquema de caso intacto; tokens y sesiones guardados solo como hash |
| Auth | login correcto e incorrecto; bloqueo y desbloqueo; expiración; CSRF obligatorio con cookie y exento con Bearer; `viewer` → 403 en lanzar, cancelar y `include_unsealed`; token revocado → 401; `serve` sin admin no arranca |
| API de lectura | sembrar el caso demo con `core.service` (abrir → auditoría → pack → sello → rerun → review) y comprobar que cada endpoint refleja la BD (conteos por riesgo = filas de `findings`; estado de sello = `verify_audit`) |
| fsjail | `..`, symlink que escapa, ruta absoluta fuera de las raíces; Windows: unidad ajena y UNC (`@pytest.mark.platforms("windows")`); POSIX: symlink (`platforms("posix")`) |
| Descargas | un archivo de evidencia → 404/403; un archivo de `06_Report` de auditoría sellada → 200 con el hash correcto |
| Órdenes | tabla de órdenes: preview = argv real; carpeta ya sellada en `new-open-case` → 409 con sugerencia; validaciones de moneda, idioma y nombre |
| Contexto | el archivo combinado contiene el original literal y su hash, más las notas firmadas; nunca se escribe en la carpeta de evidencia |
| Jobs (E2E real) | `job_runner` real con un **agente falso** configurable (un script que emite `stream-json`): estados, `session_id`, `phase`, `result`; job que sobrevive a un reinicio del servidor; cancelación del árbol (una prueba por SO con su marca); huérfano; límites por caso y global; `hermes send` falso invocado con el resumen |
| Eventos | `events.py`: secuencias de `stream-json` grabadas → fases y eventos esperados (relación entrada → salida, no instantáneas de texto) |
| Exportación | el manifiesto coincide con los archivos; el SHA-256 del ZIP coincide con el `.sha256`; evidencia excluida; no sellada excluida por defecto; sello alterado → bloqueo |
| Búsqueda | encuentra hallazgos por ID o título y evidencia por nombre o hash entre dos casos; no devuelve nada fuera de la BD |

**Aceptación manual en la máquina dedicada (H4):** el ciclo de §1 completo, más un reinicio del servicio durante un `/rerun-case` en curso.

## 15. Riesgos y preguntas abiertas

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | `--skills <skill>` + `-q "/<orden> …"` podría no ejecutar la skill como lo hace la invocación interactiva | Verificación temprana en H2 con un caso pequeño. Alternativa: construir el mensaje de invocación con el mecanismo que usa cron (`--skill` en cron carga el cuerpo completo) o redactar `-q` como instrucción explícita "Ejecuta la orden … según la skill precargada" |
| R2 | Aprobaciones en `deny`: un paso legítimo (p. ej. instalar un parser) queda bloqueado | El agente busca otra vía (comportamiento documentado). La consola muestra los bloqueos (`warning`) y Sistema muestra el modo. Cambiarlo es decisión del operador en `config.yaml` |
| R3 | Desacople y cancelación difieren entre Windows y POSIX | Helpers de Hermes para hijos; pruebas por SO con su marca; lane `wine2e` si hace falta prueba viva en Windows |
| R4 | Concurrencia SQLite (agentes escribiendo, consola leyendo) | WAL + `busy_timeout`; la consola solo escribe sus tablas; lecturas cortas |
| R5 | Coste y duración de auditorías largas | Tokens visibles por job; límite global de ejecuciones; cancelación |
| R6 | El ZIP puede ser muy grande (copias de trabajo y OCR) | Construcción en segundo plano con ZIP64 y progreso; retención configurable. Si molesta, opción futura "solo entregables" |
| R7 | `--source` podría no aceptar un valor libre | Resuelto en H2: `--source` acepta cualquier valor (`hermes_cli/main.py` lo pone en `HERMES_SESSION_SOURCE`); la consola usa `ghost-recon-console` |
| R8 | Con `KillMode=control-group` (el valor por defecto de systemd), reiniciar el servicio mata las auditorías en curso | La unidad de la consola usa `KillMode=process` (H4 lo fija en el instalador; documentado en `COMMANDS.md` §3b) |
| R9 | `max_concurrent_sessions` en `config.yaml` puede rechazar una ejecución | El runner la marca `failed` con el motivo en el log técnico; documentado en `COMMANDS.md` §3b |
| R10 | Presupuesto de delegación de un solo disparo: las ejecuciones de la consola son sesiones `chat -q` limitadas por `delegation.oneshot_max_children` (por defecto 2), lo que deja sin enjambre ni validación A/B/C | Fijar 100 (fragmento de config, instaladores y comprobación de `/gr-doctor`); hallado en la ejecución R1 |
