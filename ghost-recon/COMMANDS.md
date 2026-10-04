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

## 3b. Consola web

```
hermes ghostrecon serve [--host 127.0.0.1] [--port 9230] [--allow-remote]
hermes ghostrecon user add <nombre> [--role admin|viewer] [--password-stdin]
hermes ghostrecon user list | passwd <nombre> [--password-stdin] | disable <nombre> | enable <nombre>
hermes ghostrecon token create --user <nombre> --name <etiqueta>     (Bearer; se muestra una sola vez)
hermes ghostrecon token list | token revoke <id>
```

- Escucha en `127.0.0.1:9230`. Desde otra PC se entra por túnel: `ssh -L 9230:127.0.0.1:9230 usuario@maquina` y luego `http://localhost:9230`.
- `serve` no arranca sin un admin activo: el primero se crea con `user add … --role admin`; los demás usuarios y los tokens también se gestionan desde **Sistema › Usuarios y tokens** (solo admin). Fuera de loopback exige `--allow-remote` y un proxy TLS delante.
- `--role` es opcional (por defecto `viewer`). `user passwd <nombre> --password-stdin` lee la nueva contraseña de stdin (una línea), igual que `user add`.
- `--allow-remote` con `0.0.0.0` o una IP de Tailscale también exige listar ese nombre o IP en `allowed_hosts`; si no, la consola responde 400 `bad_host`.
- Seguridad de la cookie: la sesión usa una cookie `gr_session_<puerto>` (una por consola) HttpOnly y SameSite=Strict, pero, como cualquier cookie de localhost, también se envía a otros puertos locales. En una PC compartida usa el túnel SSH hacia un puerto local dedicado y pulsa «Salir» al terminar. Solo lo que hace el usuario renueva la sesión: las actualizaciones automáticas de la página y la vista en vivo no la mantienen abierta, así que una pestaña olvidada caduca a las 12 h de inactividad.
- Roles: `viewer` lee, sigue las ejecuciones, busca entre casos, descarga entregables de auditorías selladas, exporta tablas (CSV/XLSX) y exporta el `.zip` de las auditorías selladas; `admin` además lanza y cancela ejecuciones, descarga entregables de auditorías abiertas, incluye auditorías abiertas (como borrador) en un `.zip` y es el único que consulta y descarga esas exportaciones `DRAFT` (un viewer recibe 403 y el intento queda en el registro como `export_download_denied`), gestiona usuarios y tokens y ve el registro de la consola. Nadie se deshabilita ni se cambia el rol a sí mismo, y el último admin activo no se puede deshabilitar ni degradar; esa comprobación está serializada, así que dos admins que actúan a la vez el uno sobre el otro nunca dejan cero admins.
- **Ejecuciones desde la consola** («+ Nueva auditoría» y, en la página del caso, «▶ Re-run» y «▶ Review»):
  - el navegador de carpetas solo ve las carpetas de `case_roots`; la evidencia se copia antes a una de ellas (RustDesk/SFTP). La consola no sube archivos. El jail también contiene las uniones NTFS (junctions) y los archivos que son enlaces simbólicos: nada que apunte fuera de `case_roots` se lista, cuenta, mide ni busca;
  - cada ejecución corre `<hermes> -p <perfil> --cli --accept-hooks --skills <orden> chat -q "/<orden> …" --format stream-json --source ghost-recon-console` en su propio proceso (`job_runner`), así que sobrevive a cerrar el navegador y a reiniciar la consola. La vista previa muestra exactamente esa orden;
  - el agente arranca en un directorio de trabajo propio de cada ejecución (`console/jobs/<id>/`), nunca en la carpeta de evidencia: un `AGENTS.md`, `CLAUDE.md` o `.cursorrules` dejado entre la evidencia nunca se convierte en instrucciones y una escritura con ruta relativa nunca toca la evidencia (la carpeta del caso viaja en el `-q`);
  - el runner solo es dueño de una ejecución cuando el `runner_pid` de la fila es el suyo o el de su proceso padre (un único salto de lanzador: el redirector del venv en Windows); el servidor graba el PID que lanzó;
  - las «Notas adicionales» se guardan en `<carpeta de resultados>/_console/context_<hash>.md`, con el `context.md` original literal y su SHA-256; el agente las registra como criterio del operador (`CRIT-nn`), nunca como hecho. El `context.md` original no se toca;
  - la carpeta de resultados debe quedar dentro de `case_roots`: `--out` nunca puede ser la carpeta de evidencia ni una carpeta dentro de ella (422), y un caso que solo se conoce por su `case.json` usa siempre `<carpeta>/GhostRecon_Audits` (el `out_dir` del espejo se ignora); si la de un caso de la BD queda fuera, la consola no lanza (409) y la orden se lanza desde la terminal;
  - los lanzamientos de `/new-open-case` desde la consola siempre pasan `--out` (la carpeta elegida por el operador o, si no, `<carpeta>/GhostRecon_Audits`), así que los resultados nunca caen en una ubicación improvisada por el agente;
  - límites: una ejecución activa por carpeta o caso y `max_parallel_jobs` en total (por defecto 2); lo demás queda en cola y arranca solo;
  - «Cancelar» detiene el agente y todo lo que lanzó; la auditoría a medio hacer queda abierta, sin sellar, y el siguiente Re-run la continúa. Una ejecución cuyo proceso desaparece sin cerrar queda «interrumpida» (huérfana) y su agente se detiene;
  - la vista en vivo (SSE) lee la fila de la ejecución antes que los eventos y termina solo cuando una fila ya terminal va seguida de una lectura vacía, así que no se pierde ningún evento final;
  - «Continuar en terminal» copia `hermes -p <perfil> --resume <session_id>`; con `dashboard_url`, «Continuar en chat» abre la sesión en el dashboard;
  - archivos de cada ejecución en `<plugin-data>/ghost-recon/console/jobs/`: `<id>.jsonl` (salida del agente), `<id>.log` (errores del agente), `<id>.events.jsonl` (actividad), `<id>.runner.log` y `<id>/` (directorio de trabajo del agente).
- **Exportar resultados (.zip)** (encabezado del caso, «ZIP de A0n» en cada auditoría y el resultado de una ejecución):
  - el diálogo muestra antes qué entra y qué queda fuera y por qué; por defecto solo auditorías **selladas**; un admin puede incluir las abiertas, que salen marcadas `DRAFT` (y el nombre del ZIP lleva `-DRAFT`); mientras el caso tiene una ejecución en cola o en curso, sus auditorías abiertas nunca entran, ni `case.json` ni `corpus_inventory.csv` (el agente puede estar reescribiéndolos: el diálogo los lista en «Queda fuera» y el manifiesto en `skipped`);
  - el ZIP lleva `case.json`, `corpus_inventory.csv`, `_console/`, las carpetas completas de las auditorías elegidas (las revisiones incluidas) y `EXPORT_MANIFEST.json` (cada archivo con su tamaño y SHA-256; cada auditoría con su sello y la hora de la verificación). Nunca la evidencia original: solo se lee la carpeta de resultados, los enlaces simbólicos y las uniones NTFS no se siguen (quedan listados en `skipped`) y una carpeta de resultados que contenga la del caso se rechaza;
  - antes de empaquetar se verifican todos los sellos y, al empaquetar, cada archivo sellado se vuelve a hashear: un sello roto o un archivo que cambia durante la exportación la detiene y nombra el archivo, sin dejar ZIP;
  - se construye en segundo plano, una exportación a la vez y como mucho una pendiente por caso (mientras otra está en cola o construyéndose, el diálogo responde «Ya hay una exportación en curso para este caso (#n)»), con progreso por archivos y ZIP64; queda en `<plugin-data>/ghost-recon/console/exports/GhostRecon_<slug>_<case|A0n>_<YYYYMMDD-HHMM>.zip` (hora UTC) con `<zip>.sha256` al lado. Comprobación al recibirlo: `sha256sum -c GhostRecon_….zip.sha256` (en Windows, `Get-FileHash -Algorithm SHA256`);
  - un reinicio de la consola durante una construcción la deja «fallida» (hay que volver a exportar); se conservan como mucho las últimas `export_retention.count` (20) y ninguna con más de `export_retention.days` (30) días, comprobado al terminar cada exportación y cada hora; al arrancar se borra todo ZIP, `.sha256` o `.part` de `exports/` que no pertenezca a una exportación terminada;
  - cada exportación queda en el registro de la consola (`export_request`, `export` o `export_failed`, `export_download`) y en la Cronología del caso (`results_exported`, con el SHA-256 del ZIP y el usuario).
- **Tablas a CSV/XLSX:** Hallazgos, Evidencia, Cronología y Criterios descargan lo que muestra la tabla con sus filtros (la Evidencia completa, no solo la página cargada). El CSV va en UTF-8 con BOM, separado por comas: un Excel en español puede abrirlo en una sola columna; en ese caso usa el XLSX o «Datos › Desde texto». Un texto que empieza por `=`, `+`, `-` o `@` sale con un apóstrofo delante para que nunca se ejecute como fórmula. El XLSX lleva los metadatos «Ghost Recon» del pack y necesita `openpyxl` (dependencia del plugin); sin él la consola responde «Falta openpyxl…» y el CSV sigue disponible.
- **Búsqueda entre casos** (barra superior): casos por nombre, ID o carpeta; hallazgos por ID, título o contraparte; evidencia por ruta, nombre o hash; criterios por ID, texto o autor. Cada resultado lleva a la pestaña del caso. Sin distinguir mayúsculas ni acentos («conciliacion» encuentra «Conciliación»; igual en los filtros de texto de Casos, Hallazgos y Evidencia). Mínimo 2 caracteres y 2 s de recorrido; la barra superior muestra hasta 8 resultados por tipo (la API, `GET /search?limit=`, da 10 por defecto y como mucho 50). En **Casos**, el filtro «Riesgo abierto» deja los casos con hallazgos abiertos de ese riesgo.
- **Avisos al terminar una ejecución:**
  - en el navegador: «Avisarme al terminar» (barra superior) más el permiso del navegador, mientras la consola está abierta. Los navegadores solo notifican en `https` o en `localhost`: por eso funciona a través del túnel SSH (`http://localhost:9230`) y no por una IP de Tailscale sin TLS;
  - por gateway: con `notify_target` configurado, el runner ejecuta `hermes -p <perfil> send --to <notify_target> --subject "[Ghost Recon]" "<resumen>"` cuando la ejecución termina o falla (no si se cancela o queda interrumpida). No usa LLM ni necesita el gateway en marcha; un fallo del envío queda en `<id>.runner.log` y nunca cambia el estado de la ejecución.
- **Descargas comprobadas:** el entregable de una auditoría sellada se vuelve a hashear al descargarlo y debe coincidir con `SEALED.json` y con el hash del pack; si no, la consola responde «El entregable no coincide con el sello…» (409 `hash_mismatch`). Toda descarga rechazada queda en el registro como `report_download_denied`.
- **Mantenimiento:** al arrancar y cada hora la consola borra las sesiones vencidas o revocadas, los ZIP fuera de retención y los archivos de las ejecuciones terminadas hace más de `export_retention.days` días (las filas de esas ejecuciones, con su resultado y sus tokens, se conservan).
- Presupuesto de delegación: la consola requiere `delegation.oneshot_max_children: 100` en `config.yaml`; cada ejecución es una sesión de un solo disparo (`chat -q`) y Hermes limita el total de sub-agentes de esas sesiones a 2 por defecto, lo que deja sin enjambre ni validación A/B/C (el agente se niega a sellar). Lo fijan `config.ghost-recon.yaml` y los instaladores; `/gr-doctor` lo comprueba.
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
          notify_target: telegram                            # opcional: hermes send al terminar ("" = sin aviso)
          export_include_unsealed: false                     # valor inicial de la casilla (solo admins)
          export_retention: {count: 20, days: 30}            # ZIP y archivos de ejecuciones antiguos
          # además: host, port, session_idle_hours, session_max_days, allowed_hosts
```

- **Máquina dedicada (Linux):** la consola corre como servicio systemd con el usuario `ghostrecon` y `HERMES_HOME=/home/ghostrecon/.hermes`. El agente y el runner se lanzan con el lanzador de la instalación (`<checkout>/.hermes/bin/hermes`), nunca con lo que haya en el `PATH`. La unidad necesita `KillMode=process`: con el valor por defecto (`control-group`), `systemctl restart` mataría también las auditorías en curso. Si `config.yaml` fija `max_concurrent_sessions`, ese límite también cuenta las ejecuciones de la consola (una que no cabe queda «fallida», con el motivo en el log técnico).
- Demo local sin LLM (agente simulado y carpeta de casos temporal): `python ghost-recon/demo/console_demo.py`. Debe ejecutarse con el Python del runtime de Hermes (o del venv de pruebas), porque necesita psutil: en Windows de desarrollo `.venv/Scripts/python.exe ghost-recon/demo/console_demo.py`; en una instalación de Hermes, el intérprete del lanzador de PM. Con el Python del sistema, sin psutil, el lanzamiento responde 500.
- Diseño completo y próximo hito (instaladores con `--console` y servicio, `CONSOLE.md`, aceptación en la máquina dedicada): `ghost-recon/specs/2026-10-02-ghost-recon-console-design.md`.

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
