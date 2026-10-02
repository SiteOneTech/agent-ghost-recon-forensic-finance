"""Identifier generation for cases, audits, reviews and series (EXC-nn, ...).

The series counters live in the DB (``Store.next_series_id``); this module only shapes strings.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Optional

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 32) -> str:
    """ASCII, lowercase, hyphen-separated; never empty."""
    norm = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_RE.sub("-", norm).strip("-")
    slug = slug[:max_len].strip("-")
    return slug or "case"


def today_compact(d: Optional[date] = None) -> str:
    return (d or datetime.now().date()).strftime("%Y%m%d")


def today_iso(d: Optional[date] = None) -> str:
    return (d or datetime.now().date()).isoformat()


def case_id(name: str, d: Optional[date] = None) -> str:
    return f"GRC-{slugify(name)}-{today_compact(d)}"


def audit_id(case_id_: str, seq: int, kind: str = "initial") -> str:
    prefix = "R" if kind == "review" else "A"
    return f"{case_id_}/{prefix}{seq:02d}"


def audit_folder_name(seq: int, kind: str = "initial", d: Optional[date] = None) -> str:
    prefix = "R" if kind == "review" else "A"
    return f"{prefix}{seq:02d}_{today_iso(d)}"


def short_audit(audit_id_: str) -> str:
    """``GRC-x/A02`` -> ``A02``."""
    return audit_id_.rsplit("/", 1)[-1]
