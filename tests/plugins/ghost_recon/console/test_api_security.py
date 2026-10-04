"""HTTP security contracts of the console: auth gate, Host check, headers, cookies, CSRF, lockout, logout."""
from fastapi.testclient import TestClient


def test_api_requires_authentication(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_forged_or_foreign_session_cookie_is_a_clean_401(client):
    client.cookies.set("gr_session_9230", "forged-or-from-another-console")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_foreign_host_header_is_rejected(app):
    with TestClient(app, base_url="http://evil.example") as c:
        r = c.get("/api/v1/auth/me")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_host"


def test_loopback_host_on_any_port_reaches_the_auth_gate(app):
    with TestClient(app, base_url="http://localhost:19230") as c:  # e.g. an SSH tunnel on another local port
        assert c.get("/api/v1/auth/me").status_code == 401


def test_security_headers_on_page_and_api(client):
    page = client.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    api = client.get("/api/v1/auth/me")
    assert api.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in api.headers["content-security-policy"]


def test_pages_and_static_revalidate_while_api_is_never_stored(client):
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/api/v1/auth/me").headers["cache-control"] == "no-store"


def test_login_sets_an_httponly_strict_cookie_and_returns_csrf(client, users):
    r = client.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]})
    assert r.status_code == 200 and r.json()["csrf"] and r.json()["user"]["role"] == "admin"
    cookie = r.headers["set-cookie"].lower()
    assert "gr_session_9230=" in cookie and "httponly" in cookie and "samesite=strict" in cookie


def test_bad_credentials_are_401_then_lockout_is_429(client, users):
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "jean", "password": "wrong-password"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    r = client.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_state_changing_requests_need_the_csrf_header(client, users):
    r = client.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]})
    csrf = r.json()["csrf"]
    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "csrf"
    assert client.post("/api/v1/auth/logout", headers={"X-GR-CSRF": csrf}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401  # session revoked by logout


def test_openapi_schema_is_behind_login(client, users):
    assert client.get("/api/v1/openapi.json").status_code == 401
    client.post("/api/v1/auth/login", json={"username": "vera", "password": users["viewer"][1]})
    assert "/api/v1/auth/login" in client.get("/api/v1/openapi.json").json()["paths"]


def test_invalid_login_body_is_a_422_envelope(client):
    r = client.post("/api/v1/auth/login", json={"username": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_422_never_echoes_the_submitted_password(client):
    secret = "MY-SECRET-PASSWORD"
    for body in ({"password": secret}, {"username": "jean", "password": secret * 20}):
        r = client.post("/api/v1/auth/login", json=body)
        assert r.status_code == 422
        assert secret not in r.text
        assert all(set(f) == {"loc", "msg", "type"} for f in r.json()["error"]["fields"])


def test_two_consoles_on_one_host_keep_separate_sessions(store, cstore, users):
    from dataclasses import replace
    from plugins.ghost_recon.console.app import create_app
    from plugins.ghost_recon.console.auth import AuthService
    from plugins.ghost_recon.console.settings import ConsoleSettings
    apps = {}
    for port in (9230, 9231):
        settings = replace(ConsoleSettings(), port=port)
        apps[port] = create_app(settings, store, cstore, auth=AuthService(cstore, settings))
    # One jar for both: browsers do not separate cookies by port.
    with TestClient(apps[9230], base_url="http://localhost") as a, TestClient(apps[9231], base_url="http://localhost") as b:
        assert a.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]}).status_code == 200
        b.cookies.jar = a.cookies.jar  # same cookie jar object
        assert b.post("/api/v1/auth/login", json={"username": "vera", "password": users["viewer"][1]}).status_code == 200
        assert a.get("/api/v1/auth/me").json()["user"]["username"] == "jean"
        assert b.get("/api/v1/auth/me").json()["user"]["username"] == "vera"


def test_background_polls_never_keep_a_session_alive(login_as, cstore):
    """What the page asks on its own (``X-GR-Background: 1``) still authenticates and still expires, but leaves
    last-seen alone, so an open tab nobody uses times out; a request the user makes refreshes it."""
    from datetime import datetime, timedelta, timezone
    c = login_as("viewer")

    def seen_at(ago=None):
        if ago is not None:
            stamp = (datetime.now(timezone.utc) - ago).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            cstore.conn.execute("UPDATE console_sessions SET last_seen_at=?", (stamp,))
            cstore.conn.commit()
        return cstore.conn.execute("SELECT last_seen_at FROM console_sessions").fetchone()[0]
    before = seen_at(timedelta(minutes=10))
    assert c.get("/api/v1/jobs", headers={"X-GR-Background": "1"}).status_code == 200
    assert seen_at() == before
    assert c.get("/api/v1/jobs").status_code == 200
    assert seen_at() > before
    seen_at(timedelta(hours=13))
    assert c.get("/api/v1/jobs", headers={"X-GR-Background": "1"}).status_code == 401
