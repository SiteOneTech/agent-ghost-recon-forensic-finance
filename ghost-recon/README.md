# Ghost Recon Agent — sobre Hermes

Vertical de **auditoría financiera forense autónoma** construido encima de [Hermes Agent](../README.md) sin tocar su core: un plugin, dieciocho skills, un instalador y la documentación para que cualquier agente o persona retome el trabajo.

| Quiero… | Lee / ejecuta |
|---|---|
| Entender qué se construyó y qué falta | [`PLAN.md`](PLAN.md) §2 (estado) y §0 (decisiones) |
| Retomar el trabajo desde un IDE u otro agente | [`HANDOFF.md`](HANDOFF.md) |
| Ver cómo encaja todo (BD, carpeta del caso, flujos, enjambre, reportes) | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Saber qué hacen `/new-open-case`, `/rerun-case`, `/review-case`, `/gr-*`, `hermes ghostrecon` y las tools `gr_*` | [`COMMANDS.md`](COMMANDS.md) |
| Instalar en la máquina autónoma | `bash ghost-recon/install.sh --tavily-key <KEY>` · Windows: `powershell -ExecutionPolicy Bypass -File ghost-recon\install.ps1 -TavilyKey <KEY>` |
| Operar desde el navegador (consola web): lanzar auditorías, seguirlas en vivo y consultar casos | `case_roots` en `config.yaml`, `hermes ghostrecon user add <nombre> --role admin` y `hermes ghostrecon serve` → `http://localhost:9230` (por túnel desde otra PC) · [`COMMANDS.md`](COMMANDS.md) §3b · demo: `python ghost-recon/demo/console_demo.py` |
| Probar sin modelo (ciclo completo en un caso sintético) | `python ghost-recon/demo/smoke_test.py` |
| Correr los tests | `python -m pytest tests/plugins/ghost_recon tests/skills/test_ghost_recon_skills.py -q` |
| Editar el código con las reglas del área | [`AGENTS.md`](AGENTS.md) |

## Mapa rápido

```
plugins/ghost_recon/        plugin Hermes: tools gr_* · /gr-* · hermes ghostrecon · system prompt · core/ (sin dependencias de Hermes)
skills/ghost-recon/         new-open-case · rerun-case · review-case · método · técnicas · entregables · pase de evidencia ·
                            respuesta de contraparte · block-auditor · validation · research · report-pack · role-{legal,tax,financial,auditor,accounting,mediator}
ghost-recon/                docs, instalador, config (SOUL.md, config fragment, env.example), demo/ (demo-case, smoke_test.py)
tests/plugins/ghost_recon/  tests del core, servicio, reportes, Tavily y registro del plugin
tests/skills/test_ghost_recon_skills.py
```

## Flujo en una frase

`/new-open-case <carpeta>` → caso + inventario con hashes → auditoría `A01` → enjambre de auditores por bloque (`delegate_task`) → modelo único → excepciones/anomalías/preguntas en la BD → investigación Tavily con proveniencia → pack md/pdf/xlsx firmado → validación independiente A/B/C → **sello inmutable**. `/rerun-case` repite con la evidencia nueva en una auditoría nueva; `/review-case` cruza todas las auditorías con seis roles y emite el diagnóstico.

Ghost Recon · https://www.ghostrecon.ai/ · Sitio Uno, Inc.
