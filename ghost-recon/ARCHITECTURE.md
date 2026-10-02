# Ghost Recon sobre Hermes — Arquitectura

## 1. Visión

Hermes Agent aporta: el bucle de agente, proveedores de modelo, terminal/archivos, `delegate_task` (sub-agentes), `web_search`/`web_extract` (proveedor Tavily), skills, plugins, cron, kanban, gateway (Telegram/Discord/Slack…), TUI y Desktop.

Ghost Recon aporta, **sin tocar el core**:

| Capa | Qué | Dónde |
|---|---|---|
| Identidad | Sección de system prompt "Eres Ghost Recon…" + `SOUL.md` | plugin `register_system_prompt_section`, `ghost-recon/config/SOUL.md` |
| Órdenes | `/new-open-case`, `/rerun-case`, `/review-case` (skills → turno del agente) | `skills/ghost-recon/{new-open-case,rerun-case,review-case}` |
| Estado | BD SQLite de casos/auditorías/evidencia/hallazgos/reportes/runs/timeline | `plugins/ghost_recon/core/db.py` → `<HERMES_HOME>/plugin-data/ghost-recon/ghostrecon.db` |
| Herramientas | `gr_*` (toolset `ghost_recon`) para que el agente opere la BD, la carpeta del caso, el enjambre, la investigación, los reportes y el sello | `plugins/ghost_recon/tools.py` |
| Enjambre | planes deterministas → `delegate_task` | `core/swarm.py` + skills `ghost-recon-block-auditor`, `ghost-recon-role-*`, `ghost-recon-validation` |
| Investigación | cliente Tavily (search/extract/crawl/map/research) + skill de OSINT financiero | `core/research.py`, skill `ghost-recon-research` |
| Reportes | pack documental md/pdf/xlsx desde modelo JSON + BD | `core/reports/`, skill `ghost-recon-report-pack` |
| Utilidades | `/gr-cases`, `/gr-case`, `/gr-help`, `/gr-doctor`; CLI `hermes ghostrecon` | `commands.py`, `cli.py` |

## 2. Modelo de datos (SQLite, WAL)

Todas las tablas llevan `created_at`/`updated_at` ISO-8601 UTC y un `meta` JSON para extensiones.

```
cases          id PK (GRC-<slug>-<yyyymmdd>), slug, name, root_path (carpeta de evidencia),
               audits_dir (relativa, default GhostRecon_Audits), status (open|closed|archived),
               base_currency, language, context_md (ruta opcional), last_audit_id
audits         id PK (<case>/A01), case_id FK, seq, kind (initial|rerun|review),
               status (open|in_progress|validated|sealed|failed), folder (absoluta),
               parent_audit_id, context_md, out_override, started_at, sealed_at,
               seal_sha256 (hash del manifiesto), model_json (ruta), summary JSON
evidence       id PK, case_id, path (relativa a root), filename, ext, size, mtime, sha256, md5,
               zip_member (0/1), first_audit_id, status (NEW|DUP_PRIOR|DUP_INTERNAL|DUP_CONTENT|UNIQUE),
               doc_type, doc_date, entity, review_status, confidence, notes
findings       id PK (EXC-nn|ANO-nn|FND-nn|Q-nn por caso), case_id, audit_id (última que la tocó),
               kind (exception|anomaly|finding|question), title, description, amount, currency,
               entity, counterparty, date, category, risk (low|medium|high|critical),
               confidence (CONFIRMED|HIGHLY_PROBABLE|PROBABLE|POSSIBLE|UNRESOLVED),
               label (FACT|CALCULATION|INFERENCE|ALLEGATION|UNKNOWN),
               status (open|closed|downgraded|upgraded|superseded), evidence_refs JSON,
               next_evidence, owner (quién aporta), history JSON [{audit_id, ts, change}]
criteria       id PK (CRIT-nn por caso), case_id, audit_id, date, author, text (literal), status
reports        id PK, audit_id, kind (executive_pdf|workbook_xlsx|report_md|methodology_pdf|
               review_md|review_pdf|chronology_xlsx|custom), path, format, version, sha256, size
runs           id PK, audit_id, kind (swarm|validation|research|build|seal|review|intake),
               role, status (planned|running|done|failed), started_at, finished_at,
               input JSON, output JSON, summary
timeline       id PK, case_id, audit_id, ts, event_type, actor, description, ref JSON
research_notes id PK, case_id, audit_id, query, url, title, snippet, relevance, sha256, saved_path
```

Espejo portable: `<root>/<audits_dir>/case.json` (caso + lista de auditorías + conteos). `gr_case_open` sobre una carpeta con `case.json` y sin fila en BD **re-importa** el caso.

## 3. Carpeta del caso (nunca se escribe dentro de la evidencia)

```
<carpeta del caso>/                 ← la carpeta que recibe /new-open-case (evidencia tal cual)
├── (evidencia: PDFs, XLSX, imágenes, ZIPs, subcarpetas…)          ← intocable
├── context.md                      (opcional; o la ruta .md pasada al comando)
└── GhostRecon_Audits/              (configurable; o --out <folder>)
    ├── case.json
    ├── corpus_inventory.csv        inventario de todo el corpus con SHA-256/MD5 (se regenera por auditoría)
    ├── A01_2026-10-02/             auditoría inicial — SELLADA
    │   ├── 00_manifest.json        qué es esta auditoría (ids, kind, parent, fechas, contexto)
    │   ├── 01_Source_Index/        document_index.csv, evidence_register.csv (lote, hashes, estado dedupe)
    │   ├── 02_Working_Copies/      texto extraído / OCR / páginas (nunca originales)
    │   ├── 03_Extracted_Data/      agents/manifest_*.json, agents/out_*.json, model.json
    │   ├── 04_Reconciliation/
    │   ├── 05_Exceptions/          exceptions.json (export de la BD al sellar)
    │   ├── 06_Report/              pack documental: *.md, *.pdf, *.xlsx + LEEME.md + pack_hashes.txt
    │   ├── src/                    scripts generadores usados (copias)
    │   ├── versions/               versiones previas dentro de la misma auditoría (sub-versiones)
    │   ├── validation/             validation.json + informes de los validadores
    │   └── SEALED.json             manifiesto SHA-256 de todos los archivos + fecha + firma
    ├── A02_2026-10-15/             re-run (pase de evidencia) — carpeta nueva
    │   └── … + Evidence_Pass/      register.csv, dedupe.json, triage.md, version_effect.json
    └── reviews/
        └── R01_2026-10-20/         /review-case: cronología + 6 opiniones + diagnóstico
            ├── chronology.md / chronology.xlsx
            ├── roles/legal.md tax.md financial.md auditor.md accounting.md mediator.md
            ├── diagnosis.md / diagnosis.pdf
            └── SEALED.json
```

## 4. Flujos

### 4.1 `/new-open-case <folder> [context.md] [--out <folder>] [--name "…"] [--currency USD] [--lang es]`

1. **Skill `new-open-case`** se inyecta como turno. El agente parsea argumentos.
2. `gr_case_open(folder, context_md, name, …)` → crea/carga caso, inventario completo con hashes (incluye miembros de ZIP), `case.json`, timeline `case_opened`.
3. `gr_audit_start(case_id, kind="initial")` → crea `A01_<fecha>/` con la estructura, registro de evidencia (todo NEW/UNIQUE en la primera), `00_manifest.json`.
4. Intake (skill `ghost-recon-forensic-audit` §3-4): el agente lee `context.md`, decide alcance, modelo de negocio, criterios (`gr_criteria_add`).
5. **Enjambre de descubrimiento/extracción:** `gr_swarm_plan(audit_id, mode="extraction")` agrupa la evidencia en bloques (A comercial, B suministro/logística, C bancos/tarjetas/partes relacionadas, D OCR/visión, E por entidad/país) y escribe `agents/manifest_<bloque>.json`; devuelve `tasks[]` listos para `delegate_task`. Cada hijo: carga `ghost-recon-block-auditor` con `skill_view`, lee su manifiesto, extrae a `agents/out_<bloque>.json` con proveniencia, reporta discrepancias.
6. El agente consolida en `03_Extracted_Data/model.json` (único origen de cifras), reconstruye (fases 5-16 del método), registra excepciones/anomalías (`gr_finding_upsert`) y preguntas.
7. Investigación cuando hace falta (`gr_research` / skill `ghost-recon-research`): contrapartes, registros mercantiles, sanciones, tipos de cambio documentados… Las notas se guardan como `research_notes`.
8. **Pack documental:** el agente escribe los `.md` fuente en `06_Report/` siguiendo `ghost-recon-report-pack`; `gr_report_build(audit_id, formats=[md,pdf,xlsx])` genera PDF ejecutivo, workbook XLSX y MD, firma, metadatos, hashes, LEEME.
9. **Validación independiente:** `gr_swarm_plan(mode="validation")` → 2-3 validadores (`ghost-recon-validation`: A recálculo desde crudo, B consistencia, C adversarial) vía `delegate_task`; hallazgos → `validation/validation.json` (`gr_run_record`); corregir y reconstruir si tocó cifras.
10. `gr_audit_seal(audit_id)` → verifica criterios de completitud (pack presente, validación registrada, excepciones exportadas), escribe `SEALED.json`, estado `sealed`, timeline. Mensaje de cierre.

### 4.2 `/rerun-case <folder> [context.md] [--out <folder>]`

1. Skill `rerun-case`. `gr_case_open(folder)` carga el caso (o lo re-importa de `case.json`).
2. `gr_audit_start(case_id, kind="rerun", parent=<última sellada>)` → carpeta nueva `A0n_<fecha>/`; **pase de evidencia**: re-inventario del corpus, dedupe en dos niveles contra el corpus previo (hash exacto → `DUP_PRIOR`/`DUP_INTERNAL`/`UNIQUE`; por contenido para PDFs re-descargados → `DUP_CONTENT`), `Evidence_Pass/register.csv`, lista de excepciones abiertas heredadas.
3. Triage de lo nuevo (skill `ghost-recon-evidence-pass` §3), extracción con los parsers del encargo (copiados de `A0(n-1)/src/` a `src/`), cruce exacto, reclasificación.
4. Modelo con versión nueva; `version_effect.json` (partida · anterior · nuevo · documento causante); excepciones cerradas/degradadas/creadas con historia (IDs continúan).
5. Pack documental completo regenerado (nunca se copia a mano de la anterior), validación, sello. `A0(n-1)` permanece intacta; `gr_case_status` verifica sus hashes (`seal_ok`).

### 4.3 `/review-case <folder>`

1. Skill `review-case`. `gr_case_open(folder)`; `gr_review_plan(case_id)` → crea `reviews/R0n_<fecha>/`, construye **cronología** consolidada (timeline + auditorías + evolución de cada EXC/ANO entre versiones + criterios + runs de validación) en `chronology.md/.xlsx`, y devuelve `tasks[]` para 6 roles.
2. `delegate_task` con los 6 roles en paralelo (cada hijo carga `ghost-recon-role-<rol>` y lee cronología + packs sellados): **legal** (exposición, pruebas, qué pedir, riesgos procesales), **tributario** (efectos fiscales de las reclasificaciones, obligaciones, riesgos), **financiero** (posición de caja, utilidad, escenarios, sensibilidad), **auditor** (calidad de la evidencia, cobertura, qué validar más), **contable** (asientos, reclasificaciones, cierre, políticas), **mediador de conflictos** (intereses de cada parte, puntos de convergencia, propuesta de resolución escalonada).
3. El agente sintetiza el **diagnóstico** (`diagnosis.md`): hechos establecidos, qué cambió entre auditorías, mapa de riesgos por rol, recomendaciones priorizadas, lo que decide el caso y quién debe aportar qué. `gr_report_build(review_id, formats=[md,pdf,xlsx])` y `gr_audit_seal`.

## 5. Enjambre (`core/swarm.py`)

- **Bloques de extracción** se forman por tipo de documento y tamaño: `commercial` (facturas de venta, órdenes, albaranes, cobros), `supply` (facturas de compra, OC, flete, aduana, exports de portal), `banking` (extractos, tarjetas, wires/Zelle/ACH, capturas), `related_parties` (contratos, facturas de socios, actas), `ocr_vision` (escaneos/imágenes), `other`. Si un bloque supera `swarm.max_files_per_task` (default 60) se parte en `banking-1`, `banking-2`…
- Cada manifiesto `agents/manifest_<bloque>.json`: `audit_id`, `block`, `files[]` (ruta absoluta, hash, tipo), `schema` de salida, `rules` (sección 2 del método), `output_path`.
- `tasks[]` para `delegate_task`: `goal` autocontenido + `context` (rutas, reglas, instrucción de `skill_view("ghost-recon-block-auditor")`) + `output_schema` mínimo (`{block, files_processed, transactions_count, discrepancies[], output_path}`).
- **Validación**: tareas A (recálculo desde crudo, sin acceso a `model.json` — se le pasa solo rutas de evidencia y las cifras cabecera), B (consistencia entre entregables), C (adversarial: abogado/CPA de la contraparte).
- **Revisión**: 6 tareas de rol con la cronología y las rutas de los packs sellados.
- Límite: `delegation.max_concurrent_children` (Hermes, default 10); el plan respeta `swarm.max_parallel` (default 6) agrupando el resto en una segunda ola.

## 6. Investigación (`core/research.py`)

Cliente REST de Tavily (`https://api.tavily.com`): `search` (search_depth basic|advanced, topic general|news|finance, time_range, include_domains), `extract` (urls, extract_depth), `crawl`, `map`, `research` (si la cuenta lo expone). Clave: `TAVILY_API_KEY` (`.env` de Hermes) vía `agent.secret_scope.get_secret`. Cada llamada con `save=true` registra `research_notes` con hash del contenido y guarda el cuerpo en `03_Extracted_Data/research/<n>.json`. La skill `ghost-recon-research` define el protocolo OSINT financiero (identidad de contrapartes, registros mercantiles, sanciones/PEP, noticias, tipos de cambio y tarifas de referencia, benchmarks de flete) y la regla de que un resultado web es **INFERENCE** salvo documento oficial.

## 7. Reportes (`core/reports/`)

- `md.py`: ensambla el informe MD desde `06_Report/sections/*.md` o desde el `report.md` que escribió el agente; inserta tablas desde BD (excepciones, anomalías, preguntas, criterios, evidencia).
- `pdf.py`: ReportLab (fuentes DejaVu embebidas) — portada con KPIs, "la respuesta en una página", hallazgos, preguntas, método/validación; metadatos `Author/Creator/Producer = Ghost Recon`.
- `xlsx.py`: openpyxl — hojas 00_README, 02_DOCUMENT_INDEX, 30_EXCEPTIONS, 29_ANOMALIES, Q_QUESTIONS, CRIT_CRITERIA, 31_AUDIT_TRAIL, VERSION_EFFECT (rerun), DASHBOARD; `docProps/app.xml` reescrito a "Ghost Recon Audit Engine".
- `pack.py`: orquesta, firma, calcula hashes (`pack_hashes.txt`), escribe `LEEME.md`, registra en `reports`, y verifica que ningún binario contenga nombres de herramientas.

## 8. Extensiones previstas (no implementadas)

- **Kanban por caso:** `hermes project create --board <slug>`; una tarea por bloque/rol; el dispatcher de Hermes lanza workers con `--skills ghost-recon-block-auditor`. Útil cuando el enjambre deba sobrevivir a un reinicio.
- **Cron:** `hermes cron create "0 8 * * 1" --skill rerun-case "/rerun-case <folder>"` para pases semanales.
- **Web app:** exportar `case.json` + packs a la API de `ghostrecon-web-app`.
