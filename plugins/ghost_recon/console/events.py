"""stream-json → console events, plus the audit phase deduced from the tools the agent calls (spec §6.3). Pure.

Input: the JSONL records of ``hermes … chat -q … --format stream-json`` (hermes_cli/stream_json.py):
``system/init{model, session_id}``, ``text{text}``, ``tool_use{name, tool_call_id?, input?}``,
``tool_result{name, tool_call_id?, output, duration_ms, is_error}`` and ``result{session_id, exit_code, text, tokens,
duration_ms, error?}``, each stamped with ``timestamp`` (ms). Tool output arrives capped at 5000 characters, so a large
``gr_*`` result can be truncated JSON: summaries then fall back to the ids they can still find.

Output: console events ``{seq, ts, kind, phase, title, detail, level}``. The agent's text is accumulated for the
final summary (no chat is rebuilt); consecutive calls of one generic tool are grouped ("read_file ×4"); sub-agent tools
never reach the parent's stream, so swarm progress comes from the parent's ``delegate_task`` results.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

PHASES = (("case", "Caso"), ("audit", "Auditoría"), ("intake", "Intake"), ("swarm", "Enjambre"),
          ("findings", "Modelo y hallazgos"), ("research", "Investigación"), ("pack", "Pack"),
          ("validation", "Validación"), ("seal", "Sello"))
PHASE_LABEL: Dict[str, str] = dict(PHASES)
KINDS = ("phase", "tool_call", "tool_result", "message", "warning", "error", "result")
DETAIL_MAX = 500

Event = Dict[str, Any]

_FIXED_PHASE = {"gr_case_open": "case", "gr_audit_start": "audit", "gr_review_plan": "audit",
                "gr_criteria_add": "intake", "gr_finding_upsert": "findings", "gr_research": "research",
                "gr_report_build": "pack", "gr_audit_seal": "seal"}
_PLAN_PHASE = {"extraction": "swarm", "validation": "validation", "review": "audit"}
_PLAN_WORDS = {"extraction": ("extracción", "bloques"), "validation": ("validación", "validadores"),
               "review": ("revisión", "roles")}
_DELEGATE_TITLE = {"swarm": "Enjambre: {p} bloques", "validation": "Validación: {p} validadores"}
_CALL_TITLE = {"gr_case_open": "Abriendo el caso", "gr_audit_start": "Iniciando la auditoría",
               "gr_review_plan": "Preparando la revisión", "gr_criteria_add": "Registrando un criterio",
               "gr_swarm_plan": "Planificando el trabajo de los sub-agentes",
               "gr_finding_upsert": "Registrando hallazgos", "gr_research": "Investigando en la web",
               "gr_report_build": "Generando el pack de entregables", "gr_run_record": "Registrando una ronda",
               "gr_audit_seal": "Sellando la auditoría"}
_CASE_ID_RE = re.compile(r'"id":\s*"(GRC-[^"/]+)"')
_AUDIT_ID_RE = re.compile(r'"id":\s*"(GRC-[^"]+/[AR]\d+)"')
_REVIEW_ID_RE = re.compile(r'"review_id":\s*"(GRC-[^"]+/R\d+)"')


def _iso(ms: Any) -> str:
    if not isinstance(ms, (int, float)):
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(output: str) -> Dict[str, Any]:
    try:
        data = json.loads(output)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find(pattern: "re.Pattern[str]", text: str) -> str:
    match = pattern.search(text or "")
    return match.group(1) if match else ""


def _seq(audit_id: str) -> str:
    return audit_id.rsplit("/", 1)[-1] if audit_id else ""


def _count(value: Any) -> Optional[int]:
    return len(value) if isinstance(value, list) else None


def _tasks(args: Dict[str, Any]) -> int:
    tasks = args.get("tasks")
    return len(tasks) if isinstance(tasks, list) and tasks else 1


# ------------------------------------------------------------------------------------------------ phase table
def _plan_phase(args: Dict[str, Any], _delegate: Optional[str]) -> Optional[str]:
    return _PLAN_PHASE.get(str(args.get("mode") or "extraction"))


def _run_phase(args: Dict[str, Any], _delegate: Optional[str]) -> Optional[str]:
    return "validation" if args.get("kind") == "validation" else None


def _delegate_phase(_args: Dict[str, Any], delegate: Optional[str]) -> Optional[str]:
    return delegate


def _read_phase(args: Dict[str, Any], _delegate: Optional[str]) -> Optional[str]:
    path = str(args.get("path") or "").replace("\\", "/")
    return "intake" if path.rsplit("/", 1)[-1] == "context.md" or "/_console/context_" in path else None


_DYNAMIC_PHASE: Dict[str, Callable[[Dict[str, Any], Optional[str]], Optional[str]]] = {
    "gr_swarm_plan": _plan_phase, "gr_run_record": _run_phase, "delegate_task": _delegate_phase,
    "read_file": _read_phase}


def phase_for(name: str, args: Dict[str, Any], delegate_phase: Optional[str] = None) -> Optional[str]:
    """Phase a tool call announces (table of spec §6.3), or None when it does not move the audit."""
    if name in _FIXED_PHASE:
        return _FIXED_PHASE[name]
    rule = _DYNAMIC_PHASE.get(name)
    return rule(args, delegate_phase) if rule else None


# ------------------------------------------------------------------------------------------------ gr_* summaries
def _ok(title: str) -> List[Event]:
    return [{"kind": "tool_result", "title": title}]


def _sum_case_open(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    case = data.get("case") if isinstance(data.get("case"), dict) else {}
    case_id = case.get("id") or _find(_CASE_ID_RE, output)
    if not data:
        return _ok(f"Caso {case_id} listo" if case_id else "Caso listo")
    files = data.get("corpus_files")
    verb = "abierto" if data.get("created") else "cargado"
    return _ok(f"Caso {case_id} {verb}" + (f" · {files} archivos" if files is not None else ""))


def _sum_audit_start(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    audit = data.get("audit") if isinstance(data.get("audit"), dict) else {}
    seq = _seq(audit.get("id") or _find(_AUDIT_ID_RE, output))
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    new = summary.get("evidence_new")
    title = f"Auditoría {seq} iniciada" if seq else "Auditoría iniciada"
    return _ok(title + (f" · {new} archivos nuevos" if new is not None else ""))


def _sum_review_plan(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    seq = _seq(data.get("review_id") or _find(_REVIEW_ID_RE, output))
    roles = _count(data.get("delegate_tasks"))
    title = f"Revisión {seq} preparada" if seq else "Revisión preparada"
    return _ok(title + (f" · {roles} roles" if roles else ""))


def _sum_criterion(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    return _ok(f"Criterio {data['id']} registrado" if data.get("id") else "Criterio registrado")


def _sum_plan(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    mode = str(data.get("mode") or args.get("mode") or "extraction")
    tasks = _count(data.get("tasks"))
    n.start_delegation(_PLAN_PHASE.get(mode), tasks or 0)
    noun, unit = _PLAN_WORDS.get(mode, (mode, "tareas"))
    return _ok(f"Plan de {noun} listo" + (f": {tasks} {unit}" if tasks else ""))


def _sum_findings(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    ids = [f.get("id") for f in data.get("findings") or [] if isinstance(f, dict) and f.get("id")]
    if not ids:
        return _ok("Hallazgos registrados")
    more = f" (+{len(ids) - 5})" if len(ids) > 5 else ""
    return _ok(f"Hallazgos registrados: {', '.join(ids[:5])}{more}")


def _sum_research(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    return _ok(f"Investigación web registrada ({data.get('action') or args.get('action') or 'search'})")


def _sum_report(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    files = _count(data.get("files"))
    items = _ok("Pack generado" + (f" · {files} archivos" if files is not None else ""))
    warnings = [str(w) for w in data.get("warnings") or []]
    if warnings:
        items.append({"kind": "warning", "title": "El pack tiene avisos", "detail": "; ".join(warnings[:3]),
                      "level": "warning"})
    return items


def _sum_run(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    kind = data.get("kind") or args.get("kind") or "?"
    return _ok(f"Ronda de {kind} registrada ({data.get('status') or args.get('status') or 'done'})")


def _sum_seal(n: "Normalizer", output: str, data: Dict[str, Any], args: Dict[str, Any]) -> List[Event]:
    if data.get("sealed") is True:
        count = data.get("file_count")
        return _ok(f"Auditoría sellada · {count} archivos" if count is not None else "Auditoría sellada")
    if data.get("already_sealed"):
        return _ok("La auditoría ya estaba sellada")
    if data.get("sealed") is False:
        missing = [str(m) for m in (data.get("completion") or {}).get("missing") or []]
        return [{"kind": "warning", "title": "No se pudo sellar la auditoría",
                 "detail": f"faltan: {', '.join(missing)}" if missing else None, "level": "warning"}]
    return _ok("Sello registrado")


_SUMMARY: Dict[str, Callable[["Normalizer", str, Dict[str, Any], Dict[str, Any]], List[Event]]] = {
    "gr_case_open": _sum_case_open, "gr_audit_start": _sum_audit_start, "gr_review_plan": _sum_review_plan,
    "gr_criteria_add": _sum_criterion, "gr_swarm_plan": _sum_plan, "gr_finding_upsert": _sum_findings,
    "gr_research": _sum_research, "gr_report_build": _sum_report, "gr_run_record": _sum_run,
    "gr_audit_seal": _sum_seal}


# ------------------------------------------------------------------------------------------------ normalizer
class Normalizer:
    """Stateful and deterministic for a given input. ``feed_line``/``feed`` return the new console events; ``flush``
    closes a pending group of generic tool calls (call it when the stream goes idle and when it ends)."""

    def __init__(self) -> None:
        self.seq = 0
        self.phase: Optional[str] = None
        self.session_id = ""
        self.result: Optional[Dict[str, Any]] = None
        self._text: List[str] = []
        self._group: Optional[Dict[str, Any]] = None
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._delegate_phase: Optional[str] = None
        self._delegate_total = 0
        self._delegate_done = 0
        self._handlers: Dict[str, Callable[[Dict[str, Any]], List[Event]]] = {
            "system": self._on_system, "text": self._on_text, "tool_use": self._on_tool_use,
            "tool_result": self._on_tool_result, "result": self._on_result}

    @property
    def text(self) -> str:
        return "".join(self._text)

    def start_delegation(self, phase: Optional[str], total: int) -> None:
        """A new plan resets the progress that the next ``delegate_task`` results count against."""
        self._delegate_phase, self._delegate_total, self._delegate_done = phase, total, 0

    def feed_line(self, line: str) -> List[Event]:
        line = line.strip()
        if not line:
            return []
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            return self._emit("warning", "Línea no reconocida en la salida del agente", detail=line, level="warning")
        return self.feed(obj)

    def feed(self, obj: Dict[str, Any]) -> List[Event]:
        handler = self._handlers.get(str(obj.get("type")))
        return handler(obj) if handler else []

    def flush(self) -> List[Event]:
        group, self._group = self._group, None
        if not group:
            return []
        title = group["name"] if group["count"] == 1 else f"{group['name']} ×{group['count']}"
        errors = group["errors"]
        return self._emit("tool_call", title, ts=group["ts"], detail=f"{errors} con error" if errors else None,
                          level="warning" if errors else "info")

    # -------------------------------------------------------------------------------------------- internals
    def _emit(self, kind: str, title: str, *, ts: str = "", detail: Any = None, level: str = "info") -> List[Event]:
        self.seq += 1
        text = str(detail).strip() if detail else ""
        if len(text) > DETAIL_MAX:
            text = text[:DETAIL_MAX] + "…"
        return [{"seq": self.seq, "ts": ts, "kind": kind, "phase": self.phase, "title": title,
                 "detail": text or None, "level": level}]

    @staticmethod
    def _key(obj: Dict[str, Any]) -> str:
        return str(obj.get("tool_call_id") or obj.get("name") or "unknown")

    def _on_system(self, obj: Dict[str, Any]) -> List[Event]:
        if obj.get("subtype") != "init":
            return []
        self.session_id = str(obj.get("session_id") or self.session_id)
        model = obj.get("model")
        return self._emit("message", "Agente iniciado", ts=_iso(obj.get("timestamp")),
                          detail=f"modelo {model}" if model else None)

    def _on_text(self, obj: Dict[str, Any]) -> List[Event]:
        self._text.append(str(obj.get("text") or ""))
        return []

    def _on_tool_use(self, obj: Dict[str, Any]) -> List[Event]:
        name = str(obj.get("name") or "unknown")
        args = obj.get("input") if isinstance(obj.get("input"), dict) else {}
        ts = _iso(obj.get("timestamp"))
        self._pending[self._key(obj)] = args
        out: List[Event] = []
        phase = phase_for(name, args, self._delegate_phase)
        if phase and phase != self.phase:
            out += self.flush()
            self.phase = phase
            out += self._emit("phase", PHASE_LABEL[phase], ts=ts)
        if name in _CALL_TITLE:
            return out + self.flush() + self._emit("tool_call", _CALL_TITLE[name], ts=ts)
        if name == "delegate_task":
            return out + self.flush() + self._emit("tool_call", f"Delegando {_tasks(args)} tarea(s) a sub-agentes",
                                                   ts=ts)
        if self._group and self._group["name"] == name:
            self._group["count"] += 1
            return out
        out += self.flush()
        self._group = {"name": name, "count": 1, "errors": 0, "ts": ts}
        return out

    def _on_tool_result(self, obj: Dict[str, Any]) -> List[Event]:
        name = str(obj.get("name") or "unknown")
        args = self._pending.pop(self._key(obj), {})
        output = str(obj.get("output") or "")
        ts = _iso(obj.get("timestamp"))
        failed = bool(obj.get("is_error"))
        if "BLOCKED:" in output:
            return self.flush() + self._emit("warning", "Comando bloqueado por la política de aprobaciones", ts=ts,
                                             detail=output, level="warning")
        if name in _SUMMARY:
            out = self.flush()
            data = _parse(output)
            if failed or data.get("error"):
                return out + self._emit("warning", f"{_CALL_TITLE[name]}: falló", ts=ts,
                                        detail=data.get("error") or output, level="warning")
            for item in _SUMMARY[name](self, output, data, args):
                out += self._emit(item["kind"], item["title"], ts=ts, detail=item.get("detail"),
                                  level=item.get("level", "info"))
            return out
        if name == "delegate_task":
            out = self.flush()
            if failed:
                return out + self._emit("warning", "Los sub-agentes devolvieron un error", ts=ts, detail=output,
                                        level="warning")
            self._delegate_done += _tasks(args)
            done, total = self._delegate_done, self._delegate_total
            progress = f"{done}/{total}" if total else str(done)
            title = _DELEGATE_TITLE.get(self._delegate_phase or "", "Sub-agentes: {p} tareas terminadas")
            return out + self._emit("tool_result", title.format(p=progress), ts=ts)
        if self._group and self._group["name"] == name:
            self._group["errors"] += int(failed)
            return []
        return self._emit("warning", f"{name} falló", ts=ts, detail=output, level="warning") if failed else []

    def _on_result(self, obj: Dict[str, Any]) -> List[Event]:
        out = self.flush()
        if obj.get("session_id"):
            self.session_id = str(obj["session_id"])
        exit_code = int(obj.get("exit_code") or 0)
        error = str(obj.get("error") or "") or None
        self.result = {"session_id": self.session_id, "exit_code": exit_code,
                       "text": str(obj.get("text") or self.text),
                       "tokens": obj.get("tokens") if isinstance(obj.get("tokens"), dict) else {},
                       "duration_ms": obj.get("duration_ms"), "error": error}
        ok = exit_code == 0 and not error
        return out + self._emit("result", "Ejecución terminada" if ok else "La ejecución terminó con error",
                                ts=_iso(obj.get("timestamp")),
                                detail=None if ok else (error or f"código de salida {exit_code}"),
                                level="info" if ok else "error")
