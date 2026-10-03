# Ghost Recon Agent — Plan de construcción sobre Hermes Agent

**Estado del documento:** vivo. Es la fuente de verdad del avance. Cualquier agente (desde un IDE, Claude Code, Hermes, Cursor…) que retome el trabajo lee este archivo primero, luego `HANDOFF.md`, y actualiza la sección **Estado** al terminar cada paso.

**Objetivo:** convertir el agente Hermes (fork `SiteOneTech/agent-ghost-recon-forensic-finance`) en **Ghost Recon**, un agente autónomo de auditoría financiera forense que vive en una máquina propia y que:

1. Gestiona **casos** y, dentro de cada caso, **múltiples auditorías** (base de datos local SQLite en el entorno del agente).
2. Ejecuta el ciclo forense completo tal como lo hace Ghost Recon en el proyecto Claude "Ghost Recon Agent V3": intake con hashes, deduplicación, extracción, reconstrucción, excepciones, validación independiente, pack documental.
3. Lanza **enjambres de auditores** (sub-agentes en paralelo) por bloque de evidencia y por rol.
4. Investiga con un **agente de investigación** basado en Tavily (search / extract / crawl / map / research).
5. Produce el **pack documental** completo (.md, .pdf, .xlsx) con agentes consultores de reportes.
6. Expone tres órdenes: `/new-open-case`, `/rerun-case`, `/review-case` (más utilidades `/gr-*` y el CLI `hermes ghostrecon`).

---

## 0. Decisiones de diseño (tomadas; ajustables, pero documentar el cambio aquí)

| # | Decisión | Por qué |
|---|---|---|
| D1 | **No se toca el core de Hermes.** Todo vive en `plugins/ghost_recon/` (plugin nativo), `skills/ghost-recon/` (skills bundled) y `ghost-recon/` (docs, instalador, config). Única edición al core: una fila en la tabla de ruteo de `AGENTS.md` raíz. | Regla "plugins never touch core" de Hermes; permite hacer `git merge upstream/main` sin conflictos. |
| D2 | Las tres órdenes principales son **skills** (`skills/ghost-recon/new-open-case`, `rerun-case`, `review-case`). Hermes convierte cada skill en el slash command `/<nombre>` y lo inyecta como turno del agente (CLI, TUI, Telegram, Discord…). | Un comando de plugin (`ctx.register_command`) solo devuelve texto y no inicia un turno del agente; una skill sí. |
| D3 | Los comandos de plugin `/gr-cases`, `/gr-case`, `/gr-help`, `/gr-doctor` son informativos (texto). El CLI `hermes ghostrecon …` administra la BD sin agente. | Separación: orquestación = skills; estado/consulta = plugin. |
| D4 | **BD de casos:** SQLite en `<HERMES_HOME>/plugin-data/ghost-recon/ghostrecon.db` vía `plugins.plugin_storage.plugin_db` (WAL). Espejo portable `case.json` dentro de la carpeta del caso para re-importar si la BD se pierde. | Es el almacenamiento documentado para plugins; sobrevive a `hermes update` y a reinstalar el plugin. |
| D5 | **Carpeta del caso = carpeta de evidencia.** Nunca se escribe dentro de la evidencia. Las salidas van a `<caso>/GhostRecon_Audits/<AUDIT_ID>/` (configurable `audits_dirname`, o `--out <folder>`). Una auditoría **sellada** (`SEALED.json` con SHA-256 de todo) es inmutable: las herramientas rechazan escrituras y el re-run crea una carpeta nueva. | Requisito explícito de Jean: "nunca se toca la que ya selló". |
| D6 | **Enjambre:** el agente usa la herramienta core `delegate_task` (hasta `delegation.max_concurrent_children`, por defecto 10) con un plan determinista generado por `gr_swarm_plan` (bloques de evidencia + roles). Los hijos cargan su skill de bloque (`ghost-recon-block-auditor`) o de rol (`ghost-recon-role-*`) con `skill_view`. | `delegate_task` es el primitivo probado de Hermes; `gr_swarm_plan` deja los manifiestos en disco (`agents/manifest_*.json`) para reanudar. |
| D7 | **Investigación:** herramienta de plugin `gr_research` que llama a la API REST de Tavily (search/extract/crawl/map/research) con `TAVILY_API_KEY` leída por `agent.secret_scope.get_secret`; además el instalador configura `web.backend: tavily` para que `web_search`/`web_extract` nativos usen Tavily. Opcional: MCP `tavily-mcp` vía `hermes mcp add`. | Un solo proveedor para toda la investigación; las notas quedan registradas como evidencia de tipo `research`. |
| D8 | **Reportes:** módulo `plugins/ghost_recon/reports/` (Markdown → PDF con ReportLab, XLSX con openpyxl) invocado por `gr_report_build`. Firma "Ghost Recon · www.ghostrecon.ai"; metadatos sin nombres de herramientas. Dependencias declaradas en `plugin.yaml: python_dependencies`. | Mismo toolchain que la skill `ghost-recon-deliverables`; sin dependencias nativas de sistema. |
| D9 | Idioma de docs y entregables: **español** (con inglés donde el código lo exige: nombres de archivos, hojas, IDs). | Preferencia del cliente y del proyecto. |
| D10 | IDs: caso `GRC-<slug>-<yyyymmdd>`; auditoría `<caso>/A01`, `A02`…; revisión `R01`…; excepciones `EXC-nn`, anomalías `ANO-nn`, hallazgos `FND-nn`, criterios `CRIT-nn`, preguntas `Q-nn` — **únicos por caso y continuos entre auditorías**. | La metodología exige IDs que continúan la serie entre versiones. |
| D11 | Las skills bundled cumplen el HARDLINE de `skills/AGENTS.md` (descripción ≤ 60 caracteres, orden de secciones, herramientas nativas en backticks). El texto largo del método va en `references/` de cada skill. | `tests/skills/test_authoring_standards.py` corre sobre `skills/**`. |

---

## 1. Mapa de componentes

```
agent-ghost-recon-forensic-finance/
├── AGENTS.md                      (+1 fila de ruteo → ghost-recon/AGENTS.md)
├── ghost-recon/                   DOCS + INSTALADOR (este directorio)
│   ├── PLAN.md                    ← este archivo (plan + estado)
│   ├── HANDOFF.md                 protocolo de reanudación para otro agente
│   ├── ARCHITECTURE.md            arquitectura, modelo de datos, flujos, carpeta del caso
│   ├── COMMANDS.md                contrato de /new-open-case, /rerun-case, /review-case, /gr-*, CLI
│   ├── AGENTS.md                  guía de área para agentes de código (qué tocar, cómo probar)
│   ├── install.sh / install.ps1   instalación en la máquina autónoma (Linux/macOS/WSL / Windows)
│   ├── config/
│   │   ├── config.ghost-recon.yaml   fragmento de config.yaml a fusionar
│   │   ├── SOUL.md                   identidad del agente (se copia a HERMES_HOME/SOUL.md)
│   │   └── env.example               variables secretas (.env)
│   └── demo/
│       └── demo-case/                caso sintético para smoke test (evidencia ficticia)
├── plugins/ghost_recon/           PLUGIN HERMES (toolset `ghost_recon`)
│   ├── plugin.yaml
│   ├── __init__.py                register(ctx): tools, commands, CLI, system-prompt section, hooks
│   ├── core/                      lógica independiente de Hermes (testeable con pytest puro)
│   │   ├── db.py                  esquema SQLite + DAO
│   │   ├── ids.py                 generación de IDs (caso, auditoría, EXC-nn…)
│   │   ├── casefolder.py          layout de carpeta, case.json, inventario, hashes, dedupe, sellado
│   │   ├── swarm.py               planes de enjambre (bloques, roles, validadores) → manifiestos
│   │   ├── prompts.py             plantillas de goals/contexts de los sub-agentes
│   │   ├── service.py             operaciones de caso/auditoría (open, start, seal, findings, runs)
│   │   ├── research.py            cliente Tavily (search/extract/crawl/map/research)
│   │   ├── review.py              cronología del caso + plan de revisión por roles
│   │   └── reports/               md.py, pdf.py, xlsx.py, pack.py (pack documental + hashes)
│   ├── tools.py                   handlers de herramientas gr_* (JSON in/out)
│   ├── commands.py                /gr-cases /gr-case /gr-help /gr-doctor
│   ├── cli.py                     hermes ghostrecon init|doctor|cases|case|audits|timeline|export
│   ├── prompts.py                 texto del system-prompt section (identidad Ghost Recon)
│   └── assets/fonts/              DejaVu (Unicode) para PDF
├── skills/ghost-recon/            SKILLS BUNDLED (se sincronizan a ~/.hermes/skills/ghost-recon/)
│   ├── DESCRIPTION.md
│   ├── new-open-case/             /new-open-case  (orquestador)
│   ├── rerun-case/                /rerun-case     (pase de evidencia + nueva auditoría)
│   ├── review-case/               /review-case    (cronología + 6 roles + diagnóstico)
│   ├── ghost-recon-forensic-audit/        método (playbook) — references/ con el texto íntegro
│   ├── ghost-recon-forensic-techniques/   técnicas por tipo de misión
│   ├── ghost-recon-deliverables/          construcción/firma/QA de entregables
│   ├── ghost-recon-evidence-pass/         procedimiento de pase de evidencia
│   ├── ghost-recon-counterparty-response/ auditoría de la respuesta de la contraparte
│   ├── ghost-recon-block-auditor/         protocolo del sub-agente de bloque (enjambre)
│   ├── ghost-recon-validation/            validadores independientes A/B/C
│   ├── ghost-recon-research/              agente de investigación (Tavily/OSINT)
│   ├── ghost-recon-report-pack/           consultor de reportes (md/pdf/xlsx)
│   └── ghost-recon-role-{legal,tax,financial,auditor,accounting,mediator}/
└── tests/
    ├── plugins/ghost_recon/       tests del core (db, casefolder, swarm, reports) y del registro
    └── skills/test_ghost_recon_skills.py
```

---

## 2. Fases y estado

Leyenda: `[ ]` pendiente · `[~]` en curso · `[x]` hecho · `[!]` bloqueado (ver nota)

### Fase 0 — Preparación
- [x] Clonar fork en el workspace, rama `ghost-recon`.
- [!] Clonar en `D:\Source-Code\agent-ghost-recon-forensic-finance` desde el shell de la máquina: el shell no pudo montar la carpeta (bug Windows Update 8-sep reportado por el puente). **Mitigación:** los archivos nuevos se escriben en la carpeta vía el puente de archivos; el repo base se clona con `git` desde PowerShell (ver `HANDOFF.md` §1).
- [x] Leer AGENTS.md, plugins/AGENTS.md, skills/AGENTS.md, API de plugins, delegate_task, web/tavily, kanban, cron.
- [x] Leer skills y metodologías Ghost Recon del proyecto Claude (fuente del método).
- [!] `ghostrecon-web-app` es privado: no accesible sin credenciales GitHub. No bloquea: el método está en las skills.

### Fase 1 — Documentación de previsión (esta fase va primero por diseño)
- [x] `ghost-recon/PLAN.md` (este archivo)
- [x] `ghost-recon/HANDOFF.md`
- [x] `ghost-recon/ARCHITECTURE.md`
- [x] `ghost-recon/COMMANDS.md`
- [x] `ghost-recon/AGENTS.md`
- [x] Fila de ruteo en `AGENTS.md` raíz

### Fase 2 — Núcleo del plugin (core/ sin dependencias de Hermes)
- [x] `core/db.py` — esquema (cases, audits, evidence, findings, criteria, reports, runs, timeline, research_notes) + migraciones + DAO
- [x] `core/ids.py`
- [x] `core/casefolder.py` — layout, `case.json`, inventario SHA-256/MD5 (incluye ZIP), dedupe (DUP_PRIOR/DUP_INTERNAL/UNIQUE), exclusión de carpetas de salida, sellado y verificación de sello
- [x] `core/swarm.py` — planes `discovery`, `extraction`, `validation`, `review`; manifiestos por bloque; contexto para `delegate_task`
- [x] `core/research.py` — cliente Tavily REST (search, extract, crawl, map, research) con `httpx`
- [x] `core/review.py` — cronología consolidada del caso + evolución de excepciones + plan de roles
- [x] `core/reports/` — md.py (ensamblado), pdf.py (ReportLab, fuentes DejaVu, metadatos Ghost Recon), xlsx.py (openpyxl, hojas estándar), pack.py (construcción + hashes + LEEME)

### Fase 3 — Integración Hermes
- [x] `plugin.yaml` (python_dependencies, config_schema, provides_tools, requires_env opcional)
- [x] `__init__.py` — `register(ctx)`: tools (`gr_*`), commands (`/gr-*`), CLI (`hermes ghostrecon`), system-prompt section, hook `on_session_start` (recordatorio de casos abiertos)
- [x] `tools.py` — handlers JSON de: `gr_case_open`, `gr_case_status`, `gr_case_list`, `gr_audit_start`, `gr_evidence_index`, `gr_finding_upsert`, `gr_criteria_add`, `gr_research`, `gr_swarm_plan`, `gr_run_record`, `gr_report_build`, `gr_audit_seal`, `gr_review_plan`, `gr_timeline`
- [x] `commands.py`, `cli.py`

### Fase 4 — Skills
- [x] Orquestadores: `new-open-case`, `rerun-case`, `review-case`
- [x] Método: `ghost-recon-forensic-audit`, `ghost-recon-forensic-techniques`, `ghost-recon-deliverables`, `ghost-recon-evidence-pass`, `ghost-recon-counterparty-response` (SKILL.md operativo + `references/` íntegro)
- [x] Enjambre y validación: `ghost-recon-block-auditor`, `ghost-recon-validation`
- [x] Investigación y reportes: `ghost-recon-research`, `ghost-recon-report-pack`
- [x] Roles: legal, tax, financial, auditor, accounting, mediator
- [x] `DESCRIPTION.md` de la categoría

### Fase 5 — Instalación y configuración
- [x] `install.sh`, `install.ps1` (enable plugin, sync skills, config, .env, init BD, doctor)
- [x] `config/config.ghost-recon.yaml`, `config/SOUL.md`, `config/env.example`
- [x] `demo/demo-case/` + `demo/smoke_test.py` (evidencia sintética y ciclo completo sin LLM)

### Fase 6 — Verificación
- [x] Tests del core con pytest puro (`tests/plugins/ghost_recon/`)
- [x] Test de estándares de skills (`tests/skills/test_authoring_standards.py` sobre `skills/ghost-recon/**`)
- [x] Smoke test: abrir caso demo → auditoría → pack → sello → rerun → review (sin LLM, vía core + CLI)
- [ ] Smoke test con el agente real (`hermes` + proveedor de modelo) — **requiere la máquina de Jean con API keys** (ver HANDOFF §4)
- [x] Entrega de archivos a `D:\Source-Code\agent-ghost-recon-forensic-finance` + bundle git

### Fase 7 — Pendientes / siguientes iteraciones (no bloqueantes)
- [ ] MCP Tavily opcional (`hermes mcp add tavily`) documentado en config.ghost-recon.yaml; probar en máquina real
- [ ] Integración con Kanban de Hermes (un tablero por caso) — diseño en ARCHITECTURE §8, no implementado
- [ ] Cron: pase de evidencia programado (`hermes cron create "0 8 * * 1" "/rerun-case <carpeta>"`) — receta en COMMANDS.md
- [ ] Exportación del caso a la web app (`ghostrecon-web-app`) — cuando el repo sea accesible, mapear `case.json` → API
- [ ] Generador de gráficos (matplotlib) para el PDF ejecutivo (waterfall, circuito de dinero, posición de socios) — hoy el PDF renderiza texto y tablas del MD
- [ ] Informe de metodología como plantilla `06_Report/methodology.md` pre-rellenada por el plugin (hoy lo escribe el agente según `ghost-recon-deliverables` §6)
- [ ] `gr_swarm_run` programático con `ctx.subagent_lifecycle` (hoy el enjambre se lanza con `delegate_task` desde la skill, que es el primitivo probado)

### Fase 8 — Consola web (spec `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`)
- [x] H1 · Base: `hermes ghostrecon serve|user|token`, login/roles/tokens, API de lectura, verificación de sellos cacheada, descargas contenidas, frontend (Inicio, Casos, Caso con 7 pestañas, Sistema), demo `console_demo.py`
- [ ] H2 · Ejecuciones: navegador de carpetas, asistente Nueva auditoría con notas de contexto, motor de jobs desacoplado, vista en vivo, Re-run/Review
  - Pendientes de la revisión final de H1 (antes de tocar el esquema):
    - migraciones versionadas de `console_*` con tabla de versión de una fila
    - lock en la contabilidad del bloqueo de login
    - `touch_session` best-effort y cabeceras de seguridad en los 500
    - prueba E2E real con `HERMES_HOME` temporal + `config.yaml`
    - purga de sesiones vencidas
- [ ] H3 · Exportación `.zip` verificable, tablas CSV/XLSX, búsqueda entre casos, avisos, verificación de hash al descargar entregables de auditorías selladas (409 `hash_mismatch`, registro de descargas denegadas)
- [ ] H4 · Instaladores `--console`/servicio, `CONSOLE.md`, aceptación en la máquina dedicada

---

## 3. Riesgos y cómo se mitigaron

| Riesgo | Mitigación |
|---|---|
| Hermes cambia la API de plugins | El plugin usa solo la superficie documentada de `ctx` (register_tool/command/cli_command/system_prompt_section, get_config, plugin_db). `core/` no importa Hermes. |
| Sub-agentes sin memoria ni AGENTS.md (`skip_context_files=True`) | Cada goal del enjambre es autocontenido: incluye la ruta del manifiesto, las reglas críticas y la orden de cargar su skill con `skill_view`. |
| Pérdida de estado intermedio (carpetas efímeras) | Todo insumo derivado se escribe dentro de `GhostRecon_Audits/<AUDIT>/` (`agents/`, `extract/`, `src/`); nada en /tmp. |
| Auditoría sellada modificada por error | `SEALED.json` + verificación de hashes; `gr_audit_seal` marca `status=sealed` y los tools de escritura rechazan; `gr_case_status` reporta `seal_ok`. |
| Dependencias Python ausentes en la máquina | `plugin.yaml: python_dependencies` + `install.sh` instala con `hermes pm`/`uv pip` dentro del venv de Hermes; `/gr-doctor` lo verifica. |
| Descripciones de skills > 60 chars rompen CI | Todas las skills nuevas cumplen el HARDLINE; test dedicado. |

---

## 4. Registro de cambios de este plan

- 2026-10-02 · v1 · Plan inicial, decisiones D1–D11, fases 0–7 (Claude, sesión Cowork con Jean).
- 2026-10-02 · v1.1 · Fases 1–6 completadas en el workspace cloud: plugin `plugins/ghost_recon` (14 tools, 4 comandos, CLI, system-prompt), 18 skills (pasan `test_authoring_standards`), instalador, demo, 53 tests + smoke test verdes; plugin cargado por el camino real de discovery de Hermes con HERMES_HOME temporal. Pendiente: smoke test con agente real en la máquina autónoma (HANDOFF §4) y Fase 7.
- 2026-10-02 · v1.2 · Revisión de código independiente (sub-agente) y correcciones: `open_case` ya no sobreescribe hashes auditados ni convierte lo nuevo en DUP_PRIOR antes de un rerun; evidencia MODIFIED entra al enjambre del rerun y conserva el hash anterior en `meta.previous_hashes`; ZIP cifrados/archivos ilegibles se registran como UNREADABLE sin abortar el intake; workbook limpia caracteres de control y trata todo texto que empieza por `=` como texto; `secret()` no cae al env de otro perfil; `max_parallel` acotado por `delegation.max_concurrent_children`; `gr_swarm_plan(mode=review)` devuelve `delegate_tasks`; `Store` serializado con RLock; instalador compatible con bash 3.2 y con el comando real `hermes skills opt-in --sync`. 55 tests + smoke verdes.
- 2026-10-02 · v1.3 · Fase 8 (consola web) diseñada y H1 implementado: servidor propio en loopback (túnel), login con roles admin/viewer y tokens Bearer, API `/api/v1` de solo lectura sobre la BD de casos, caché de verificación de sellos, descargas contenidas en la carpeta de cada auditoría, frontend sin build. Sin cambios al core de Hermes.
