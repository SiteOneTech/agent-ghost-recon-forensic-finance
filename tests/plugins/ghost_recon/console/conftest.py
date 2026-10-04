"""Fixtures for the console tests (they build on tests/plugins/ghost_recon/conftest.py: gr_env, store)."""
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from plugins.ghost_recon.console.settings import ConsoleSettings

REPO = Path(__file__).resolve().parents[4]
DEMO = REPO / "ghost-recon" / "demo" / "demo-case"
FAKE_AGENT = REPO / "ghost-recon" / "demo" / "fake_agent.py"

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


@pytest.fixture
def wait_until():
    """Poll ``predicate`` until it returns something truthy (returned) or fail after ``timeout`` seconds."""
    def _wait(predicate, timeout=30.0, interval=0.05, message="condition"):
        deadline = time.monotonic() + timeout
        while True:
            value = predicate()
            if value:
                return value
            assert time.monotonic() < deadline, f"timed out after {timeout} s waiting for {message}"
            time.sleep(interval)
    return _wait


@pytest.fixture
def fake_agent(tmp_path):
    """Factory: writes a fake-agent config and returns the ``hermes_command`` that runs the fake with it."""
    made = []

    def _make(default=None, folders=None):
        config = tmp_path / f"fake-agent-{len(made)}.json"
        config.write_text(json.dumps({"default": default or {}, "folders": folders or {}}), encoding="utf-8")
        made.append(config)
        return lambda args: [sys.executable, str(FAKE_AGENT), "--fake-config", str(config), *args]
    return _make


@pytest.fixture
def module_runner():
    """Factory: the runner as ``python -m`` from the repo root (the production launcher form is covered by
    test_runner.py::test_runner_entry_point_runs_through_this_installation_launcher)."""
    from plugins.ghost_recon.console.procs import RUNNER_MODULE

    def _make(poll=0.05):
        return lambda job_id: [sys.executable, "-m", RUNNER_MODULE, str(job_id), "--poll", str(poll)]
    return _make


@pytest.fixture
def make_jobs(cstore, store, settings, fake_agent, module_runner):
    """Factory: a JobService over the test DB with the fake agent and the ``python -m`` runner, no background thread.
    Teardown stops every process tree a test left running."""
    from plugins.ghost_recon.console import procs
    from plugins.ghost_recon.console.jobs import JobService
    from plugins.ghost_recon.console.store import ACTIVE_STATUSES
    made = []

    def _make(*, hermes=None, runner=None, config=None):
        service = JobService(cstore, store, config or settings, hermes_command=hermes or fake_agent(),
                             runner_command=runner or module_runner(), tick_seconds=0, stream_poll=0.05)
        made.append(service)
        return service

    yield _make
    for service in made:
        service.stop()
    for job in cstore.list_jobs(statuses=ACTIVE_STATUSES):
        procs.kill_tree(job["runner_pid"], job["runner_started"])
        procs.kill_tree(job["pid"], job["pid_started"])
