"""`ghostrecon user|token|serve` through the real CLI entry point (standalone module on the temp DB)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.ghost_recon.console.cli import is_loopback, serve_preflight

REPO = Path(__file__).resolve().parents[4]


def _cli(gr_env, *args, stdin=""):
    env = {**os.environ, "GHOSTRECON_DB": str(gr_env / "db" / "ghostrecon.db"), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "plugins.ghost_recon.cli", *args], cwd=REPO, env=env, input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_user_and_token_lifecycle(gr_env):
    added = _cli(gr_env, "user", "add", "jean", "--role", "admin", "--password-stdin", stdin="admin-pass-123\n")
    assert added.returncode == 0, added.stderr
    listed = _cli(gr_env, "user", "list").stdout
    assert "jean" in listed and "admin" in listed
    created = _cli(gr_env, "token", "create", "--user", "jean", "--name", "webapp")
    token = next(w for w in created.stdout.split() if w.startswith("grt_"))
    tokens = _cli(gr_env, "token", "list").stdout
    assert "webapp" in tokens and token not in tokens


def test_duplicate_user_fails_cleanly(gr_env):
    _cli(gr_env, "user", "add", "jean", "--role", "admin", "--password-stdin", stdin="admin-pass-123\n")
    dup = _cli(gr_env, "user", "add", "jean", "--role", "viewer", "--password-stdin", stdin="other-pass-123\n")
    assert dup.returncode == 1 and "error" in dup.stderr


def test_serve_refuses_to_start_without_an_admin(gr_env):
    r = _cli(gr_env, "serve", "--port", "1")
    assert r.returncode == 1 and "user add" in r.stderr


@pytest.mark.parametrize("host,expected", [("127.0.0.1", True), ("localhost", True), ("::1", True),
                                           ("0.0.0.0", False), ("192.168.1.20", False)])
def test_is_loopback(host, expected):
    assert is_loopback(host) is expected


def test_preflight_requires_allow_remote_for_non_loopback(cstore, auth):
    auth.add_user("jean", "admin-pass-123", "admin")
    assert serve_preflight(cstore, "0.0.0.0", allow_remote=False)
    assert serve_preflight(cstore, "0.0.0.0", allow_remote=True) == []
    assert serve_preflight(cstore, "127.0.0.1", allow_remote=False) == []
