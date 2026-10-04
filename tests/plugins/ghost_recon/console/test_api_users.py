"""Users and API tokens from Sistema (admin only): the CLI's rules, sessions closed on reset or disable, the raw token
shown once, no self-lockout, and every change in the console audit log with the acting admin."""
from fastapi.testclient import TestClient

from plugins.ghost_recon.console.auth import MIN_PASSWORD


def test_user_and_token_administration_is_admin_only(login_as):
    viewer = login_as("viewer")
    calls = [("GET", "/api/v1/users", None), ("GET", "/api/v1/tokens", None),
             ("POST", "/api/v1/users", {"username": "ana", "role": "viewer", "password": "clave-larga-123",
                                         "password_confirm": "clave-larga-123"}),
             ("POST", "/api/v1/users/jean/disable", None), ("POST", "/api/v1/tokens", {"username": "vera", "name": "x"}),
             ("POST", "/api/v1/tokens/1/revoke", None)]
    for method, url, body in calls:
        r = viewer.request(method, url, json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", url


def test_an_admin_creates_users_with_the_cli_rules(login_as, cstore):
    admin = login_as("admin")
    base = {"username": "ana", "role": "admin", "password": "clave-larga-123"}
    mismatch = admin.post("/api/v1/users", json={**base, "password_confirm": "otra-clave-123"})
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "password_mismatch"
    short = admin.post("/api/v1/users", json={**base, "password": "corta", "password_confirm": "corta"})
    assert short.status_code == 422 and str(MIN_PASSWORD) in short.json()["error"]["message"]
    assert admin.post("/api/v1/users", json={**base, "password_confirm": base["password"]}).status_code == 201
    duplicate = admin.post("/api/v1/users", json={**base, "password_confirm": base["password"]})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "conflict"
    assert "ana" in [u["username"] for u in admin.get("/api/v1/users").json()["items"]]
    entry = next(e for e in cstore.list_audit_log() if e["action"] == "user_add")
    assert (entry["username"], entry["target"], entry["detail"]["role"]) == ("jean", "ana", "admin")


def test_a_password_reset_closes_the_users_sessions(login_as):
    admin, vera = login_as("admin"), login_as("viewer")
    body = {"password": "nueva-clave-123", "password_confirm": "nueva-clave-123"}
    assert admin.post("/api/v1/users/vera/password", json=body).status_code == 200
    assert vera.get("/api/v1/auth/me").status_code == 401
    assert vera.post("/api/v1/auth/login", json={"username": "vera", "password": "nueva-clave-123"}).status_code == 200


def test_disable_enable_and_role_changes_take_effect_and_are_logged(login_as, cstore):
    admin, vera = login_as("admin"), login_as("viewer")
    assert admin.post("/api/v1/users/vera/disable").status_code == 200
    assert vera.get("/api/v1/auth/me").status_code == 401
    assert admin.post("/api/v1/users/vera/enable").status_code == 200
    assert admin.post("/api/v1/users/vera/role", json={"role": "admin"}).status_code == 200
    assert login_as("viewer").get("/api/v1/auth/me").json()["user"]["role"] == "admin"  # vera, now admin
    actions = {e["action"] for e in cstore.list_audit_log() if e["username"] == "jean"}
    assert {"user_disable", "user_enable", "user_role"} <= actions


def test_an_admin_cannot_disable_or_demote_themself(login_as):
    admin = login_as("admin")
    for url, body in (("/api/v1/users/jean/disable", None), ("/api/v1/users/jean/role", {"role": "viewer"})):
        r = admin.post(url, json=body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "self_action", url


def test_a_token_is_shown_once_works_as_bearer_and_can_be_revoked(login_as, app, cstore):
    admin = login_as("admin")
    created = admin.post("/api/v1/tokens", json={"username": "vera", "name": "web-app"})
    assert created.status_code == 201
    raw, token_id = created.json()["token"], created.json()["id"]
    assert raw not in admin.get("/api/v1/tokens").text
    with TestClient(app, base_url="http://localhost") as api:
        bearer = {"Authorization": f"Bearer {raw}"}
        assert api.get("/api/v1/auth/me", headers=bearer).json()["user"]["username"] == "vera"
        assert admin.post(f"/api/v1/tokens/{token_id}/revoke").status_code == 200
        assert api.get("/api/v1/auth/me", headers=bearer).status_code == 401
    assert admin.post(f"/api/v1/tokens/{token_id}/revoke").status_code == 404
    log = cstore.list_audit_log()
    assert any(e["action"] == "token_create" and e["username"] == "jean" and e["detail"]["user"] == "vera" for e in log)
    assert any(e["action"] == "token_revoke" and e["username"] == "jean" for e in log)


def test_unknown_users_are_404(login_as):
    body = {"password": "clave-larga-123", "password_confirm": "clave-larga-123"}
    r = login_as("admin").post("/api/v1/users/nadie/password", json=body)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
