"""Case folder layout, evidence inventory, deduplication, sealing.

Invariants enforced here (the method's critical rules):
    * The evidence tree is never written to. Outputs live under ``<root>/<audits_dir>/`` only.
    * Every file (and every ZIP member) gets SHA-256 + MD5, size and mtime; the hash is the identity.
    * A sealed audit folder (``SEALED.json`` present) is immutable: ``guard_writable`` raises.
    * ``case.json`` is a portable mirror of the DB state for the case (re-import if the DB is lost).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import SIGNATURE

DEFAULT_AUDITS_DIR = "GhostRecon_Audits"
SEALED_FILE = "SEALED.json"
MANIFEST_FILE = "00_manifest.json"
CASE_JSON = "case.json"
CORPUS_INVENTORY = "corpus_inventory.csv"

AUDIT_SUBDIRS = [
    "01_Source_Index", "02_Working_Copies", "03_Extracted_Data/agents", "03_Extracted_Data/research",
    "04_Reconciliation", "05_Exceptions", "06_Report", "src", "versions", "validation",
]
REVIEW_SUBDIRS = ["roles", "06_Report", "validation", "versions"]
RERUN_EXTRA_SUBDIRS = ["Evidence_Pass"]

# Files we never treat as evidence (OS noise). Output folders are excluded by name, not by pattern.
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitkeep"}
IGNORED_PREFIXES = ("~$", "._")

EXTRACT_TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".eml"}

# Block classification (swarm). Order matters: first match wins. Keywords are matched on the lowercase
# relative path (folder names count), Spanish and English.
BLOCK_RULES: List[Tuple[str, List[str]]] = [
    ("banking", ["extracto", "statement", "estado de cuenta", "bank", "banco", "chase", "wells", "bofa",
                 "citi", "mercantil", "banesco", "bbva", "santander", "wire", "zelle", "ach", "transfer",
                 "transferencia", "cheque", "check", "tarjeta", "card", "amex", "visa", "mastercard",
                 "credit", "paypal", "stripe", "processor", "payoneer", "wise"]),
    ("commercial", ["factura de venta", "sales invoice", "invoice", "factura", "fact-", "inv-", "orden de compra",
                    "purchase order", "po-", "oc-", "pedido", "order", "albaran", "albarán", "delivery", "packing",
                    "remision", "remisión", "cobro", "collection", "receipt", "recibo", "cliente", "customer",
                    "nota de credito", "credit note", "cotizacion", "quote"]),
    ("supply", ["proveedor", "supplier", "vendor", "compra", "purchase", "flete", "freight", "dhl", "fedex",
                "ups", "awb", "bl-", "bill of lading", "aduana", "customs", "arancel", "import", "shipment",
                "embarque", "portal", "despacho", "dispatch", "manifiesto", "inventario", "inventory", "stock"]),
    ("related_parties", ["socio", "partner", "shareholder", "accionista", "acta", "minutes", "contrato",
                         "contract", "agreement", "convenio", "prestamo", "préstamo", "loan", "licencia",
                         "license", "intercompany", "relacionad", "related", "nomina", "nómina", "payroll",
                         "salario", "salary", "distribuc", "dividend"]),
    ("correspondence", ["whatsapp", "chat", "email", "correo", "mensaje", "message", ".eml", "telegram"]),
]
OCR_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".heic", ".webp", ".gif"}


class SealedAuditError(RuntimeError):
    """Raised on any attempt to write inside an audit folder that carries SEALED.json."""


@dataclass
class EvidenceRow:
    path: str                 # relative to case root (ZIP members: "archive.zip::member/path")
    filename: str
    ext: str
    size: int
    mtime: Optional[str]
    sha256: str
    md5: str
    zip_member: bool = False
    block: str = "other"
    status: str = "NEW"
    first_audit_id: Optional[str] = None
    doc_type: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------------------------- hashing

def hash_bytes_iter(chunks: Iterable[bytes]) -> Tuple[str, str, int]:
    h256, hmd5, size = hashlib.sha256(), hashlib.md5(), 0
    for c in chunks:
        h256.update(c); hmd5.update(c); size += len(c)
    return h256.hexdigest(), hmd5.hexdigest(), size


def hash_file(path: Path) -> Tuple[str, str, int]:
    def _chunks():
        with open(path, "rb") as fh:
            while True:
                b = fh.read(1024 * 1024)
                if not b:
                    break
                yield b
    return hash_bytes_iter(_chunks())


def sha256_file(path: Path) -> str:
    return hash_file(path)[0]


def _mtime_iso(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------------------------- classification

def classify_block(rel_path: str, ext: str) -> str:
    low = rel_path.lower().replace("\\", "/")
    if ext.lower() in OCR_EXTS:
        return "ocr_vision"
    for block, keys in BLOCK_RULES:
        for k in keys:
            if k in low:
                return block
    return "other"


def guess_doc_type(rel_path: str, ext: str) -> str:
    low = rel_path.lower()
    pairs = [("extracto", "bank_statement"), ("statement", "bank_statement"), ("factura", "invoice"),
             ("invoice", "invoice"), ("order", "purchase_order"), ("orden", "purchase_order"), ("contrato", "contract"),
             ("contract", "contract"), ("acta", "minutes"), ("nomina", "payroll"), ("payroll", "payroll"),
             ("flete", "freight"), ("freight", "freight"), ("whatsapp", "chat_export"), ("chat", "chat_export")]
    for k, t in pairs:
        if k in low:
            return t
    if ext.lower() in OCR_EXTS:
        return "image"
    return {".pdf": "pdf_document", ".xlsx": "spreadsheet", ".xls": "spreadsheet", ".csv": "table",
            ".docx": "word_document", ".eml": "email", ".zip": "archive"}.get(ext.lower(), "document")


# ---------------------------------------------------------------------------------------------- inventory

def _is_ignored(name: str) -> bool:
    return name in IGNORED_NAMES or name.startswith(IGNORED_PREFIXES)


def inventory(root: Path, exclude_dirs: Iterable[str] = (DEFAULT_AUDITS_DIR,), include_zip_members: bool = True,
              extra_exclude_paths: Iterable[Path] = ()) -> List[EvidenceRow]:
    """Walk ``root`` recursively; hash every file; expand ZIP archives into members (hashed from bytes).
    ``exclude_dirs`` are top-level or nested directory NAMES skipped entirely (output folders).
    ``extra_exclude_paths`` are absolute paths (e.g. an ``--out`` folder living inside the root)."""
    root = Path(root).resolve()
    excl_names = set(exclude_dirs)
    excl_paths = {Path(p).resolve() for p in extra_exclude_paths}
    rows: List[EvidenceRow] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames
                             if d not in excl_names and not d.startswith(".") and (dp / d).resolve() not in excl_paths)
        for fn in sorted(filenames):
            if _is_ignored(fn):
                continue
            p = dp / fn
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            ext = p.suffix.lower()
            try:
                sha, md5, size = hash_file(p)
                mt = _mtime_iso(p)
            except OSError as exc:  # unreadable (permissions, cloud placeholder): register, never abort the intake
                rows.append(EvidenceRow(path=rel, filename=fn, ext=ext, size=0, mtime=None, sha256=f"UNREADABLE:{rel}",
                                        md5="", status="UNREADABLE", block=classify_block(rel, ext),
                                        doc_type=guess_doc_type(rel, ext), meta={"error": str(exc)}))
                continue
            rows.append(EvidenceRow(path=rel, filename=fn, ext=ext, size=size, mtime=mt, sha256=sha,
                                    md5=md5, block=classify_block(rel, ext), doc_type=guess_doc_type(rel, ext)))
            if include_zip_members and ext == ".zip":
                rows.extend(_zip_members(p, rel))
    return rows


def _zip_members(zpath: Path, rel: str) -> List[EvidenceRow]:
    """Hash every member of a ZIP. Encrypted or unsupported members (RuntimeError / NotImplementedError) and corrupt
    archives are registered as UNREADABLE rows instead of aborting the intake."""
    out: List[EvidenceRow] = []
    try:
        zf = zipfile.ZipFile(zpath)
    except (zipfile.BadZipFile, OSError) as exc:
        out.append(EvidenceRow(path=f"{rel}::", filename=Path(rel).name, ext=".zip", size=0, mtime=None,
                               sha256=f"UNREADABLE:{rel}::", md5="", zip_member=True, status="UNREADABLE",
                               block="other", doc_type="archive", meta={"error": str(exc)}))
        return out
    with zf:
        for info in zf.infolist():
            if info.is_dir() or _is_ignored(Path(info.filename).name):
                continue
            member_rel = f"{rel}::{info.filename}"
            ext = Path(info.filename).suffix.lower()
            mt = None
            try:
                mt = datetime(*info.date_time, tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
            try:
                with zf.open(info) as fh:
                    sha, md5, size = hash_bytes_iter(iter(lambda: fh.read(1024 * 1024), b""))
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile, OSError) as exc:
                out.append(EvidenceRow(path=member_rel, filename=Path(info.filename).name, ext=ext, size=info.file_size,
                                       mtime=mt, sha256=f"UNREADABLE:{member_rel}", md5="", zip_member=True,
                                       status="UNREADABLE", block=classify_block(member_rel, ext),
                                       doc_type=guess_doc_type(member_rel, ext), meta={"error": str(exc)}))
                continue
            out.append(EvidenceRow(path=member_rel, filename=Path(info.filename).name, ext=ext, size=size,
                                   mtime=mt, sha256=sha, md5=md5, zip_member=True,
                                   block=classify_block(member_rel, ext), doc_type=guess_doc_type(member_rel, ext)))
    return out


def write_inventory_csv(rows: Iterable[EvidenceRow | Dict[str, Any]], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cols = ["path", "filename", "ext", "size", "mtime", "sha256", "md5", "zip_member", "block", "status",
            "first_audit_id", "doc_type"]
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            d = r.as_dict() if isinstance(r, EvidenceRow) else dict(r)
            d["zip_member"] = 1 if d.get("zip_member") else 0
            w.writerow(d)
    return dest


# ---------------------------------------------------------------------------------------------- dedupe

def text_fingerprint(path: Path) -> Optional[str]:
    """Content-level fingerprint for level-2 dedupe (re-downloaded statements). Text files: normalized text
    hash. PDFs: ``pdftotext`` when available, else None (caller reports 'content check unavailable')."""
    ext = path.suffix.lower()
    text: Optional[str] = None
    if ext in EXTRACT_TEXT_EXTS:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
    elif ext == ".pdf" and shutil.which("pdftotext"):
        try:
            res = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=120)
            text = res.stdout.decode("utf-8", errors="ignore")
        except (OSError, subprocess.SubprocessError):
            return None
    if text is None:
        return None
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else None


def dedupe(rows: List[EvidenceRow], known_hashes: Dict[str, str], *, root: Optional[Path] = None,
           known_fingerprints: Optional[Dict[str, str]] = None, audit_id: Optional[str] = None,
           first_audit: bool = False) -> Dict[str, Any]:
    """Assign status to each row of the current corpus walk.

    * Rows whose hash is in ``known_hashes`` (registered in a previous audit) -> ``DUP_PRIOR`` (already audited).
    * New rows whose hash repeats inside the batch -> ``DUP_INTERNAL`` (the first copy stays NEW).
    * New rows with a text fingerprint equal to a known one -> ``DUP_CONTENT``.
    * Otherwise ``NEW``. On the first audit everything new is ``NEW``.
    Returns {"rows": rows, "stats": {...}, "new": [...], "dup_prior": [...], ...}.
    """
    seen_batch: Dict[str, str] = {}
    known_fp = dict(known_fingerprints or {})
    buckets: Dict[str, List[EvidenceRow]] = {"NEW": [], "DUP_PRIOR": [], "DUP_INTERNAL": [], "DUP_CONTENT": []}
    for r in rows:
        if r.status == "UNREADABLE":
            buckets.setdefault("UNREADABLE", []).append(r)
            if audit_id and not r.first_audit_id:
                r.first_audit_id = audit_id
            continue
        if r.sha256 in known_hashes and not first_audit:
            r.status = "DUP_PRIOR"
            r.meta["duplicate_of"] = known_hashes[r.sha256]
        elif r.sha256 in seen_batch:
            r.status = "DUP_INTERNAL"
            r.meta["duplicate_of"] = seen_batch[r.sha256]
        else:
            r.status = "NEW"
            seen_batch[r.sha256] = r.path
            if root is not None and not r.zip_member and known_fp:
                fp = text_fingerprint(root / r.path)
                if fp and fp in known_fp:
                    r.status = "DUP_CONTENT"
                    r.meta["duplicate_of"] = known_fp[fp]
        if r.status == "NEW" and audit_id:
            r.first_audit_id = audit_id
        buckets[r.status].append(r)
    stats = {k: len(v) for k, v in buckets.items()}
    stats["total"] = len(rows)
    return {"rows": rows, "stats": stats, **{k.lower(): [r.path for r in v] for k, v in buckets.items()}}


# ---------------------------------------------------------------------------------------------- folders

def audits_root(case_root: Path, audits_dir: str = DEFAULT_AUDITS_DIR, out_override: Optional[str] = None) -> Path:
    if out_override:
        return Path(out_override).resolve()
    return (Path(case_root) / audits_dir).resolve()


def create_audit_folder(audits_root_: Path, folder_name: str, kind: str, manifest: Dict[str, Any]) -> Path:
    base = Path(audits_root_)
    folder = base / ("reviews" if kind == "review" else "") / folder_name if kind == "review" else base / folder_name
    if folder.exists() and any(folder.iterdir()):
        raise FileExistsError(f"audit folder already exists and is not empty: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    subdirs = REVIEW_SUBDIRS if kind == "review" else AUDIT_SUBDIRS + (RERUN_EXTRA_SUBDIRS if kind == "rerun" else [])
    for sd in subdirs:
        (folder / sd).mkdir(parents=True, exist_ok=True)
    manifest = {**manifest, "kind": kind, "folder": str(folder), "created_at": _now(), "signature": SIGNATURE}
    (folder / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def is_sealed(folder: Path) -> bool:
    return (Path(folder) / SEALED_FILE).exists()


def guard_writable(folder: Path) -> Path:
    folder = Path(folder)
    if is_sealed(folder):
        raise SealedAuditError(f"audit is sealed and immutable: {folder}. Open a new audit with /rerun-case.")
    return folder


def write_text(folder: Path, rel: str, text: str) -> Path:
    """Write a text file inside an audit folder, refusing if sealed. Creates parents."""
    guard_writable(folder)
    p = Path(folder) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def write_json(folder: Path, rel: str, data: Any) -> Path:
    return write_text(folder, rel, json.dumps(data, ensure_ascii=False, indent=2, default=str))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------------------------------------- sealing

def _walk_files(folder: Path) -> List[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn == SEALED_FILE:
                continue
            out.append(Path(dirpath) / fn)
    return out


def seal(folder: Path, audit_id: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute SHA-256 of every file in the audit folder and write SEALED.json. Returns the seal record.
    The manifest hash (sha256 over 'relpath sha256\\n' lines) is what the DB stores as ``seal_sha256``."""
    folder = Path(folder)
    if is_sealed(folder):
        raise SealedAuditError(f"already sealed: {folder}")
    files: Dict[str, str] = {}
    for p in _walk_files(folder):
        files[p.relative_to(folder).as_posix()] = sha256_file(p)
    manifest_lines = "".join(f"{k} {v}\n" for k, v in sorted(files.items()))
    manifest_hash = hashlib.sha256(manifest_lines.encode("utf-8")).hexdigest()
    record = {
        "audit_id": audit_id, "sealed_at": _now(), "file_count": len(files), "manifest_sha256": manifest_hash,
        "files": files, "signature": SIGNATURE, **(extra or {}),
    }
    (folder / SEALED_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def verify_seal(folder: Path) -> Dict[str, Any]:
    """Re-hash the folder and compare with SEALED.json. ``ok`` is True only if nothing changed."""
    folder = Path(folder)
    rec = read_json(folder / SEALED_FILE)
    if not rec:
        return {"ok": False, "sealed": False, "reason": "no SEALED.json"}
    expected: Dict[str, str] = rec.get("files", {})
    current = {p.relative_to(folder).as_posix(): sha256_file(p) for p in _walk_files(folder)}
    missing = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    modified = sorted(k for k in expected if k in current and current[k] != expected[k])
    return {"ok": not (missing or added or modified), "sealed": True, "missing": missing, "added": added,
            "modified": modified, "file_count": len(expected), "sealed_at": rec.get("sealed_at"),
            "manifest_sha256": rec.get("manifest_sha256")}


# ---------------------------------------------------------------------------------------------- case.json mirror

def write_case_json(audits_root_: Path, data: Dict[str, Any]) -> Path:
    p = Path(audits_root_) / CASE_JSON
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p


def read_case_json(audits_root_: Path) -> Optional[Dict[str, Any]]:
    return read_json(Path(audits_root_) / CASE_JSON)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
