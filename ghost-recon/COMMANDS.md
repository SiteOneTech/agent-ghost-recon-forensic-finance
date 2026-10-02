# Ghost Recon — Contrato de comandos

Los comandos se escriben igual en CLI, TUI, Desktop y gateway (Telegram acepta `/new_open_case`, Hermes normaliza `_` ≡ `-`).

## 1. Órdenes principales (skills → turno del agente)

### `/new-open-case <folder> [context.md] [--out <folder>] [--name "<nombre>"] [--currency USD] [--lang es|en]`

Abre (o carga) el caso anclado a `<folder>` y ejecuta una **auditoría completa** sobre la evidencia que contiene.

- `<folder>`: carpeta de evidencia (absoluta o relativa al cwd del agente). Es la identidad del caso.
- `context.md` (opcional): ruta a un Markdown con contexto (quién pide, qué se investiga, período, moneda, socios, criterios). Si no se pasa y existe `<folder>/context.md`, se usa.
- `--out`: carpeta de salidas distinta de `<folder>/GhostRecon_Audits/`.
- Resultado: `A01_<fecha>/` con pack documental (`06_Report/`), validación y `SEALED.json`. Mensaje de cierre con respuestas cabecera, abiertos y quién aporta qué.
- Si el caso ya existe con una auditoría sellada, el agente **no** reabre: informa y sugiere `/rerun-case`.

### `/rerun-case <folder> [context.md] [--out <folder>]`

Caso ya abierto. Busca evidencia nueva en `<folder>` (y subcarpetas, ZIPs), la deduplica contra el corpus auditado, y produce una **nueva auditoría** `A0n_<fecha>/` con el pack completo. La auditoría anterior no se toca (se verifica su sello).

- Si no hay evidencia nueva (100 % duplicados) igualmente registra el pase y genera un pack mínimo (registro de evidencia + nota) — el registro con hash es la prueba de que se revisó.
- `context.md` nuevo (p. ej. respuesta de la contraparte, criterios de la gerencia) se registra como `CRIT-nn`/declaraciones, nunca como hecho.

### `/review-case <folder>`

Análisis completo del caso: **cronología** de todas las auditorías (qué llegó, qué cambió, excepciones abiertas/cerradas/degradadas, criterios, validaciones) + **opinión y diagnóstico desde seis roles** (legal, tributario, financiero, auditor, contable, mediador de conflictos) + **recomendaciones** priorizadas. Salida en `GhostRecon_Audits/reviews/R0n_<fecha>/` (md, pdf, xlsx) y sello.

## 2. Comandos informativos del plugin (texto, sin turno del agente)

| Comando | Qué devuelve |
|---|---|
| `/gr-cases` | Lista de casos (id, nombre, carpeta, nº auditorías, última, estado). |
| `/gr-case <id\|folder>` | Estado del caso: auditorías con estado y sello verificado, excepciones abiertas por riesgo, última validación, rutas del último pack. |
| `/gr-help` | Esta ayuda resumida. |
| `/gr-doctor` | Diagnóstico: BD, dependencias (openpyxl, reportlab), fuentes, `TAVILY_API_KEY`, `web.backend`, skills instaladas, límites de delegación. |

## 3. CLI (sin agente)

```
hermes ghostrecon init                       crea la BD y verifica dependencias
hermes ghostrecon doctor
hermes ghostrecon cases [--json]
hermes ghostrecon case <id|folder> [--json]
hermes ghostrecon audits <id|folder>
hermes ghostrecon timeline <id|folder> [--json]
hermes ghostrecon verify <audit_id>          verifica el sello (hashes) de una auditoría
hermes ghostrecon export <id|folder> --out <file.json>
hermes ghostrecon import <case.json>         re-importa un caso desde su espejo
```

## 4. Herramientas del agente (toolset `ghost_recon`)

Todas devuelven JSON. Errores: `{"error": "…"}`.

| Tool | Entrada | Salida |
|---|---|---|
| `gr_case_open` | `folder`, `context_md?`, `name?`, `base_currency?`, `language?`, `out_dir?` | caso, conteos de evidencia, auditorías existentes, `next_step` |
| `gr_case_status` | `case` (id o folder) | estado completo + `seal_ok` por auditoría |
| `gr_case_list` | — | lista |
| `gr_audit_start` | `case_id`, `kind` (initial\|rerun\|review), `context_md?`, `out_dir?` | `audit_id`, `folder`, evidencia nueva/duplicada, excepciones heredadas |
| `gr_evidence_index` | `audit_id`, `status?`, `block?`, `limit?` | filas de evidencia (ruta, hash, tipo, estado) |
| `gr_finding_upsert` | `audit_id`, `findings[]` (kind, id?, title, …) | ids asignados/actualizados |
| `gr_criteria_add` | `audit_id`, `author`, `text`, `date?` | `CRIT-nn` |
| `gr_research` | `action` (search\|extract\|crawl\|map\|research), `query?`, `urls?`, `options?`, `audit_id?`, `save?` | resultados Tavily (+ nota registrada) |
| `gr_swarm_plan` | `audit_id`, `mode` (extraction\|validation\|review), `max_parallel?` | `tasks[]` para `delegate_task` + manifiestos escritos |
| `gr_run_record` | `audit_id`, `kind`, `role?`, `status`, `summary`, `output?` | id de run |
| `gr_report_build` | `audit_id`, `formats?` [md,pdf,xlsx], `report_md?`, `model_json?`, `title?` | archivos, hashes, avisos de QA |
| `gr_audit_seal` | `audit_id`, `force?` | `SEALED.json`, criterios de completitud evaluados |
| `gr_review_plan` | `case_id`, `roles?` | `review_id`, carpeta, cronología escrita, `tasks[]` |
| `gr_timeline` | `case` | eventos cronológicos + evolución de hallazgos |

## 5. Recetas

- **Pase de evidencia semanal:** `hermes cron create "0 8 * * 1" "/rerun-case D:\\Casos\\FlexiPOS" --deliver origin`
- **Desde Telegram:** `/new_open_case /srv/casos/acme context.md`
- **Solo investigar una contraparte:** pedir al agente "investiga Acme Ltd con gr_research y registra las notas en la auditoría A02".
