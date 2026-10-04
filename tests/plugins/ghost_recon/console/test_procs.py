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
