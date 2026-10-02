"""Inventory (incl. ZIP members), block classification, dedupe statuses, sealing invariants."""
import zipfile

import pytest

from plugins.ghost_recon.core import casefolder as cf


def _mk(root, rel, content=b"x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def test_inventory_hashes_files_and_zip_members_and_skips_outputs(tmp_path):
    _mk(tmp_path, "Bancos/extracto_2026-01.pdf", b"stmt")
    _mk(tmp_path, "GhostRecon_Audits/A01/x.txt", b"out")
    _mk(tmp_path, ".DS_Store", b"noise")
    with zipfile.ZipFile(tmp_path / "lote.zip", "w") as z:
        z.writestr("inner/factura_1.csv", "a,b\n")
    rows = cf.inventory(tmp_path)
    paths = sorted(r.path for r in rows)
    assert paths == ["Bancos/extracto_2026-01.pdf", "lote.zip", "lote.zip::inner/factura_1.csv"]
    by = {r.path: r for r in rows}
    assert by["Bancos/extracto_2026-01.pdf"].block == "banking"
    assert by["lote.zip::inner/factura_1.csv"].block == "commercial" and by["lote.zip::inner/factura_1.csv"].zip_member
    assert len(by["lote.zip"].sha256) == 64 and len(by["lote.zip"].md5) == 32


@pytest.mark.parametrize("rel,ext,block", [
    ("Chase/statement_jan.pdf", ".pdf", "banking"),
    ("Ventas/invoice_001.pdf", ".pdf", "commercial"),
    ("Flete/DHL_awb.pdf", ".pdf", "supply"),
    ("Socios/contrato_licencia.pdf", ".pdf", "related_parties"),
    ("WhatsApp/chat.txt", ".txt", "correspondence"),
    ("scan/IMG_001.jpg", ".jpg", "ocr_vision"),
    ("misc/notas.docx", ".docx", "other"),
])
def test_classify_block(rel, ext, block):
    assert cf.classify_block(rel, ext) == block


def test_dedupe_assigns_dup_prior_internal_and_new(tmp_path):
    a = _mk(tmp_path, "a.txt", b"same"); b = _mk(tmp_path, "b.txt", b"same"); c = _mk(tmp_path, "c.txt", b"other")
    rows = cf.inventory(tmp_path)
    known = {cf.sha256_file(c): "old/c.txt"}
    res = cf.dedupe(rows, known, root=tmp_path, audit_id="X/A02")
    st = {r.path: r.status for r in res["rows"]}
    assert st["a.txt"] == "NEW" and st["b.txt"] == "DUP_INTERNAL" and st["c.txt"] == "DUP_PRIOR"
    assert res["stats"]["NEW"] == 1 and res["stats"]["DUP_INTERNAL"] == 1 and res["stats"]["DUP_PRIOR"] == 1
    assert [r.first_audit_id for r in res["rows"] if r.path == "a.txt"] == ["X/A02"]


def test_dedupe_first_audit_ignores_known(tmp_path):
    _mk(tmp_path, "a.txt", b"q")
    rows = cf.inventory(tmp_path)
    res = cf.dedupe(rows, {rows[0].sha256: "elsewhere"}, first_audit=True, audit_id="X/A01")
    assert res["rows"][0].status == "NEW"


def test_content_fingerprint_detects_redownloaded_text(tmp_path):
    a = _mk(tmp_path, "a.txt", b"Saldo  1.000\n\nCierre"); b = _mk(tmp_path, "b.txt", b"saldo 1.000 cierre")
    assert cf.text_fingerprint(a) == cf.text_fingerprint(b)


def test_seal_verify_and_guard(tmp_path):
    folder = cf.create_audit_folder(tmp_path / "GhostRecon_Audits", "A01_2026-01-01", "initial", {"audit_id": "X/A01"})
    assert (folder / cf.MANIFEST_FILE).exists() and (folder / "06_Report").is_dir()
    cf.write_text(folder, "06_Report/report.md", "hola")
    rec = cf.seal(folder, "X/A01")
    assert rec["file_count"] == 2 and len(rec["manifest_sha256"]) == 64
    assert cf.verify_seal(folder)["ok"]
    with pytest.raises(cf.SealedAuditError):
        cf.write_text(folder, "06_Report/other.md", "x")
    with pytest.raises(cf.SealedAuditError):
        cf.seal(folder, "X/A01")
    (folder / "06_Report" / "report.md").write_text("tampered", encoding="utf-8")
    v = cf.verify_seal(folder)
    assert not v["ok"] and v["modified"] == ["06_Report/report.md"]


def test_review_folder_lives_under_reviews(tmp_path):
    folder = cf.create_audit_folder(tmp_path / "out", "R01_2026-01-01", "review", {})
    assert folder.parent.name == "reviews" and (folder / "roles").is_dir()
