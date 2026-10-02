"""Swarm plans: deterministic task lists for Hermes' ``delegate_task`` plus on-disk manifests.

Three modes:
    extraction  — one sub-agent per evidence block (commercial / supply / banking / related_parties /
                  correspondence / ocr_vision / other), split by ``max_files_per_task``.
    validation  — independent validators A (recompute from raw), B (consistency), C (adversarial).
    review      — one sub-agent per professional role (legal, tax, financial, auditor, accounting, mediator).

Every task is self-contained (children get no memory, no AGENTS.md): goal + context carry the manifest
path, the critical rules, the output path and the instruction to load the matching skill with ``skill_view``.
Manifests are written under ``03_Extracted_Data/agents/`` (audits) or ``roles/`` (reviews) so a resumed
session can re-dispatch without recomputing anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import SIGNATURE
from . import casefolder as cf
from .db import Store
from .prompts import render

BLOCK_ORDER = ["banking", "commercial", "supply", "related_parties", "correspondence", "ocr_vision", "other"]
BLOCK_LABELS = {
    "banking": "Bancos, tarjetas, listados (wires/Zelle/ACH), procesadores e intermediarios",
    "commercial": "Comercial: órdenes, facturas de venta, albaranes/entregas, cobros, notas de crédito",
    "supply": "Suministro y logística: facturas de compra, OC, flete, aduana, portal del fabricante, inventario",
    "related_parties": "Partes relacionadas, socios, contratos, actas, nómina, préstamos, licencias",
    "correspondence": "Correspondencia: chats, correos, mensajes (hechos declarados, fechas, compromisos)",
    "ocr_vision": "Escaneos e imágenes: OCR / lectura visual con verificación",
    "other": "Documentos sin clasificar: leer contenido y asignar bloque",
}

CRITICAL_RULES = (
    "1) Nunca modificar, renombrar, mover ni borrar evidencia original; trabajar solo en la carpeta de salida indicada. "
    "2) Nunca inventar datos: tipos de cambio, saldos de apertura, beneficiarios, fechas o precios desconocidos quedan UNKNOWN y se reportan como discrepancia. "
    "3) Nunca forzar relaciones: una coincidencia exige importe exacto más fecha o referencia; lo parecido es inferencia, no prueba. "
    "4) Nunca contar dos veces (orden + factura + depósito pueden ser un solo hecho económico). "
    "5) Nunca asumir la naturaleza de un movimiento: un beneficiario probado por el banco establece quién recibió, nunca por qué. "
    "6) Lenguaje forense neutral: unexplained / unreconciled / undocumented / unsupported; nunca fraude, robo, desvío. "
    "7) Cada extracto bancario debe cuadrar al centavo (apertura + entradas − salidas = cierre) antes de usarse; si no cuadra es una discrepancia. "
    "8) Reportar 'unclear' en vez de adivinar; cada dato lleva proveniencia (documento, página/fila)."
)

EXTRACTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "block": {"type": "string"},
        "files_processed": {"type": "integer"},
        "files_unreadable": {"type": "array", "items": {"type": "string"}},
        "transactions_count": {"type": "integer"},
        "output_path": {"type": "string"},
        "discrepancies": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "string"},
    },
    "required": ["block", "files_processed", "output_path", "summary"],
}

VALIDATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "validator": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "object"}},
        "verdict": {"type": "string"},
        "output_path": {"type": "string"},
    },
    "required": ["validator", "findings", "verdict"],
}

REVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"role": {"type": "string"}, "output_path": {"type": "string"}, "headline": {"type": "string"},
                   "top_risks": {"type": "array", "items": {"type": "string"}},
                   "recommendations": {"type": "array", "items": {"type": "string"}}},
    "required": ["role", "output_path", "headline"],
}

VALIDATORS = [
    ("A", "recompute", "Auditor A — recálculo desde crudo (sin acceso al modelo ni a los informes)"),
    ("B", "consistency", "Auditor B — consistencia entre entregables, IDs, conteos, textos obsoletos, aritmética"),
    ("C", "adversarial", "Auditor C — adversarial: abogado/CPA de la contraparte; afirmaciones que sobrepasan la evidencia"),
]


def _chunk(items: List[Any], size: int) -> List[List[Any]]:
    size = max(1, size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def plan_extraction(store: Store, audit_id: str, *, max_files_per_task: int = 60, max_parallel: int = 6,
                    only_new: Optional[bool] = None) -> Dict[str, Any]:
    """Group the audit's evidence into blocks, write one manifest per task, return delegate_task tasks."""
    audit = store.get_audit(audit_id)
    if not audit:
        raise ValueError(f"audit not found: {audit_id}")
    folder = cf.guard_writable(Path(audit["folder"]))
    case = store.get_case(audit["case_id"])
    root = Path(case["root_path"])
    if only_new is None:
        only_new = audit["kind"] == "rerun"
    rows = store.list_evidence(case["id"])
    rows = [r for r in rows if r["status"] in ("NEW", "REGISTERED", "MODIFIED") and not r["zip_member"]
            and (not only_new or r["first_audit_id"] == audit_id or r["status"] == "MODIFIED")]
    by_block: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_block.setdefault(r["block"], []).append(r)
    tasks: List[Dict[str, Any]] = []
    manifests: List[str] = []
    agents_dir = folder / "03_Extracted_Data" / "agents"
    for block in BLOCK_ORDER:
        files = by_block.get(block) or []
        if not files:
            continue
        chunks = _chunk(files, max_files_per_task)
        for i, chunk in enumerate(chunks, 1):
            name = block if len(chunks) == 1 else f"{block}-{i}"
            out_path = agents_dir / f"out_{name}.json"
            manifest = {
                "audit_id": audit_id, "case_id": case["id"], "case_name": case["name"], "block": name,
                "block_label": BLOCK_LABELS[block], "base_currency": case["base_currency"], "language": case["language"],
                "evidence_root": str(root), "output_path": str(out_path), "rules": CRITICAL_RULES,
                "files": [{"path": str(root / f["path"]), "rel": f["path"], "sha256": f["sha256"], "doc_type": f["doc_type"],
                           "size": f["size"], "status": f["status"]} for f in chunk],
                "output_schema": EXTRACTION_OUTPUT_SCHEMA, "signature": SIGNATURE,
            }
            mpath = cf.write_json(folder, f"03_Extracted_Data/agents/manifest_{name}.json", manifest)
            manifests.append(str(mpath))
            goal = render("extraction_goal", block=name, block_label=BLOCK_LABELS[block], manifest=str(mpath),
                          output=str(out_path), n=len(chunk), case_name=case["name"], currency=case["base_currency"],
                          language=case["language"])
            context = render("extraction_context", rules=CRITICAL_RULES, manifest=str(mpath), output=str(out_path),
                             working=str(folder / "02_Working_Copies"), evidence_root=str(root),
                             context_md=audit.get("context_md") or "(sin contexto adicional)")
            tasks.append({"goal": goal, "context": context, "output_schema": EXTRACTION_OUTPUT_SCHEMA,
                          "group": f"wave-{(len(tasks) // max_parallel) + 1}", "block": name, "manifest": str(mpath),
                          "output_path": str(out_path), "files": len(chunk)})
    waves = _chunk(tasks, max_parallel)
    plan = {"audit_id": audit_id, "mode": "extraction", "tasks": tasks, "waves": len(waves),
            "max_parallel": max_parallel, "manifests": manifests, "files_total": len(rows),
            "blocks": {b: len(v) for b, v in by_block.items()},
            "how_to_run": ("Call delegate_task once per wave with tasks[i].goal/context/output_schema (drop the helper keys). "
                           "Wait for every result, then consolidate every out_*.json into 03_Extracted_Data/model.json.")}
    cf.write_json(folder, "03_Extracted_Data/agents/swarm_plan_extraction.json", plan)
    store.add_run(audit_id, "swarm", role="extraction", status="planned",
                  input={"tasks": len(tasks), "waves": len(waves)}, summary=f"plan de extracción: {len(tasks)} tareas")
    return plan


def plan_validation(store: Store, audit_id: str, *, headline_figures: Optional[Dict[str, Any]] = None,
                    validators: Optional[List[str]] = None) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise ValueError(f"audit not found: {audit_id}")
    folder = cf.guard_writable(Path(audit["folder"]))
    case = store.get_case(audit["case_id"])
    report_dir = folder / "06_Report"
    deliverables = sorted(str(p) for p in report_dir.glob("*") if p.is_file())
    model = audit.get("model_json") or next((str(p) for p in (folder / "03_Extracted_Data").glob("model*.json")), "")
    want = set(validators or [v[0] for v in VALIDATORS])
    tasks = []
    for code, key, label in VALIDATORS:
        if code not in want:
            continue
        out_path = folder / "validation" / f"out_auditor_{code}.json"
        goal = render(f"validation_goal_{key}", audit_id=audit_id, case_name=case["name"], output=str(out_path),
                      evidence_root=case["root_path"], deliverables="\n".join(deliverables) or "(sin entregables aún)",
                      model=model if code != "A" else "(sin acceso: recalcula desde los documentos)",
                      headline=json.dumps(headline_figures or {}, ensure_ascii=False))
        context = render("validation_context", rules=CRITICAL_RULES, label=label, output=str(out_path),
                         exceptions=str(folder / "05_Exceptions" / "exceptions.json"))
        tasks.append({"goal": goal, "context": context, "output_schema": VALIDATION_OUTPUT_SCHEMA,
                      "validator": code, "output_path": str(out_path)})
    plan = {"audit_id": audit_id, "mode": "validation", "tasks": tasks,
            "how_to_run": ("Call delegate_task with all validators in ONE call (they are independent). Read every result; "
                           "record each with gr_run_record(kind='validation', role='A'|'B'|'C'); fix, rebuild the pack and "
                           "repeat the round if any fix touched figures. Do not seal with a material finding open.")}
    cf.write_json(folder, "validation/swarm_plan_validation.json", plan)
    store.add_run(audit_id, "swarm", role="validation", status="planned", input={"tasks": len(tasks)},
                  summary=f"plan de validación: {len(tasks)} validadores")
    return plan


def plan_review(store: Store, review_id: str, roles: List[Dict[str, Any]], chronology_path: str,
                sealed_packs: List[Dict[str, Any]]) -> Dict[str, Any]:
    audit = store.get_audit(review_id)
    folder = cf.guard_writable(Path(audit["folder"]))
    case = store.get_case(audit["case_id"])
    tasks = []
    packs_txt = "\n".join(f"- {p['audit_id']} ({p['status']}): {p['folder']}" for p in sealed_packs) or "(sin auditorías selladas)"
    for role in roles:
        out_path = folder / "roles" / f"{role['key']}.md"
        goal = render("review_goal", role_key=role["key"], role_label=role["label"], skill=role["skill"],
                      case_name=case["name"], chronology=chronology_path, packs=packs_txt, output=str(out_path),
                      focus="\n".join(f"- {q}" for q in role["focus"]), language=case["language"])
        context = render("review_context", rules=CRITICAL_RULES, output=str(out_path), review_id=review_id)
        tasks.append({"goal": goal, "context": context, "output_schema": REVIEW_OUTPUT_SCHEMA, "role": role["key"],
                      "output_path": str(out_path)})
    plan = {"review_id": review_id, "mode": "review", "tasks": tasks,
            "how_to_run": ("Call delegate_task with the six roles in ONE call. Then write diagnosis.md yourself "
                           "(synthesis across roles: established facts, what changed between audits, risk map, "
                           "prioritised recommendations, who must provide what) and build the pack with gr_report_build.")}
    cf.write_json(folder, "roles/swarm_plan_review.json", plan)
    store.add_run(review_id, "swarm", role="review", status="planned", input={"tasks": len(tasks)},
                  summary=f"plan de revisión: {len(tasks)} roles")
    return plan


def strip_for_delegate(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only the keys delegate_task accepts (goal, context, output_schema, group)."""
    keep = ("goal", "context", "output_schema", "group")
    return [{k: t[k] for k in keep if k in t} for t in tasks]
