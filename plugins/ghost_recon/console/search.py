"""Search across cases (spec §8 "Búsqueda"): cases, findings, evidence and criteria containing a text, read through the
case ``Store`` (nothing outside the database is ever searched). Bounded: the query has 2–100 characters, each type
returns at most ``limit`` items (``more`` says when there were others) and the scan stops after ``SEARCH_BUDGET_S``
seconds (``timed_out``)."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterator, Sequence

from ..core.db import Store
from .readmodel import EVIDENCE_TEXT_FIELDS, FINDING_TEXT_FIELDS, matches

TYPES = ("case", "finding", "evidence", "criteria")
MIN_QUERY, MAX_QUERY = 2, 100
DEFAULT_LIMIT, MAX_LIMIT = 10, 50
SEARCH_BUDGET_S = 2.0
CASE_TEXT_FIELDS = ("id", "name", "slug", "root_path")
CRITERIA_TEXT_FIELDS = ("id", "text", "author")
TITLE_MAX = 160


def _short(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1] + "…"


def _cases(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    if matches(case, needle, CASE_TEXT_FIELDS):
        yield {"id": case["id"], "title": case["name"], "detail": case["root_path"], "tab": "summary"}


def _findings(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    for f in store.list_findings(case["id"]):
        if matches(f, needle, FINDING_TEXT_FIELDS):
            yield {"id": f["id"], "title": _short(f["title"]), "detail": f"{f['kind']} · {f['risk']} · {f['status']}",
                   "meta": {"kind": f["kind"], "risk": f["risk"], "status": f["status"]}, "tab": "findings"}


def _evidence(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    for e in store.list_evidence(case["id"]):
        if matches(e, needle, EVIDENCE_TEXT_FIELDS):
            yield {"id": e["sha256"], "title": e["path"], "detail": f"{e['status']} · SHA-256 {e['sha256'][:12]}…",
                   "meta": {"status": e["status"]}, "tab": "evidence"}


def _criteria(store: Store, case: Dict[str, Any], needle: str) -> Iterator[Dict[str, Any]]:
    for c in store.list_criteria(case["id"]):
        if matches(c, needle, CRITERIA_TEXT_FIELDS):
            yield {"id": c["id"], "title": _short(c["text"]), "detail": c["author"], "tab": "criteria"}


SOURCES: Dict[str, Callable[[Store, Dict[str, Any], str], Iterator[Dict[str, Any]]]] = {
    "case": _cases, "finding": _findings, "evidence": _evidence, "criteria": _criteria}


def search(store: Store, q: str, *, types: Sequence[str] = TYPES, limit: int = DEFAULT_LIMIT,
           clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Results grouped by type; each item carries its case and the case tab that shows it."""
    needle = q.strip().lower()
    deadline = clock() + SEARCH_BUDGET_S
    items: Dict[str, list] = {t: [] for t in types}
    more = {t: False for t in types}
    timed_out = False
    for case in store.list_cases():
        if clock() > deadline:
            timed_out = True
            break
        for kind in types:
            if more[kind]:
                continue
            for hit in SOURCES[kind](store, case, needle):
                if len(items[kind]) >= limit:
                    more[kind] = True
                    break
                items[kind].append({"type": kind, "case_id": case["id"], "case_name": case["name"], **hit})
        if all(more.values()):
            break
    return {"q": q, "items": items, "more": more, "timed_out": timed_out}
