# Ghost Recon — Auditoría de la respuesta de la contraparte (referencia íntegra, v1.1)

Cuándo se usa: la contraparte de una auditoría Ghost Recon responde con un documento (PDF, libro, correo) que discute cifras, criterios o conclusiones. El objetivo no es "refutar" sino cotejar cada afirmación con la evidencia, puentear al centavo las diferencias, separar lo que coincide, lo que difiere por criterio, lo que no tiene documento y lo que contradice un documento, y pedir formalmente lo que falta. En Hermes se ejecuta como `/rerun-case <carpeta> respuesta.md` (auditoría nueva de tipo rerun con el contexto de la respuesta) y, si procede, un pack para abogados como documentos adicionales de esa auditoría.

## 1. Intake (carpeta nueva; la evidencia original no se toca)

1. La auditoría nueva (`gr_audit_start(kind="rerun")`) crea `03_Extracted_Data/`, `src/`, `versions/`, `validation/`.
2. Hash SHA-256 y MD5 del correo (.eml) y de cada adjunto (el inventario lo hace); extraer los adjuntos del .eml y comprobar que su hash coincide con los archivos sueltos de la carpeta de evidencia. Registrar cabeceras (From/To/CC, Date, Message-ID, In-Reply-To) y la secuencia temporal de metadatos (creación/modificación de cada archivo y hora del envío) **como dato, sin interpretación**.
3. Extracción completa: texto del PDF por **página física** (citar siempre la física), todas las celdas y fórmulas del libro, cuerpo del correo, imágenes incrustadas (leerlas una por una con `vision_analyze`: suelen ser las únicas "pruebas" aportadas).
4. Inventario de lo que la respuesta **dice tener** frente a lo que **adjunta** (tabla fuente declarada / en el correo / en el expediente).

## 2. Modelo único (`03_Extracted_Data/model_respuesta.json`)

Secciones mínimas: `meta` (incluida la **escala única de prueba con sus excepciones declaradas**), `evidencia` (hashes), `custodia`, `auditoria` (cifras vigentes), `contraparte` (sus cifras leídas celda a celda), `aritmetica_contraparte` (recálculo de sus totales desde sus partidas, con `assert`), `convergencia` (solo cifras iguales al centavo con fuente; las coincidencias con matiz y las aclaraciones van en tabla aparte y no se cuentan), `afirmaciones` RA-nn (página física, cita literal con [sic], cifra de ambos, clasificación, análisis, evidencia, efecto, documento requerido, estado), `puente` (de la posición de la auditoría a la de la contraparte, con `assert` de cierre al centavo), `ajustada` (posición tras incorporar lo que supera la escala de prueba), `escenarios` (misma definición de columna en todos; el rango se **calcula** sobre los escenarios), `inconsistencias` II-nn (solo contradicciones internas verificadas), `declaraciones` DR-nn (texto literal; "declara/confirma", nunca "admite"), `cruce_solicitudes` (preguntas anteriores con constancia de si la solicitud fue entregada), `comparativo` interno, `solicitud` (puntos con tramos y plazos), `exposicion_del_solicitante`, `banda_riesgo`, `argumentos_no_usados`, `metadatos`, `kpis`, `en_una_pagina`.

Clasificación de cada afirmación: CONFIRMA · DIFIERE POR CRITERIO (y/o POR CORTE) · SIN SOPORTE (documento citado no aportado) · CONTRADICE EVIDENCIA (contra documento del expediente) · CONTRADICCION INTERNA · DECLARACION RELEVANTE · PENDIENTE DE DOCUMENTO · FUERA DE ALCANCE · OPINION. **Dentro de una misma partida, separar lo "sin documento" de lo "contradicho"**.

Escala única de prueba (aplicada por igual a ambas partes): (1) extracto completo → se incorpora; (2) captura/comprobante + documento que lo contraste → "probable"; (3) asiento → pendiente; (4) declaración → pendiente. Toda excepción a la escala se **escribe en la escala**. Simetría: toda partida nueva a favor del solicitante se trata con el mismo nivel que la de la contraparte.

Las afirmaciones RA-nn, inconsistencias II-nn y declaraciones DR-nn se registran además como hallazgos del caso con `gr_finding_upsert` (kind=finding, category=RA|II|DR) para que la cronología del caso las conserve.

## 3. Entregables

- **Para la contraparte:** carta del solicitante (sin firma del sistema; CC mínimo; dos tramos de plazo; reservas: no aceptación por cercanía de totales, incorporación ≠ conformidad con el mecanismo, no reconocimiento de saldos de libros, no renuncia a periodos cerrados, derecho a ampliar; **no abrir cuestiones que expongan al solicitante**, dejarlas al abogado) + **anexo de 2 páginas** (convergencia y puente) **sin códigos internos** (RA-, EXC-, hojas) y sin fuentes que la contraparte no tenga; no pedir a la contraparte documentos que tiene el solicitante.
- **Internos:** PDF ejecutivo (uso interno del solicitante y de su abogado; en una página; qué llegó; convergencia; puente; escenarios y posición ajustada; la partida decisiva en una página con tabla "qué dice / qué muestran los documentos / documento"; registro RA; DR; II; cruce; solicitud; comparativo; método y validación), workbook, MD íntegro, comparativo interno (qué confirma/contradice/ignora; posición auditoría vs ajustada vs contraparte; **exposición del solicitante y cómo se cubre**; banda de riesgo con sensibilidad; argumentos verificados de reserva; lo que la contraparte pedirá a su vez; qué hacer antes de enviar), LEEME, hashes.
- Lenguaje: hechos; sin "admite", "reclamo", "amenaza", "desestima", "ficticio", "incumplido", "evasión" fuera de comillas; las palabras de la contraparte solo entre comillas con [sic]; metadatos "se registran como dato, sin interpretación"; sin datos personales de terceros. Cero nombres de herramientas o proveedores en texto y metadatos. Los documentos que viajan a la contraparte llevan metadatos neutros (autor = firmante).

## 4. Validación (obligatoria, varias rondas)

Ronda 1 sobre la versión preliminar y ronda 2 sobre la revisada, cada una con tres pasadas independientes sin acceso al modelo ni a los scripts: **A recálculo** (verificar la **cobertura temporal** de cada dataset parseado antes de declarar algo "no verificable"), **B consistencia**, **C adversarial** (abogado/CPA de la contraparte: las diez mejores réplicas; frases atacables de la carta con redacción alternativa; simetría; exposición del solicitante; qué pedirá a su vez). Ronda 3 de cierre. Registrar con `gr_run_record(kind="validation")` y describir la validación como **pasadas separadas del propio sistema Ghost Recon, no auditores humanos ni opinión de auditoría**.

## 5. Cierre

Hashes de todos los entregables; LEEME con "para quién" por archivo y las decisiones pendientes del solicitante antes de enviar; sello (`gr_audit_seal`); cifras ajustadas marcadas "a formalizar" en el pase siguiente de la auditoría base, nunca sustituidas a mano.

## Lecciones del caso de referencia

1. Comprobar la cobertura temporal del parseo antes de declarar "no verificable". 2. Un rango "en todos los escenarios" se calcula sobre los escenarios. 3. Separar "sin documento" de "contradicho" partida por partida. 4. El anexo a la contraparte no remite a códigos internos ni a fuentes que no tiene. 5. No pedir a la contraparte lo que tiene el solicitante. 6. No abrir en la carta cuestiones que exponen al solicitante. 7. Las notas de crédito pueden ajustar precio sin anular facturas: verificarlo antes de afirmar unidades facturadas. 8. "Auditores independientes" induce a error: son pasadas del sistema. 9. Partida doble para pagos del administrador al otro socio por cuenta de la sociedad. 10. Netear por consistencia lo que tiene el mismo nivel de prueba y corregir la imprecisión del informe anterior de forma explícita.

## 6. Segundo pase: evidencia nueva del solicitante, sub-versión y pack para abogados

1. **Hash y extracción de la evidencia nueva** en la auditoría nueva; texto de cada PDF por página; los documentos-imagen se transcriben y se marca que son transcripción; metadatos de los borradores de la contraparte como dato.
2. **Reconstrucción documental antes que declaración**: la cronología se arma desde los extractos (nivel 1) y el chat con número de línea; la declaración del solicitante se contrasta después y **cada afirmación que los documentos corrigen va a una tabla "qué dijo / qué muestran los documentos / fuente"**. Los hechos adversos al solicitante se declaran primero y con los documentos.
3. **Sub-versión**: el modelo conserva las claves previas, añade `que_cambio`, el escenario documentado nuevo y las cifras de la contraparte cuando la diferencia es inmaterial (declarando la diferencia).
4. **Pack para abogados** con modelo único propio que lee los modelos de la auditoría; un LÉEME con "para quién" por archivo, decisiones del solicitante y pendientes del abogado; terminología declarada; línea de privilegio.
5. **Cartas**: fechadas "[fecha de envío]"; una sola fórmula de capacidad de firma; citas del chat literales con [sic]; IDs de terceros truncados; sin reservas de acudir a bancos o autoridades; los hechos del solicitante como declaraciones suyas; versión mínima junto a la narrativa, para que el abogado elija.
6. **Anexo a la contraparte**: sin firma del sistema, sin referencia a documentos no entregados.
7. **Constancia de diligencia**: hechos y actuaciones, fechas de actos aún no ejecutados en corchetes, sin conclusiones jurídicas.
8. **Informe ejecutivo "dónde está el dinero"**: responde las preguntas del solicitante en su orden, con una descomposición verificable del flujo, rótulo de versión en cada cifra, base alternativa y banda de riesgo como sensibilidades declaradas.
9. **Cuadres**: filas con fórmulas, totales recalculados, nota explícita cuando el total de una hoja fuente difiere de la suma de filas, y sección "qué queda por fuera" con la excepción que lo sustenta.
10. **Validación**: A recálculo, B consistencia, **C desde la posición de la contraparte y del abogado/CPA**, cierre.

## Lecciones del segundo pase

11. **Cronología única**: una sola fecha por hecho en todos los documentos (tomar la fecha del extracto, no la del chat). 12. **No afirmar "deuda" sin cerrar la cadena del chat**. 13. Las referencias de línea del chat se verifican una a una contra el export con hash. 14. Los porcentajes citados de informes anteriores se recalculan desde el modelo. 15. Un residual "neto" cambia de signo al incorporar una partida: etiquetar el signo y la composición. 16. Las descomposiciones narrativas se verifican con suma antes de escribirlas. 17. Los PDF largos se paginan por sección; QA de densidad de tinta por página. 18. Nunca reemplazar separadores decimales sobre párrafos, solo sobre números formateados. 19. Nombres de personas ajenas al caso solo en la transcripción del extracto, no en informes ni cartas. 20. Los metadatos de todo documento que viaja a la contraparte se neutralizan y se verifican antes de entregar.
