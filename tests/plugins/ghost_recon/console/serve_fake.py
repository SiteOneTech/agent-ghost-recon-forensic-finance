"""Test helper (not a test): a real console server process wired to the fake agent, for the H2 acceptance E2E.

    python tests/plugins/ghost_recon/console/serve_fake.py --port N --case-root DIR --fake-config CFG [--tick S]

Standalone ``ghostrecon serve`` reads its settings only from Hermes' config.yaml (and the console takes no new env vars
for settings), so this builds the same app — ``create_app`` + ``JobService`` + uvicorn — with a case root and the fake
agent. The DB comes from GHOSTRECON_DB, as for every standalone run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
FAKE_AGENT = REPO / "ghost-recon" / "demo" / "fake_agent.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--case-root", required=True)
    parser.add_argument("--fake-config", required=True)
    parser.add_argument("--tick", type=float, default=0.5)
    parser.add_argument("--poll", type=float, default=0.1)
    args = parser.parse_args()

    import uvicorn
    from plugins.ghost_recon import runtime
    from plugins.ghost_recon.console.app import create_app
    from plugins.ghost_recon.console.jobs import JobService
    from plugins.ghost_recon.console.procs import RUNNER_MODULE
    from plugins.ghost_recon.console.settings import ConsoleSettings
    from plugins.ghost_recon.console.store import ConsoleStore

    settings = ConsoleSettings(port=args.port, case_roots=(args.case_root,))
    cstore = ConsoleStore.open_default()
    store = runtime.store()
    jobs = JobService(
        cstore, store, settings,
        hermes_command=lambda a: [sys.executable, str(FAKE_AGENT), "--fake-config", args.fake_config, *a],
        runner_command=lambda job_id: [sys.executable, "-m", RUNNER_MODULE, str(job_id), "--poll", str(args.poll)],
        tick_seconds=args.tick)
    uvicorn.run(create_app(settings, store, cstore, jobs=jobs), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
