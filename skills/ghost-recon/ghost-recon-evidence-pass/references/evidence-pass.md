# Ghost Recon — Procedimiento de pase de evidencia (Evidence Pass) — referencia íntegra

**Versión 1.3 · origen: pase NEW-EVIDENCE-9-22 del caso FlexiPOS (2025 v3 / 2026 v4 / Definitivo v2) y sus complementos del mismo día.** Aplica cuando llega un lote nuevo de documentos a una auditoría Ghost Recon que ya tiene entregables (versión N). En Hermes, cada pase es una **auditoría nueva** (`/rerun-case` → `gr_audit_start(kind="rerun")`); la auditoría sellada no se edita. Complementa `ghost-recon-forensic-audit` §11 y `ghost-recon-deliverables`.

## 0. Preparación

- Localizar la raíz del caso, la auditoría sellada anterior (`A0(n-1)_<fecha>/`), su modelo (`03_Extracted_Data/model.json`), sus workbooks y sus scripts `src/` (el plugin copia `src/` a la auditoría nueva). Si los datos intermedios no existen, reconstruir el índice de movimientos desde el workbook y desde `agents/*.json`.
- Registrar **quién aportó** el lote y **cuándo** (preguntar si no consta; provisionalmente "gerencia, <fecha>") → `gr_run_record(kind="intake")`.
- Leer el §00/§0 del informe MD vigente y la lista de excepciones abiertas (`Evidence_Pass/inherited_open_findings.json`): el pase se evalúa contra ellas.

## 1. Intake e integridad

- `gr_audit_start(kind="rerun")` inventaría **todo el corpus** (carpetas de evidencia + miembros de todos los ZIP; excluye las carpetas de salida) con SHA-256 y MD5, tamaño, fecha y ruta → `01_Source_Index/corpus_inventory.csv`, `Evidence_Pass/register.csv`.
- Cada archivo del lote nuevo recibe fila en el **registro de evidencia** con su hash, estado y referencia. Los originales no se tocan (trabajar sobre texto extraído en `02_Working_Copies/`).

## 2. Deduplicación en dos niveles

1. **Hash exacto** contra el corpus → `DUP_PRIOR` (idéntico a un archivo ya auditado, cualquier carpeta o ZIP), `DUP_INTERNAL` (repetido dentro del lote), `NEW`. Un archivo ya auditado que sigue en su ruta queda `REGISTERED`; si su contenido cambió queda `MODIFIED` (hallazgo: la evidencia cambió).
2. **Contenido**: para los `NEW` que parezcan documentos ya vistos (mismo tipo, cuenta y período; típicamente PDF re-descargados del banco), texto extraído y comparado → `DUP_CONTENT`. Lo demás es `NEW`.
3. Resultado en `Evidence_Pass/dedupe.json` y en la hoja de evidencia del workbook. Un lote 100 % duplicado también se registra: el registro con hash es la prueba de que se revisó.

## 3. Triage de lo nuevo

- Clasificar cada documento nuevo por bloque (bancos/tarjetas; comercial; suministro; partes relacionadas; **listados** del banco como wires, Zelle, ACH; declaraciones) y anotar **qué excepción abierta podría resolver** (p. ej. "listado de wires → EXC-12 salidas sin beneficiario") → `Evidence_Pass/triage.md`.
- Decidir a qué período/versión alimenta cada uno (un lote puede tocar dos ejercicios).

## 4. Extracción con los parsers del encargo

- Extractos bancarios: parser por secciones; **cuadre al centavo** (anterior + depósitos − retiros − cheques = nuevo) antes de usar el extracto; continuidad con el mes anterior y siguiente.
- Tarjetas: cuadre de cargos parseados contra "Total New Charges"/"New Charges" y pagos.
- Listados (wires, Zelle): comprobar que el número de filas parseadas = el declarado por el listado; normalizar beneficiarios a un catálogo único.
- Guardar todo en `03_Extracted_Data/agents/*.json` con proveniencia (documento, página/fila). Con muchos documentos nuevos, `gr_swarm_plan(mode="extraction")` (solo evidencia nueva) → `delegate_task`.

## 5. Cruce con lo existente

- Clave exacta: fecha (±2 días por posteo), importe, cuenta, referencia. Nunca por similitud.
- **Completitud en ambos sentidos**: cada fila del listado tiene movimiento en los extractos y cada movimiento del tipo tiene fila en el listado. Lo que no cruza es excepción.
- Los listados de beneficiarios no cubren ACH ni entradas: declararlo.

## 6. Reclasificación (reglas)

- Beneficiario → categoría: socio, parte relacionada, proveedor con factura (gasto/COGS), proveedor sin factura (`pendiente`), tercero sin soporte (`pendiente`).
- **Un beneficiario probado por el banco no establece la naturaleza del pago**: sin factura, contrato o acta queda "concepto pendiente" y se presentan los escenarios (gasto / pago a socio / reembolso).
- Las **estimaciones se sustituyen por datos reales** en cuanto existen y se muestra la diferencia.
- Pagos de pasivos de años anteriores siguen siendo no-P&L aunque el listado los identifique.
- Nada se edita a mano en un entregable: todo cambio pasa por el modelo.

## 7. Modelo y efecto de versión

- Re-correr el modelo completo en la auditoría nueva; `model.json` con `version_effect`: partida · valor anterior · valor nuevo · diferencia · documento causante · hoja. Incluir la regla de lectura "donde diga X, léase Y" para las secciones no reescritas.
- Excepciones: cerrar, degradar o crear con historial mediante `gr_finding_upsert` (los IDs continúan la serie del caso; el historial lo guarda la BD); conteos **calculados desde la hoja**, nunca tecleados.
- Posición de los socios: recalcular en **las dos bases** cuando un criterio está pendiente y con la misma base en las cabeceras de todos los documentos; escenario alternativo cuando la naturaleza de un pago está pendiente.

## 8. Regeneración de entregables

- Pack completo nuevo con `gr_report_build` (informe MD con `§00` al inicio: tabla anterior→nuevo→por qué y **notas vN al inicio de cada sección cuyo texto quedó obsoleto**; workbook con hojas de evidencia, cruce y VERSION_EFFECT; PDF ejecutivo reconstruido desde el modelo con portada de 4 KPI en la **misma base**, "en una página", "qué cambió", hallazgos, continuidad, preguntas abiertas, método y validación, alcance). Nunca se copia a mano un entregable de la auditoría anterior.
- Metodología: sección nueva con el procedimiento aplicado; anexo de entregables con versiones.
- Metadatos y firma Ghost Recon en todos; cero nombres de herramientas (el plugin lo verifica).

## 9. Validación independiente (obligatoria)

`gr_swarm_plan(mode="validation")` → **Auditor A** (recálculo desde crudo, sin acceso al modelo), **Auditor B** (consistencia: cifras iguales entre workbook, MD y PDF; IDs y conteos; textos obsoletos; aritmética interna; lenguaje neutral; nombres de herramientas), **Auditor C** (adversarial: cada cifra y cada ID de las páginas nuevas contra el documento original y contra la hoja/fila citada; afirmaciones que sobrepasan la evidencia). Corregir, re-correr, y registrar las rondas con `gr_run_record(kind="validation")`.

## 10. Cierre

- Paquete `Evidence_Pass/` (registro con hash, inventario del corpus, dedupe, triage, modelo del pase, scripts) dentro de la auditoría nueva; `gr_audit_seal`.
- Mensaje de cierre: qué llegó (duplicados / nuevos), qué resolvió, qué cambió (cifras clave anterior→nuevo), qué queda abierto y quién lo aporta, carpetas temporales que pueden borrarse.

## 11. Complementos y criterios de la gerencia (sub-versiones)

Un **complemento** es lo que llega después de cerrar un pase: un documento suelto, una aclaración de la gerencia, una corrección de criterio. Se procesa con el mismo procedimiento y produce una auditoría nueva (o, si la anterior aún no está sellada, una sub-versión dentro de ella con la versión previa en `versions/`).

- **Registro de criterios de la gerencia (CRIT-nn).** Toda instrucción de un socio que la auditoría aplica se registra con `gr_criteria_add` (fecha, autor, texto literal, estado) y se declara en cada entregable. No son conclusiones de la auditoría y quedan "pendientes de la conformidad de la otra parte". Cuando un criterio cambia la *lectura* de una partida, el importe no se altera: se muestra aparte con su criterio.
- **Explicaciones de la gerencia sobre un cargo** se registran como declaración, no como evidencia: el cargo se mantiene "pendiente de factura/regularización" y la excepción se redirige a quien tiene los recibos.
- **Documento suelto que cierra una excepción**: fila en el registro con hash, cruce exacto con el movimiento del extracto, reclasificación en el modelo y actualización de *todas* las menciones; comprobar con una búsqueda de patrones sobre un volcado de texto de todos los entregables que no queda ninguna mención vigente del estado anterior.
- **Scripts derivados por parche**: los scripts vN.1 se generan aplicando reemplazos exactos (con aserción de existencia y unicidad) a los scripts vN.
- **Verificación tras el complemento:** volcado de texto de los entregables + patrones de las cifras que cambiaron + revisor independiente de consistencia.

## Errores que este procedimiento enseñó a evitar

1. Gasto presentado sin los devengos que sí estaban en la utilidad (usar `margen − utilidad`, no un subtotal del modelo).
2. Mezclar en un mismo desglose una cifra "v1" con partidas menores identificadas después; mostrarlas aparte.
3. Copiar notas de la versión anterior sin revisarlas.
4. Cabeceras con bases distintas para cada socio.
5. Conteos de excepciones tecleados en lugar de calculados.
6. Etiquetas que empiezan por "=" escritas como fórmula.
7. Textos truncados en celdas o tablas.
8. IDs de documento distintos en cada workbook sin tabla de equivalencias.
9. Reclasificar por beneficiario un pago que ya estaba correctamente clasificado como pasivo de año anterior.
10. Desbordes de página en PDF: medir % de tinta por página y no entregar con páginas casi vacías.
11. Escenario alternativo que deduce un pago de la utilidad pero lo mantiene en "lo recibido" por el socio: doble cómputo.
12. Llamar "sin beneficiario" a un pago con beneficiario probado pero sin soporte de concepto: son dos estados distintos.
13. Textos v1/v2 que sobreviven en hojas no reescritas: añadir el marcador "→ vN: …" en la misma celda.
14. Redondeo de mitades (.545): half-up explícito (Decimal) en todos los generadores.
15. Tokens de herramientas en textos heredados dentro del workbook: escanear todas las celdas antes de guardar.
16. Datos intermedios en carpetas temporales desaparecen entre llamadas: guardar todo insumo derivado en la carpeta de la auditoría.
17. Las dudas de la gerencia sobre el informe son señales de texto poco claro: cada respuesta que se da en el chat debe llevarse al entregable y regenerar el conjunto.
18. Una recomendación de liquidación puede emitirse sobre la "posición documentada" cuando la evidencia pedida no llega: se fecha la solicitud, se declara que las cifras son las documentadas y se muestra la única sensibilidad que cambiaría el sentido.
19. Antes de sumar dos cifras comprobar si una ya contiene a la otra (doble cómputo).
20. Dejar un `LEEME` por carpeta con el archivo vigente y los superados.
21. **Continuidad con el ejercicio anterior no auditado**: una sola página con documento y monto por partida (base de reconocimiento del ingreso; cada partida del ejercicio anterior que pasó por la caja o el costo del ejercicio auditado con columnas ¿en el resultado? / ¿en la caja? / documento y hoja; el neto de caja; el efecto en la utilidad; los cuadres que no se mueven).
22. **Numeración y referencias cruzadas del PDF**: "Página N de M" en una posición distinta de la línea de documentos complementarios; al insertar una página revisar todas las referencias a páginas.
