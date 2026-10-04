"""The agent command is bound to this Hermes installation (launcher or runtime command), never to PATH."""
import subprocess

from plugins.ghost_recon.console import procs


def test_hermes_command_starts_this_installation():
    r = subprocess.run(procs.hermes_command(["--version"]), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip()


def test_the_runner_command_targets_the_runner_module_of_this_installation():
    cmd = procs.runner_command(7)
    assert cmd[-1] == "7" and procs.RUNNER_MODULE in " ".join(cmd)


def test_process_identity_tolerates_clock_drift_but_not_another_process():
    """Linux derives create_time from the boot time, re-read on every call, so a clock step shifts it: a drift of a
    second or so is still the same process; seconds apart is another one, and an unknown start time is never a match."""
    assert procs.same_process(1000.0, 1001.5) and procs.same_process(1001.5, 1000.0)
    assert not procs.same_process(1000.0, 1005.0)
    assert not procs.same_process(1000.0, None)
