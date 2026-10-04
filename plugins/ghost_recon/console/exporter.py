"""ZIP of a case's results (spec §11): what goes in, the seal checks before and while packing, and the manifest.

Only the case's results folder is read (``<case>/<audits_dir>`` or its ``--out``), never the evidence: ``case.json``,
``corpus_inventory.csv``, ``_console/`` and the selected audit folders (reviews included). Only regular files go in:
symlinks, junctions and special files (FIFOs, sockets, devices) are skipped and listed, every file must resolve inside
the results folder, and a results folder that holds the case's evidence folder is refused. Unsealed audits go in only
on request and marked DRAFT; while a job is active on the case its open audits never do, nor the root files the agent
may be rewriting (``case.json``, ``corpus_inventory.csv``). Each selected seal is verified first and every sealed file
is hashed again as it is packed, so a change at any moment fails the export naming the file. The archive is written as
``<name>.part`` and renamed only once complete, with its SHA-256 beside it in ``<name>.sha256`` (``sha256sum -c``
format).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from ..core import casefolder as cf, ids
from ..core.db import Store, utcnow
from . import CONSOLE_VERSION, integrity
from .commands import CONSOLE_DIR
from .paths import case_results_root, resolve_within
from .store import ConsoleStore

MANIFEST_NAME = "EXPORT_MANIFEST.json"
GENERATOR = f"Ghost Recon Console {CONSOLE_VERSION}"
ROOT_FILES = (cf.CASE_JSON, cf.CORPUS_INVENTORY)
CHUNK = 1024 * 1024
ZIP64_FORCE_BYTES = 1 << 30  # stream larger members with ZIP64 headers from the start
EXCLUDED_REASONS = {
    "not_sealed": "está abierta (sin sellar): solo entra si un admin incluye las auditorías abiertas",
    "job_running": "hay una ejecución activa en el caso y la auditoría abierta puede estar a medio escribir",
}
HELD_TEXT = "hay una ejecución activa en el caso y el agente puede estar reescribiéndolo"


class ExportError(Exception):
    """An export the console refuses or stops; ``status`` and ``code`` map to the API error envelope."""

    def __init__(self, status: int, code: str, message: str, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}  # more fields for the error envelope (e.g. the export already in progress)


def exports_dir() -> Path:
    """``<plugin data>/console/exports/`` (beside ``jobs/``, next to ``ghostrecon.db``)."""
    from .. import runtime
    path = runtime.db_path().parent / "console" / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Selection:
    case: Dict[str, Any]
    results_root: Path
    scope: str
    seq: Optional[str]
    audits: List[Dict[str, Any]]    # the audit rows that go in, each with "draft" (True = not sealed)
    excluded: List[Dict[str, str]]  # {"id", "seq", "reason"}
    busy: bool = False              # a job is queued or running on the case

    @property
    def draft(self) -> bool:
        return any(a["draft"] for a in self.audits)


def results_root_for(case: Dict[str, Any]) -> Path:
    """The case's results folder (resolved): refused when it is missing or when the case's evidence folder lies
    inside it, since then the archive could carry original evidence."""
    root = case_results_root(case)
    if not root.is_dir():
        raise ExportError(409, "results_missing", f"La carpeta de resultados del caso no existe: {root}")
    if resolve_within(case["root_path"], [root]) is not None:
        raise ExportError(409, "results_hold_evidence", "La carpeta de resultados del caso contiene su carpeta de "
                          "evidencia; la evidencia original nunca se exporta, así que la consola no la empaqueta.")
    return root.resolve()


def select(store: Store, case: Dict[str, Any], *, scope: str, seq: Optional[str], include_unsealed: bool,
           busy: bool) -> Selection:
    """Which audits an export takes and why the others stay out. ``busy``: a job is active on the case."""
    root = results_root_for(case)
    audits = store.list_audits(case["id"])
    if scope == "audit":
        audits = [a for a in audits if ids.short_audit(a["id"]) == seq]
        if not audits:
            raise ExportError(404, "not_found", f"auditoría no encontrada: {seq}")
    chosen: List[Dict[str, Any]] = []
    excluded: List[Dict[str, str]] = []
    for audit in audits:
        short = ids.short_audit(audit["id"])
        sealed = audit["status"] == "sealed"
        reason = None if sealed else ("job_running" if busy else (None if include_unsealed else "not_sealed"))
        if reason:
            excluded.append({"id": audit["id"], "seq": short, "reason": reason})
            continue
        if resolve_within(audit["folder"], [root]) is None:
            raise ExportError(409, "audit_outside_results", f"La carpeta de {short} no existe o no está dentro de "
                              "la carpeta de resultados del caso: no se exporta.")
        chosen.append({**audit, "draft": not sealed})
    if not chosen:
        if scope == "audit":
            first = excluded[0]
            raise ExportError(409, first["reason"], f"{first['seq']} no se puede exportar: "
                              f"{EXCLUDED_REASONS[first['reason']]}.")
        raise ExportError(409, "nothing_to_export", "El caso no tiene auditorías que se puedan exportar: ninguna "
                          "está sellada (un admin puede incluir las abiertas, marcadas como borrador).")
    return Selection(case, root, scope, seq if scope == "audit" else None, chosen, excluded, busy)


def selection_view(sel: Selection) -> Dict[str, Any]:
    """What the preview shows. ``skipped``: the root files held out while a job runs (links are only found by the
    build's walk and land in the manifest)."""
    return {"scope": sel.scope, "seq": sel.seq, "draft": sel.draft, "results_root": str(sel.results_root),
            "audits": [{"id": a["id"], "seq": ids.short_audit(a["id"]), "kind": a["kind"], "status": a["status"],
                        "draft": a["draft"]} for a in sel.audits],
            "excluded": [{**e, "text": EXCLUDED_REASONS[e["reason"]]} for e in sel.excluded],
            "skipped": [{"path": name, "reason": "job_running", "text": HELD_TEXT} for name in held_root_files(sel)]}


@dataclass(frozen=True)
class Entry:
    arcname: str
    path: Path
    audit_folder: Optional[Path] = None      # set for the files of a SEALED audit: they are checked as packed
    seal: Optional[Dict[str, str]] = None    # that audit's SEALED.json hashes
    seal_sha256: Optional[str] = None        # the audit row's seal hash: SEALED.json must still hash to it


def _is_link(path: Path) -> bool:
    """Symlink or Windows reparse point (junction); ``Path.is_junction`` only exists on Python 3.12+."""
    if path.is_symlink():
        return True
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)  # Windows only; 0 elsewhere
    except OSError:
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _arc(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_regular(path: Path) -> bool:
    """A regular file itself (``lstat``): never a FIFO, socket or device, whose read could block the build forever."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _walk(base: Path, root: Path, skipped: List[Dict[str, str]]) -> Iterator[Path]:
    """Regular files under ``base``, sorted; symlinks and junctions are never followed nor packed, special files
    (FIFOs, sockets, devices) are never opened, and a file that does not resolve inside ``root`` is left out. All of
    them go to ``skipped``."""
    for dirpath, dirnames, filenames in os.walk(base):
        here = Path(dirpath)
        kept = []
        for name in sorted(dirnames):
            if _is_link(here / name):
                skipped.append({"path": _arc(here / name, root), "reason": "symlink"})
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = here / name
            if _is_link(path):
                skipped.append({"path": _arc(path, root), "reason": "symlink"})
            elif not _is_regular(path):
                skipped.append({"path": _arc(path, root), "reason": "not_a_regular_file"})
            elif resolve_within(path, [root]) is None:
                skipped.append({"path": _arc(path, root), "reason": "outside_results"})
            else:
                yield path


def held_root_files(sel: Selection) -> List[str]:
    """The root files left out because a job on the case may be rewriting them right now."""
    return [name for name in ROOT_FILES
            if sel.busy and not _is_link(sel.results_root / name) and _is_regular(sel.results_root / name)]


def plan_entries(sel: Selection) -> Tuple[List[Entry], List[Dict[str, str]]]:
    root, skipped, entries = sel.results_root, [], []
    held = held_root_files(sel)
    for name in ROOT_FILES:
        path = root / name
        if _is_link(path):
            skipped.append({"path": name, "reason": "symlink"})
        elif name in held:
            skipped.append({"path": name, "reason": "job_running"})
        elif _is_regular(path):
            entries.append(Entry(name, path))
    console = root / CONSOLE_DIR
    if _is_link(console):
        skipped.append({"path": CONSOLE_DIR, "reason": "symlink"})
    elif console.is_dir():
        entries += [Entry(_arc(p, root), p) for p in _walk(console, root, skipped)]
    for audit in sel.audits:
        folder = resolve_within(audit["folder"], [root])
        seal = None if audit["draft"] else integrity.seal_hashes(folder)
        sealed_folder = None if audit["draft"] else folder
        entries += [Entry(_arc(p, root), p, sealed_folder, seal, audit.get("seal_sha256"))
                    for p in _walk(folder, root, skipped)]
    return entries, skipped


def verify_seals(store: Store, cstore: ConsoleStore, sel: Selection, username: str) -> Dict[str, str]:
    """Every selected sealed audit re-hashed against its seal (and cached as a seal check). The first broken one
    stops the export, naming what changed. ``{audit_id: checked_at}``."""
    verified: Dict[str, str] = {}
    for audit in sel.audits:
        if audit["draft"]:
            continue
        check = integrity.record_seal_check(store, cstore, audit, username)
        if not check["ok"]:
            raise ExportError(409, "seal_broken", f"El sello de {ids.short_audit(audit['id'])} está roto: "
                              f"{integrity.changed_files(check['detail'])}. No se exportó nada.")
        verified[audit["id"]] = check["checked_at"]
    return verified


def _zip_time(mtime: float) -> Tuple[int, int, int, int, int, int]:
    stamp = max(datetime.fromtimestamp(mtime, timezone.utc), datetime(1980, 1, 1, tzinfo=timezone.utc))
    return stamp.timetuple()[:6]


def _pack(zf: zipfile.ZipFile, entry: Entry) -> Tuple[str, int, Optional[bytes]]:
    """Stream one file into the archive, hashing exactly the bytes written. A sealed audit's SEALED.json (small)
    also comes back, so it is judged on the very bytes that were packed."""
    keep = entry.audit_folder is not None and entry.path.name == cf.SEALED_FILE
    kept: List[bytes] = []
    st = entry.path.stat()
    info = zipfile.ZipInfo(entry.arcname, date_time=_zip_time(st.st_mtime))
    info.compress_type = zipfile.ZIP_DEFLATED
    digest, size = hashlib.sha256(), 0
    with open(entry.path, "rb") as src, zf.open(info, "w", force_zip64=st.st_size >= ZIP64_FORCE_BYTES) as dst:
        while chunk := src.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            dst.write(chunk)
            if keep:
                kept.append(chunk)
    return digest.hexdigest(), size, b"".join(kept) if keep else None


def _manifest_hash(files: Dict[str, str]) -> str:
    """The seal hash the DB stores (``casefolder.seal``): sha256 over the sorted ``relpath sha256`` lines."""
    return hashlib.sha256("".join(f"{k} {v}\n" for k, v in sorted(files.items())).encode("utf-8")).hexdigest()


def _seal_matches_row(entry: Entry, data: Optional[bytes]) -> bool:
    """The SEALED.json packed describes exactly the files the audit row registered, and the hashes the other files
    are checked against (read when the entries were planned) are the ones in it."""
    try:
        files = json.loads(data or b"").get("files")
    except (ValueError, AttributeError):
        return False
    return (isinstance(files, dict) and bool(entry.seal_sha256) and _manifest_hash(files) == entry.seal_sha256
            and files == entry.seal)


def _check_sealed(entry: Entry, sha: str, data: Optional[bytes]) -> str:
    """The packed bytes of a sealed file must still be the sealed ones; returns its path inside the audit."""
    rel = integrity.relative(entry.audit_folder, entry.path)
    if rel == cf.SEALED_FILE:  # the seal itself must be the one the audit row registered, as packed
        if not _seal_matches_row(entry, data):
            raise ExportError(409, "seal_broken", f"{entry.arcname} cambió mientras se exportaba (no coincide con el "
                              "sello registrado de la auditoría). No se exportó nada.")
    else:
        try:
            integrity.check(rel, sha, integrity.expected_hash(entry.seal, rel))
        except integrity.IntegrityError as exc:
            raise ExportError(409, "seal_broken", f"{entry.arcname} cambió mientras se exportaba ({exc.message}). "
                              "No se exportó nada.") from exc
    return rel


def zip_name(sel: Selection, now: datetime) -> str:
    """``GhostRecon_<slug>_<scope>_<YYYYMMDD-HHMM>.zip`` (UTC); ``<scope>`` is ``case`` or the audit (``A02``), with
    ``-DRAFT`` when unsealed audits go in."""
    scope = (sel.seq or "case") + ("-DRAFT" if sel.draft else "")
    return f"GhostRecon_{sel.case['slug']}_{scope}_{now.strftime('%Y%m%d-%H%M')}.zip"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def build(store: Store, cstore: ConsoleStore, sel: Selection, *, export_id: int, exported_by: str, dest_dir: Path,
          now: Optional[datetime] = None, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Verify, pack and publish the archive. ``{"file_name", "path", "size", "sha256", "manifest"}``; ExportError
    (nothing left behind) when a seal is broken or changes during the build."""
    verified = verify_seals(store, cstore, sel, exported_by)
    entries, skipped = plan_entries(sel)
    dest_dir = Path(dest_dir)
    name = zip_name(sel, now or datetime.now(timezone.utc))
    if (dest_dir / name).exists() or (dest_dir / f"{name}.part").exists():
        name = f"{name[:-4]}_e{export_id}.zip"  # two exports in the same minute never share a file
    final, part = dest_dir / name, dest_dir / f"{name}.part"
    files: List[Dict[str, Any]] = []
    packed: Dict[Path, Tuple[Optional[Dict[str, str]], Set[str]]] = {}  # sealed folder -> (plan-time seal, packed)
    try:
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for done, entry in enumerate(entries, 1):
                sha, size, seal_bytes = _pack(zf, entry)
                if entry.audit_folder is not None:
                    rel = _check_sealed(entry, sha, seal_bytes)
                    packed.setdefault(entry.audit_folder, (entry.seal, set()))[1].add(rel)
                files.append({"path": entry.arcname, "size": size, "sha256": sha})
                if progress:
                    progress(done, len(entries))
            for folder, (seal, rels) in packed.items():
                # The plan-time seal is the one proven equal to the SEALED.json packed (``_seal_matches_row``): a file
                # it lists that never went in is missing (links count as missing too).
                lost = sorted(set(seal or {}) - rels)
                if lost:
                    raise ExportError(409, "seal_broken", f"{_arc(folder / lost[0], sel.results_root)} falta o es un "
                                      "enlace en la auditoría sellada. No se exportó nada.")
            manifest = {
                "export_id": export_id, "case_id": sel.case["id"], "case_name": sel.case["name"], "scope": sel.scope,
                "seq": sel.seq, "draft": sel.draft,
                "audits": [{"id": a["id"], "seq": ids.short_audit(a["id"]), "kind": a["kind"],
                            "sealed": not a["draft"], "state": "DRAFT" if a["draft"] else "SEALED",
                            "seal_sha256": None if a["draft"] else a.get("seal_sha256"),
                            "verified_at": verified.get(a["id"])} for a in sel.audits],
                "excluded": sel.excluded, "skipped": skipped, "files": files,
                "exported_by": exported_by, "exported_at": utcnow(), "generator": GENERATOR}
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        sha = _sha256_file(part)
        os.replace(part, final)
        sidecar = dest_dir / f"{name}.sha256"
        sidecar_part = dest_dir / f"{name}.sha256.part"
        try:
            sidecar_part.write_bytes(f"{sha}  {name}\n".encode("utf-8"))  # LF on every OS
            os.replace(sidecar_part, sidecar)
        except BaseException:
            sidecar_part.unlink(missing_ok=True)
            final.unlink(missing_ok=True)  # never a ZIP without its sidecar
            raise
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return {"file_name": name, "path": final, "size": final.stat().st_size, "sha256": sha, "manifest": manifest}
