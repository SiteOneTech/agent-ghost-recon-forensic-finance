"""Test helper (not a test): the real ``hermes ghostrecon serve`` of a temporary Hermes home, with the fake agent.

    HERMES_HOME=<home> python tests/plugins/ghost_recon/console/serve_hermes.py --fake-config CFG   (no GHOSTRECON_DB)

Runs Hermes' own CLI entry point (``hermes_cli.main`` with ``ghostrecon serve``): plugin discovery, the plugin's
settings from that home's config.yaml, ``serve``'s preflight, ``create_app`` and uvicorn. One thing differs: the
plugin's ``procs.hermes_command`` is wrapped so ``hermes … chat`` and ``hermes … send`` run the fake agent; the job
runner still starts through this installation's launcher and resolves its database on its own.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
FAKE_AGENT = REPO / "ghost-recon" / "demo" / "fake_agent.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-config", required=True)
    args = parser.parse_args()

    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    discover_plugins()
    # The plugin package as Hermes loaded it, found the way hermes_cli/main.py finds `hermes ghostrecon`.
    handler = get_plugin_manager()._cli_commands["ghostrecon"]["handler_fn"]
    procs = importlib.import_module(f"{handler.__module__.rsplit('.', 1)[0]}.console.procs")
    real = procs.hermes_command

    def hermes_command(hermes_args, *, module="hermes_cli.main"):
        if module != "hermes_cli.main":
            return real(hermes_args, module=module)  # the job runner: this installation's launcher, untouched
        return [sys.executable, str(FAKE_AGENT), "--fake-config", args.fake_config, *hermes_args]

    procs.hermes_command = hermes_command
    from hermes_cli.main import main as hermes_main
    sys.argv = ["hermes", "ghostrecon", "serve"]
    return hermes_main()


if __name__ == "__main__":
    sys.exit(main())
