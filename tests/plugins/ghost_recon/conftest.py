"""Fixtures for the Ghost Recon plugin tests: a temp DB (GHOSTRECON_DB) and a copy of the demo case."""
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "ghost-recon" / "demo" / "demo-case"


@pytest.fixture
def gr_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTRECON_DB", str(tmp_path / "db" / "ghostrecon.db"))
    from plugins.ghost_recon import runtime
    runtime._stores.clear()
    yield tmp_path
    runtime._stores.clear()


@pytest.fixture
def store(gr_env):
    from plugins.ghost_recon import runtime
    return runtime.store()


@pytest.fixture
def demo_case(gr_env):
    dest = gr_env / "demo-case"
    shutil.copytree(DEMO, dest)
    return dest
