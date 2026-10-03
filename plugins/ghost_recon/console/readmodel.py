"""Read models for the console API: plain dicts built from the case ``Store`` and the console tables. No writes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..core import ids
from ..core.db import Store
from .paths import case_results_root
from .store import ConsoleStore

RISKS = ("critical", "high", "medium", "low")
MAX_PAGE = 500
FINDING_TEXT_FIELDS = ("id", "title", "description", "counterparty", "entity", "category")
EVIDENCE_TEXT_FIELDS = ("path", "filename", "sha256", "doc_type", "entity")


def count_by(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        k = row.get(key) or "?"
        out[k] = out.get(k, 0) + 1
    return out


def open_by_risk(findings: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    out = {r: 0 for r in RISKS}
    for f in findings:
        if f.get("status") == "open":
            risk = f.get("risk") or "medium"
            out[risk] = out.get(risk, 0) + 1
    return out


def current_seal_check(cstore: ConsoleStore, audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The cached check, unless it is an OK for a different seal than the audit has now (then: unverified).

    A failed check always stands, whatever hash it recorded."""
    check = cstore.get_seal_check(audit["id"]) or None
    if check and check["ok"] and (check.get("detail") or {}).get("manifest_sha256") != audit.get("seal_sha256"):
        return None
    return check


def audit_view(store: Store, cstore: ConsoleStore, audit: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": audit["id"], "seq": ids.short_audit(audit["id"]), "kind": audit["kind"], "status": audit["status"],
            "folder": audit["folder"], "started_at": audit["started_at"], "sealed_at": audit.get("sealed_at"),
            "seal_sha256": audit.get("seal_sha256"), "seal_check": current_seal_check(cstore, audit),
            "reports": len(store.list_reports(audit["id"]))}


def seal_state(audits: List[Dict[str, Any]]) -> str:
    """Case-level seal summary from the cached checks: a broken seal wins; unchecked sealed audits = unverified."""
    checks = [a["seal_check"] for a in audits if a["status"] == "sealed"]
    if not checks:
        return "none"
    if any(c is not None and not c["ok"] for c in checks):
        return "broken"
    return "ok" if all(c is not None for c in checks) else "unverified"


def case_row(store: Store, cstore: ConsoleStore, case: Dict[str, Any]) -> Dict[str, Any]:
    audits = [audit_view(store, cstore, a) for a in store.list_audits(case["id"])]
    events = store.list_events(case["id"])
    risk = open_by_risk(store.list_findings(case["id"]))
    return {"id": case["id"], "name": case["name"], "root_path": case["root_path"], "status": case["status"],
            "base_currency": case["base_currency"], "language": case["language"],
            "audits_count": len(audits), "sealed_count": sum(1 for a in audits if a["status"] == "sealed"),
            "last_audit": audits[-1] if audits else None, "open_by_risk": risk, "open_total": sum(risk.values()),
            "evidence_total": store.evidence_stats(case["id"]).get("total", 0),
            "last_activity": events[-1]["ts"] if events else case["updated_at"], "seal_state": seal_state(audits)}


def _recent_first(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: r["last_activity"] or "", reverse=True)


def list_cases(store: Store, cstore: ConsoleStore, *, q: str = "", status: str = "") -> List[Dict[str, Any]]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if any(needle in r[k].lower() for k in ("name", "id", "root_path"))]
    return _recent_first(rows)


def overview(store: Store, cstore: ConsoleStore) -> Dict[str, Any]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    risk = {r: sum(row["open_by_risk"].get(r, 0) for row in rows) for r in RISKS}
    return {"kpis": {"cases_total": len(rows), "cases_active": sum(1 for r in rows if r["status"] == "open"),
                     "audits_sealed": sum(r["sealed_count"] for r in rows), "open_by_risk": risk,
                     "open_total": sum(risk.values()), "jobs_active": 0},
            "recent_cases": _recent_first(rows)[:8], "recent_events": cstore.recent_events(15)}


def case_detail(store: Store, cstore: ConsoleStore, case: Dict[str, Any]) -> Dict[str, Any]:
    findings = store.list_findings(case["id"])
    return {"case": case, "summary": case_row(store, cstore, case), "results_root": str(case_results_root(case)),
            "audits": [audit_view(store, cstore, a) for a in store.list_audits(case["id"])],
            "findings": {"total": len(findings), "by_kind": count_by(findings, "kind"),
                         "by_status": count_by(findings, "status")},
            "evidence": store.evidence_stats(case["id"]), "criteria": len(store.list_criteria(case["id"])),
            "research_notes": len(store.list_research_notes(case["id"]))}


def _matches(row: Dict[str, Any], needle: str, fields: Tuple[str, ...]) -> bool:
    return any(needle in str(row.get(k) or "").lower() for k in fields)


def filter_findings(rows: List[Dict[str, Any]], *, kind: str = "", risk: str = "", status: str = "",
                    q: str = "") -> List[Dict[str, Any]]:
    needle = q.strip().lower()
    return [f for f in rows if (not kind or f["kind"] == kind) and (not risk or f["risk"] == risk)
            and (not status or f["status"] == status) and (not needle or _matches(f, needle, FINDING_TEXT_FIELDS))]


def filter_evidence(rows: List[Dict[str, Any]], *, q: str = "") -> List[Dict[str, Any]]:
    needle = q.strip().lower()
    return [e for e in rows if not needle or _matches(e, needle, EVIDENCE_TEXT_FIELDS)]


def page(rows: List[Dict[str, Any]], cursor: str = "", limit: int = 100) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Offset pagination; the cursor is the next offset as a string, limit clamped to [1, MAX_PAGE]."""
    try:
        start = max(0, int(cursor or 0))
    except ValueError:
        start = 0
    end = start + max(1, min(int(limit), MAX_PAGE))
    return rows[start:end], (str(end) if end < len(rows) else None)
