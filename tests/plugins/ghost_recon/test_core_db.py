"""Store contract: ids continue the case series, history is kept, export/import round-trips."""
from plugins.ghost_recon.core.db import Store, connect


def _store():
    return Store(connect(":memory:"))


def _case(st, root="/cases/x"):
    return st.create_case(id="GRC-x-20260101", slug="x", name="X", root_path=root, audits_dir="GhostRecon_Audits")


def test_finding_ids_continue_series_and_keep_history():
    st = _store(); c = _case(st)
    a = st.create_audit(id="GRC-x-20260101/A01", case_id=c["id"], seq=1, kind="initial", folder="/out/A01")
    f1 = st.upsert_finding(c["id"], a["id"], {"kind": "exception", "title": "t1"})
    f2 = st.upsert_finding(c["id"], a["id"], {"kind": "exception", "title": "t2"})
    q1 = st.upsert_finding(c["id"], a["id"], {"kind": "question", "title": "q"})
    assert (f1["id"], f2["id"], q1["id"]) == ("EXC-01", "EXC-02", "Q-01")
    b = st.create_audit(id="GRC-x-20260101/A02", case_id=c["id"], seq=2, kind="rerun", folder="/out/A02")
    f3 = st.upsert_finding(c["id"], b["id"], {"kind": "exception", "title": "t3"})
    assert f3["id"] == "EXC-03"
    upd = st.upsert_finding(c["id"], b["id"], {"id": "EXC-01", "kind": "exception", "status": "closed"})
    assert upd["status"] == "closed" and len(upd["history"]) == 2 and upd["history"][1]["audit_id"] == b["id"]
    assert upd["history"][1]["change"] == {"status": "closed"}


def test_criteria_series_is_independent_from_findings():
    st = _store(); c = _case(st)
    c1 = st.add_criterion(c["id"], None, "mgmt", "rule one")
    c2 = st.add_criterion(c["id"], None, "mgmt", "rule two")
    assert (c1["id"], c2["id"]) == ("CRIT-01", "CRIT-02")


def test_next_audit_seq_is_per_prefix():
    st = _store(); c = _case(st)
    st.create_audit(id="GRC-x-20260101/A01", case_id=c["id"], seq=1, kind="initial", folder="/o/A01")
    st.create_audit(id="GRC-x-20260101/R01", case_id=c["id"], seq=1, kind="review", folder="/o/R01")
    assert st.next_audit_seq(c["id"], "A") == 2
    assert st.next_audit_seq(c["id"], "R") == 2


def test_export_import_round_trip():
    st = _store(); c = _case(st)
    a = st.create_audit(id="GRC-x-20260101/A01", case_id=c["id"], seq=1, kind="initial", folder="/o/A01")
    st.upsert_evidence(c["id"], [{"path": "a.pdf", "filename": "a.pdf", "sha256": "h1", "first_audit_id": a["id"]}])
    st.upsert_finding(c["id"], a["id"], {"kind": "anomaly", "title": "dup"})
    st.add_criterion(c["id"], a["id"], "mgmt", "x")
    data = st.export_case(c["id"])
    st2 = _store()
    st2.import_case(data)
    assert st2.get_case(c["id"])["name"] == "X"
    assert [e["sha256"] for e in st2.list_evidence(c["id"])] == ["h1"]
    assert st2.list_findings(c["id"])[0]["id"] == "ANO-01"
    assert st2.list_criteria(c["id"])[0]["id"] == "CRIT-01"


def test_known_hashes_can_exclude_current_audit():
    st = _store(); c = _case(st)
    st.upsert_evidence(c["id"], [{"path": "a", "filename": "a", "sha256": "h1", "first_audit_id": "X/A01"},
                                 {"path": "b", "filename": "b", "sha256": "h2", "first_audit_id": "X/A02"}])
    assert set(st.known_hashes(c["id"])) == {"h1", "h2"}
    assert set(st.known_hashes(c["id"], exclude_audit_id="X/A02")) == {"h1"}
