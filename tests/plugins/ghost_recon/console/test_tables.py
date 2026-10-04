"""Case tables as CSV/XLSX: the rows and filters of the JSON endpoints, text Excel opens intact (accents, commas,
line breaks) and never runs as a formula, and the Ghost Recon metadata of the pack."""
import csv
import io
import zipfile

import pytest

from plugins.ghost_recon.console import tables
from plugins.ghost_recon.core import ENGINE, service
from plugins.ghost_recon.core.reports.pack import scan_tool_names

TRICKY = 'Pago "Zelle", socio B — señal de alerta\nsegunda línea; ñandú'
FORMULA = '=HYPERLINK("http://ejemplo.invalid","clic")'


def _csv_rows(response):
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM: Excel reads the file as UTF-8
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))


@pytest.fixture
def tricky(store, seeded):
    """Findings whose text breaks naive CSV: quotes, commas, a line break, accents, a formula and a negative amount."""
    service.upsert_findings(store, seeded["a2"], [
        {"kind": "finding", "title": TRICKY, "counterparty": "Socio B, S.A.", "risk": "high", "amount": -1500.0},
        {"kind": "anomaly", "title": FORMULA, "risk": "low"},
    ])
    return {f["title"]: f for f in store.list_findings(seeded["case_id"])}


def test_csv_round_trips_accents_commas_quotes_and_line_breaks(login_as, seeded, tricky):
    r = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/findings.csv")
    assert r.headers["content-type"].startswith("text/csv") and ".csv" in r.headers["content-disposition"]
    row = next(x for x in _csv_rows(r) if x["ID"] == tricky[TRICKY]["id"])
    assert row["Título"] == TRICKY and row["Contraparte"] == "Socio B, S.A."
    assert float(row["Importe"]) == -1500.0  # a number keeps its sign


def test_text_that_looks_like_a_formula_stays_text(login_as, seeded, tricky):
    c = login_as("viewer")
    row = next(x for x in _csv_rows(c.get(f"/api/v1/cases/{seeded['case_id']}/findings.csv"))
               if x["ID"] == tricky[FORMULA]["id"])
    assert row["Título"] == "'" + FORMULA
    assert tables.csv_cell("-12.50") == "-12.50" and tables.csv_cell("@SUM(A1)") == "'@SUM(A1)"


@pytest.mark.parametrize("table,params,key,json_key", [
    ("findings", {"risk": "high"}, "ID", "id"),
    ("findings", {"status": "open", "q": "zelle"}, "ID", "id"),
    ("evidence", {"status": "NEW", "q": "bancos"}, "Ruta", "path"),
    ("evidence", {"audit": "A02"}, "Ruta", "path"),
    ("timeline", {}, "Evento", "event_type"),
    ("criteria", {}, "ID", "id"),
])
def test_a_table_file_holds_exactly_the_rows_of_its_json_endpoint(login_as, seeded, table, params, key, json_key):
    c = login_as("viewer")
    base = f"/api/v1/cases/{seeded['case_id']}/{table}"
    shown = c.get(base, params={**params, "limit": 500}).json()["items"]
    exported = _csv_rows(c.get(f"{base}.csv", params=params))
    assert [r[key] for r in exported] == [str(i[json_key]) for i in shown]


def test_xlsx_opens_with_the_ghost_recon_metadata_and_no_live_formula(login_as, seeded, tricky, tmp_path):
    openpyxl = pytest.importorskip("openpyxl", reason="plugin python_dependency, not in the core test group")
    r = login_as("viewer").get(f"/api/v1/cases/{seeded['case_id']}/findings.xlsx")
    assert r.status_code == 200 and r.headers["content-type"] == tables.XLSX_MEDIA
    path = tmp_path / "t.xlsx"
    path.write_bytes(r.content)
    wb = openpyxl.load_workbook(path)
    assert "Ghost Recon" in wb.properties.creator and "Acme Demo" in wb.properties.title
    with zipfile.ZipFile(path) as zf:
        assert f"<Application>{ENGINE}</Application>" in zf.read("docProps/app.xml").decode("utf-8")
    assert scan_tool_names([path]) == {}  # no library names, like the pack
    cells = {c.value: c for row in wb.active.iter_rows(min_row=2) for c in row if isinstance(c.value, str)}
    assert cells[FORMULA].data_type == "s" and cells[TRICKY].value == TRICKY


def test_xlsx_without_openpyxl_is_a_clear_503_and_csv_still_works(login_as, seeded, monkeypatch):
    def missing():
        raise tables.XlsxUnavailable("Falta openpyxl")
    monkeypatch.setattr(tables, "load_openpyxl", missing)
    c = login_as("viewer")
    r = c.get(f"/api/v1/cases/{seeded['case_id']}/criteria.xlsx")
    assert r.status_code == 503 and r.json()["error"]["code"] == "xlsx_unavailable"
    assert c.get(f"/api/v1/cases/{seeded['case_id']}/criteria.csv").status_code == 200


def test_table_files_need_a_login_a_known_table_and_are_audited(login_as, client, seeded):
    url = f"/api/v1/cases/{seeded['case_id']}"
    assert client.get(f"{url}/findings.csv").status_code == 401
    c = login_as("viewer")
    assert c.get(f"{url}/passwords.csv").status_code == 404 and c.get(f"{url}/findings.pdf").status_code == 404
    assert c.get("/api/v1/cases/GRC-nope-20260101/findings.csv").status_code == 404
    c.get(f"{url}/findings.csv", params={"risk": "high"})
    entry = next(e for e in login_as("admin").get("/api/v1/system/audit-log").json()["items"]
                 if e["action"] == "table_export")
    assert entry["username"] == "vera" and entry["detail"]["filters"] == {"risk": "high"}
