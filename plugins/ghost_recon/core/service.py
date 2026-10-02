"""Case service — the operations behind the gr_* tools and the CLI (Store + casefolder glued together).

Every public function takes a ``Store`` and plain values and returns JSON-serialisable dicts, so the
Hermes tool layer is a thin adapter and the standalone CLI / tests drive the same code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import SIGNATURE, __version__
from . import casefolder as cf
from . import ids
from .db import Store


class CaseError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- open / status

def open_case(store: Store, folder: str, *, name: Optional[str] = None, context_md: Optional[str] = None,
              base_currency: Optional[str] = None, language: Optional[str] = None,
              audits_dir: str = cf.DEFAULT_AUDITS_DIR, out_dir: Optional[str] = None) -> Dict[str, Any]:
    """Create or load the case anchored to ``folder``. Inventories the corpus (hashes) and refreshes the mirror.
    If the folder carries a ``case.json`` but the DB has no row, the case is re-imported."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise CaseError(f"evidence folder not found: {root}")
    case = store.get_case(str(root))
    aroot = cf.audits_root(root, audits_dir, out_dir)
    created = False
    if not case:
        mirror = cf.read_case_json(aroot)
        if mirror and mirror.get("case"):
            case = store.import_case(mirror)
            store.add_event(case["id"], "case_reimported", f"Caso re-importado desde {aroot / cf.CASE_JSON}")
        else:
            cname = name or root.name
            cid = ids.case_id(cname)
            if store.get_case(cid):
                cid = f"{cid}-{abs(hash(str(root))) % 1000:03d}"
            ctx = _resolve_context(root, context_md)
            case = store.create_case(id=cid, slug=ids.slugify(cname), name=cname, root_path=str(root),
                                     audits_dir=audits_dir, base_currency=base_currency or "USD",
                                     language=language or "es", context_md=ctx,
                                     meta={"out_dir": str(aroot) if out_dir else None, "engine": __version__})
            store.add_event(cid, "case_opened", f"Caso abierto sobre {root}", ref={"context_md": ctx})
            created = True
    else:
        updates: Dict[str, Any] = {}
        if context_md:
            updates["context_md"] = _resolve_context(root, context_md)
        if base_currency:
            updates["base_currency"] = base_currency
        if language:
            updates["language"] = language
        if name and name != case["name"]:
            updates["name"] = name
        if updates:
            store.update_case(case["id"], **updates)
            case = store.get_case(case["id"])
    # Fresh inventory of the whole corpus (not yet assigned to an audit).
    rows = cf.inventory(root, exclude_dirs=(audits_dir,), extra_exclude_paths=[aroot])
    # New paths enter as NEW (unassigned until an audit starts); audited rows are never overwritten here.
    store.upsert_evidence(case["id"], [r.as_dict() for r in rows], preserve_assigned=True)
    cf.write_inventory_csv(rows, aroot / cf.CORPUS_INVENTORY)
    refresh_mirror(store, case["id"])
    status = case_status(store, case["id"])
    status["created"] = created
    status["corpus_files"] = len(rows)
    status["next_step"] = _next_step(store, case["id"])
    return status


def _resolve_context(root: Path, context_md: Optional[str]) -> Optional[str]:
    if context_md:
        p = Path(context_md).expanduser()
        if not p.is_absolute():
            p = (root / p)
        return str(p.resolve()) if p.exists() else str(p)
    default = root / "context.md"
    return str(default) if default.exists() else None


def _next_step(store: Store, case_id: str) -> str:
    audits = store.list_audits(case_id, kinds=("initial", "rerun"))
    if not audits:
        return "gr_audit_start(kind='initial') y seguir la skill new-open-case"
    last = audits[-1]
    if last["status"] != "sealed":
        return f"continuar la auditoría abierta {last['id']} (carpeta {last['folder']})"
    return "gr_audit_start(kind='rerun') para un pase de evidencia, o gr_review_plan para /review-case"


def case_status(store: Store, key: str) -> Dict[str, Any]:
    case = _require_case(store, key)
    audits = []
    for a in store.list_audits(case["id"]):
        seal = cf.verify_seal(Path(a["folder"])) if a["status"] == "sealed" else {"ok": None, "sealed": False}
        audits.append({**a, "seal_ok": seal.get("ok"), "seal_changes": {k: seal.get(k, []) for k in ("missing", "added", "modified")}
                       if seal.get("sealed") else None, "reports": store.list_reports(a["id"])})
    findings = store.list_findings(case["id"])
    open_by_risk: Dict[str, int] = {}
    for f in findings:
        if f["status"] == "open":
            open_by_risk[f["risk"]] = open_by_risk.get(f["risk"], 0) + 1
    return {
        "case": case, "audits": audits, "evidence": store.evidence_stats(case["id"]),
        "findings": {"total": len(findings), "open_by_risk": open_by_risk,
                     "by_kind": _count(findings, "kind"), "by_status": _count(findings, "status")},
        "criteria": len(store.list_criteria(case["id"])),
        "audits_root": str(cf.audits_root(Path(case["root_path"]), case["audits_dir"], (case.get("meta") or {}).get("out_dir"))),
    }


def _count(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r.get(key) or "?"] = out.get(r.get(key) or "?", 0) + 1
    return out


def _require_case(store: Store, key: str) -> Dict[str, Any]:
    case = store.get_case(key)
    if not case:
        p = Path(key).expanduser()
        if p.exists():
            case = store.get_case(str(p.resolve()))
    if not case:
        raise CaseError(f"case not found: {key}. Run gr_case_open(folder) first.")
    return case


def refresh_mirror(store: Store, case_id: str) -> Path:
    case = store.get_case(case_id)
    aroot = cf.audits_root(Path(case["root_path"]), case["audits_dir"], (case.get("meta") or {}).get("out_dir"))
    data = store.export_case(case_id)
    data["evidence"] = [{k: v for k, v in e.items() if k != "meta"} for e in data["evidence"]]
    data["signature"] = SIGNATURE
    return cf.write_case_json(aroot, data)


# ---------------------------------------------------------------------------------------------- audits

def start_audit(store: Store, case_key: str, kind: str = "initial", *, context_md: Optional[str] = None,
                out_dir: Optional[str] = None, content_dedupe: bool = True) -> Dict[str, Any]:
    """Create the next audit folder and run the intake / evidence pass.

    initial: first audit; every file is NEW and assigned to this audit.
    rerun:   requires a sealed previous audit; dedupes the corpus against everything registered before;
             writes Evidence_Pass/register.csv + dedupe.json; inherits open findings.
    review:  handled by review.start_review (kept separate: different folder layout).
    """
    if kind not in ("initial", "rerun"):
        raise CaseError("kind must be 'initial' or 'rerun' (reviews use gr_review_plan)")
    case = _require_case(store, case_key)
    root = Path(case["root_path"])
    audits = store.list_audits(case["id"], kinds=("initial", "rerun"))
    open_ones = [a for a in audits if a["status"] != "sealed"]
    if open_ones:
        raise CaseError(f"audit {open_ones[-1]['id']} is still open ({open_ones[-1]['folder']}); seal it or continue it.")
    if kind == "initial" and audits:
        raise CaseError(f"case already has {len(audits)} audit(s); use kind='rerun' (/rerun-case).")
    if kind == "rerun" and not audits:
        kind = "initial"
    parent = audits[-1] if audits else None
    seq = store.next_audit_seq(case["id"], "A")
    aid = ids.audit_id(case["id"], seq, kind)
    aroot = cf.audits_root(root, case["audits_dir"], out_dir or (case.get("meta") or {}).get("out_dir"))
    ctx = _resolve_context(root, context_md) or case.get("context_md")
    # Evidence pass FIRST (an unreadable corpus must not leave an open audit row behind)
    known = store.known_hashes(case["id"], exclude_audit_id=aid) if kind == "rerun" else {}
    rows = cf.inventory(root, exclude_dirs=(case["audits_dir"],), extra_exclude_paths=[aroot])
    manifest = {"audit_id": aid, "case_id": case["id"], "case_name": case["name"], "seq": seq,
                "parent_audit_id": parent["id"] if parent else None, "context_md": ctx,
                "base_currency": case["base_currency"], "language": case["language"], "engine": __version__}
    folder = cf.create_audit_folder(aroot, ids.audit_folder_name(seq, kind), kind, manifest)
    audit = store.create_audit(id=aid, case_id=case["id"], seq=seq, kind=kind, folder=str(folder),
                               parent_audit_id=parent["id"] if parent else None, context_md=ctx,
                               out_override=out_dir)
    known_fp: Dict[str, str] = {}
    if kind == "rerun" and content_dedupe:
        # fingerprints of previously registered text/PDF files (level-2 dedupe)
        for e in store.list_evidence(case["id"]):
            if e["sha256"] in known and not e["zip_member"] and e["status"] not in ("DUP_PRIOR", "DUP_INTERNAL", "DUP_CONTENT"):
                fp = cf.text_fingerprint(root / e["path"]) if (root / e["path"]).exists() else None
                if fp:
                    known_fp[fp] = e["path"]
    result = cf.dedupe(rows, known, root=root, known_fingerprints=known_fp, audit_id=aid, first_audit=(kind == "initial"))
    # Rows registered by an earlier audit keep their first_audit_id/status; everything else belongs to this one.
    existing = {e["path"]: e for e in store.list_evidence(case["id"])}
    store.upsert_evidence(case["id"], [r.as_dict() for r in rows])
    for r in rows:
        prev = existing.get(r.path)
        if prev and prev.get("first_audit_id") and prev["first_audit_id"] != aid:
            r.first_audit_id = prev["first_audit_id"]
            # Same path as an audited file: unchanged -> REGISTERED; different bytes -> MODIFIED (a finding).
            if prev["sha256"] == r.sha256:
                r.status = "REGISTERED"
                store.update_evidence(case["id"], r.path, status=r.status)
            else:
                r.status = "MODIFIED"
                meta = dict(prev.get("meta") or {}); meta.setdefault("previous_hashes", []).append(
                    {"sha256": prev["sha256"], "audit_id": prev["first_audit_id"], "replaced_in": aid})
                store.update_evidence(case["id"], r.path, status=r.status, meta=meta)
        else:
            r.first_audit_id = aid
            store.update_evidence(case["id"], r.path, status=r.status, first_audit_id=aid)
    # Final statistics after the path rule (REGISTERED / MODIFIED are not batch duplicates).
    stats: Dict[str, int] = {}
    for r in rows:
        stats[r.status] = stats.get(r.status, 0) + 1
    stats["total"] = len(rows)
    result["stats"] = stats
    cf.write_inventory_csv(rows, aroot / cf.CORPUS_INVENTORY)
    cf.write_inventory_csv(rows, folder / "01_Source_Index" / "corpus_inventory.csv")
    new_rows = [r for r in rows if r.first_audit_id == aid and r.status == "NEW"]
    modified = [r.path for r in rows if r.status == "MODIFIED"]
    cf.write_inventory_csv(new_rows, folder / "01_Source_Index" / "evidence_register.csv")
    inherited = []
    if kind == "rerun":
        cf.write_inventory_csv([r for r in rows if r.status != "REGISTERED"], folder / "Evidence_Pass" / "register.csv")
        cf.write_json(folder, "Evidence_Pass/dedupe.json", {k: v for k, v in result.items() if k != "rows"})
        inherited = [f for f in store.list_findings(case["id"]) if f["status"] == "open"]
        cf.write_json(folder, "Evidence_Pass/inherited_open_findings.json", inherited)
        if parent:
            _copy_scripts(Path(parent["folder"]) / "src", folder / "src")
    summary = {"evidence_new": len(new_rows), "evidence_total_corpus": len(rows), "dedupe": result["stats"],
               "inherited_open_findings": len(inherited), "modified_evidence": modified}
    if modified:
        store.add_event(case["id"], "evidence_modified", f"{len(modified)} archivo(s) ya auditados cambiaron de contenido",
                        audit_id=aid, ref={"paths": modified[:50]})
    store.update_audit(aid, status="in_progress", summary=summary)
    store.add_event(case["id"], "audit_started", f"Auditoría {ids.short_audit(aid)} ({kind}) iniciada en {folder}",
                    audit_id=aid, ref=summary)
    refresh_mirror(store, case["id"])
    return {"audit": store.get_audit(aid), "folder": str(folder), "evidence": {**result["stats"], "new_files": [r.path for r in new_rows][:200]},
            "inherited_open_findings": inherited, "context_md": ctx, "parent_audit": parent["id"] if parent else None,
            "manifest": str(folder / cf.MANIFEST_FILE)}


def _copy_scripts(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.is_file():
            (dst / p.name).write_bytes(p.read_bytes())


def record_run(store: Store, audit_id: str, kind: str, *, role: Optional[str] = None, status: str = "done",
               summary: str = "", input: Optional[dict] = None, output: Optional[dict] = None) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise CaseError(f"audit not found: {audit_id}")
    cf.guard_writable(Path(audit["folder"]))
    rid = store.add_run(audit_id, kind, role=role, status=status, input=input, output=output, summary=summary)
    store.add_event(audit["case_id"], f"run_{kind}", f"{kind}{'/' + role if role else ''}: {status} — {summary[:200]}",
                    audit_id=audit_id, ref={"run_id": rid})
    if kind == "validation":
        vpath = Path(audit["folder"]) / "validation" / "validation.json"
        data = cf.read_json(vpath, default={"rounds": []}) or {"rounds": []}
        data["rounds"].append({"run_id": rid, "role": role, "status": status, "summary": summary, "output": output or {}})
        cf.write_json(Path(audit["folder"]), "validation/validation.json", data)
    return {"run_id": rid, "audit_id": audit_id, "kind": kind, "status": status}


def upsert_findings(store: Store, audit_id: str, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise CaseError(f"audit not found: {audit_id}")
    cf.guard_writable(Path(audit["folder"]))
    out = [store.upsert_finding(audit["case_id"], audit_id, f) for f in findings]
    _export_findings(store, audit)
    refresh_mirror(store, audit["case_id"])
    return {"audit_id": audit_id, "findings": [{"id": f["id"], "kind": f["kind"], "status": f["status"], "risk": f["risk"]} for f in out]}


def _export_findings(store: Store, audit: Dict[str, Any]) -> None:
    data = {"audit_id": audit["id"], "findings": store.list_findings(audit["case_id"]),
            "criteria": store.list_criteria(audit["case_id"]), "signature": SIGNATURE}
    cf.write_json(Path(audit["folder"]), "05_Exceptions/exceptions.json", data)


def add_criterion(store: Store, audit_id: str, author: str, text: str, date: Optional[str] = None) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise CaseError(f"audit not found: {audit_id}")
    cf.guard_writable(Path(audit["folder"]))
    c = store.add_criterion(audit["case_id"], audit_id, author, text, date)
    store.add_event(audit["case_id"], "criterion_added", f"{c['id']} ({author}): {text[:120]}", audit_id=audit_id)
    _export_findings(store, audit)
    return c


# ---------------------------------------------------------------------------------------------- sealing

COMPLETION_CHECKS = ("manifest", "evidence_register", "model_json", "report_md", "report_pdf", "workbook_xlsx",
                     "validation", "exceptions_export")


def completion_report(store: Store, audit: Dict[str, Any]) -> Dict[str, Any]:
    folder = Path(audit["folder"])
    reports = store.list_reports(audit["id"])
    kinds = {r["kind"] for r in reports}
    is_review = audit["kind"] == "review"
    checks = {
        "manifest": (folder / cf.MANIFEST_FILE).exists(),
        "evidence_register": is_review or (folder / "01_Source_Index" / "evidence_register.csv").exists(),
        "model_json": is_review or bool(audit.get("model_json")) or any((folder / "03_Extracted_Data").glob("model*.json")),
        "report_md": ("report_md" in kinds) or ("review_md" in kinds) or any((folder / "06_Report").glob("*.md")),
        "report_pdf": ("executive_pdf" in kinds) or ("review_pdf" in kinds) or any((folder / "06_Report").glob("*.pdf")),
        "workbook_xlsx": ("workbook_xlsx" in kinds) or ("chronology_xlsx" in kinds) or any((folder / "06_Report").glob("*.xlsx")),
        "validation": bool(store.list_runs(audit["id"], kind="validation")) or (folder / "validation" / "validation.json").exists(),
        "exceptions_export": is_review or (folder / "05_Exceptions" / "exceptions.json").exists(),
    }
    return {"checks": checks, "complete": all(checks.values()), "missing": [k for k, v in checks.items() if not v]}


def seal_audit(store: Store, audit_id: str, *, force: bool = False) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise CaseError(f"audit not found: {audit_id}")
    folder = Path(audit["folder"])
    if cf.is_sealed(folder):
        return {"audit_id": audit_id, "already_sealed": True, "verify": cf.verify_seal(folder)}
    if audit["kind"] != "review":
        _export_findings(store, audit)  # deterministic export from the DB; part of the sealed record
    comp = completion_report(store, audit)
    if not comp["complete"] and not force:
        return {"audit_id": audit_id, "sealed": False, "completion": comp,
                "hint": "complete the missing items or call with force=true (recorded in the seal)"}
    extra = {"forced": bool(force and not comp["complete"]), "completion": comp,
             "reports": [{"kind": r["kind"], "path": r["path"], "sha256": r["sha256"]} for r in store.list_reports(audit_id)]}
    rec = cf.seal(folder, audit_id, extra)
    store.update_audit(audit_id, status="sealed", sealed_at=rec["sealed_at"], seal_sha256=rec["manifest_sha256"])
    store.add_event(audit["case_id"], "audit_sealed", f"Auditoría {ids.short_audit(audit_id)} sellada ({rec['file_count']} archivos)",
                    audit_id=audit_id, ref={"manifest_sha256": rec["manifest_sha256"], "forced": extra["forced"]})
    refresh_mirror(store, audit["case_id"])
    return {"audit_id": audit_id, "sealed": True, "sealed_at": rec["sealed_at"], "file_count": rec["file_count"],
            "manifest_sha256": rec["manifest_sha256"], "forced": extra["forced"], "completion": comp}


def verify_audit(store: Store, audit_id: str) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise CaseError(f"audit not found: {audit_id}")
    v = cf.verify_seal(Path(audit["folder"]))
    return {"audit_id": audit_id, **v, "db_seal_sha256": audit.get("seal_sha256"),
            "db_matches": (audit.get("seal_sha256") == v.get("manifest_sha256")) if v.get("sealed") else None}


def evidence_index(store: Store, audit_id: str, *, status: Optional[str] = None, block: Optional[str] = None,
                   only_this_audit: bool = False, limit: int = 0) -> Dict[str, Any]:
    audit = store.get_audit(audit_id)
    if not audit:
        raise CaseError(f"audit not found: {audit_id}")
    rows = store.list_evidence(audit["case_id"], first_audit_id=audit_id if only_this_audit else None,
                               status=status, block=block, limit=limit)
    root = store.get_case(audit["case_id"])["root_path"]
    slim = [{k: e[k] for k in ("path", "filename", "ext", "size", "sha256", "block", "status", "first_audit_id",
                              "doc_type", "zip_member")} for e in rows]
    return {"audit_id": audit_id, "root_path": root, "count": len(slim), "rows": slim,
            "blocks": _count(rows, "block"), "statuses": _count(rows, "status")}


def timeline(store: Store, case_key: str) -> Dict[str, Any]:
    case = _require_case(store, case_key)
    events = store.list_events(case["id"])
    findings = store.list_findings(case["id"])
    evolution = [{"id": f["id"], "kind": f["kind"], "title": f["title"], "status": f["status"], "risk": f["risk"],
                  "history": f.get("history") or []} for f in findings]
    return {"case": {k: case[k] for k in ("id", "name", "root_path", "status")}, "events": events,
            "audits": [{k: a[k] for k in ("id", "kind", "status", "folder", "started_at", "sealed_at")} for a in store.list_audits(case["id"])],
            "findings_evolution": evolution, "criteria": store.list_criteria(case["id"])}
