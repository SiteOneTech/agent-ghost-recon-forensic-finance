# HANDOFF — cómo retomar este trabajo desde un IDE u otro agente

Este documento existe para que, si la sesión que construyó Ghost Recon sobre Hermes se corta, otro agente (Claude Code, Cursor, Hermes mismo, un humano) pueda continuar sin perder el hilo. Léelo completo antes de tocar nada.

## 0. Orden de lectura (10 minutos)

1. `ghost-recon/PLAN.md` — objetivo, decisiones D1–D11 y **la sección 2 "Fases y estado"** (qué está hecho).
2. `ghost-recon/ARCHITECTURE.md` — componentes, modelo de datos, flujos de cada comando, layout de la carpeta del caso.
3. `ghost-recon/COMMANDS.md` — contrato exacto de `/new-open-case`, `/rerun-case`, `/review-case`, `/gr-*` y `hermes ghostrecon`.
4. `ghost-recon/AGENTS.md` — reglas de edición y pruebas para este área.
5. El código: `plugins/ghost_recon/` y `skills/ghost-recon/`.
6. `AGENTS.md` raíz de Hermes (invariantes del proyecto: no tocar core, caching, HARDLINE de skills).

## 1. Estado del repositorio local en la máquina de Jean (`D:\Source-Code\agent-ghost-recon-forensic-finance`)

Durante la sesión original, el shell remoto no pudo montar esa carpeta (bug de Windows Update del 8-sep-2026 reportado por el puente de Cowork), así que el fork completo se clonó **en el workspace cloud** (rama `ghost-recon`, un commit) y los archivos Ghost Recon se copiaron a disco con el puente de archivos. Mientras tanto, en esa carpeta aparecieron **dos clones del repo base** hechos a mano: `agent-ghost-recon-forensic-finance\` y `agent-ghost-recon-forensic-finance-1\` (cada uno con su `.git`, rama `main` de origin).

Resultado en disco (2-oct-2026):

| Ruta | Qué contiene |
|---|---|
| `D:\Source-Code\agent-ghost-recon-forensic-finance\` (raíz) | SOLO los archivos Ghost Recon (`ghost-recon/`, `plugins/ghost_recon/`, `skills/ghost-recon/`, `tests/...`, `AGENTS.md`) — sin el repo base |
| `D:\Source-Code\agent-ghost-recon-forensic-finance\agent-ghost-recon-forensic-finance\` | **Clon completo del fork + los archivos Ghost Recon encima** (working tree listo; cambios sin commitear) |
| `D:\Source-Code\agent-ghost-recon-forensic-finance\agent-ghost-recon-forensic-finance-1\` | Clon completo del fork SIN Ghost Recon (duplicado; puede borrarse) |

**Para dejar un solo repo limpio** (PowerShell):

```powershell
cd D:\Source-Code\agent-ghost-recon-forensic-finance\agent-ghost-recon-forensic-finance
git status --short | Select-Object -First 5        # debe listar ghost-recon/, plugins/ghost_recon/, skills/ghost-recon/ ...
git checkout -b ghost-recon
git add ghost-recon plugins/ghost_recon skills/ghost-recon tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py AGENTS.md
git commit -m "feat(ghost-recon): Ghost Recon forensic-audit agent on Hermes (plugin + skills + docs)"
# opcional: mover este clon a la raíz y borrar la copia -1 y los archivos sueltos de la raíz
```

**Alternativa con historial exacto de la sesión:** `git fetch ghost-recon\ghost-recon.bundle ghost-recon:ghost-recon && git checkout ghost-recon` (el bundle contiene el commit `feat(ghost-recon)…` sobre `main` de origin; `ghost-recon.patch` es el mismo cambio en formato `git am`).

## 2. Convención de estado

- El avance se marca en `PLAN.md §2` con `[ ] [~] [x] [!]`. Al terminar un paso: marcar `[x]`, y si cambió una decisión, anotarla en `PLAN.md §0` y en `§4 Registro de cambios`.
- Cada módulo de `plugins/ghost_recon/core/` tiene docstring con su contrato. Si no existe el archivo, el paso de PLAN está pendiente de verdad.
- Los tests son la definición de "hecho": `tests/plugins/ghost_recon/` debe pasar.

## 3. Cómo probar sin la máquina autónoma

```bash
# Core puro (no requiere el venv de Hermes):
cd <repo>
python -m pytest tests/plugins/ghost_recon -q

# Con el runner oficial (requiere .venv construido con PM; ver AGENTS.md raíz § Testing):
python -m pm.build_env --source . --out .venv --group dev --group test
scripts/run_tests.sh tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py tests/skills/test_authoring_standards.py -q

# Smoke test del ciclo completo sin LLM (core + CLI):
python -m plugins.ghost-recon.cli --help          # no: el paquete tiene guion; usar:
python ghost-recon/demo/smoke_test.py          # abre caso demo, auditoría, pack, sello, rerun, review
```

## 4. Qué falta probar en la máquina real (requiere API keys)

1. `bash ghost-recon/install.sh` (o `install.ps1`) → `hermes plugins list` muestra `ghost-recon` enabled; `hermes skills list` muestra la categoría `ghost-recon`.
2. `hermes` → `/gr-doctor` → todo OK (BD, fuentes, openpyxl, reportlab, TAVILY_API_KEY).
3. `/new-open-case ghost-recon/demo/demo-case` → debe terminar con el pack en `GhostRecon_Audits/A01_<fecha>/06_Report/` y `SEALED.json`.
4. `/rerun-case ghost-recon/demo/demo-case` tras añadir un archivo nuevo a `evidence/` → `A02_<fecha>` nueva, `A01` intacta (`gr_case_status` → `seal_ok: true`).
5. `/review-case ghost-recon/demo/demo-case` → `GhostRecon_Audits/reviews/R01_<fecha>/` con 6 opiniones de rol + diagnóstico.

## 5. Reglas que no se negocian (heredadas del método Ghost Recon)

- La evidencia original jamás se modifica, renombra, mueve ni borra.
- Una auditoría sellada no se edita: se crea otra.
- Ningún número se teclea a mano en un entregable: todo sale del modelo JSON y de la BD.
- Lenguaje forense neutral (unexplained / unreconciled / undocumented…), etiquetas FACT/CALCULATION/INFERENCE/ALLEGATION/UNKNOWN y confianza en cada conclusión.
- Validación independiente obligatoria antes de sellar.
- Ningún nombre de proveedor de modelo ni de librería en textos o metadatos de los entregables.

## 6. Contacto del contexto

Proyecto Claude "Ghost Recon Agent V3" (metodologías `methodology/*.md`, skills `skills/ghost-recon-*`), propietario Jean C. Garcia (Sitio Uno / Ghost Recon, https://www.ghostrecon.ai/).
