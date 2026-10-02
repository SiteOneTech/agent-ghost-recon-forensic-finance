"""Tavily REST client for the research agent (search / extract / crawl / map / research).

Pure stdlib (``urllib``) so it works inside the Hermes venv without extra wheels. The API key is passed in by
the caller (the Hermes layer reads it with ``agent.secret_scope.get_secret("TAVILY_API_KEY")``).

Every call can be persisted: ``save_result`` writes the raw JSON under ``03_Extracted_Data/research/`` and
registers a ``research_notes`` row per hit, so a web finding has the same provenance discipline as a document
(hash of the content, URL, query, date). A web result is INFERENCE unless it is an official record.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import casefolder as cf
from .db import Store

DEFAULT_BASE_URL = "https://api.tavily.com"
ACTIONS = ("search", "extract", "crawl", "map", "research")


class TavilyError(RuntimeError):
    pass


class TavilyClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 60, opener=None):
        if not api_key:
            raise TavilyError("TAVILY_API_KEY is not configured (add it to the Hermes .env).")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener  # test seam: callable(url, payload_dict, method) -> dict

    # ---------------------------------------------------------------- transport
    def _call(self, path: str, payload: Optional[Dict[str, Any]] = None, method: str = "POST") -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if self._opener:
            return self._opener(url, payload, method)
        data = json.dumps(payload or {}).encode("utf-8") if method == "POST" else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "GhostRecon-Research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:500]
            raise TavilyError(f"Tavily HTTP {e.code} on {path}: {body}") from e
        except urllib.error.URLError as e:
            raise TavilyError(f"Tavily network error on {path}: {e.reason}") from e

    # ---------------------------------------------------------------- actions
    def search(self, query: str, *, search_depth: str = "advanced", topic: str = "general", max_results: int = 8,
               time_range: Optional[str] = None, include_domains: Optional[List[str]] = None,
               exclude_domains: Optional[List[str]] = None, include_raw_content: bool = False,
               include_answer: bool = False, days: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query, "search_depth": search_depth, "topic": topic,
                                   "max_results": max_results, "include_raw_content": include_raw_content,
                                   "include_answer": include_answer}
        if time_range:
            payload["time_range"] = time_range
        if days and topic == "news":
            payload["days"] = days
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains
        return self._call("/search", payload)

    def extract(self, urls: List[str], *, extract_depth: str = "basic", include_images: bool = False) -> Dict[str, Any]:
        return self._call("/extract", {"urls": urls[:20], "extract_depth": extract_depth, "include_images": include_images})

    def crawl(self, url: str, *, max_depth: int = 1, max_breadth: int = 20, limit: int = 50,
              instructions: Optional[str] = None, select_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"url": url, "max_depth": max_depth, "max_breadth": max_breadth, "limit": limit}
        if instructions:
            payload["instructions"] = instructions
        if select_paths:
            payload["select_paths"] = select_paths
        return self._call("/crawl", payload)

    def map(self, url: str, *, max_depth: int = 1, max_breadth: int = 20, limit: int = 100,
            instructions: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"url": url, "max_depth": max_depth, "max_breadth": max_breadth, "limit": limit}
        if instructions:
            payload["instructions"] = instructions
        return self._call("/map", payload)

    def research(self, query: str, *, model: str = "auto", poll_seconds: int = 5, max_wait: int = 600) -> Dict[str, Any]:
        """Asynchronous deep research (where the account exposes it): POST /research then poll."""
        started = self._call("/research", {"input": query, "model": model})
        rid = started.get("request_id") or started.get("id")
        if not rid:
            return started
        deadline = time.time() + max_wait
        while time.time() < deadline:
            status = self._call(f"/research/{rid}", method="GET")
            if status.get("status") in ("completed", "failed", "error"):
                return status
            time.sleep(poll_seconds)
        return {"request_id": rid, "status": "timeout", "hint": "poll GET /research/<id> later"}

    def run(self, action: str, **kw: Any) -> Dict[str, Any]:
        if action not in ACTIONS:
            raise TavilyError(f"unknown action {action!r}; use one of {ACTIONS}")
        return getattr(self, action)(**kw)


# ---------------------------------------------------------------------------------------------- persistence

def save_result(store: Store, audit_id: str, action: str, query: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a Tavily result into the audit folder and the research_notes table. Returns {saved_path, notes}."""
    audit = store.get_audit(audit_id)
    if not audit:
        raise ValueError(f"audit not found: {audit_id}")
    folder = cf.guard_writable(Path(audit["folder"]))
    rdir = folder / "03_Extracted_Data" / "research"
    rdir.mkdir(parents=True, exist_ok=True)
    n = len(list(rdir.glob("*.json"))) + 1
    raw = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    path = rdir / f"{n:03d}_{action}_{digest[:8]}.json"
    path.write_text(json.dumps({"action": action, "query": query, "sha256": digest, "result": result},
                               ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    notes: List[int] = []
    hits = result.get("results") or []
    if isinstance(hits, list) and hits:
        for h in hits[:50]:
            if not isinstance(h, dict):
                continue
            content = (h.get("content") or h.get("raw_content") or "")[:600]
            notes.append(store.add_research_note(
                audit["case_id"], audit_id, action, query, url=h.get("url"), title=h.get("title"),
                snippet=content, relevance=h.get("score"), sha256=digest, saved_path=str(path)))
    else:
        notes.append(store.add_research_note(audit["case_id"], audit_id, action, query, sha256=digest,
                                             saved_path=str(path), snippet=str(result.get("answer") or "")[:600]))
    store.add_event(audit["case_id"], "research", f"{action}: {query[:120]}", audit_id=audit_id,
                    ref={"saved_path": str(path), "hits": len(hits) if isinstance(hits, list) else 0})
    return {"saved_path": str(path), "sha256": digest, "notes": notes}


def summarize_for_agent(result: Dict[str, Any], max_chars: int = 12000) -> Dict[str, Any]:
    """Trim raw contents so a tool result stays small; the full JSON is on disk."""
    out = dict(result)
    hits = out.get("results")
    if isinstance(hits, list):
        slim = []
        for h in hits:
            if isinstance(h, dict):
                slim.append({k: (v[:1200] if isinstance(v, str) and k in ("content", "raw_content") else v)
                             for k, v in h.items() if k != "images"})
        out["results"] = slim
    text = json.dumps(out, ensure_ascii=False, default=str)
    if len(text) > max_chars:
        out["_truncated"] = True
        out["results"] = (out.get("results") or [])[:5]
    return out
