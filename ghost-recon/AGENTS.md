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
