"""In-session slash commands (text only, no agent turn): /gr-cases, /gr-case, /gr-doctor, /gr-help.

The three main orders (/new-open-case, /rerun-case, /review-case) are skills, because a skill invocation starts a
real agent turn; these commands only report state.
"""

from __future__ import annotations

import importlib
import shlex
from pathlib import Path
from typing import Any, Dict, List

from . import runtime
from .core import ids, service
from .core.reports.pdf import FONTS_DIR

HELP = """Ghost Recon — comandos
  /new-open-case <carpeta> [contexto.md] [--out <carpeta>] [--name "..."] [--currency USD] [--lang es]
        Abre el caso anclado a la carpeta de evidencia y ejecuta la auditoría completa (A01) con pack documental y sello.
  /rerun-case <carpeta> [contexto.md] [--out <carpeta>]
        Pase de evidencia: deduplica contra lo auditado y produce una auditoría nueva (A0n); la sellada no se toca.
  /review-case <carpeta>
        Cronología de todas las auditorías + opinión y diagnóstico de 6 roles (legal, tributario, financiero, auditor, contable, mediador).
  /gr-cases                  lista de casos
  /gr-case <id|carpeta>      estado del caso (auditorías, sellos verificados, excepciones abiertas, packs)
  /gr-doctor                 diagnóstico del entorno (BD, dependencias, fuentes, TAVILY_API_KEY)
  CLI sin agente: hermes ghostrecon init|doctor|cases|case|audits|timeline|verify|export|import
Método: skills ghost-recon-* (skill_view). Docs: ghost-recon/COMMANDS.md en el repositorio."""


def cmd_help(raw_args: str = "") -> str:
    return HELP


def cmd_cases(raw_args: str = "") -> str:
    st = runtime.store()
    cases = st.list_cases()
    if not cases:
        return f"No hay casos en {runtime.db_path()}. Usa /new-open-case <carpeta>."
    lines = [f"Casos ({len(cases)}) — BD {runtime.db_path()}", ""]
    for c in cases:
        audits = st.list_audits(c["id"])
        last = f"{ids.short_audit(audits[-1]['id'])} {audits[-1]['status']}" if audits else "sin auditorías"
        lines.append(f"• {c['id']} — {c['name']} [{c['status']}] · {len(audits)} auditoría(s) · última: {last}\n    {c['root_path']}")
    return "\n".join(lines)


def cmd_case(raw_args: str = "") -> str:
    key = (raw_args or "").strip().strip('"')
    if not key:
        return "Uso: /gr-case <id|carpeta>"
    try:
        s = service.case_status(runtime.store(), key)
    except service.CaseError as exc:
        return f"⚠ {exc}"
    c = s["case"]
    lines = [f"{c['name']} ({c['id']}) [{c['status']}] · moneda {c['base_currency']} · {c['root_path']}",
             f"Evidencia: {s['evidence']} · Salidas: {s['audits_root']}",
             f"Hallazgos: {s['findings']['total']} (abiertos por riesgo: {s['findings']['open_by_risk'] or '—'}) · criterios: {s['criteria']}", "",
             "Auditorías:"]
    for a in s["audits"]:
        seal = "sello OK" if a.get("seal_ok") else ("SELLO ALTERADO" if a.get("seal_ok") is False else "abierta")
        lines.append(f"  {ids.short_audit(a['id'])} {a['kind']:8} {a['status']:12} {seal:14} {a['folder']}")
        for r in a.get("reports") or []:
            lines.append(f"      - {r['kind']}: {Path(r['path']).name} ({r['version']})")
    return "\n".join(lines)


def doctor_report() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    try:
        st = runtime.store()
        add("database", True, f"{runtime.db_path()} · {len(st.list_cases())} caso(s)")
    except Exception as exc:
        add("database", False, str(exc))
    for mod in ("openpyxl", "reportlab"):
        try:
            m = importlib.import_module(mod)
            add(f"python:{mod}", True, getattr(m, "__version__", getattr(m, "Version", "")))
        except Exception as exc:
            add(f"python:{mod}", False, f"missing: {exc} — hermes pm / uv pip install {mod}")
    add("fonts:DejaVu", (FONTS_DIR / "DejaVuSans.ttf").exists(), str(FONTS_DIR))
    import shutil
    add("pdftotext", bool(shutil.which("pdftotext")), "poppler-utils (opcional; dedupe por contenido de PDFs y extracción)")
    add("TAVILY_API_KEY", bool(runtime.secret("TAVILY_API_KEY")), "necesaria para gr_research; añadir al .env de Hermes")
    try:
        from agent.skill_utils import get_external_skills_dirs  # noqa: F401
        from tools.skills_tool import _skills_dir
        sd = Path(_skills_dir())
        found = sorted(p.parent.name for p in sd.glob("**/SKILL.md") if p.parent.name.startswith(("ghost-recon", "new-open-case", "rerun-case", "review-case")))
        add("skills:ghost-recon", len(found) >= 3, f"{len(found)} skills en {sd}: {', '.join(found)[:300]}")
    except Exception as exc:
        add("skills:ghost-recon", False, f"no se pudo inspeccionar: {exc}")
    try:
        from hermes_cli.config import load_config
        cfg = load_config() or {}
        web = (cfg.get("web") or {})
        add("web.backend", True, f"{web.get('backend') or web.get('search_backend') or 'auto'} (recomendado: tavily)")
        deleg = cfg.get("delegation") or {}
        add("delegation.max_concurrent_children", True, str(deleg.get("max_concurrent_children", 10)))
        try:
            oneshot = int(deleg.get("oneshot_max_children", 2))  # Hermes default when unset
        except (TypeError, ValueError):
            oneshot = 2
        add("delegation.oneshot_max_children", oneshot == 0 or oneshot >= 20,
            f"{oneshot} — la consola lanza auditorías con `chat -q` (una sola vez) y el valor por defecto de Hermes (2) "
            "deja sin enjambre ni validación A/B/C; fije delegation.oneshot_max_children: 100")
    except Exception:
        add("config", True, "config no inspeccionada (fuera de Hermes)")
    return {"ok": all(c["ok"] for c in checks if c["check"] not in ("pdftotext",)), "checks": checks,
            "settings": {k: runtime.setting(k) for k in runtime.DEFAULTS}}


def cmd_doctor(raw_args: str = "") -> str:
    rep = doctor_report()
    lines = ["Ghost Recon doctor — " + ("OK" if rep["ok"] else "ATENCIÓN"), ""]
    for c in rep["checks"]:
        lines.append(f"  [{'OK' if c['ok'] else '!!'}] {c['check']}: {c['detail']}")
    lines += ["", "Settings: " + ", ".join(f"{k}={v}" for k, v in rep["settings"].items())]
    return "\n".join(lines)


COMMANDS = [
    ("gr-help", cmd_help, "Ghost Recon: ayuda de comandos", ""),
    ("gr-cases", cmd_cases, "Ghost Recon: lista de casos", ""),
    ("gr-case", cmd_case, "Ghost Recon: estado de un caso", "<id|carpeta>"),
    ("gr-doctor", cmd_doctor, "Ghost Recon: diagnóstico del entorno", ""),
]
