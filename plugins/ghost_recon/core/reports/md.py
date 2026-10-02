"""Markdown assembly: header block + agent narrative + annex tables from the DB + signature.

Also a tiny Markdown parser (``parse_blocks``) shared by the PDF renderer: headings, paragraphs, bullet/numbered
lists, pipe tables, horizontal rules, block quotes. Inline: **bold**, *italic*, `code`.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import SIGNATURE
from .. import ids


def fmt_money(v: Any, currency: str = "") -> str:
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{abs(f):,.2f}"
    s = ("−" if f < 0 else "") + s
    return f"{s} {currency}".strip()


def md_escape(s: Any) -> str:
    return str(s if s is not None else "").replace("|", "/").replace("\n", " ").strip()


def table(headers: List[str], rows: List[List[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(md_escape(c) for c in r) + " |")
    return "\n".join(out)


def header_block(case: Dict[str, Any], audit: Dict[str, Any], title: str, version: str, companion: Optional[str] = None) -> str:
    lines = [f"# {title}", "",
             f"**Caso:** {case['name']} ({case['id']}) · **Auditoría:** {ids.short_audit(audit['id'])} ({audit['kind']}) · "
             f"**Versión:** {version} · **Fecha:** {datetime.now().date().isoformat()} · **Moneda base:** {case['base_currency']}", ""]
    if companion:
        lines += [f"Documento complementario: `{companion}`", ""]
    lines += ["Nota de neutralidad: este informe describe diferencias como no explicadas, no conciliadas o no documentadas; "
              "no atribuye intención. Cada conclusión lleva su etiqueta (FACT / CALCULATION / INFERENCE / ALLEGATION / UNKNOWN) "
              "y su nivel de confianza.", ""]
    return "\n".join(lines)


def annex_from_db(case: Dict[str, Any], findings: List[Dict[str, Any]], criteria: List[Dict[str, Any]],
                  evidence: List[Dict[str, Any]], research: List[Dict[str, Any]], version_effect: Optional[List[Dict[str, Any]]] = None) -> str:
    cur = case.get("base_currency", "")
    parts = ["", "---", "", "# Anexos (generados desde la base de datos del caso)", ""]
    kinds = [("exception", "Registro de excepciones"), ("anomaly", "Registro de anomalías"),
             ("question", "Preguntas para quien tiene la evidencia"), ("finding", "Hallazgos")]
    for kind, label in kinds:
        rows = [f for f in findings if f["kind"] == kind]
        parts += [f"## {label} ({len(rows)})", ""]
        if rows:
            parts.append(table(["ID", "Título", "Importe", "Contraparte", "Riesgo", "Confianza", "Etiqueta", "Estado", "Evidencia que lo resolvería", "Quién la aporta"],
                               [[f["id"], f["title"], fmt_money(f.get("amount"), f.get("currency") or cur), f.get("counterparty") or "",
                                 f["risk"], f["confidence"], f["label"], f["status"], f.get("next_evidence") or "", f.get("owner") or ""] for f in rows]))
        else:
            parts.append("(sin registros)")
        parts.append("")
    parts += [f"## Criterios registrados ({len(criteria)})", ""]
    parts.append(table(["ID", "Fecha", "Autor", "Texto literal", "Estado"],
                       [[c["id"], c.get("date"), c["author"], c["text"], c["status"]] for c in criteria]) if criteria else "(ninguno)")
    if version_effect:
        parts += ["", "## Efecto de versión (partida · anterior · nuevo · diferencia · documento causante)", "",
                  table(["Partida", "Anterior", "Nuevo", "Diferencia", "Documento", "Hoja/Sección"],
                        [[v.get("item"), fmt_money(v.get("previous"), cur), fmt_money(v.get("new"), cur), fmt_money(v.get("difference"), cur),
                          v.get("document"), v.get("sheet")] for v in version_effect])]
    parts += ["", f"## Índice de evidencia ({len(evidence)} archivos)", "",
              table(["Ruta", "Tipo", "Tamaño", "SHA-256", "Estado", "Auditoría"],
                    [[e["path"], e.get("doc_type") or "", e.get("size"), (e.get("sha256") or "")[:16] + "…", e.get("status"),
                      ids.short_audit(e["first_audit_id"]) if e.get("first_audit_id") else ""] for e in evidence])]
    if research:
        parts += ["", f"## Investigación externa registrada ({len(research)} notas)", "",
                  table(["#", "Acción", "Consulta", "Fuente", "Título"],
                        [[r["id"], r["action"], r["query"][:80], r.get("url") or "", (r.get("title") or "")[:80]] for r in research])]
    parts += ["", "---", "", f"*{SIGNATURE}*", ""]
    return "\n".join(parts)


def skeleton_report(case: Dict[str, Any], audit: Dict[str, Any], model: Dict[str, Any]) -> str:
    """Minimal narrative when the agent has not written report.md yet (smoke tests, interrupted sessions)."""
    kpis = model.get("kpis") or {}
    lines = ["## 1. La respuesta en una página", "",
             "Este pack se generó sin narrativa del auditor (modo esqueleto). Las tablas de los anexos provienen de la base de "
             "datos del caso y del modelo; la narrativa debe completarse en `06_Report/report.md` y reconstruir el pack.", ""]
    if kpis:
        lines += ["| Indicador | Valor |", "|---|---|"] + [f"| {k} | {fmt_money(v, case.get('base_currency', '')) if isinstance(v, (int, float)) else v} |" for k, v in kpis.items()]
    lines += ["", "## 2. Alcance y evidencia", "", f"Carpeta de evidencia: `{case['root_path']}`.", "",
              "## 3. Hallazgos", "", "Ver anexos.", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- parser

_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def parse_blocks(md: str) -> List[Dict[str, Any]]:
    """Return a list of blocks: {type: heading|paragraph|bullets|numbered|table|rule|quote|code, ...}."""
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: List[Dict[str, Any]] = []
    i, n = 0, len(lines)
    para: List[str] = []

    def flush_para():
        nonlocal para
        if para:
            blocks.append({"type": "paragraph", "text": " ".join(s.strip() for s in para)})
            para = []

    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            flush_para(); i += 1; continue
        if s.startswith("```"):
            flush_para()
            j = i + 1; code = []
            while j < n and not lines[j].strip().startswith("```"):
                code.append(lines[j]); j += 1
            blocks.append({"type": "code", "text": "\n".join(code)}); i = j + 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush_para(); blocks.append({"type": "heading", "level": len(m.group(1)), "text": m.group(2).strip()}); i += 1; continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush_para(); blocks.append({"type": "rule"}); i += 1; continue
        if s.startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1].strip()):
            flush_para()
            header = [c.strip() for c in s.strip("|").split("|")]
            j = i + 2; rows = []
            while j < n and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")]); j += 1
            blocks.append({"type": "table", "header": header, "rows": rows}); i = j; continue
        if re.match(r"^[-*•]\s+", s):
            flush_para(); items = []
            while i < n and re.match(r"^\s*[-*•]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*•]\s+", "", lines[i]).strip()); i += 1
            blocks.append({"type": "bullets", "items": items}); continue
        if re.match(r"^\d+[.)]\s+", s):
            flush_para(); items = []
            while i < n and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]).strip()); i += 1
            blocks.append({"type": "numbered", "items": items}); continue
        if s.startswith(">"):
            flush_para(); q = []
            while i < n and lines[i].strip().startswith(">"):
                q.append(lines[i].strip()[1:].strip()); i += 1
            blocks.append({"type": "quote", "text": " ".join(q)}); continue
        para.append(line); i += 1
    flush_para()
    return blocks


def assemble(case: Dict[str, Any], audit: Dict[str, Any], *, title: str, version: str, body_md: str,
             findings: List[Dict[str, Any]], criteria: List[Dict[str, Any]], evidence: List[Dict[str, Any]],
             research: List[Dict[str, Any]], version_effect: Optional[List[Dict[str, Any]]] = None,
             companion: Optional[str] = None) -> str:
    body = body_md.strip()
    if body.startswith("# "):  # the agent wrote its own H1: keep ours as the document title, demote theirs
        body = "#" + body
    return header_block(case, audit, title, version, companion) + "\n" + body + "\n" + \
        annex_from_db(case, findings, criteria, evidence, research, version_effect)


def read_sections(report_dir: Path) -> Optional[str]:
    """``06_Report/report.md`` wins; otherwise concatenate ``06_Report/sections/*.md`` in name order."""
    rp = report_dir / "report.md"
    if rp.exists():
        return rp.read_text(encoding="utf-8")
    sd = report_dir / "sections"
    if sd.is_dir():
        parts = [p.read_text(encoding="utf-8") for p in sorted(sd.glob("*.md"))]
        if parts:
            return "\n\n".join(parts)
    return None
