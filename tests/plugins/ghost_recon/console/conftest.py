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


@pytest.fixture
def auth(cstore, settings):
    from plugins.ghost_recon.console.auth import AuthService
    return AuthService(cstore, settings)


@pytest.fixture
def users(auth):
    auth.add_user(ADMIN[0], ADMIN[1], "admin")
    auth.add_user(VIEWER[0], VIEWER[1], "viewer")
    return {"admin": ADMIN, "viewer": VIEWER}
