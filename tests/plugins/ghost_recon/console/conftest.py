"""Fixtures for the console tests (they build on tests/plugins/ghost_recon/conftest.py: gr_env, store, demo_case)."""
import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings

ADMIN = ("jean", "admin-pass-123")
VIEWER = ("vera", "viewer-pass-123")


@pytest.fixture
def settings():
    return ConsoleSettings()


@pytest.fixture
def cstore(store):
    """Console store on its own connection to the same temp DB as ``store`` (case tables already migrated)."""
    from plugins.ghost_recon.console.store import ConsoleStore
    return ConsoleStore.open_default()
