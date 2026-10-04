"""Process glue with Hermes for console jobs: the commands that run the agent and the job runner, and how those
processes are spawned, watched and stopped.

Every Hermes-internal import of the job engine lives in this module (spec §4.3). The executable is never looked up on
PATH: ``hermes_cli._launchers`` builds the command bound to the running installation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import List, Sequence

RUNNER_MODULE = "plugins.ghost_recon.console.job_runner"


def hermes_root() -> Path:
    """Root of the running Hermes installation (the directory that holds ``hermes_cli/``)."""
    spec = importlib.util.find_spec("hermes_cli")
    if spec is None or not spec.origin:
        raise RuntimeError("hermes_cli no es importable: la consola debe ejecutarse desde una instalación de Hermes")
    return Path(spec.origin).resolve().parents[1]


def hermes_command(args: Sequence[str], *, module: str = "hermes_cli.main") -> List[str]:
    """argv that runs ``module`` with this installation's interpreter and dependencies.

    POSIX: ``installation_command`` (the PM launcher ``<root>/.hermes/bin/hermes``, an ``exec`` wrapper, when the
    install has one; else the installation-bound runtime command). Windows: always ``runtime_command``, because the
    launcher there can be a ``.cmd`` shim, unsafe as argv[0] with operator-supplied arguments (kanban's rule)."""
    from hermes_cli._launchers import installation_command, runtime_command
    from hermes_cli._subprocess_compat import IS_WINDOWS
    build = runtime_command if IS_WINDOWS else installation_command
    return [str(part) for part in build(hermes_root(), [str(a) for a in args], module=module)]


def runner_command(job_id: int) -> List[str]:
    """argv of the detached runner process of ``job_id``."""
    return hermes_command([str(int(job_id))], module=RUNNER_MODULE)


def profile_args() -> List[str]:
    """``["-p", <profile>]`` for the profile this console serves; ``[]`` for a custom home outside the profile tree.
    Explicit even for ``default``: a bare ``hermes`` would follow the sticky ``active_profile`` file instead."""
    from hermes_constants import get_hermes_home, profile_name_for_home
    name = profile_name_for_home(get_hermes_home())
    return ["-p", name] if name else []
