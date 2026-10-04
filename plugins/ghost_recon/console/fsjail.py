"""Folder browser for evidence folders, jailed to the configured ``case_roots`` (spec §9 "Rutas").

A path from the browser is rejected when it is empty, relative, UNC or carries a ``..`` segment; otherwise it is
resolved (symlinks followed) and accepted only inside a root. Listings hide hidden/system entries and the results
folder; search is bounded in depth, results and time. Read-only: nothing here writes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from ..core import casefolder as cf
from ..core.db import Store
from .paths import case_results_root, resolve_within

MAX_SEARCH_DEPTH = 4
MAX_SEARCH_RESULTS = 200
SEARCH_BUDGET_S = 3.0
COUNT_CAP = 2000
INSPECT_CAP = 50_000
CONTEXT_PREVIEW_CHARS = 20_000
MANY_IMAGES = 50
_HIDDEN_ATTRS = 0x2 | 0x4  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM; st_file_attributes exists on Windows only
_UNC_RE = re.compile(r"^(\\\\|//)")
_SEGMENT_RE = re.compile(r"[\\/]")


class FsJailError(Exception):
    """A rejected path or query; ``code`` is machine-readable and the message is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def folder_key(path: Any) -> str:
    """Comparable form of a folder path (case-insensitive on Windows)."""
    return os.path.normcase(str(path))


def configured_roots(raw: Iterable[str]) -> List[Path]:
    """Configured roots that exist, resolved; a missing or unreadable root is skipped (the doctor reports it)."""
    roots: List[Path] = []
    for item in raw:
        try:
            path = Path(item).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def resolve(raw: str, roots: Sequence[Path]) -> Path:
    text = str(raw or "").strip()
    if not text or "\x00" in text:
        raise FsJailError("bad_path", "ruta vacía o inválida")
    if _UNC_RE.match(text):
        raise FsJailError("outside_roots", "las rutas de red (UNC) no están permitidas")
    if ".." in _SEGMENT_RE.split(text):
        raise FsJailError("bad_path", "la ruta no puede contener '..'")
    if not Path(text).is_absolute():
        raise FsJailError("bad_path", "la ruta debe ser absoluta")
    path = resolve_within(text, roots)
    if path is None:
        raise FsJailError("outside_roots", "la ruta no existe o está fuera de las carpetas de casos")
    return path


def _root_of(path: Path, roots: Sequence[Path]) -> Path:
    best: Optional[Path] = None
    for root in roots:
        try:
            if os.path.commonpath([folder_key(root), folder_key(path)]) == folder_key(root):
                best = root if best is None or len(str(root)) > len(str(best)) else best
        except ValueError:  # another drive
            continue
    return best or path


def _visible_name(name: str) -> bool:
    return not (name.startswith(".") or name in cf.IGNORED_NAMES or name.startswith(cf.IGNORED_PREFIXES))


def _hidden(entry: os.DirEntry) -> bool:
    if not _visible_name(entry.name):
        return True
    try:
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attrs & _HIDDEN_ATTRS)


def _entry_inside_roots(entry: os.DirEntry, roots: Sequence[Path]) -> bool:
    """Check whether a directory entry resolves inside the roots (blocks symlinks, junctions, and other escapes)."""
    try:
        return resolve_within(entry.path, roots) is not None
    except OSError:
        return False


def _subfolders(folder: Path, roots: Sequence[Path], skip: Sequence[str]) -> List[Path]:
    """Visible subfolders that resolve inside the roots (blocks symlinks, junctions, and cross-root escapes)."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    found: List[Path] = []
    for entry in entries:
        if _hidden(entry) or entry.name in skip:
            continue
        try:
            if not entry.is_dir(follow_symlinks=True):
                continue
            if not _entry_inside_roots(entry, roots):
                continue
        except OSError:
            continue
        found.append(Path(entry.path))
    return sorted(found, key=lambda p: p.name.casefold())


def count_files(folder: Path, skip: Sequence[str] = (), cap: int = COUNT_CAP) -> Dict[str, Any]:
    """Files under ``folder`` (hidden entries, symlinks and ``skip`` folders excluded), stopping at ``cap``."""
    total = 0
    for _dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if _visible_name(d) and d not in skip]
        for f in filenames:
            if not _visible_name(f):
                continue
            fpath = Path(_dirpath) / f
            try:
                if fpath.is_symlink():
                    continue
            except OSError:
                continue
            total += 1
        if total >= cap:
            return {"files": cap, "capped": True}
    return {"files": total, "capped": False}


def existing_case(store: Store, folder: Path, audits_dirname: str) -> Optional[Dict[str, Any]]:
    """The case anchored to ``folder``: from the DB, else from its ``case.json`` mirror (a case opened elsewhere);
    None when the folder is not a case yet."""
    case = store.get_case(str(folder))
    if case:
        audits = store.list_audits(case["id"])
        return {"id": case["id"], "name": case["name"], "source": "db", "audits": len(audits),
                "sealed": sum(1 for a in audits if a["status"] == "sealed"),
                "last_status": audits[-1]["status"] if audits else None,
                "results_root": str(case_results_root(case)), "base_currency": case["base_currency"],
                "language": case["language"]}
    mirror = cf.read_case_json(cf.audits_root(folder, audits_dirname)) or {}
    info = mirror.get("case") if isinstance(mirror.get("case"), dict) else None
    if not info:
        return None
    audits = [a for a in mirror.get("audits") or [] if isinstance(a, dict)]
    meta = info.get("meta") if isinstance(info.get("meta"), dict) else {}
    return {"id": info.get("id"), "name": info.get("name") or folder.name, "source": "case.json",
            "audits": len(audits), "sealed": sum(1 for a in audits if a.get("status") == "sealed"),
            "last_status": audits[-1].get("status") if audits else None,
            "results_root": str(cf.audits_root(folder, audits_dirname, meta.get("out_dir"))),
            "base_currency": info.get("base_currency"), "language": info.get("language")}


def context_info(folder: Path, roots: Sequence[Path]) -> Optional[Dict[str, Any]]:
    """The folder's ``context.md`` (hash over the exact bytes), unless it is missing or links outside the roots."""
    path = folder / "context.md"
    if not path.is_file() or resolve_within(path, roots) is None:
        return None
    data = path.read_bytes()
    text = data.decode("utf-8", "replace")
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "text": text[:CONTEXT_PREVIEW_CHARS], "truncated": len(text) > CONTEXT_PREVIEW_CHARS}


def _mark(case: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {"id": case["id"], "name": case["name"], "sealed": case["sealed"]} if case else None


def roots_view(roots: Sequence[Path]) -> List[Dict[str, Any]]:
    view = []
    for root in roots:
        try:
            free: Optional[int] = shutil.disk_usage(root).free
        except OSError:
            free = None
        view.append({"name": root.name or str(root), "path": str(root), "free_bytes": free})
    return view


def list_dir(raw: str, roots: Sequence[Path], *, store: Store, audits_dirname: str) -> Dict[str, Any]:
    folder = resolve(raw, roots)
    if not folder.is_dir():
        raise FsJailError("not_a_folder", "la ruta no es una carpeta")
    root = _root_of(folder, roots)
    breadcrumb = [{"name": root.name or str(root), "path": str(root)}]
    current = root
    for part in (folder.relative_to(root).parts if folder != root else ()):
        current = current / part
        breadcrumb.append({"name": part, "path": str(current)})
    skip = (audits_dirname,)
    items = [{"name": p.name, "path": str(p), "case": _mark(existing_case(store, p, audits_dirname)),
              **count_files(p, skip)} for p in _subfolders(folder, roots, skip)]
    return {"path": str(folder), "name": folder.name or str(folder), "root": str(root),
            "parent": str(folder.parent) if folder != root else None, "breadcrumb": breadcrumb,
            "case": _mark(existing_case(store, folder, audits_dirname)), **count_files(folder, skip), "items": items}


def search(query: str, roots: Sequence[Path], *, skip: Sequence[str] = (), max_depth: int = MAX_SEARCH_DEPTH,
           limit: int = MAX_SEARCH_RESULTS, budget_s: float = SEARCH_BUDGET_S,
           clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Folders whose name contains ``query`` (case-insensitive), breadth-first, at most ``max_depth`` levels below
    a root, ``limit`` results and ``budget_s`` seconds."""
    needle = (query or "").strip().casefold()
    if len(needle) < 2:
        raise FsJailError("bad_query", "escribe al menos 2 caracteres")
    deadline = clock() + budget_s
    items: List[Dict[str, str]] = []
    truncated = timed_out = False
    queue = deque((root, root, 0) for root in roots)
    while queue and not truncated:
        if clock() > deadline:
            timed_out = True
            break
        folder, root, depth = queue.popleft()
        for path in _subfolders(folder, roots, skip):
            if needle in path.name.casefold():
                if len(items) >= limit:
                    truncated = True
                    break
                items.append({"name": path.name, "path": str(path), "root": str(root)})
            if depth + 1 < max_depth:
                queue.append((path, root, depth + 1))
    return {"items": items, "truncated": truncated, "timed_out": timed_out}


def inspect(raw: str, roots: Sequence[Path], *, store: Store, audits_dirname: str, defaults: Mapping[str, str],
            active_jobs: Iterable[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """Pre-launch review of an evidence folder: files by type, ZIPs, size, context.md, existing case, output folder,
    warnings and the order that fits (Re-run when the case already has a sealed audit)."""
    folder = resolve(raw, roots)
    if not folder.is_dir():
        raise FsJailError("not_a_folder", "la ruta no es una carpeta")
    by_type: Dict[str, int] = {}
    files = size = zips = images = 0
    capped = False
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if _visible_name(d) and d != audits_dirname and
                       resolve_within(str(Path(dirpath) / d), roots) is not None]
        for name in filenames:
            if not _visible_name(name):
                continue
            fpath = Path(dirpath) / name
            try:
                if fpath.is_symlink():
                    continue
                size += fpath.stat().st_size
            except OSError:
                continue
            ext = Path(name).suffix.lower() or "(sin extensión)"
            by_type[ext] = by_type.get(ext, 0) + 1
            files += 1
            if ext == ".zip":
                zips += 1
            if ext in cf.OCR_EXTS:
                images += 1
        if files >= INSPECT_CAP:
            capped = True
            break
    case = existing_case(store, folder, audits_dirname)
    key = folder_key(folder)
    active = [int(j["id"]) for j in active_jobs if folder_key(j["folder"]) == key]
    warnings: List[Dict[str, str]] = []
    if files == 0:
        warnings.append({"code": "empty", "text": "La carpeta no tiene archivos de evidencia."})
    if images >= MANY_IMAGES:
        warnings.append({"code": "many_images", "text": f"Hay {images} imágenes: el OCR tardará."})
    if case and case["sealed"]:
        warnings.append({"code": "sealed_case",
                         "text": "Ya es un caso con una auditoría sellada: usa Re-run para la evidencia nueva."})
    if active:
        warnings.append({"code": "active_job",
                         "text": f"Hay una ejecución activa en esta carpeta (#{active[0]}): la nueva quedará en cola."})
    known = case or {}
    return {"path": str(folder), "name": folder.name, "files": files, "capped": capped, "size": size,
            "by_type": [{"ext": e, "count": n} for e, n in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))],
            "zips": zips, "images": images, "context": context_info(folder, roots), "case": case,
            "results_root": known.get("results_root") or str(cf.audits_root(folder, audits_dirname)),
            "active_jobs": active, "warnings": warnings,
            "suggested_command": "rerun-case" if case and case["sealed"] else "new-open-case",
            "defaults": {"name": known.get("name") or folder.name,
                         "currency": known.get("base_currency") or defaults.get("currency", "USD"),
                         "lang": known.get("language") or defaults.get("lang", "es")}}
