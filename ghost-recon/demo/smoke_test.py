#!/usr/bin/env python3
"""Ghost Recon smoke test — the full case cycle WITHOUT an LLM (core + CLI only).

Copies demo/demo-case to a temp folder, then: open case → initial audit → extraction plan → findings +
criteria → model.json + report.md → pack (md/pdf/xlsx) → validation record → seal → add new evidence → rerun
(dedupe, inherited findings, version effect) → pack → seal → review (chronology + role plan) → pack → seal.
Prints a summary and exits 0 when every invariant holds. Run from the repo root:

    python ghost-recon/demo/smoke_test.py            # uses a temp DB (GHOSTRECON_DB)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

tmp = Path(tempfile.mkdtemp(prefix="ghostrecon-smoke-"))
os.environ["GHOSTRECON_DB"] = str(tmp / "ghostrecon.db")

from plugins.ghost_recon import runtime  # noqa: E402
from plugins.ghost_recon.core import casefolder as cf, review, service, swarm  # noqa: E402
from plugins.ghost_recon.core.reports import pack  # noqa: E402


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        sys.exit(1)


def main() -> int:
    case_dir = tmp / "demo-case"
    shutil.copytree(REPO / "ghost-recon" / "demo" / "demo-case", case_dir)
    st = runtime.store()
    print(f"temp case: {case_dir}")

    s = service.open_case(st, str(case_dir), name="Acme Importaciones (demo)")
    cid = s["case"]["id"]
    check(s["created"] and s["corpus_files"] == 9, f"case opened {cid} with 9 corpus rows (8 files + 1 zip member)")

    a = service.start_audit(st, cid, "initial")
    aid = a["audit"]["id"]; folder = Path(a["folder"])
    check(a["evidence"]["NEW"] == 9, "initial audit: every file NEW")
    plan = swarm.plan_extraction(st, aid)
    check({t["block"] for t in plan["tasks"]} >= {"banking", "commercial", "related_parties"}, f"extraction plan blocks: {sorted(plan['blocks'])}")
    check(all(Path(m).exists() for m in plan["manifests"]), "manifests written")

    service.add_criterion(st, aid, "socio A", "los pagos a Taller XYZ no son gasto de la sociedad", "2026-01-15")
    service.upsert_findings(st, aid, [
        {"kind": "exception", "title": "Wire 12/01 sin beneficiario impreso", "amount": 4000, "currency": "USD", "date": "2026-01-12",
         "risk": "high", "confidence": "UNRESOLVED", "label": "FACT", "next_evidence": "wire advice del banco, cuenta ****4832, 12-ene-2026, 4.000,00",
         "owner": "socio B (administrador)"},
        {"kind": "anomaly", "title": "Zelle a J. Perez sin factura ni registro de nómina", "amount": 2000, "risk": "medium"},
        {"kind": "question", "title": "¿Qué concepto tiene la transferencia a socio B del 27/02 (3.000,00)?", "amount": 3000, "owner": "socio B"},
    ])
    cf.write_json(folder, "03_Extracted_Data/model.json", {
        "kpis": {"Ingreso económico (entregas)": 23000, "Caja demostrada 31-mar": 13000, "Salidas sin concepto": 9000, "Posición socio A (base sociedad)": 2000},
        "audit_trail": [{"figure": "Ingreso económico", "value": 23000, "sheet": "07_REVENUE", "documents": ["FAC-2026-001", "FAC-2026-002"], "confidence": "CONFIRMED", "method": "facturas con entrega"}],
    })
    cf.write_text(folder, "06_Report/report.md", "## 1. La respuesta en una página\n\nIngreso económico **23.000 USD**; caja demostrada 13.000; salidas sin concepto 9.000 (EXC-01, ANO-01, Q-01).\n\n| Pregunta | Respuesta | Confianza |\n|---|---|---|\n| Cuánto ganó | 23.000 − 9.500 = 13.500 (bruto) | CALCULATION |\n| Cuánta caja debería tener | 13.000 demostrada; 9.000 pendientes de concepto | FACT / UNRESOLVED |\n\n## 6. Lo que queda abierto\n\n1. EXC-01 wire advice (4.000).\n2. Q-01 concepto transferencia a socio B (3.000).\n")
    vplan = swarm.plan_validation(st, aid, headline_figures={"ingreso": 23000})
    check(len(vplan["tasks"]) == 3, "validation plan has A/B/C")
    res = pack.build_pack(st, aid)
    check(len(res["files"]) == 3 and not res["warnings"], f"pack v1 built ({[Path(f['path']).name for f in res['files']]}) without warnings")
    service.record_run(st, aid, "validation", role="A", status="done", summary="recálculo OK")
    service.record_run(st, aid, "validation", role="B", status="done", summary="consistencia OK")
    sealed = service.seal_audit(st, aid)
    check(sealed["sealed"] and not sealed["forced"], f"A01 sealed ({sealed['file_count']} files)")
    try:
        cf.write_text(folder, "06_Report/x.md", "x"); check(False, "sealed folder must refuse writes")
    except cf.SealedAuditError:
        check(True, "sealed folder refuses writes")

    # new evidence + a duplicate under another name
    (case_dir / "Bancos" / "extracto_2026-03.txt").write_text("BANCO DEMO — Marzo 2026\nSaldo anterior 13,000.00\nSaldo nuevo 13,000.00\n", encoding="utf-8")
    shutil.copy(case_dir / "Facturas" / "FAC-2026-001.csv", case_dir / "Facturas" / "FAC-2026-001 (copia).csv")
    service.open_case(st, str(case_dir))  # what /rerun-case does first (must not disturb audited hashes)
    b = service.start_audit(st, cid, "rerun")
    bid = b["audit"]["id"]; bfolder = Path(b["folder"])
    ev = b["evidence"]
    check(ev["NEW"] == 1 and ev["DUP_PRIOR"] == 1 and ev["REGISTERED"] == 9, f"rerun dedupe: {ev}")
    check(len(b["inherited_open_findings"]) == 3, "rerun inherits the 3 open findings")
    plan2 = swarm.plan_extraction(st, bid)
    check(plan2["files_total"] == 1 and plan2["tasks"][0]["block"] == "banking", "rerun extraction plan covers only the new statement")
    cf.write_json(bfolder, "03_Extracted_Data/model.json", {"kpis": {"Ingreso económico (entregas)": 23000, "Caja demostrada 31-mar": 13000},
                                                           "version_effect": [{"item": "Caja demostrada", "previous": 13000, "new": 13000, "difference": 0, "document": "extracto_2026-03", "sheet": "27_CASH"}]})
    service.upsert_findings(st, bid, [{"id": "EXC-01", "kind": "exception", "status": "open", "risk": "high", "description": "sigue abierta: el extracto de marzo no trae el wire advice"}])
    cf.write_text(bfolder, "06_Report/report.md", "## 00. Adenda v2\n\nLlegó el extracto de marzo (NEW) y una copia de FAC-2026-001 (DUP_PRIOR). Nada cambió en las cifras.\n")
    res2 = pack.build_pack(st, bid)
    check(not res2["warnings"], "pack A02 built without warnings")
    service.record_run(st, bid, "validation", role="B", status="done", summary="OK")
    check(service.seal_audit(st, bid)["sealed"], "A02 sealed")
    check(service.verify_audit(st, aid)["ok"], "A01 seal still intact after rerun")
    f = st.get_finding(cid, "EXC-01")
    check(len(f["history"]) == 2 and f["history"][1]["audit_id"] == bid, "EXC-01 history continues across audits")

    rv = review.start_review(st, cid)
    rid = rv["review_id"]; rfolder = Path(rv["folder"])
    check(len(rv["plan"]["tasks"]) == 6 and Path(rv["chronology_md"]).exists(), "review: 6 role tasks + chronology")
    for role in rv["roles"]:
        cf.write_text(rfolder, f"roles/{role}.md", f"# {role}\n\nOpinión de prueba.\n")
    cf.write_text(rfolder, "diagnosis.md", "## Diagnóstico\n\nEXC-01 decide el caso; pedir el wire advice.\n")
    res3 = pack.build_pack(st, rid)
    check(len(res3["files"]) == 3 and not res3["warnings"], "review pack built")
    service.record_run(st, rid, "validation", role="B", status="done", summary="OK")
    check(service.seal_audit(st, rid)["sealed"], "R01 sealed")

    status = service.case_status(st, cid)
    check(all(a["seal_ok"] for a in status["audits"]), "all seals verify")
    mirror = cf.read_case_json(cf.audits_root(case_dir))
    check(mirror and len(mirror["audits"]) == 3, "case.json mirror lists 3 audits")
    print(json.dumps({"case": cid, "audits": [(a["id"], a["status"]) for a in status["audits"]], "findings": status["findings"]}, ensure_ascii=False))
    print(f"SMOKE TEST OK — outputs in {case_dir / 'GhostRecon_Audits'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
