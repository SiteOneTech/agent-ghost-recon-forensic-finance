"""Pack orchestration: assemble MD → build PDF + XLSX → hashes → LEEME → register in DB → tool-name scan.

``build_pack(store, audit_id, formats=("md","pdf","xlsx"), report_md=None, model_json=None, title=None)``
returns {"files": [...], "warnings": [...], "version": "v1"}.

Sources of truth: the agent's narrative (``06_Report/report.md`` or ``sections/*.md``), the model
(``03_Extracted_Data/model.json`` → kpis, audit_trail, version_effect) and the DB (findings, criteria, evidence,
research). Reviews use ``diagnosis.md`` + ``roles/*.md`` + ``chronology.md``.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .. import SIGNATURE, __version__, casefolder as cf, ids
from ..db import Store
from . import FORBIDDEN_TOOL_NAMES
from . import md as mdmod
from .md import fmt_money


def _load_model(audit: Dict[str, Any], model_json: Optional[str]) -> Dict[str, Any]:
    folder = Path(audit["folder"])
    cands = [Path(model_json)] if model_json else []
    if audit.get("model_json"):
        cands.append(Path(audit["model_json"]))
    cands += sorted((folder / "03_Extracted_Data").glob("model*.json"), reverse=True)
    for p in cands:
        if p.exists():
            data = cf.read_json(p, default={})
            if isinstance(data, dict):
                data["_path"] = str(p)
                return data
    return {}


PACK_KINDS = ("report_md", "executive_pdf", "workbook_xlsx", "review_md", "review_pdf")


def _version(store: Store, audit: Dict[str, Any]) -> str:
    n = len({r["version"] for r in store.list_reports(audit["id"]) if r["kind"] in PACK_KINDS})
    return f"v{n + 1}"


def _kpis_for_cover(model: Dict[str, Any], findings: List[Dict[str, Any]], currency: str) -> Dict[str, str]:
    kpis = model.get("kpis") or {}
    out: Dict[str, str] = {}
    for k, v in list(kpis.items())[:4]:
        out[str(k)] = fmt_money(v, currency) if isinstance(v, (int, float)) else str(v)
    if len(out) < 4:
        exc = [f for f in findings if f["kind"] == "exception"]
        out.setdefault("Excepciones abiertas", f"{sum(1 for f in exc if f['status'] == 'open')} de {len(exc)}")
    if len(out) < 4:
        q = [f for f in findings if f["kind"] == "question" and f["status"] == "open"]
        out.setdefault("Preguntas abiertas", str(len(q)))
    return out


def build_pack(store: Store, audit_id: str, *, formats: Sequence[str] = ("md", "pdf", "xlsx"), report_md: Optional[str] = None,
               model_json: Optional[str] = None, title: Optional[str] = None, subtitle: Optional[str] = None) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise ValueError(f"audit not found: {audit_id}")
    folder = cf.guard_writable(Path(audit["folder"]))
    case = store.get_case(audit["case_id"])
    is_review = audit["kind"] == "review"
    report_dir = folder / "06_Report"
    report_dir.mkdir(parents=True, exist_ok=True)
    version = _version(store, audit)
    short = ids.short_audit(audit_id)
    cur = case.get("base_currency", "USD")
    findings = store.list_findings(case["id"])
    criteria = store.list_criteria(case["id"])
    evidence = store.list_evidence(case["id"])
    research = store.list_research_notes(case["id"], audit_id)
    model = {} if is_review else _load_model(audit, model_json)
    warnings: List[str] = []
    files: List[Dict[str, Any]] = []

    # ------------------------------------------------------------- narrative
    if report_md:
        body = Path(report_md).read_text(encoding="utf-8")
    elif is_review:
        parts = []
        diag = folder / "diagnosis.md"
        if diag.exists():
            parts.append(diag.read_text(encoding="utf-8"))
        else:
            warnings.append("diagnosis.md not found: the review pack has no synthesis yet")
        for rp in sorted((folder / "roles").glob("*.md")):
            parts.append(f"\n\n## Opinión del rol: {rp.stem}\n\n" + rp.read_text(encoding="utf-8"))
        chron = folder / "chronology.md"
        if chron.exists():
            parts.append("\n\n" + chron.read_text(encoding="utf-8").replace("# Cronología", "## Cronología", 1))
        body = "\n".join(parts) if parts else "## Revisión sin contenido\n\n(diagnosis.md y roles/*.md vacíos)"
    else:
        body = mdmod.read_sections(report_dir)
        if body is None:
            body = mdmod.skeleton_report(case, audit, model)
            warnings.append("06_Report/report.md not found: skeleton narrative used (complete it and rebuild)")
    if not model and not is_review:
        warnings.append("model.json not found: no KPI / audit-trail / version-effect sheets")

    kind_label = "Revisión de caso" if is_review else ("Informe de auditoría forense" if audit["kind"] == "initial" else "Informe de auditoría forense (pase de evidencia)")
    doc_title = title or f"{kind_label} — {case['name']}"
    prefix = "GhostRecon_Revision" if is_review else "GhostRecon_Informe"
    base = f"{prefix}_{case['slug']}_{short}_{version}"
    md_path = report_dir / f"{base}.md"
    xlsx_name = f"GhostRecon_Workbook_{case['slug']}_{short}_{version}.xlsx"
    pdf_name = f"GhostRecon_Ejecutivo_{case['slug']}_{short}_{version}.pdf" if not is_review else f"GhostRecon_Revision_{case['slug']}_{short}_{version}.pdf"

    full_md = mdmod.assemble(case, audit, title=doc_title, version=version, body_md=body, findings=findings, criteria=criteria,
                             evidence=evidence, research=research, version_effect=model.get("version_effect"),
                             companion=xlsx_name if "xlsx" in formats else None)
    if "md" in formats:
        md_path.write_text(full_md, encoding="utf-8")
        files.append(_reg(store, audit_id, "review_md" if is_review else "report_md", md_path, "md", version))

    # ------------------------------------------------------------- xlsx
    if "xlsx" in formats:
        try:
            from .xlsx import build_workbook
            validation = cf.read_json(folder / "validation" / "validation.json", default=None)
            xp = build_workbook(case, audit, dest=report_dir / xlsx_name, version=version, model=model, findings=findings,
                                criteria=criteria, evidence=evidence, research=research, validation=validation)
            files.append(_reg(store, audit_id, "workbook_xlsx", xp, "xlsx", version))
        except ImportError as exc:
            warnings.append(f"xlsx skipped: {exc}")
        except Exception as exc:  # the md must still be delivered; the agent fixes and rebuilds
            warnings.append(f"xlsx failed: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------- pdf
    if "pdf" in formats:
        try:
            from .pdf import build_pdf
            meta_lines = [f"Caso {case['id']} · Auditoría {short} ({audit['kind']}) · {version}",
                          f"Fecha de emisión: {datetime.now().date().isoformat()} · Moneda base: {cur}",
                          f"Carpeta de evidencia: {case['root_path']}"]
            pp = build_pdf(full_md, report_dir / pdf_name, title=doc_title, subtitle=subtitle or SIGNATURE, meta_lines=meta_lines,
                           kpis=_kpis_for_cover(model, findings, cur), companion=xlsx_name if "xlsx" in formats else "")
            files.append(_reg(store, audit_id, "review_pdf" if is_review else "executive_pdf", pp, "pdf", version))
        except ImportError as exc:
            warnings.append(f"pdf skipped: {exc}")
        except Exception as exc:
            warnings.append(f"pdf failed: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------- hashes, LEEME, scan
    hashes = [(f["path"], f["sha256"]) for f in files]
    (report_dir / "pack_hashes.txt").write_text("".join(f"{h}  {Path(p).name}\n" for p, h in hashes), encoding="utf-8")
    leeme = [f"# LEEME — pack documental {short} {version}", "", f"Caso: {case['name']} ({case['id']})", f"Generado: {datetime.now().isoformat(timespec='seconds')} · motor {__version__}", "",
             "| Archivo | Para quién | SHA-256 |", "|---|---|---|"]
    who = {"md": "otros agentes / archivo (citable, íntegro)", "pdf": "lectura ejecutiva (socios, abogado, contador)", "xlsx": "revisión línea a línea (evidencia, registros, pista de auditoría)"}
    for f in files:
        leeme.append(f"| {Path(f['path']).name} | {who.get(f['format'], '')} | {f['sha256']} |")
    if warnings:
        leeme += ["", "## Avisos de construcción", ""] + [f"- {w}" for w in warnings]
    leeme += ["", "Versiones anteriores: carpeta `versions/`. Ningún número de este pack se tecleó a mano: todo proviene de model.json y de la base de datos del caso.", "", f"— {SIGNATURE}"]
    (report_dir / "LEEME.md").write_text("\n".join(leeme) + "\n", encoding="utf-8")
    scan = scan_tool_names([Path(f["path"]) for f in files], ignore=[case["root_path"], str(folder)])
    if scan:
        warnings.append(f"tool names found in deliverables (fix before delivery): {scan}")
    store.add_event(case["id"], "pack_built", f"Pack {version} de {short}: {', '.join(Path(f['path']).name for f in files)}",
                    audit_id=audit_id, ref={"warnings": warnings})
    return {"audit_id": audit_id, "version": version, "files": files, "warnings": warnings, "leeme": str(report_dir / "LEEME.md"),
            "hashes": str(report_dir / "pack_hashes.txt")}


def _reg(store: Store, audit_id: str, kind: str, path: Path, fmt: str, version: str) -> Dict[str, Any]:
    sha = cf.sha256_file(path)
    size = path.stat().st_size
    store.add_report(audit_id, kind, str(path), fmt, version=version, sha256=sha, size=size)
    return {"kind": kind, "path": str(path), "format": fmt, "sha256": sha, "size": size, "version": version}


def scan_tool_names(paths: List[Path], ignore: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """Case-insensitive scan of deliverable bytes (XLSX members decompressed) for library/provider names.
    ``ignore`` substrings (e.g. the case root path, which may legitimately contain such a word) are blanked first."""
    hits: Dict[str, List[str]] = {}
    pat = re.compile("|".join(re.escape(n) for n in FORBIDDEN_TOOL_NAMES), re.I)
    ignores = [i for i in (ignore or []) if i]
    for p in paths:
        try:
            if p.suffix.lower() == ".xlsx":
                with zipfile.ZipFile(p) as zf:
                    blobs = [zf.read(n) for n in zf.namelist()]
            else:
                blobs = [p.read_bytes()]
        except (OSError, zipfile.BadZipFile):
            continue
        found = set()
        for b in blobs:
            text = b.decode("latin-1", errors="ignore")
            for ig in ignores:
                text = text.replace(ig, "").replace(ig.replace("\\", "/"), "")
            for m in pat.finditer(text):
                found.add(m.group(0).lower())
        if found:
            hits[p.name] = sorted(found)
    return hits
