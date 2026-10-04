"""Read models for the console API: plain dicts built from the case ``Store`` and the console tables. No writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from ..core import ids
from ..core.db import Store
from . import events
from .commands import display_command
from .paths import case_results_root
from .store import ACTIVE_STATUSES, ConsoleStore

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


def list_cases(store: Store, cstore: ConsoleStore, *, q: str = "", status: str = "",
               risk: str = "") -> List[Dict[str, Any]]:
    """``risk``: cases with open findings of that risk; ``any``: with any open finding (spec §10.3 "riesgo abierto")."""
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if risk == "any":
        rows = [r for r in rows if r["open_total"] > 0]
    elif risk:
        rows = [r for r in rows if r["open_by_risk"].get(risk, 0) > 0]
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if any(needle in r[k].lower() for k in ("name", "id", "root_path"))]
    return _recent_first(rows)


def overview(store: Store, cstore: ConsoleStore) -> Dict[str, Any]:
    rows = [case_row(store, cstore, c) for c in store.list_cases()]
    risk = {r: sum(row["open_by_risk"].get(r, 0) for row in rows) for r in RISKS}
    active = [job_row(store, j) for j in cstore.list_jobs(statuses=ACTIVE_STATUSES)]
    return {"kpis": {"cases_total": len(rows), "cases_active": sum(1 for r in rows if r["status"] == "open"),
                     "audits_sealed": sum(r["sealed_count"] for r in rows), "open_by_risk": risk,
                     "open_total": sum(risk.values()), "jobs_active": len(active),
                     "jobs_running": sum(1 for j in active if j["status"] == "running")},
            "recent_cases": _recent_first(rows)[:8], "recent_events": cstore.recent_events(15),
            "active_jobs": active}


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


@dataclass(frozen=True)
class TableFilters:
    """The filters of the case tables (findings: kind, risk, status, q; evidence: status, audit, q)."""
    kind: str = ""
    risk: str = ""
    status: str = ""
    q: str = ""
    audit: str = ""


def findings_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    return filter_findings(store.list_findings(case_id), kind=f.kind, risk=f.risk, status=f.status, q=f.q)


def evidence_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    rows = store.list_evidence(case_id, status=f.status or None,
                               first_audit_id=f"{case_id}/{f.audit}" if f.audit else None)
    return filter_evidence(rows, q=f.q)


def timeline_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    """Newest first."""
    return sorted(store.list_events(case_id), key=lambda e: (e["ts"], e["id"]), reverse=True)


def criteria_rows(store: Store, case_id: str, f: TableFilters) -> List[Dict[str, Any]]:
    return store.list_criteria(case_id)


# One source for the rows of each case table: the JSON endpoints and the CSV/XLSX exports both read through it, so an
# export always holds what the table shows with the same filters.
TABLE_ROWS: Dict[str, Callable[[Store, str, TableFilters], List[Dict[str, Any]]]] = {
    "findings": findings_rows, "evidence": evidence_rows, "timeline": timeline_rows, "criteria": criteria_rows}


def page(rows: List[Dict[str, Any]], cursor: str = "", limit: int = 100) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Offset pagination; the cursor is the next offset as a string, limit clamped to [1, MAX_PAGE]."""
    try:
        start = max(0, int(cursor or 0))
    except ValueError:
        start = 0
    end = start + max(1, min(int(limit), MAX_PAGE))
    return rows[start:end], (str(end) if end < len(rows) else None)


def _seconds(start: Optional[str], end: Optional[str]) -> Optional[int]:
    """Seconds between two ISO-8601 UTC stamps (until now when ``end`` is empty)."""
    if not start:
        return None
    try:
        begin = datetime.fromisoformat(start.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
    except ValueError:
        return None
    return max(0, int((finish - begin).total_seconds()))


def job_row(store: Store, job: Dict[str, Any]) -> Dict[str, Any]:
    """A job as the tables and Home's "En curso" list show it."""
    case = store.get_case(job["case_id"]) if job.get("case_id") else {}
    phase = job.get("phase") or ""
    return {"id": job["id"], "command": job["command"], "status": job["status"],
            "active": job["status"] in ACTIVE_STATUSES, "folder": job["folder"],
            "folder_name": Path(job["folder"]).name, "case_id": job.get("case_id"), "case_name": case.get("name"),
            "phase": phase or None, "phase_label": events.PHASE_LABEL.get(phase), "launched_by": job["launched_by"],
            "created_at": job["created_at"], "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "duration_s": _seconds(job.get("started_at"), job.get("finished_at"))}


def progress(store: Store, case_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The "Hasta ahora" counters, read from the case DB; None until the case exists."""
    if not case_id or not store.get_case(case_id):
        return None
    findings = store.list_findings(case_id)
    return {"evidence": store.evidence_stats(case_id).get("total", 0), "findings": count_by(findings, "kind"),
            "findings_total": len(findings), "criteria": len(store.list_criteria(case_id)),
            "research_notes": len(store.list_research_notes(case_id))}


def job_view(store: Store, cstore: ConsoleStore, job: Dict[str, Any], *, profile_args: Sequence[str],
             dashboard_url: str) -> Dict[str, Any]:
    """Everything the Ejecución view shows; ``resume`` appears once the agent reported its session."""
    session = job.get("session_id") or ""
    audits = store.list_audits(job["case_id"]) if job.get("case_id") else []
    resume = None
    if session:
        resume = {"terminal": display_command(["hermes", *profile_args, "--resume", session]),
                  "chat_url": f"{dashboard_url}/chat?resume={quote(session)}" if dashboard_url else None}
    return {**job_row(store, job), "args": job.get("args") or {}, "argv": job.get("argv") or [],
            "context_file": job.get("context_file"), "session_id": session or None, "exit_code": job.get("exit_code"),
            "result_text": job.get("result_text"), "tokens": job.get("tokens") or {}, "error": job.get("error"),
            "phases": [{"id": key, "label": text} for key, text in events.PHASES], "resume": resume,
            "progress": progress(store, job.get("case_id")),
            "last_audit": audit_view(store, cstore, audits[-1]) if audits else None}
