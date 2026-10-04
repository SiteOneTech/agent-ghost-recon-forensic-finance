"""Filesystem paths the console reasons about: a case's results root and (Task 5) path containment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

from ..core import casefolder as cf


def case_results_root(case: dict) -> Path:
    """Where a case's outputs live: ``<root>/<audits_dir>`` or the case's ``--out`` override."""
    return cf.audits_root(Path(case["root_path"]), case["audits_dir"], (case.get("meta") or {}).get("out_dir"))


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
