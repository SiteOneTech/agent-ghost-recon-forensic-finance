"""Integrity of sealed results (spec §9 "Descargas", §11 "Integridad").

A file of a sealed audit is trusted only while its bytes still hash to what the seal recorded in ``SEALED.json`` and,
for a deliverable, to the hash registered when the pack was built. Deliverable downloads and the ZIP export both go
through these checks, so a changed file is refused by name instead of leaving the console.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import casefolder as cf, service
from ..core.db import Store
from .store import ConsoleStore

SEAL_DETAIL_KEYS = ("missing", "added", "modified", "file_count", "manifest_sha256", "db_matches", "reason", "sealed")
_CHANGE_WORDS = (("modified", "modificado"), ("missing", "falta"), ("added", "añadido"))
_REASONS = {"read_error": "no se pudo leer la carpeta de la auditoría", "no SEALED.json": "falta SEALED.json"}


class IntegrityError(Exception):
    """A sealed file that cannot be trusted; ``rel`` is its path inside the audit folder (safe to show)."""

    def __init__(self, code: str, rel: str, message: str):
        super().__init__(message)
        self.code = code
        self.rel = rel
        self.message = message


def record_seal_check(store: Store, cstore: ConsoleStore, audit: Dict[str, Any], username: str) -> Dict[str, Any]:
    """Re-hash a sealed audit against its seal and cache the outcome (``console_seal_checks``, the "verificado hace X"
    of the views): ``{"ok", "detail", "checked_at"}``. A folder that cannot be read is a failed check."""
    try:
        result = service.verify_audit(store, audit["id"])
    except (OSError, service.CaseError):
        result = {"ok": False, "reason": "read_error"}  # machine code only: the exception text carries paths
    ok = bool(result.get("ok")) and result.get("db_matches") is not False
    detail = {k: result.get(k) for k in SEAL_DETAIL_KEYS}
    check = cstore.save_seal_check(audit["id"], ok, detail, username)
    return {"ok": ok, "detail": detail, "checked_at": check["checked_at"]}


def changed_files(detail: Dict[str, Any], limit: int = 5) -> str:
    """What a failed seal check found, for a message: "06_Report/x.md (modificado), …" or the reason it failed."""
    parts: List[str] = [f"{rel} ({word})" for key, word in _CHANGE_WORDS for rel in (detail.get(key) or [])]
    if parts:
        more = f" y {len(parts) - limit} más" if len(parts) > limit else ""
        return ", ".join(parts[:limit]) + more
    if detail.get("db_matches") is False:
        return "el hash del sello no coincide con el registrado en la base de datos"
    return _REASONS.get(detail.get("reason") or "", "el sello no se pudo comprobar")


def seal_hashes(folder: Path) -> Optional[Dict[str, str]]:
    """``relative path -> sha256`` as the audit's ``SEALED.json`` recorded them; None when missing or unreadable."""
    record = cf.read_json(Path(folder) / cf.SEALED_FILE)
    files = record.get("files") if isinstance(record, dict) else None
    return files if isinstance(files, dict) else None


def relative(folder: Path, path: Path) -> str:
    """``path`` relative to the audit ``folder`` in the seal's notation (forward slashes)."""
    return Path(path).resolve().relative_to(Path(folder).resolve()).as_posix()


def expected_hash(sealed: Optional[Dict[str, str]], rel: str) -> str:
    """The hash the seal recorded for ``rel``; IntegrityError when there is no readable seal or ``rel`` is not in it."""
    if sealed is None:
        raise IntegrityError("no_seal_manifest", rel, f"no se puede leer el sello (SEALED.json) para comprobar {rel}")
    expected = sealed.get(rel)
    if not expected:
        raise IntegrityError("not_in_seal", rel, f"{rel} no estaba en la auditoría cuando se selló")
    return expected


def check(rel: str, actual: str, expected: str, registered: str = "") -> None:
    """``actual`` must equal the sealed hash and, when given, the hash registered for the deliverable."""
    if actual != expected or (registered and actual != registered):
        raise IntegrityError("hash_mismatch", rel, f"{rel} cambió después de sellar la auditoría")


def verified_bytes(folder: Path, path: Path, *, registered: str = "") -> bytes:
    """The bytes of ``path`` (a file inside the sealed audit ``folder``) only if they pass ``check``. The bytes
    returned are exactly the ones hashed, so nothing can change between the check and the download."""
    rel = relative(folder, path)
    expected = expected_hash(seal_hashes(folder), rel)
    data = Path(path).read_bytes()
    check(rel, hashlib.sha256(data).hexdigest(), expected, registered)
    return data
