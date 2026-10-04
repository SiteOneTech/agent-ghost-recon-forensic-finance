# ghost-recon/ + plugins/ghost_recon/ + skills/ghost-recon/ — guía de área

Aplica encima del `AGENTS.md` raíz de Hermes. Documentos: `ghost-recon/PLAN.md` (estado), `HANDOFF.md`
(reanudación), `ARCHITECTURE.md`, `COMMANDS.md`.

## Qué es

Ghost Recon es un vertical de auditoría financiera forense construido como **plugin + skills** de Hermes.
No modifica el core. Si hace falta algo que el `ctx` de plugins no ofrece, se amplía la superficie
genérica de plugins (ver `plugins/AGENTS.md`), nunca se cablea lógica Ghost Recon en el core.

## Reglas de edición

- `plugins/ghost_recon/core/` **no importa Hermes**: solo stdlib + `openpyxl`/`reportlab`/`httpx`
  (opcionales, importados perezosamente). Así se prueba con pytest puro y sobrevive a refactors del core.
- La frontera con Hermes es `plugins/ghost_recon/__init__.py`, `tools.py`, `commands.py`, `cli.py`:
  usan solo `ctx.register_*`, `ctx.get_config`, `plugins.plugin_storage.plugin_db`,
  `hermes_constants.get_hermes_home`, `agent.secret_scope.get_secret`.
- Rutas: nunca `~/.hermes` literal; la BD se abre con `plugin_db("ghost-recon", "ghostrecon.db")`.
- Toda escritura en una carpeta de auditoría pasa por `core/casefolder.py` que **rechaza** si existe
  `SEALED.json`. No añadir atajos.
- IDs de hallazgos (`EXC-nn`, `ANO-nn`, `FND-nn`, `Q-nn`, `CRIT-nn`) los asigna `core/ids.py` desde la BD;
  nunca se calculan en prosa ni en una skill.
- Entregables: ningún número tecleado; `core/reports` lee `model.json` + BD. Firma y metadatos
  "Ghost Recon"; `pack.py` falla si un binario contiene nombres de herramientas.
- Skills bundled: cumplir HARDLINE de `skills/AGENTS.md` (descripción ≤ 60 chars con punto final,
  secciones `When to Use / Prerequisites / How to Run / Quick Reference / Procedure / Pitfalls /
  Verification`, herramientas nativas en backticks). El texto largo va en `references/`.
- La consola (`plugins/ghost_recon/console/`) **solo escribe** sus tablas `console_*`, el archivo de contexto combinado
  (`<resultados>/_console/context_<hash>.md`), los eventos `console_job_*` y `results_exported` de la cronología del
  caso (con `Store.add_event`) y, bajo `<plugin-data>/ghost-recon/console/`, los ZIP de `exports/` (más su `.sha256`) y
  los archivos de `jobs/`. Solo borran esos archivos: `housekeeping.py` (retención de ZIP con `prune_exports`, que
  `ExportService` también llama tras cada construcción, y archivos de ejecuciones terminadas), `exporter.build` (su
  propio `.part`, o el ZIP si falla su `.sha256`) y `ExportService.recover` (al arrancar, todo ZIP, `.sha256` o `.part`
  que no sea de una exportación terminada); en `exports/` siempre como nombre simple vía `paths.file_inside`. Los datos
  de caso se leen por `core` (`Store`, `service`). Toda carpeta que llega del navegador pasa por `console/fsjail.resolve`
  (dentro de `case_roots`); toda descarga de un archivo de caso, por `console/paths.resolve_within`, y la de un ZIP o su
  `.sha256`, por `ExportService._inside` (nombre simple directamente dentro de `exports/`). En el frontend, nada de
  `innerHTML` con datos: siempre `h()` (`static/lib/dom.js`).
- Un archivo de una auditoría sellada solo sale de la consola tras `console/integrity.py` (descarga de entregables y ZIP):
  se vuelve a hashear contra `SEALED.json`. El ZIP solo lee la carpeta de resultados y nunca sigue enlaces.
- La raíz del repositorio ignora `export*`; `plugins/ghost_recon/console/.gitignore` los reincluye. Un módulo nuevo de la
  consola cuyo nombre empiece por `export` no necesita nada más.
- Procesos de la consola: lo que toca internos de Hermes para lanzar, vigilar o detener ejecuciones vive solo en
  `console/procs.py` (lanzador de la instalación, entorno del perfil, desacople, árbol con psutil e identidad PID +
  create time). La orden (`commands.py`), las fases (`events.py`) y los límites (`jobs.py`) son Python probado; el JS
  solo pinta. Toda escritura de estado de un job es condicional (`update_job(..., expect=...)`).
- La UI no nombra hitos ni comandos: lo que aún no existe aparece deshabilitado con el aviso «Próximamente».

## Pruebas

```bash
python -m pytest tests/plugins/ghost_recon -q                      # core puro
scripts/run_tests.sh tests/plugins/ghost_recon tests/skills -q     # con el runner oficial
python ghost-recon/demo/smoke_test.py                          # ciclo completo sin LLM
```

## Dónde está cada cosa

| Necesito… | Archivo |
|---|---|
| cambiar el esquema de la BD | `core/db.py` (`SCHEMA`, `migrate()`) + `ARCHITECTURE.md §2` |
| cambiar el layout de la carpeta del caso | `core/casefolder.py` (`AUDIT_SUBDIRS`, `audit_folder_name`) + `ARCHITECTURE.md §3` |
| cambiar cómo se forman los bloques del enjambre | `core/swarm.py` (`BLOCK_RULES`, `plan_extraction`) |
| cambiar los goals que reciben los sub-agentes | `plugins/ghost_recon/core/prompts.py` (`TEMPLATES`) |
| añadir un rol a `/review-case` | `core/review.py` (`ROLES`) + nueva skill `skills/ghost-recon/ghost-recon-role-<rol>/` |
| cambiar la portada/hojas del pack | `core/reports/pdf.py`, `xlsx.py` |
| cambiar el texto de identidad del agente | `plugins/ghost_recon/prompts.py` (`SYSTEM_SECTION`), `ghost-recon/config/SOUL.md` |
| añadir un endpoint a la consola | `console/routers/<recurso>.py` + `console/readmodel.py` (lógica pura) + `ROUTERS` en `console/app.py` |
| cambiar login, roles o sesiones de la consola | `console/auth.py`, `console/deps.py` (`require`, CSRF) |
| cambiar una pantalla de la consola | `console/static/views/*.js` (pestañas del caso en `views/case/`) y `static/app.css` |
| cambiar colores/logo de la consola | `console/static/theme.css` (variables) |
| cambiar una orden lanzable o su texto `-q` | `console/commands.py` (`ORDERS`, `build_query`) + la skill de la orden |
| cambiar cómo se deducen las fases o el feed de una ejecución | `console/events.py` (`PHASES`, `_FIXED_PHASE`, `_SUMMARY`) |
| cambiar límites, cola, cancelación o huérfanos | `console/jobs.py` (`JobService`) y `console/job_runner.py` |
| cambiar qué carpetas ve el navegador de la consola | `console/fsjail.py` y `case_roots` en la configuración |
| cambiar qué entra en el ZIP de resultados o su manifiesto | `console/exporter.py` (`select`, `plan_entries`, `build`); la cola y las filas en `console/exports.py` |
| cambiar las columnas o los formatos de las tablas exportables | `console/tables.py` (`TABLES`, `to_csv`, `to_xlsx`); las filas en `console/readmodel.py` (`TABLE_ROWS`) |
| cambiar la búsqueda entre casos | `console/search.py` (`SOURCES`, límites) |
| cambiar el aviso al terminar una ejecución | `console/commands.py` (`notify_args`) y `console/job_runner.py` (`notify_message`, `_notify`) |
| cambiar la limpieza periódica (sesiones, ZIP, archivos de ejecuciones) | `console/housekeeping.py` |
