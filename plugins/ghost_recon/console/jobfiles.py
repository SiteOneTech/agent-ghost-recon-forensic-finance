"""Per-job files under ``<plugin data>/console/jobs/`` (the folder that holds ``ghostrecon.db``):
``<id>.jsonl`` (agent stdout, stream-json), ``<id>.log`` (agent stderr), ``<id>.events.jsonl`` (normalized console
events, written by the runner) and ``<id>.runner.log`` (the runner's own stderr). Byte offsets make reads incremental."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def jobs_dir() -> Path:
    from .. import runtime
    path = runtime.db_path().parent / "console" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.jsonl"


def log_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.log"


def events_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.events.jsonl"


def runner_log_path(base: Path, job_id: int) -> Path:
    return Path(base) / f"{int(job_id)}.runner.log"


def read_lines(path: Path, offset: int = 0, *, final: bool = False) -> Tuple[List[str], int]:
    """Lines appended after byte ``offset`` and the new offset. A trailing line without its newline stays for the
    next read, unless ``final`` (the writer is gone)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except FileNotFoundError:
        return [], offset
    end = len(data) if final else data.rfind(b"\n") + 1
    if end <= 0:
        return [], offset
    lines = [line.decode("utf-8", "replace") for line in data[:end].splitlines() if line.strip()]
    return lines, offset + end


def append_events(path: Path, events: Iterable[Dict[str, Any]]) -> None:
    payload = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    if payload:
        with open(path, "ab") as fh:
            fh.write(payload.encode("utf-8"))


def read_events(path: Path, after: int = 0, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Console events with ``seq > after`` written after byte ``offset``, and the new offset."""
    lines, new_offset = read_lines(path, offset)
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and int(event.get("seq") or 0) > after:
            events.append(event)
    return events, new_offset


def tail(path: Path, lines: int = 200, max_bytes: int = 256_000) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - max_bytes))
            data = fh.read()
    except FileNotFoundError:
        return ""
    return "\n".join(data.decode("utf-8", "replace").splitlines()[-lines:])
