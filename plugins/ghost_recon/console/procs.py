"""Process glue with Hermes for console jobs: the commands that run the agent and the job runner, and how those
processes are spawned, watched and stopped.

Every Hermes-internal import of the job engine lives in this module (spec §4.3). The executable is never looked up on
PATH: ``hermes_cli._launchers`` builds the command bound to the running installation.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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


# Linux computes create_time as ctime + boot_time() and re-reads the boot time on every call, so an NTP/timesyncd
# step, a VM time sync or a resume shifts a live process's create_time; a strict match would turn a healthy job into
# an orphan and make kill_tree refuse its own agent. PID reuse to the same number within 2 s is negligible.
_IDENTITY_TOLERANCE_S = 2.0


def child_env() -> Dict[str, str]:
    """Environment of the runner and the agent: the served profile's, with its credentials (root AGENTS.md: child
    spawns use ``served_profile_child_env``, never ``os.environ.copy()``)."""
    from tools.environments.local import served_profile_child_env
    return served_profile_child_env(inherit_credentials=True)


def spawn_detached(argv: Sequence[str], *, cwd: Any, env: Dict[str, str], stdout: Any = subprocess.DEVNULL,
                   stderr: Any = subprocess.DEVNULL) -> subprocess.Popen:
    """Start ``argv`` detached from the console's session/console, so stopping the server never takes it down.
    The only per-OS branch of the job engine, and it is Hermes': a new session on POSIX; a new process group, hidden
    console and job breakaway on Windows, retried without breakaway when a job object forbids it."""
    from hermes_cli._subprocess_compat import (IS_WINDOWS, windows_detach_flags_without_breakaway,
                                               windows_detach_popen_kwargs)
    common = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL, "stdout": stdout, "stderr": stderr,
              "close_fds": True}
    try:
        return subprocess.Popen(list(argv), **common, **windows_detach_popen_kwargs())
    except PermissionError:
        if not IS_WINDOWS:
            raise
        return subprocess.Popen(list(argv), **common, creationflags=windows_detach_flags_without_breakaway())


def identity(pid: Any) -> Optional[float]:
    """The process create time, stored beside a PID as its fingerprint; None when the process is gone."""
    import psutil
    try:
        return psutil.Process(int(pid)).create_time()
    except (psutil.Error, TypeError, ValueError):
        return None


def same_process(create_time: float, started: Any) -> bool:
    """Whether a process created at ``create_time`` is the one fingerprinted as ``started``. An unknown fingerprint
    (None) never matches: without it nothing proves the PID still names our process."""
    return started is not None and abs(float(create_time) - float(started)) <= _IDENTITY_TOLERANCE_S


def _matching(pid: Any, started: Any):
    import psutil
    if not pid:
        return None
    try:
        proc = psutil.Process(int(pid))
        if not same_process(proc.create_time(), started):
            return None
    except (psutil.Error, TypeError, ValueError):
        return None
    try:
        if proc.status() == psutil.STATUS_ZOMBIE:
            return None
    except psutil.AccessDenied:
        pass
    except psutil.Error:
        return None
    return proc


def alive(pid: Any, started: Any) -> bool:
    """True while the process that had ``pid`` at ``started`` still runs. A zombie (a dead child nobody has waited
    for yet) and a recycled PID both count as dead, and so does any PID without a fingerprint (``started`` None):
    its identity cannot be confirmed, so it is never taken for the job's process."""
    return _matching(pid, started) is not None


def kill_tree(pid: Any, started: Any, *, timeout: float = 10.0) -> bool:
    """Terminate the process and every descendant, snapshotting the tree first so reparented grandchildren are
    included; escalate to kill after half the timeout. False when the identity does not match or is unknown
    (nothing signalled)."""
    import psutil
    root = _matching(pid, started)
    if root is None:
        return False
    try:
        tree = root.children(recursive=True) + [root]
    except psutil.Error:
        tree = [root]
    for proc in tree:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _gone, survivors = psutil.wait_procs(tree, timeout=timeout / 2)
    for proc in survivors:
        try:
            proc.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(survivors, timeout=timeout / 2)
    return True
