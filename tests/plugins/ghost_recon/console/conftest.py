"""Fixtures for the console tests (they build on tests/plugins/ghost_recon/conftest.py: gr_env, store)."""
import shutil
from pathlib import Path

import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings

REPO = Path(__file__).resolve().parents[4]
DEMO = REPO / "ghost-recon" / "demo" / "demo-case"

ADMIN = ("jean", "admin-pass-123")
VIEWER = ("vera", "viewer-pass-123")


@pytest.fixture
def case_root(gr_env):
    """The configured case root of the console tests (spec §12 ``case_roots``)."""
    root = gr_env / "Casos"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture
def demo_case(case_root):
    """The demo case copied INSIDE the case root (overrides the plugin-level fixture) so jobs can target it."""
    dest = case_root / "demo-case"
    shutil.copytree(DEMO, dest)
    return dest


@pytest.fixture
def settings(case_root):
    return ConsoleSettings(case_roots=(str(case_root),))


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


def _seal_with_md_pack(store, audit_id, folder: Path, report_md: str) -> None:
    """Seal an audit with an md-only pack (forced: pdf/xlsx need the plugin's optional deps)."""
    from plugins.ghost_recon.core import casefolder as cf, service
    from plugins.ghost_recon.core.reports import pack
    cf.write_json(folder, "03_Extracted_Data/model.json", {"kpis": {"total": 1}})
    cf.write_text(folder, "06_Report/report.md", report_md)
    pack.build_pack(store, audit_id, formats=["md"])
    service.record_run(store, audit_id, "validation", role="A", status="done", summary="ok")
    assert service.seal_audit(store, audit_id, force=True)["sealed"]


@pytest.fixture
def seeded(store, demo_case):
    """Demo case: A01 sealed (3 findings, 1 criterion, md pack) and A02 open (rerun) with an md report."""
    from plugins.ghost_recon.core import casefolder as cf, service
    from plugins.ghost_recon.core.reports import pack
    case_id = service.open_case(store, str(demo_case), name="Acme Demo")["case"]["id"]
    a1 = service.start_audit(store, case_id, "initial")
    a1_id = a1["audit"]["id"]
    service.upsert_findings(store, a1_id, [
        {"kind": "exception", "title": "Pagos Zelle sin factura", "amount": 12450.0, "risk": "high",
         "counterparty": "Socio B"},
        {"kind": "anomaly", "title": "Factura posterior al pago", "amount": 3200.0, "risk": "medium"},
        {"kind": "question", "title": "¿Quién autorizó el acta?", "risk": "low", "status": "closed"},
    ])
    service.add_criterion(store, a1_id, "Gerencia", "Periodo ene–jun 2026")
    _seal_with_md_pack(store, a1_id, Path(a1["folder"]), "## 1. Respuesta\n\nTexto.\n")
    (demo_case / "Bancos" / "nuevo.txt").write_text("nuevo", encoding="utf-8")
    a2 = service.start_audit(store, case_id, "rerun")
    a2_folder = Path(a2["folder"])
    cf.write_text(a2_folder, "06_Report/report.md", "## 1. Respuesta\n\nBorrador.\n")
    pack.build_pack(store, a2["audit"]["id"], formats=["md"])
    return {"case_id": case_id, "a1": a1_id, "a2": a2["audit"]["id"], "a1_folder": Path(a1["folder"]),
            "a2_folder": a2_folder, "root": demo_case}
