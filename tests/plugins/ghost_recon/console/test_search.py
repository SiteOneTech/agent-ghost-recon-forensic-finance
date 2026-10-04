"""Cross-case search (spec §14 "Búsqueda") and the Casos "riesgo abierto" filter: findings by ID or title and
evidence by name or hash across two cases, nothing outside the DB, bounded and behind the login."""
import shutil
from pathlib import Path

import pytest

from plugins.ghost_recon.console import search as search_mod
from plugins.ghost_recon.core import service

DEMO = Path(__file__).resolve().parents[4] / "ghost-recon" / "demo" / "demo-case"


@pytest.fixture
def two_cases(store, seeded, case_root):
    """``seeded`` (Acme Demo) plus "Beta Holding", a second case with its own EXC-01 and criterion."""
    folder = case_root / "Beta Holding"
    shutil.copytree(DEMO, folder)
    beta = service.open_case(store, str(folder), name="Beta Holding")["case"]["id"]
    audit = service.start_audit(store, beta, "initial")["audit"]["id"]
    service.upsert_findings(store, audit, [{"kind": "exception", "title": "Transferencia sin soporte",
                                            "risk": "critical"}])
    service.add_criterion(store, audit, "Socio A", "Las transferencias internas no son ingresos.")
    return {"acme": seeded["case_id"], "beta": beta, "beta_root": folder}


def _search(c, **params):
    r = c.get("/api/v1/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_findings_are_found_by_id_and_by_title_across_cases(login_as, two_cases):
    c = login_as("viewer")
    by_id = _search(c, q="EXC-01", types="finding")["items"]["finding"]
    assert {(f["case_id"], f["id"]) for f in by_id} == {(two_cases["acme"], "EXC-01"), (two_cases["beta"], "EXC-01")}
    by_title = _search(c, q="sin soporte")["items"]["finding"]
    assert [(f["case_id"], f["tab"]) for f in by_title] == [(two_cases["beta"], "findings")]


def test_evidence_is_found_by_name_and_by_hash(login_as, store, two_cases):
    c = login_as("viewer")
    by_name = _search(c, q="extracto", types="evidence", limit=50)["items"]["evidence"]
    assert {e["case_id"] for e in by_name} == {two_cases["acme"], two_cases["beta"]}
    row = store.list_evidence(two_cases["beta"])[0]
    by_hash = _search(c, q=row["sha256"][:16], types="evidence")["items"]["evidence"]
    assert (two_cases["beta"], row["path"]) in {(e["case_id"], e["title"]) for e in by_hash}


def test_cases_and_criteria_are_found_and_link_to_their_tab(login_as, two_cases):
    found = _search(login_as("viewer"), q="beta holding")["items"]
    assert [(i["id"], i["tab"]) for i in found["case"]] == [(two_cases["beta"], "summary")]
    criteria = _search(login_as("viewer"), q="transferencias internas", types="criteria")["items"]["criteria"]
    assert [(i["case_id"], i["id"], i["tab"]) for i in criteria] == [(two_cases["beta"], "CRIT-01", "criteria")]


def test_nothing_outside_the_database_is_ever_found(login_as, two_cases):
    (two_cases["beta_root"] / "fantasma-xyz.txt").write_text("no inventariado", encoding="utf-8")
    result = _search(login_as("viewer"), q="fantasma-xyz")
    assert all(hits == [] for hits in result["items"].values())


def test_search_is_bounded_and_behind_the_login(client, login_as, two_cases):
    assert client.get("/api/v1/search", params={"q": "extracto"}).status_code == 401
    c = login_as("viewer")
    one = _search(c, q="extracto", limit=1)
    assert all(len(hits) <= 1 for hits in one["items"].values()) and one["more"]["evidence"] is True
    for params in ({"q": "a"}, {"q": "  "}, {"q": "x" * 101}, {"q": "extracto", "limit": 51},
                   {"q": "extracto", "types": "finding,passwords"}):
        assert c.get("/api/v1/search", params=params).status_code == 422


def test_the_scan_stops_at_its_time_budget(store, two_cases):
    ticks = iter(range(0, 1000, 5))  # every call: five more seconds
    result = search_mod.search(store, "extracto", clock=lambda: float(next(ticks)))
    assert result["timed_out"] is True and len({h["case_id"] for h in result["items"]["evidence"]}) <= 1


def test_cases_filter_by_open_risk(login_as, two_cases):
    c = login_as("viewer")

    def ids(risk):
        r = c.get("/api/v1/cases", params={"risk": risk})
        assert r.status_code == 200
        return {row["id"] for row in r.json()["items"]}
    assert ids("critical") == {two_cases["beta"]} and ids("high") == {two_cases["acme"]}
    assert ids("low") == set()  # Acme's low-risk finding is closed
    assert ids("any") == {two_cases["acme"], two_cases["beta"]}
    assert c.get("/api/v1/cases", params={"risk": "extreme"}).status_code == 422
