"""Filesystem paths the console reasons about: a case's results root and path containment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

from ..core import casefolder as cf


def case_results_root(case: dict) -> Path:
    """Where a case's outputs live: ``<root>/<audits_dir>`` or the case's ``--out`` override."""
    return cf.audits_root(Path(case["root_path"]), case["audits_dir"], (case.get("meta") or {}).get("out_dir"))


def file_inside(directory, name: Optional[str]) -> Optional[Path]:
    """``directory / name`` when ``name`` is a plain file name of a regular file that resolves directly inside
    ``directory`` (no separators, no ``..``, no link that leads elsewhere); otherwise None."""
    if not name or name in (".", "..") or "/" in name or "\\" in name or Path(name).is_absolute():
        return None
    path = Path(directory) / name
    try:
        if path.resolve().parent != Path(directory).resolve():
            return None
    except OSError:
        return None
    return path if path.is_file() else None


def resolve_within(candidate, roots: Iterable, *, strict: bool = True) -> Optional[Path]:
    """``candidate`` resolved (symlinks followed) when it lies inside one of ``roots``; otherwise None.
    Missing paths, other drives and anything that escapes a root all return None. Case-insensitive on Windows.
    ``strict=False`` accepts a path that does not exist yet (a folder about to be created), resolving what exists."""
    try:
        path = Path(candidate).resolve(strict=strict)
    except (OSError, RuntimeError, ValueError):
        return None
    target = os.path.normcase(str(path))
    for root in roots:
        try:
            base = os.path.normcase(str(Path(root).resolve(strict=True)))
            if os.path.commonpath([base, target]) == base:
                return path
        except (OSError, RuntimeError, ValueError):  # unresolvable root or a different drive
            continue
    return None
