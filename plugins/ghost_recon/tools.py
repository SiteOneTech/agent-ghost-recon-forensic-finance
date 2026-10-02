"""Agent-facing tools (toolset ``ghost_recon``). Handlers take ``args: dict`` and return a JSON string.

Thin adapters over ``core.service`` / ``core.swarm`` / ``core.research`` / ``core.review`` / ``core.reports.pack``.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Tuple

from . import runtime
from .core import research as research_mod
from .core import review as review_mod
from .core import service, swarm
from .core.casefolder import SealedAuditError
from .core.reports import pack as pack_mod
from .core.service import CaseError


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _err(msg: str, **extra: Any) -> str:
    return json.dumps({"error": msg, **extra}, ensure_ascii=False)


def _guard(fn: Callable[[Dict[str, Any]], Any]) -> Callable[..., str]:
    def handler(args: Dict[str, Any], **_: Any) -> str:
        try:
            return _ok(fn(args or {}))
        except (CaseError, SealedAuditError, ValueError) as exc:
            return _err(str(exc))
        except Exception as exc:  # the agent must see the failure, never a stack trace
            return _err(f"{type(exc).__name__}: {exc}")
    handler.__name__ = fn.__name__
    return handler


def _str(desc: str, **kw: Any) -> Dict[str, Any]:
    return {"type": "string", "description": desc, **kw}


def _schema(name: str, description: str, properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


# ---------------------------------------------------------------------------------------------- handlers

def gr_case_open(a: Dict[str, Any]) -> Any:
    return service.open_case(runtime.store(), a["folder"], name=a.get("name"), context_md=a.get("context_md"),
                             base_currency=a.get("base_currency") or runtime.setting("base_currency"),
                             language=a.get("language") or runtime.setting("language"),
                             audits_dir=runtime.setting("audits_dirname"), out_dir=a.get("out_dir"))


def gr_case_status(a: Dict[str, Any]) -> Any:
    return service.case_status(runtime.store(), a["case"])


def gr_case_list(a: Dict[str, Any]) -> Any:
    st = runtime.store()
    out = []
    for c in st.list_cases():
        audits = st.list_audits(c["id"])
        out.append({"id": c["id"], "name": c["name"], "root_path": c["root_path"], "status": c["status"],
                    "audits": len(audits), "last_audit": audits[-1]["id"] if audits else None,
                    "last_status": audits[-1]["status"] if audits else None, "updated_at": c["updated_at"]})
    return {"cases": out, "db": str(runtime.db_path())}


def gr_audit_start(a: Dict[str, Any]) -> Any:
    return service.start_audit(runtime.store(), a["case_id"], a.get("kind", "initial"), context_md=a.get("context_md"),
                               out_dir=a.get("out_dir"), content_dedupe=a.get("content_dedupe", True))


def gr_evidence_index(a: Dict[str, Any]) -> Any:
    return service.evidence_index(runtime.store(), a["audit_id"], status=a.get("status"), block=a.get("block"),
                                  only_this_audit=bool(a.get("only_this_audit", False)), limit=int(a.get("limit") or 0))


def gr_finding_upsert(a: Dict[str, Any]) -> Any:
    findings = a.get("findings") or []
    if isinstance(findings, str):
        findings = json.loads(findings)
    return service.upsert_findings(runtime.store(), a["audit_id"], findings)


def gr_criteria_add(a: Dict[str, Any]) -> Any:
    return service.add_criterion(runtime.store(), a["audit_id"], a["author"], a["text"], a.get("date"))


def gr_research(a: Dict[str, Any]) -> Any:
    key = runtime.secret("TAVILY_API_KEY")
    client = research_mod.TavilyClient(key or "", base_url=str(runtime.setting("tavily_base_url")))
    action = a.get("action", "search")
    opts = dict(a.get("options") or {})
    if action == "search":
        result = client.search(a["query"], **opts)
    elif action == "extract":
        result = client.extract(a.get("urls") or [], **opts)
    elif action in ("crawl", "map"):
        url = (a.get("urls") or [a.get("query")])[0]
        result = getattr(client, action)(url, **opts)
    elif action == "research":
        result = client.research(a["query"], **opts)
    else:
        raise ValueError(f"unknown action {action!r}")
    out: Dict[str, Any] = {"action": action, "result": research_mod.summarize_for_agent(result)}
    if a.get("audit_id") and a.get("save", True):
        out["saved"] = research_mod.save_result(runtime.store(), a["audit_id"], action, a.get("query") or ",".join(a.get("urls") or []), result)
    out["note"] = "Un resultado web es INFERENCE salvo documento oficial; cita URL y fecha en el informe."
    return out


def _delegation_limit() -> int:
    """delegation.max_concurrent_children from the Hermes config (default 10); standalone → 10."""
    try:
        from hermes_cli.config import load_config
        return int(((load_config() or {}).get("delegation") or {}).get("max_concurrent_children") or 10)
    except Exception:
        return 10


def gr_swarm_plan(a: Dict[str, Any]) -> Any:
    st = runtime.store()
    mode = a.get("mode", "extraction")
    if mode == "extraction":
        wanted = int(a.get("max_parallel") or runtime.setting("swarm_max_parallel"))
        plan = swarm.plan_extraction(st, a["audit_id"], max_files_per_task=int(a.get("max_files_per_task") or runtime.setting("swarm_max_files_per_task")),
                                     max_parallel=max(1, min(wanted, _delegation_limit())), only_new=a.get("only_new"))
    elif mode == "validation":
        plan = swarm.plan_validation(st, a["audit_id"], headline_figures=a.get("headline_figures"), validators=a.get("validators"))
    elif mode == "review":
        rv = review_mod.start_review(st, a.get("case_id") or a["audit_id"], roles=a.get("roles"))
        rv["delegate_tasks"] = swarm.strip_for_delegate(rv["plan"]["tasks"])
        return rv
    else:
        raise ValueError("mode must be extraction | validation | review")
    plan["delegate_tasks"] = swarm.strip_for_delegate(plan["tasks"])
    return plan


def gr_run_record(a: Dict[str, Any]) -> Any:
    return service.record_run(runtime.store(), a["audit_id"], a["kind"], role=a.get("role"), status=a.get("status", "done"),
                              summary=a.get("summary", ""), input=a.get("input"), output=a.get("output"))


def gr_report_build(a: Dict[str, Any]) -> Any:
    formats = a.get("formats") or runtime.setting("report_formats")
    if isinstance(formats, str):
        formats = [f.strip() for f in formats.split(",") if f.strip()]
    return pack_mod.build_pack(runtime.store(), a["audit_id"], formats=tuple(formats), report_md=a.get("report_md"),
                               model_json=a.get("model_json"), title=a.get("title"), subtitle=a.get("subtitle"))


def gr_audit_seal(a: Dict[str, Any]) -> Any:
    return service.seal_audit(runtime.store(), a["audit_id"], force=bool(a.get("force", False)))


def gr_review_plan(a: Dict[str, Any]) -> Any:
    rv = review_mod.start_review(runtime.store(), a["case_id"], roles=a.get("roles"), out_dir=a.get("out_dir"))
    rv["delegate_tasks"] = swarm.strip_for_delegate(rv["plan"]["tasks"])
    return rv


def gr_timeline(a: Dict[str, Any]) -> Any:
    return service.timeline(runtime.store(), a["case"])


# ---------------------------------------------------------------------------------------------- schemas

FINDING_ITEM = {"type": "object", "properties": {
    "id": _str("Existing id to update (EXC-01, ANO-03, Q-02, FND-01). Omit to create."),
    "kind": _str("exception | anomaly | finding | question", enum=["exception", "anomaly", "finding", "question"]),
    "title": _str("Short factual title."), "description": _str("Neutral description with provenance."),
    "amount": {"type": "number"}, "currency": _str("ISO code"), "entity": _str("Entity"), "counterparty": _str("Counterparty"),
    "date": _str("YYYY-MM-DD"), "category": _str("Category"),
    "risk": _str("low | medium | high | critical", enum=["low", "medium", "high", "critical"]),
    "confidence": _str("CONFIRMED | HIGHLY_PROBABLE | PROBABLE | POSSIBLE | UNRESOLVED"),
    "label": _str("FACT | CALCULATION | INFERENCE | ALLEGATION | UNKNOWN"),
    "status": _str("open | closed | downgraded | upgraded | superseded"),
    "evidence_refs": {"type": "array", "items": {"type": "string"}, "description": "Document ids / paths / sheet rows"},
    "next_evidence": _str("Exact document that would resolve it (account, months, invoice numbers)."),
    "owner": _str("Who can provide that evidence.")}, "required": ["kind"]}

TOOLS: List[Tuple[str, Dict[str, Any], Callable[..., str], str]] = [
    ("gr_case_open", _schema("gr_case_open",
        "Open or load the Ghost Recon case anchored to an evidence folder: inventories every file (SHA-256/MD5, ZIP members), "
        "writes case.json, returns status and the next step. Never writes inside the evidence.",
        {"folder": _str("Evidence folder (absolute path)."), "name": _str("Case name (default: folder name)."),
         "context_md": _str("Optional path to a Markdown context file (default <folder>/context.md if present)."),
         "base_currency": _str("Reporting currency, e.g. USD."), "language": _str("es | en"),
         "out_dir": _str("Alternative output folder instead of <folder>/GhostRecon_Audits.")}, ["folder"]), _guard(gr_case_open), "📁"),
    ("gr_case_status", _schema("gr_case_status", "Full status of a case: audits with seal verification, evidence stats, open findings by risk, reports.",
        {"case": _str("Case id, slug or evidence folder path.")}, ["case"]), _guard(gr_case_status), "📋"),
    ("gr_case_list", _schema("gr_case_list", "List all Ghost Recon cases in the local database.", {}), _guard(gr_case_list), "🗂️"),
    ("gr_audit_start", _schema("gr_audit_start",
        "Create the next audit folder for a case and run the intake / evidence pass (hashes, two-level dedupe, evidence register, "
        "inherited open findings for reruns). kind=initial for the first audit, rerun for a new evidence pass (previous audit must be sealed).",
        {"case_id": _str("Case id."), "kind": _str("initial | rerun", enum=["initial", "rerun"]),
         "context_md": _str("Optional context .md for this audit."), "out_dir": _str("Alternative output root."),
         "content_dedupe": {"type": "boolean", "description": "Level-2 text dedupe for re-downloaded documents (default true)."}},
        ["case_id"]), _guard(gr_audit_start), "🧾"),
    ("gr_evidence_index", _schema("gr_evidence_index", "Evidence rows of the case (path, hash, type, block, status, first audit); filter by status/block.",
        {"audit_id": _str("Audit id."), "status": _str("NEW | REGISTERED | MODIFIED | DUP_PRIOR | DUP_INTERNAL | DUP_CONTENT"),
         "block": _str("banking | commercial | supply | related_parties | correspondence | ocr_vision | other"),
         "only_this_audit": {"type": "boolean"}, "limit": {"type": "integer"}}, ["audit_id"]), _guard(gr_evidence_index), "🔍"),
    ("gr_finding_upsert", _schema("gr_finding_upsert",
        "Create or update exceptions (EXC-nn), anomalies (ANO-nn), findings (FND-nn) and questions (Q-nn). Ids are assigned by the "
        "database and continue the case series across audits; every update keeps history. Refused on sealed audits.",
        {"audit_id": _str("Audit id."), "findings": {"type": "array", "items": FINDING_ITEM}}, ["audit_id", "findings"]), _guard(gr_finding_upsert), "⚠️"),
    ("gr_criteria_add", _schema("gr_criteria_add", "Register a management/party criterion verbatim (CRIT-nn): a declaration applied by the audit, never a conclusion.",
        {"audit_id": _str("Audit id."), "author": _str("Who stated it."), "text": _str("Verbatim text."), "date": _str("YYYY-MM-DD")},
        ["audit_id", "author", "text"]), _guard(gr_criteria_add), "📝"),
    ("gr_research", _schema("gr_research",
        "Research agent (Tavily): search (query), extract (urls), crawl/map (urls[0]) or deep research (query). With audit_id the raw result "
        "is saved under 03_Extracted_Data/research and every hit becomes a research note (provenance). Web results are INFERENCE unless official.",
        {"action": _str("search | extract | crawl | map | research", enum=["search", "extract", "crawl", "map", "research"]),
         "query": _str("Query (search/research)."), "urls": {"type": "array", "items": {"type": "string"}, "description": "URLs (extract/crawl/map)."},
         "options": {"type": "object", "description": "Provider options: search_depth, topic (general|news|finance), max_results, time_range, include_domains, extract_depth, max_depth, limit, instructions."},
         "audit_id": _str("Audit to attach the notes to."), "save": {"type": "boolean", "description": "Persist (default true when audit_id given)."}},
        ["action"]), _guard(gr_research), "🌐"),
    ("gr_swarm_plan", _schema("gr_swarm_plan",
        "Deterministic swarm plan: mode=extraction (one sub-agent per evidence block, manifests written), validation (auditors A/B/C) "
        "or review (six roles; creates the review folder). Returns delegate_tasks ready to pass to delegate_task, wave by wave.",
        {"audit_id": _str("Audit id (extraction/validation)."), "mode": _str("extraction | validation | review", enum=["extraction", "validation", "review"]),
         "case_id": _str("Case id (review)."), "max_parallel": {"type": "integer"}, "max_files_per_task": {"type": "integer"},
         "only_new": {"type": "boolean", "description": "Extraction: only evidence new in this audit (default: true for reruns)."},
         "headline_figures": {"type": "object", "description": "Validation: published headline figures auditor A must recompute."},
         "validators": {"type": "array", "items": {"type": "string"}, "description": "Subset of A, B, C."},
         "roles": {"type": "array", "items": {"type": "string"}, "description": "Review: subset of legal, tax, financial, auditor, accounting, mediator."}},
        ["mode"]), _guard(gr_swarm_plan), "🐝"),
    ("gr_run_record", _schema("gr_run_record", "Record a run (swarm result, validation round, research, build) on an audit; validation rounds are also appended to validation/validation.json.",
        {"audit_id": _str("Audit id."), "kind": _str("swarm | validation | research | build | intake | review"), "role": _str("A | B | C | block name | role"),
         "status": _str("done | failed | running", enum=["planned", "running", "done", "failed"]), "summary": _str("Short summary."),
         "input": {"type": "object"}, "output": {"type": "object"}}, ["audit_id", "kind", "summary"]), _guard(gr_run_record), "🧪"),
    ("gr_report_build", _schema("gr_report_build",
        "Build the deliverable pack (md, pdf, xlsx) for an audit or review from 06_Report/report.md (or sections/*.md; reviews: diagnosis.md + roles/*.md), "
        "03_Extracted_Data/model.json and the database. Signs, sets metadata, writes LEEME.md + pack_hashes.txt, registers reports, scans for tool names.",
        {"audit_id": _str("Audit or review id."), "formats": {"type": "array", "items": {"type": "string"}, "description": "Subset of md, pdf, xlsx."},
         "report_md": _str("Explicit narrative file (optional)."), "model_json": _str("Explicit model file (optional)."),
         "title": _str("Document title."), "subtitle": _str("Cover subtitle.")}, ["audit_id"]), _guard(gr_report_build), "📄"),
    ("gr_audit_seal", _schema("gr_audit_seal", "Seal an audit/review: completion checks (pack, validation, exceptions export), SHA-256 manifest of every file, SEALED.json, status=sealed. Irreversible.",
        {"audit_id": _str("Audit id."), "force": {"type": "boolean", "description": "Seal even if completion checks fail (recorded)."}}, ["audit_id"]), _guard(gr_audit_seal), "🔏"),
    ("gr_review_plan", _schema("gr_review_plan", "Start a /review-case: creates reviews/R0n, writes the consolidated chronology (md/json/xlsx) and returns the six-role delegate_tasks.",
        {"case_id": _str("Case id or folder."), "roles": {"type": "array", "items": {"type": "string"}}, "out_dir": _str("Alternative output root.")},
        ["case_id"]), _guard(gr_review_plan), "⚖️"),
    ("gr_timeline", _schema("gr_timeline", "Chronological events of a case plus the evolution of every finding across audits.",
        {"case": _str("Case id or folder.")}, ["case"]), _guard(gr_timeline), "🕒"),
]
