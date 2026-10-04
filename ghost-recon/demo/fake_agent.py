#!/usr/bin/env python3
"""Stand-in for ``hermes … chat -q … --format stream-json`` (console tests and demo; no LLM, no keys).

    python ghost-recon/demo/fake_agent.py --fake-config cfg.json <the Hermes arguments the console built>

Emits the real record shapes of ``hermes_cli/stream_json.py`` (system/init, tool_use, tool_result, text, result),
sleeping between steps, and exits with the configured code. The console runs the agent with the case folder as its
working directory, so the config holds a ``default`` behaviour plus overrides keyed by folder name:

    {"default": {"steps": 3, "delay": 0.05}, "folders": {"hang-case": {"hang": true}}}

Keys: ``steps`` (delegated blocks), ``delay`` (seconds per step), ``exit_code``, ``error`` (in the result record),
``hang`` (spawn a sleeping grandchild and wait to be killed), ``no_result`` (exit without the result record),
``open_case`` (really open the case in the Ghost Recon DB on /new-open-case; default true) and ``record_argv`` (path
where the full argv is written as JSON).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL_OUTPUT_CAP = 5000  # the same cap as hermes_cli/stream_json.py


def emit(record: dict) -> None:
    sys.stdout.write(json.dumps({**record, "timestamp": int(time.time() * 1000)}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def tool(name: str, args: dict, output, call_id: str) -> None:
    emit({"type": "tool_use", "name": name, "tool_call_id": call_id, "input": args})
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    emit({"type": "tool_result", "name": name, "tool_call_id": call_id,
          "output": text if len(text) <= TOOL_OUTPUT_CAP else text[:TOOL_OUTPUT_CAP] + "...", "duration_ms": 5,
          "is_error": False})


def behaviour(config_path: str, folder_name: str) -> dict:
    data = json.loads(Path(config_path).read_text(encoding="utf-8")) if config_path else {}
    merged = dict(data.get("default") or {})
    merged.update((data.get("folders") or {}).get(folder_name) or {})
    return merged


def open_case(folder: Path):
    sys.path.insert(0, str(REPO))
    from plugins.ghost_recon import runtime
    from plugins.ghost_recon.core import service
    return service.open_case(runtime.store(), str(folder), audits_dir=str(runtime.setting("audits_dirname")))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-config", default="")
    parser.add_argument("-q", "--query", default="")
    args, _hermes_flags = parser.parse_known_args()
    folder = Path.cwd()
    cfg = behaviour(args.fake_config, folder.name)
    if cfg.get("record_argv"):
        Path(cfg["record_argv"]).write_text(json.dumps(sys.argv, ensure_ascii=False), encoding="utf-8")
    session = f"fake-{os.getpid()}"
    emit({"type": "system", "subtype": "init", "model": "fake/agent", "session_id": session})
    if cfg.get("hang"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        emit({"type": "tool_use", "name": "terminal", "tool_call_id": "hang",
              "input": {"command": "sleep 600", "pid": child.pid}})
        while True:
            time.sleep(0.2)
    steps, delay = int(cfg.get("steps", 3)), float(cfg.get("delay", 0.05))
    if args.query.startswith("/new-open-case") and cfg.get("open_case", True):
        tool("gr_case_open", {"folder": str(folder)}, open_case(folder), "c1")
    tool("read_file", {"path": str(folder / "context.md")}, "contexto", "c2")
    tool("gr_swarm_plan", {"audit_id": "fake", "mode": "extraction"},
         {"mode": "extraction", "tasks": [{"block": f"b{i}"} for i in range(steps)], "waves": 1}, "c3")
    for i in range(steps):
        time.sleep(delay)
        tool("delegate_task", {"tasks": [{"goal": f"bloque {i + 1}"}]}, "ok", f"d{i}")
    emit({"type": "text", "text": "Auditoría simulada "})
    emit({"type": "text", "text": "completada."})
    code = int(cfg.get("exit_code", 0))
    if cfg.get("no_result"):
        return code
    record = {"type": "result", "session_id": session, "exit_code": code, "text": "Auditoría simulada completada.",
              "tokens": {"input": 120, "output": 45, "total": 165, "cache_read": 0, "cache_write": 0},
              "duration_ms": int(steps * delay * 1000)}
    if cfg.get("error"):
        record["error"] = cfg["error"]
    emit(record)
    print(f"\nsession_id: {session}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
