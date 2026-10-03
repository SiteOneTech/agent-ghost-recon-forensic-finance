"""Filesystem paths the console reasons about: a case's results root and (Task 5) path containment."""

from __future__ import annotations

from pathlib import Path

from ..core import casefolder as cf


def case_results_root(case: dict) -> Path:
    """Where a case's outputs live: ``<root>/<audits_dir>`` or the case's ``--out`` override."""
    return cf.audits_root(Path(case["root_path"]), case["audits_dir"], (case.get("meta") or {}).get("out_dir"))
