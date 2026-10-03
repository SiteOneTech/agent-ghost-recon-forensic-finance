"""Read API over the case DB: every figure the console shows must agree with the case Store."""


def test_overview_on_an_empty_db_returns_zeros(login_as):
    o = login_as("viewer").get("/api/v1/system/overview").json()
    assert o["kpis"]["cases_total"] == 0 and o["kpis"]["open_total"] == 0
    assert o["recent_cases"] == [] and o["recent_events"] == []


def test_overview_totals_agree_with_case_rows(login_as, seeded):
    c = login_as("viewer")
    o = c.get("/api/v1/system/overview").json()
    rows = c.get("/api/v1/cases").json()["items"]
    assert o["kpis"]["open_total"] == sum(r["open_total"] for r in rows)
    assert o["kpis"]["audits_sealed"] == sum(r["sealed_count"] for r in rows)
    assert o["recent_events"] and o["recent_events"][0]["case_name"] == "Acme Demo"


def test_case_list_open_counts_match_the_store(login_as, seeded, store):
    rows = login_as("viewer").get("/api/v1/cases").json()["items"]
    row = next(r for r in rows if r["id"] == seeded["case_id"])
    open_findings = [f for f in store.list_findings(seeded["case_id"]) if f["status"] == "open"]
    assert row["open_total"] == len(open_findings)
    for risk in ("critical", "high", "medium", "low"):
        assert row["open_by_risk"][risk] == sum(1 for f in open_findings if f["risk"] == risk)
    assert row["audits_count"] == len(store.list_audits(seeded["case_id"]))
    assert row["seal_state"] == "unverified"  # a sealed audit exists and nobody has verified it yet


def test_case_list_filters_by_text_and_status(login_as, seeded):
    c = login_as("viewer")
    assert [r["id"] for r in c.get("/api/v1/cases", params={"q": "ACME"}).json()["items"]] == [seeded["case_id"]]
    assert c.get("/api/v1/cases", params={"q": "no-such-case"}).json()["items"] == []
    assert c.get("/api/v1/cases", params={"status": "archived"}).json()["items"] == []


def test_case_detail_lists_audits_in_store_order(login_as, seeded, store):
    d = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}").json()
    assert [a["id"] for a in d["audits"]] == [a["id"] for a in store.list_audits(seeded["case_id"])]
    assert [a["seq"] for a in d["audits"]] == ["A01", "A02"]
    assert d["results_root"].endswith("GhostRecon_Audits")


def test_unknown_case_is_404_with_error_envelope(login_as):
    r = login_as("viewer").get("/api/v1/cases/GRC-nope-20260101")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_findings_filters_agree_with_the_store(login_as, seeded, store):
    c = login_as("viewer")
    base = f"/api/v1/cases/{seeded['case_id']}/findings"
    high = c.get(base, params={"risk": "high"}).json()["items"]
    assert high and all(f["risk"] == "high" for f in high)
    assert len(c.get(base).json()["items"]) == len(store.list_findings(seeded["case_id"]))
    assert [f["title"] for f in c.get(base, params={"q": "zelle"}).json()["items"]] == ["Pagos Zelle sin factura"]
    assert all(f["status"] == "open" for f in c.get(base, params={"status": "open"}).json()["items"])
    assert c.get(f"{base}/{high[0]['id']}").json()["history"]
    assert c.get(f"{base}/EXC-99").status_code == 404


def test_evidence_pages_cover_every_row_exactly_once(login_as, seeded, store):
    c = login_as("viewer")
    url = f"/api/v1/cases/{seeded['case_id']}/evidence"
    seen, cursor = [], None
    while True:
        body = c.get(url, params={"limit": 3, **({"cursor": cursor} if cursor else {})}).json()
        seen += [e["path"] for e in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    expected = [e["path"] for e in store.list_evidence(seeded["case_id"])]
    assert sorted(seen) == sorted(expected) and len(seen) == len(set(seen))


def test_evidence_limit_is_clamped(login_as, seeded):
    c = login_as("viewer")
    url = f"/api/v1/cases/{seeded['case_id']}/evidence"
    assert len(c.get(url, params={"limit": 100000}).json()["items"]) <= 500
    assert len(c.get(url, params={"limit": -5}).json()["items"]) == 1


def test_evidence_stats_add_up_to_the_total(login_as, seeded):
    s = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/evidence/stats").json()
    assert sum(v for k, v in s["statuses"].items() if k != "total") == s["statuses"]["total"]
    assert sum(s["blocks"].values()) == s["statuses"]["total"]


def test_timeline_is_newest_first(login_as, seeded):
    items = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/timeline").json()["items"]
    stamps = [e["ts"] for e in items]
    assert stamps and stamps == sorted(stamps, reverse=True)


def test_criteria_and_research_lists(login_as, seeded, store):
    c = login_as("viewer")
    crit = c.get(f"/api/v1/cases/{seeded['case_id']}/criteria").json()["items"]
    assert [x["id"] for x in crit] == [x["id"] for x in store.list_criteria(seeded["case_id"])]
    assert c.get(f"/api/v1/cases/{seeded['case_id']}/research").json()["items"] == []


def test_case_folder_with_accents_and_spaces_round_trips(login_as, store, gr_env):
    from plugins.ghost_recon.core import service
    folder = gr_env / "Caso Logística Norte"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto ñ.txt").write_text("x", encoding="utf-8")
    case_id = service.open_case(store, str(folder), name="Logística Norte")["case"]["id"]
    c = login_as("viewer")
    d = c.get(f"/api/v1/cases/{case_id}").json()
    assert d["case"]["name"] == "Logística Norte" and d["case"]["root_path"].endswith("Caso Logística Norte")
    paths = [e["path"] for e in c.get(f"/api/v1/cases/{case_id}/evidence", params={"q": "ñ"}).json()["items"]]
    assert paths == ["Bancos/extracto ñ.txt"]


def test_audit_log_is_admin_only(login_as):
    assert login_as("viewer").get("/api/v1/system/audit-log").status_code == 403
    items = login_as("admin").get("/api/v1/system/audit-log").json()["items"]
    assert any(e["action"] == "login" for e in items)


def test_doctor_reports_core_and_console_checks(login_as):
    body = login_as("viewer").get("/api/v1/system/doctor").json()
    names = {c["check"] for c in body["checks"]}
    assert {"database", "approvals.single_query_mode"} <= names
    assert body["console"]["port"] > 0
