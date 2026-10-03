#!/usr/bin/env python3
"""Ghost Recon console demo: seeds an isolated DB with the demo case and starts the console (no LLM, no Hermes).

    python ghost-recon/demo/console_demo.py [--port 9230]

Copies demo/demo-case to a temp folder, builds a sealed A01 (md pack, findings, a criterion) and an open A02,
creates the admin ``demo`` / ``demo-pass-123`` and the viewer ``visor`` / ``visor-pass-123``, and serves the
console on http://localhost:<port>. Use it to try the UI and for H4 acceptance rehearsals.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=9230)
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="gr-console-demo-"))
    os.environ["GHOSTRECON_DB"] = str(tmp / "ghostrecon.db")

    import uvicorn
    from plugins.ghost_recon import runtime
    from plugins.ghost_recon.console.app import create_app
    from plugins.ghost_recon.console.auth import AuthService
    from plugins.ghost_recon.console.settings import ConsoleSettings
    from plugins.ghost_recon.console.store import ConsoleStore
    from plugins.ghost_recon.core import casefolder as cf, service
    from plugins.ghost_recon.core.reports import pack

    case_dir = tmp / "Acme Importaciones"
    shutil.copytree(REPO / "ghost-recon" / "demo" / "demo-case", case_dir)
    store = runtime.store()
    case_id = service.open_case(store, str(case_dir), name="Acme Importaciones")["case"]["id"]
    a1 = service.start_audit(store, case_id, "initial")
    a1_id, a1_folder = a1["audit"]["id"], Path(a1["folder"])
    service.upsert_findings(store, a1_id, [
        {"kind": "exception", "title": "Pagos Zelle a socio sin factura soporte", "amount": 12450.0, "currency": "USD",
         "risk": "high", "confidence": "PROBABLE", "label": "CALCULATION", "counterparty": "Socio B",
         "owner": "Socio B", "next_evidence": "Facturas del socio ene–mar 2026",
         "evidence_refs": ["Bancos/extracto_2026-01.txt", "Bancos/listado_zelle_2026Q1.zip"]},
        {"kind": "anomaly", "title": "Factura de proveedor con fecha posterior al pago", "amount": 3200.0,
         "currency": "USD", "risk": "medium", "confidence": "POSSIBLE", "label": "INFERENCE", "owner": "Fábrica"},
        {"kind": "question", "title": "¿Quién autorizó el acta de diciembre?", "risk": "medium",
         "confidence": "UNRESOLVED", "label": "UNKNOWN", "owner": "Gerencia"},
    ])
    service.add_criterion(store, a1_id, "Gerencia", "El periodo auditado es enero–junio 2026.")
    cf.write_json(a1_folder, "03_Extracted_Data/model.json", {"kpis": {"Ingresos": 182000.0}})
    cf.write_text(a1_folder, "06_Report/report.md", "## 1. Respuesta\n\nResumen del caso demo.\n")
    pack.build_pack(store, a1_id, formats=["md"])
    service.record_run(store, a1_id, "validation", role="A", status="done", summary="recálculo desde crudo OK")
    service.seal_audit(store, a1_id, force=True)
    (case_dir / "Bancos" / "extracto_2026-03.txt").write_text("2026-03-02;ZELLE;Socio B;-1500.00\n", encoding="utf-8")
    service.start_audit(store, case_id, "rerun")

    settings = ConsoleSettings(port=args.port)
    cstore = ConsoleStore.open_default()
    auth = AuthService(cstore, settings)
    auth.add_user("demo", "demo-pass-123", "admin")
    auth.add_user("visor", "visor-pass-123", "viewer")
    print(f"Consola demo en http://localhost:{args.port}\n  admin:  demo / demo-pass-123\n"
          f"  viewer: visor / visor-pass-123\n  datos:  {tmp}", flush=True)
    uvicorn.run(create_app(settings, store, cstore, auth=auth), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
