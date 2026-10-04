"""Orders the console can launch, as a table (spec §6.1): validation, the ``-q`` text each skill expects, the agent
argv and the operator's combined context file (§7). ``plan`` is the single source of both the preview and the launch,
so the preview is exactly what runs."""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..core import casefolder as cf
from ..core.db import Store
from . import fsjail
from .paths import resolve_within

SOURCE_TAG = "ghost-recon-console"
NOTIFY_SUBJECT = "[Ghost Recon]"
ORDER_LABELS = {"new-open-case": "Nueva auditoría", "rerun-case": "Re-run", "review-case": "Review"}
MAX_NAME = 120
MAX_NOTES = 20_000
LANGS = ("es", "en")
CONSOLE_DIR = "_console"
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_UNSAFE_RE = re.compile(r'["\x00-\x1f\x7f]')
NO_ROOTS_MESSAGE = ("La consola no tiene carpetas de casos configuradas. Pide a quien administra la máquina que añada "
                    "la carpeta de casos en case_roots (config.yaml → plugins.entries.ghost-recon.settings.console) "
                    "y reinicie la consola.")
NO_CONTEXT = "none"  # LaunchRequest.context_sha256 when the preview showed no context.md
CONTEXT_CHANGED_MESSAGE = ("El context.md de la carpeta cambió desde la vista previa: revísalo de nuevo y vuelve a "
                           "lanzar.")
MISSING_ROOTS_MESSAGE = ("Ninguna de las carpetas de casos configuradas en case_roots existe en esta máquina. Pide a "
                         "quien administra la máquina que la cree o corrija la configuración.")


@dataclass(frozen=True)
class Order:
    command: str
    skill: str
    requires: str       # "not_sealed" | "case" | "sealed"
    context_arg: bool   # the skill takes a context .md as its second argument
    options: bool       # --name / --currency / --lang
    out: bool           # --out
    pin_out: bool = False  # always pass --out: the operator's, else the default results root


ORDERS: Dict[str, Order] = {
    "new-open-case": Order("new-open-case", "new-open-case", "not_sealed", True, True, True, True),
    "rerun-case": Order("rerun-case", "rerun-case", "case", True, False, True),
    "review-case": Order("review-case", "review-case", "sealed", False, False, False),
}

_REQUIREMENTS: Dict[str, Tuple[Callable[[Optional[Dict[str, Any]]], bool], str, str]] = {
    "not_sealed": (lambda case: not (case and case["sealed"]), "use_rerun",
                   "Esta carpeta ya es un caso con una auditoría sellada: usa Re-run para la evidencia nueva."),
    "case": (lambda case: bool(case), "not_a_case", "Esta carpeta todavía no es un caso: usa Nueva auditoría."),
    "sealed": (lambda case: bool(case and case["sealed"]), "no_sealed_audit",
               "La revisión necesita al menos una auditoría sellada del caso."),
}


class CommandError(Exception):
    """A launch the console refuses; ``status`` and ``code`` map to the API error envelope."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LaunchRequest:
    command: str
    folder: str
    name: str = ""
    currency: str = ""
    lang: str = ""
    out: str = ""
    notes: str = ""
    context_sha256: Optional[str] = None  # the context.md the operator reviewed ("none": the preview had none)


def _q(text: str) -> str:
    return f'"{text}"'


def _safe(label: str, value: str) -> str:
    if _UNSAFE_RE.search(value):
        raise CommandError(422, "invalid_argument", f"{label}: no puede contener comillas dobles ni saltos de línea")
    return value


def _jail(raw: str, roots: Sequence[Path], label: str) -> Path:
    try:
        path = fsjail.resolve(raw, roots)
    except fsjail.FsJailError as exc:
        raise CommandError(403 if exc.code == "outside_roots" else 422, exc.code, f"{label}: {exc.message}") from exc
    if not path.is_dir():
        raise CommandError(422, "not_a_folder", f"{label}: no es una carpeta")
    _safe(label, str(path))
    return path


def _out_folder(order: Order, req: LaunchRequest, roots: Sequence[Path], folder: Path) -> Optional[Path]:
    """``--out``: inside the roots and never the evidence folder or a folder inside it (spec §7)."""
    if not (order.out and req.out.strip()):
        return None
    out = _jail(req.out, roots, "carpeta de salida")
    if resolve_within(out, [folder]) is not None:
        raise CommandError(422, "out_in_evidence",
                           "carpeta de salida: no puede ser la carpeta de evidencia ni una carpeta dentro de ella")
    return out


def _results_root(results_root: Path, roots: Sequence[Path]) -> Path:
    """Where the combined context is written and whose path reaches ``-q``: it must be safe text and resolve inside
    ``case_roots`` (the case folder lies inside them too), whatever the case record says."""
    _safe("carpeta de resultados del caso", str(results_root))
    if resolve_within(results_root, roots, strict=False) is None:
        raise CommandError(409, "results_outside_roots",
                           f"La carpeta de resultados del caso ({results_root}) está fuera de las carpetas de casos "
                           "(case_roots): la consola no escribe allí. Lanza esta orden desde la terminal.")
    return results_root


def _options(order: Order, req: LaunchRequest) -> Dict[str, str]:
    if not order.options:
        return {}
    name = req.name.strip()
    if len(name) > MAX_NAME:
        raise CommandError(422, "invalid_argument", f"el nombre admite como máximo {MAX_NAME} caracteres")
    currency = req.currency.strip().upper()
    if currency and not CURRENCY_RE.match(currency):
        raise CommandError(422, "invalid_argument", "la moneda debe ser un código ISO-4217 de 3 letras (p. ej. USD)")
    lang = req.lang.strip().lower()
    if lang and lang not in LANGS:
        raise CommandError(422, "invalid_argument", f"el idioma debe ser uno de: {', '.join(LANGS)}")
    return {"name": _safe("nombre", name), "currency": currency, "lang": lang}


def combined_name(original_sha: str, notes: str, username: str) -> str:
    """Same inputs, same name: the preview can show the exact path the launch will write."""
    digest = hashlib.sha256(f"{original_sha}\n{username}\n{notes}".encode("utf-8")).hexdigest()[:12]
    return f"context_{digest}.md"


def build_query(order: Order, folder: Path, context_file: str, opts: Dict[str, str], out: Optional[Path]) -> str:
    """The ``-q`` text with the argument conventions of the order's skill (skills/ghost-recon/<order>/SKILL.md):
    folder first, then the context ``.md`` for the orders that take one, then the flags. ``/review-case`` has no
    context argument, so the operator's notes travel on a second line."""
    parts = [f"/{order.command}", _q(str(folder))]
    if context_file and order.context_arg:
        parts.append(_q(context_file))
    for flag, key in (("--name", "name"), ("--currency", "currency"), ("--lang", "lang")):
        if opts.get(key):
            parts += [flag, _q(opts[key]) if key == "name" else opts[key]]
    if out is not None and order.out:
        parts += ["--out", _q(str(out))]
    query = " ".join(parts)
    if context_file and not order.context_arg:
        query += f"\nContexto adicional del operador (declaraciones, no hechos): {_q(context_file)}"
    return query


def agent_args(skill: str, query: str, profile_args: Sequence[str]) -> List[str]:
    """Hermes arguments of a console job (spec §6.1); ``--format stream-json`` implies ``--quiet``."""
    return [*profile_args, "--cli", "--accept-hooks", "--skills", skill, "chat", "-q", query,
            "--format", "stream-json", "--source", SOURCE_TAG]


def notify_args(target: str, profile_args: Sequence[str]) -> List[str]:
    """Hermes arguments of the job-end notice (spec §6.2): ``-p <perfil> send --to <destino> --subject "[Ghost
    Recon]"``. The runner appends the summary as the message; no LLM and no running gateway are involved."""
    return [*profile_args, "send", "--to", target, "--subject", NOTIFY_SUBJECT]


def plan(req: LaunchRequest, *, store: Store, roots: Sequence[Path], audits_dirname: str, username: str,
         profile_args: Sequence[str], hermes: Callable[[Sequence[str]], List[str]]) -> Dict[str, Any]:
    """Validate a launch and compute everything it needs. No side effects: the preview calls it as is."""
    order = ORDERS.get(req.command)
    if order is None:
        raise CommandError(422, "unknown_command", f"orden desconocida: {req.command}")
    if not roots:
        raise CommandError(409, "no_case_roots", NO_ROOTS_MESSAGE)
    folder = _jail(req.folder, roots, "carpeta")
    opts = _options(order, req)
    out = _out_folder(order, req, roots, folder)
    case = fsjail.existing_case(store, folder, audits_dirname)
    check, code, message = _REQUIREMENTS[order.requires]
    if not check(case):
        raise CommandError(409, code, message)
    notes = req.notes.strip()
    if len(notes) > MAX_NOTES:
        raise CommandError(422, "invalid_argument", f"las notas admiten como máximo {MAX_NOTES} caracteres")
    case_results = Path(case["results_root"]) if case else cf.audits_root(folder, audits_dirname)
    results_root = _results_root(out or case_results, roots)
    found = fsjail.context_info(folder, roots)
    original = {k: found[k] for k in ("path", "sha256", "size")} if found else None
    if req.context_sha256 is not None and req.context_sha256 != (original or {}).get("sha256", NO_CONTEXT):
        raise CommandError(409, "context_changed", CONTEXT_CHANGED_MESSAGE)
    if notes:
        context_file = str(results_root / CONSOLE_DIR / combined_name((original or {}).get("sha256", ""), notes,
                                                                     username))
    else:
        context_file = original["path"] if original and order.context_arg else ""
    # The agent improvises a results folder when --out is absent, which can land outside case_roots. The default
    # (<folder>/<audits_dirname>) is the product's own location, so it skips the evidence-folder check of an operator out.
    query_out = out or (results_root if order.pin_out else None)
    query = build_query(order, folder, _safe("archivo de contexto", context_file), opts, query_out)
    return {"command": order.command, "skill": order.skill, "folder": str(folder), "out": str(out) if out else "",
            "case": case, "results_root": str(results_root), "original_context": original, "notes": notes,
            "context_file": context_file, "query": query,
            "argv": [str(a) for a in hermes(agent_args(order.skill, query, profile_args))],
            "args": {**opts, "out": str(out) if out else ""}}


def combined_context_text(plan_: Dict[str, Any], username: str, now: str) -> str:
    """The combined context of spec §7: the original ``context.md`` verbatim with its hash, then the operator's
    signed notes, declared as statements to record as criteria (never facts)."""
    original = plan_["original_context"]
    if original:
        data = Path(original["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != original["sha256"]:
            raise CommandError(409, "context_changed", CONTEXT_CHANGED_MESSAGE)
        source = f"Fuente: {original['path']} · SHA-256 {original['sha256']}"
        literal = data.decode("utf-8", "replace")
    else:
        source, literal = "Sin context.md en la carpeta.", ""
    if literal and not literal.endswith("\n"):
        literal += "\n"
    return (f"# Contexto de la ejecución ({plan_['command']}) · consola Ghost Recon\n\n"
            f"## Contexto original\n\n{source}\n\n{literal}\n"
            f"## Notas del operador — {username}, {now}\n\n"
            f"> Declaraciones del operador: registrar como criterio/declaración (CRIT-nn, autor {username}), "
            f"no como hecho.\n\n{plan_['notes']}\n")


def write_combined_context(plan_: Dict[str, Any], username: str, now: str, roots: Sequence[Path]) -> Path:
    """Write the combined context where ``plan`` said (``<results>/_console/``), as exact UTF-8 bytes. The final
    path is resolved first: a planted ``_console`` symlink must not send the write outside the roots."""
    path = resolve_within(plan_["context_file"], roots, strict=False)
    if path is None:
        raise CommandError(409, "results_outside_roots", "el archivo de contexto quedaría fuera de las carpetas de "
                           "casos (case_roots); no se escribió nada")
    text = combined_context_text(plan_, username, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def display_command(argv: Sequence[str], *, windows: Optional[bool] = None) -> str:
    """Copyable command line: POSIX shell quoting, or the Windows CreateProcess rules."""
    if windows is None:
        from hermes_cli._subprocess_compat import IS_WINDOWS
        windows = IS_WINDOWS
    return subprocess.list2cmdline(list(argv)) if windows else shlex.join(list(argv))
