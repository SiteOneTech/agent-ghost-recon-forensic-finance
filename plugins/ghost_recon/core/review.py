"""/review-case: consolidated chronology of a case + the six-role review plan.

``start_review`` creates ``<audits_root>/reviews/R0n_<date>/``, writes ``chronology.md`` (+ ``chronology.json``,
and ``chronology.xlsx`` when openpyxl is available), and returns the delegate_task plan for the roles.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import SIGNATURE
from . import casefolder as cf
from . import ids
from .db import Store
from . import swarm

ROLES: List[Dict[str, Any]] = [
    {"key": "legal", "label": "Abogado (legal)", "skill": "ghost-recon-role-legal", "focus": [
        "¿Qué hechos están probados documentalmente y cuáles son declaraciones o inferencias?",
        "¿Qué exposición legal tiene cada parte y qué pruebas faltan para sostener o rebatir cada posición?",
        "¿Qué solicitudes formales de documentos corresponden, a quién, con qué plazos y bajo qué derecho de inspección?",
        "¿Qué frases de los entregables podrían atacarse y cómo deberían redactarse?",
        "¿Qué cuestiones NO conviene abrir por exponer al solicitante?"]},
    {"key": "tax", "label": "Asesor tributario", "skill": "ghost-recon-role-tax", "focus": [
        "¿Qué efectos fiscales tienen las reclasificaciones (distribuciones vs gastos, pagos a socios, pasivos de años anteriores)?",
        "¿Qué obligaciones declarativas o de retención aparecen y en qué jurisdicción?",
        "¿Qué riesgos tributarios genera cada escenario de la auditoría y cuál es su materialidad?",
        "¿Qué documentación fiscal (declaraciones, elecciones, 1099/K-1 o equivalentes) debe solicitarse?"]},
    {"key": "financial", "label": "Analista financiero", "skill": "ghost-recon-role-financial", "focus": [
        "¿Cuál es la posición de caja y la utilidad económica reconstruida y cómo cambiaron entre auditorías?",
        "¿Qué sensibilidades mueven las conclusiones (partidas pendientes de concepto, bases alternativas)?",
        "¿Cuál es la posición de cada socio bajo cada base y qué rango de liquidación es defendible?",
        "¿Qué indicadores de salud financiera y de gobierno del efectivo deben imponerse hacia adelante?"]},
    {"key": "auditor", "label": "Auditor (calidad de evidencia)", "skill": "ghost-recon-role-auditor", "focus": [
        "¿Qué cobertura tiene la evidencia (meses de extractos, cuentas, listados) y dónde hay huecos?",
        "¿Qué conclusiones tienen confianza CONFIRMED y cuáles dependen de inferencias?",
        "¿Las validaciones independientes están registradas y sus hallazgos cerrados?",
        "¿Qué procedimientos adicionales (confirmaciones de terceros, wire advices, conciliaciones) reducirían más la incertidumbre?"]},
    {"key": "accounting", "label": "Contador", "skill": "ghost-recon-role-accounting", "focus": [
        "¿Qué asientos y reclasificaciones corresponden según la reconstrucción (no-P&L, pasivos de años anteriores, partes relacionadas)?",
        "¿Qué políticas contables (reconocimiento de ingresos, inventario, FX) deben adoptarse para el cierre?",
        "¿Qué diferencias hay entre los libros/cierres aportados por las partes y la reconstrucción, y cómo se corrigen?",
        "¿Qué controles internos mínimos evitan que se repitan las excepciones?"]},
    {"key": "mediator", "label": "Mediador de conflictos", "skill": "ghost-recon-role-mediator", "focus": [
        "¿Cuáles son los intereses reales de cada parte y dónde convergen las cifras?",
        "¿Qué puntos están resueltos por la evidencia, cuáles dependen de criterios no acordados y cuáles de documentos faltantes?",
        "¿Qué propuesta de resolución escalonada (pasos, cifras, plazos, condiciones) maximiza la probabilidad de acuerdo?",
        "¿Qué lenguaje y qué secuencia de comunicación reducen la escalada?"]},
]


def build_chronology(store: Store, case_id: str) -> Dict[str, Any]:
    case = store.get_case(case_id)
    audits = store.list_audits(case_id)
    events = store.list_events(case_id)
    findings = store.list_findings(case_id)
    criteria = store.list_criteria(case_id)
    entries: List[Dict[str, Any]] = []
    for e in events:
        entries.append({"ts": e["ts"], "type": e["event_type"], "audit_id": e.get("audit_id"), "text": e["description"]})
    for a in audits:
        entries.append({"ts": a["started_at"], "type": "audit", "audit_id": a["id"],
                        "text": f"{ids.short_audit(a['id'])} {a['kind']} → {a['status']} ({a['folder']})",
                        "summary": a.get("summary") or {}, "reports": [r["path"] for r in store.list_reports(a["id"])]})
        for run in store.list_runs(a["id"]):
            entries.append({"ts": run["started_at"], "type": f"run:{run['kind']}", "audit_id": a["id"],
                            "text": f"{run['kind']}{'/' + run['role'] if run.get('role') else ''}: {run['status']} — {run.get('summary', '')}"})
    for f in findings:
        for h in f.get("history") or []:
            entries.append({"ts": h.get("ts", ""), "type": f"finding:{f['kind']}", "audit_id": h.get("audit_id"),
                            "text": f"{f['id']} «{f['title']}» — {h.get('change')} (status={f['status']}, risk={f['risk']})"})
    for c in criteria:
        entries.append({"ts": c.get("created_at", ""), "type": "criterion", "audit_id": c.get("audit_id"),
                        "text": f"{c['id']} ({c['author']}, {c.get('date')}): {c['text']}"})
    entries.sort(key=lambda x: (x.get("ts") or "", x["type"]))
    return {"case": case, "audits": audits, "entries": entries, "findings": findings, "criteria": criteria,
            "open_findings": [f for f in findings if f["status"] == "open"]}


def chronology_markdown(chron: Dict[str, Any]) -> str:
    case = chron["case"]
    lines = [f"# Cronología del caso {case['name']} ({case['id']})", "",
             f"Carpeta: `{case['root_path']}` · Moneda base: {case['base_currency']} · Generado por Ghost Recon", "",
             "## Auditorías", "", "| Auditoría | Tipo | Estado | Inicio | Sello | Evidencia nueva | Carpeta |", "|---|---|---|---|---|---|---|"]
    for a in chron["audits"]:
        s = a.get("summary") or {}
        lines.append(f"| {ids.short_audit(a['id'])} | {a['kind']} | {a['status']} | {a['started_at'][:10]} | "
                     f"{(a.get('sealed_at') or '')[:10]} | {s.get('evidence_new', '')} | `{a['folder']}` |")
    lines += ["", "## Línea de tiempo", "", "| Fecha | Tipo | Auditoría | Evento |", "|---|---|---|---|"]
    for e in chron["entries"]:
        aid = ids.short_audit(e["audit_id"]) if e.get("audit_id") else ""
        lines.append(f"| {(e.get('ts') or '')[:19].replace('T', ' ')} | {e['type']} | {aid} | {e['text'].replace('|', '/')} |")
    lines += ["", "## Evolución de hallazgos", "", "| ID | Tipo | Título | Estado | Riesgo | Confianza | Historia |", "|---|---|---|---|---|---|---|"]
    for f in chron["findings"]:
        hist = "; ".join(f"{ids.short_audit(h['audit_id']) if h.get('audit_id') else '-'}: {h.get('change') if isinstance(h.get('change'), str) else ', '.join(h.get('change', {}).keys())}"
                         for h in (f.get("history") or []))
        lines.append(f"| {f['id']} | {f['kind']} | {f['title'].replace('|', '/')} | {f['status']} | {f['risk']} | {f['confidence']} | {hist} |")
    lines += ["", "## Criterios registrados (declaraciones de las partes, no conclusiones)", ""]
    if chron["criteria"]:
        lines += ["| ID | Fecha | Autor | Texto | Estado |", "|---|---|---|---|---|"]
        lines += [f"| {c['id']} | {c.get('date')} | {c['author']} | {c['text'].replace('|', '/')} | {c['status']} |" for c in chron["criteria"]]
    else:
        lines.append("(ninguno)")
    lines += ["", f"— {SIGNATURE}"]
    return "\n".join(lines) + "\n"


def start_review(store: Store, case_key: str, *, roles: Optional[List[str]] = None, out_dir: Optional[str] = None) -> Dict[str, Any]:
    case = store.get_case(case_key)
    if not case:
        p = Path(case_key).expanduser()
        case = store.get_case(str(p.resolve())) if p.exists() else {}
    if not case:
        raise ValueError(f"case not found: {case_key}")
    audits = store.list_audits(case["id"], kinds=("initial", "rerun"))
    if not audits:
        raise ValueError("the case has no audits yet; run /new-open-case first")
    open_reviews = [a for a in store.list_audits(case["id"], kinds=("review",)) if a["status"] != "sealed"]
    if open_reviews:
        raise ValueError(f"review {open_reviews[-1]['id']} is still open ({open_reviews[-1]['folder']})")
    seq = store.next_audit_seq(case["id"], "R")
    rid = ids.audit_id(case["id"], seq, "review")
    aroot = cf.audits_root(Path(case["root_path"]), case["audits_dir"], out_dir or (case.get("meta") or {}).get("out_dir"))
    manifest = {"review_id": rid, "case_id": case["id"], "case_name": case["name"], "seq": seq,
                "audits_reviewed": [a["id"] for a in audits]}
    folder = cf.create_audit_folder(aroot, ids.audit_folder_name(seq, "review"), "review", manifest)
    store.create_audit(id=rid, case_id=case["id"], seq=seq, kind="review", folder=str(folder),
                       parent_audit_id=audits[-1]["id"])
    store.update_audit(rid, status="in_progress")
    chron = build_chronology(store, case["id"])
    md_path = cf.write_text(folder, "chronology.md", chronology_markdown(chron))
    cf.write_json(folder, "chronology.json", {k: v for k, v in chron.items() if k != "case"} | {"case_id": case["id"]})
    xlsx_path = None
    try:
        from .reports.xlsx import build_chronology_workbook
        xlsx_path = build_chronology_workbook(chron, folder / "06_Report" / f"GhostRecon_Cronologia_{case['slug']}.xlsx")
        store.add_report(rid, "chronology_xlsx", str(xlsx_path), "xlsx", sha256=cf.sha256_file(xlsx_path), size=xlsx_path.stat().st_size)
    except Exception as exc:  # openpyxl missing or similar — the md/json chronology is the contract
        cf.write_text(folder, "06_Report/chronology_xlsx.skipped.txt", f"xlsx not built: {exc}")
    selected = [r for r in ROLES if not roles or r["key"] in roles]
    packs = [{"audit_id": a["id"], "status": a["status"], "folder": a["folder"]} for a in audits]
    plan = swarm.plan_review(store, rid, selected, str(md_path), packs)
    store.add_event(case["id"], "review_started", f"Revisión {ids.short_audit(rid)} iniciada ({len(selected)} roles)", audit_id=rid)
    return {"review_id": rid, "folder": str(folder), "chronology_md": str(md_path),
            "chronology_xlsx": str(xlsx_path) if xlsx_path else None, "audits_reviewed": [a["id"] for a in audits],
            "open_findings": len(chron["open_findings"]), "roles": [r["key"] for r in selected], "plan": plan}
