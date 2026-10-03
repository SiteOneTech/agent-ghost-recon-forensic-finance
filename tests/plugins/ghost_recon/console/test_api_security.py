"""HTTP security contracts of the console: auth gate, Host check, headers, cookies, CSRF, lockout, logout."""
from fastapi.testclient import TestClient


def test_api_requires_authentication(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_forged_or_foreign_session_cookie_is_a_clean_401(client):
    client.cookies.set("gr_session", "forged-or-from-another-console")
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


def test_login_sets_an_httponly_strict_cookie_and_returns_csrf(client, users):
    r = client.post("/api/v1/auth/login", json={"username": "jean", "password": users["admin"][1]})
    assert r.status_code == 200 and r.json()["csrf"] and r.json()["user"]["role"] == "admin"
    cookie = r.headers["set-cookie"].lower()
    assert "gr_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie


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
