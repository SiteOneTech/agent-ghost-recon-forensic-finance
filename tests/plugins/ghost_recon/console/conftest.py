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


@pytest.fixture
def app(store, cstore, settings, auth):
    from plugins.ghost_recon.console.app import create_app
    return create_app(settings, store, cstore, auth=auth)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def login_as(app, users):
    """Factory: a logged-in TestClient for 'admin' or 'viewer', with its CSRF header preset."""
    from fastapi.testclient import TestClient
    opened = []

    def _login(role: str):
        c = TestClient(app, base_url="http://localhost")
        c.__enter__()
        opened.append(c)
        username, password = users[role]
        r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        c.headers["X-GR-CSRF"] = r.json()["csrf"]
        return c

    yield _login
    for c in opened:
        c.__exit__(None, None, None)
