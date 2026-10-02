"""Goal / context templates for swarm tasks and the system-prompt section.

Templates are plain ``str.format`` strings keyed by name. Kept in Python (not loose files) so the core
stays importable from any working directory and the texts are versioned with the code.
"""

from __future__ import annotations

TEMPLATES = {
    # ------------------------------------------------------------------ extraction (block auditors)
    "extraction_goal": (
        "Eres un auditor de bloque de Ghost Recon (auditoría financiera forense) para el caso «{case_name}». "
        "Bloque: {block} — {block_label}. Procesa los {n} documentos listados en el manifiesto {manifest}: lee el "
        "CONTENIDO de cada uno (no solo el nombre), extrae cada transacción/partida con proveniencia (documento, "
        "página o fila), aplica los cuadres obligatorios (extractos al centavo; listados con conteo declarado) y "
        "escribe tu salida como JSON en {output} con las claves: block, files_processed, files_unreadable[], "
        "transactions[] (id, date, posting_date, account, entity, counterparty, description, amount_original, "
        "currency, debit, credit, amount_base, category, related_party, source_doc, page_or_row, confidence), "
        "documents[] (rel, doc_type, doc_date, entity, counterparty, reference, currency, amount, period, "
        "review_status, confidence, notes), discrepancies[] (file, description, amount, why), summary. "
        "Moneda base {currency}; idioma {language}. Antes de empezar carga la skill con "
        "skill_view(name='ghost-recon-block-auditor') y síguela. Reporta 'unclear' en lugar de adivinar."
    ),
    "extraction_context": (
        "REGLAS CRÍTICAS (no negociables): {rules}\n\n"
        "Manifiesto (lista de archivos con ruta absoluta y hash): {manifest}\n"
        "Salida obligatoria (JSON): {output}\n"
        "Carpeta de trabajo para texto extraído/OCR (nunca escribas en la evidencia): {working}\n"
        "Raíz de evidencia (solo lectura): {evidence_root}\n"
        "Contexto del caso (archivo .md, léelo si existe): {context_md}\n"
        "Herramientas: read_file para texto/CSV/JSON; terminal con pdftotext -layout (o python + pdfplumber) para PDF; "
        "vision_analyze para imágenes/escaneos; openpyxl/pandas para XLSX. No uses web_search en esta tarea."
    ),
    # ------------------------------------------------------------------ validation
    "validation_goal_recompute": (
        "Eres el Auditor A (recálculo independiente) de Ghost Recon para la auditoría {audit_id} del caso «{case_name}». "
        "NO tienes acceso al modelo ni a los informes: recomputa las cifras cabecera directamente desde los documentos "
        "en {evidence_root} (extractos, facturas, listados) y compáralas una a una con estas cifras publicadas: {headline}. "
        "Entregables publicados (solo para saber qué cifras se afirman; no copies sus cálculos): {deliverables}. "
        "Escribe en {output} un JSON con validator='A', findings[] (figure, published, recomputed, difference, "
        "evidence, severity: material|minor|none, note) y verdict (OK | FIX_REQUIRED). Al terminar, resume en 10 líneas."
    ),
    "validation_goal_consistency": (
        "Eres el Auditor B (consistencia) de Ghost Recon para la auditoría {audit_id} del caso «{case_name}». "
        "Lee TODOS los entregables: {deliverables} y el modelo {model}. Busca: cifras que difieren entre hojas, "
        "MD y PDF; IDs de excepción duplicados o conteos tecleados que no coinciden con las filas; textos de versiones "
        "anteriores; aritmética interna del PDF (sumas, mitades, saldos); fórmulas guardadas como texto; etiquetas de "
        "versión distintas; placeholders; cualquier mención de proveedores de modelos o librerías (claude, anthropic, "
        "openai, reportlab, openpyxl, pikepdf, libreoffice) en texto o metadatos. Escribe en {output} un JSON con "
        "validator='B', findings[] (location, issue, expected, found, severity, fix) y verdict (OK | FIX_REQUIRED)."
    ),
    "validation_goal_adversarial": (
        "Eres el Auditor C (adversarial) de Ghost Recon para la auditoría {audit_id} del caso «{case_name}»: actúa "
        "como el abogado y el CPA de la contraparte. Lee los entregables: {deliverables}. Para cada afirmación "
        "material, pregunta: ¿sobrepasa la evidencia (hecho vs probable vs declaración)? ¿usa lenguaje no neutral? "
        "¿hay asimetría entre las partes? ¿qué réplica haría la contraparte y qué documento la resolvería? ¿expone "
        "al solicitante? Escribe en {output} un JSON con validator='C', findings[] (claim, location, attack, "
        "evidence_level, suggested_wording, severity) y verdict (OK | FIX_REQUIRED). Lista las 10 mejores réplicas."
    ),
    "validation_context": (
        "{label}. REGLAS: {rules}\nRegistro de excepciones vigente: {exceptions}\nSalida obligatoria: {output}\n"
        "Carga la skill skill_view(name='ghost-recon-validation') antes de empezar y sigue su protocolo. "
        "No modifiques ningún entregable: solo reportas."
    ),
    # ------------------------------------------------------------------ review (roles)
    "review_goal": (
        "Eres el rol «{role_label}» del panel de revisión de Ghost Recon para el caso «{case_name}» "
        "(revisión {output}). Carga primero skill_view(name='{skill}') y síguela. Lee la cronología consolidada "
        "{chronology} y los packs documentales sellados:\n{packs}\n"
        "Responde, desde tu rol y solo con lo que la evidencia sostiene, a estas preguntas:\n{focus}\n"
        "Escribe tu opinión en Markdown en {output} con secciones: Resumen (5 líneas), Hechos en que te apoyas "
        "(con IDs de excepción/documento), Análisis desde el rol, Riesgos (ordenados por materialidad), "
        "Recomendaciones (accionables, con responsable y plazo), Qué evidencia cambiaría tu opinión. Idioma: {language}. "
        "Devuelve también role, output_path, headline, top_risks[], recommendations[]."
    ),
    "review_context": (
        "Revisión {review_id}. REGLAS: {rules}\nSalida obligatoria: {output}\n"
        "No eres el auditor: no recalcules el modelo; interpreta. Marca cada conclusión como FACT / CALCULATION / "
        "INFERENCE / ALLEGATION / UNKNOWN y da un nivel de confianza. Esto no es asesoría legal ni fiscal formal: "
        "dilo en una línea al inicio."
    ),
}


def render(name: str, **kw: object) -> str:
    try:
        return TEMPLATES[name].format(**kw)
    except KeyError as exc:
        raise KeyError(f"prompt template {name!r} missing or missing field {exc}") from exc
