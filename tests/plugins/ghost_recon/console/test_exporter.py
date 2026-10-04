"""The results ZIP (spec §11): the manifest matches the archive and the archive its sidecar, the evidence never goes
in (symlinks and junctions included), a broken seal blocks naming the file, unsealed audits only as DRAFT and never
while a job is active, and a sealed file that changes during the build fails it."""
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.ghost_recon.console import exporter
from plugins.ghost_recon.console.exporter import ExportError

NOW = datetime(2026, 10, 4, 15, 30, tzinfo=timezone.utc)


def _select(store, seeded, **kw):
    options = {"scope": "case", "seq": None, "include_unsealed": False, "busy": False, **kw}
    return exporter.select(store, store.get_case(seeded["case_id"]), **options)


def _build(store, cstore, seeded, dest, export_id=1, **kw):
    return exporter.build(store, cstore, _select(store, seeded, **kw), export_id=export_id, exported_by="vera",
                          dest_dir=dest, now=NOW)


@pytest.fixture
def dest(tmp_path):
    """Where the archives go (tmp_path itself also holds the test DB and the case root)."""
    path = tmp_path / "exports"
    path.mkdir()
    return path


def _open(result):
    zf = zipfile.ZipFile(result["path"])
    return zf, json.loads(zf.read(exporter.MANIFEST_NAME))


def test_the_manifest_lists_every_packed_file_and_the_zip_matches_its_sidecar(store, cstore, seeded, dest):
    result = _build(store, cstore, seeded, dest)
    zf, manifest = _open(result)
    names = [n for n in zf.namelist() if n != exporter.MANIFEST_NAME]
    assert [f["path"] for f in manifest["files"]] == names
    for f in manifest["files"]:
        data = zf.read(f["path"])
        assert (f["size"], f["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
    digest = hashlib.sha256(Path(result["path"]).read_bytes()).hexdigest()
    sidecar = dest / f"{result['file_name']}.sha256"
    assert result["sha256"] == digest
    assert sidecar.read_bytes() == f"{digest}  {result['file_name']}\n".encode("utf-8")  # sha256sum -c format
    a1 = store.get_audit(seeded["a1"])
    assert [(a["id"], a["state"], a["seal_sha256"]) for a in manifest["audits"]] == [(a1["id"], "SEALED",
                                                                                    a1["seal_sha256"])]
    assert manifest["audits"][0]["verified_at"] and manifest["exported_by"] == "vera"
    assert manifest["generator"].startswith("Ghost Recon Console ") and manifest["export_id"] == 1
    assert [e["seq"] for e in manifest["excluded"]] == ["A02"] and manifest["draft"] is False
    assert result["file_name"] == f"GhostRecon_{store.get_case(seeded['case_id'])['slug']}_case_20261004-1530.zip"
    assert not list(dest.glob("*.part"))


def test_the_evidence_never_enters_the_archive(store, cstore, seeded, dest):
    zf, _ = _open(_build(store, cstore, seeded, dest, include_unsealed=True))
    folders = {Path(store.get_audit(a)["folder"]).name for a in (seeded["a1"], seeded["a2"])}
    allowed = ("case.json", "corpus_inventory.csv", exporter.MANIFEST_NAME, "_console/",
               *(f"{name}/" for name in folders))
    assert all(n.startswith(allowed) for n in zf.namelist())
    evidence = {e["path"] for e in store.list_evidence(seeded["case_id"])}
    assert evidence and not evidence & set(zf.namelist())


@pytest.mark.platforms("posix")
def test_symlinks_inside_the_results_folder_are_never_followed_posix(store, cstore, seeded, dest):
    report_dir = seeded["a2_folder"] / "06_Report"
    os.symlink(seeded["root"] / "Bancos" / "extracto_2026-01.txt", report_dir / "extracto.txt")
    console = seeded["a1_folder"].parent / "_console"
    console.mkdir()
    os.symlink(seeded["root"], console / "evidencia", target_is_directory=True)
    zf, manifest = _open(_build(store, cstore, seeded, dest, include_unsealed=True))
    assert not any(n.endswith("extracto.txt") or "/evidencia" in n for n in zf.namelist())
    assert {(s["path"].rsplit("/", 1)[-1], s["reason"]) for s in manifest["skipped"]} == {
        ("extracto.txt", "symlink"), ("evidencia", "symlink")}


@pytest.mark.platforms("windows")
def test_junctions_inside_the_results_folder_are_never_followed_windows(store, cstore, seeded, dest):
    import _winapi
    console = seeded["a1_folder"].parent / "_console"
    console.mkdir()
    _winapi.CreateJunction(str(seeded["root"] / "Bancos"), str(console / "evidencia"))
    zf, manifest = _open(_build(store, cstore, seeded, dest))
    assert not any("evidencia" in n for n in zf.namelist())
    assert manifest["skipped"] == [{"path": "_console/evidencia", "reason": "symlink"}]


def test_a_results_folder_that_holds_the_evidence_is_refused(store, seeded):
    store.update_case(seeded["case_id"], meta={"out_dir": str(seeded["root"])})
    with pytest.raises(ExportError) as refused:
        _select(store, seeded)
    assert refused.value.code == "results_hold_evidence"


def test_a_broken_seal_blocks_the_export_and_names_the_file(store, cstore, seeded, dest):
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    report.write_text(report.read_text(encoding="utf-8") + "\nalterado", encoding="utf-8")
    with pytest.raises(ExportError) as blocked:
        _build(store, cstore, seeded, dest)
    assert blocked.value.code == "seal_broken" and f"06_Report/{report.name}" in blocked.value.message
    assert list(dest.iterdir()) == []
    assert cstore.get_seal_check(seeded["a1"])["ok"] is False  # the views now show the broken seal too


def test_a_sealed_file_changed_during_the_build_fails_it(store, cstore, seeded, dest, monkeypatch):
    """Review Focus: the file changes after the seal check passed and before it is packed."""
    report = next((seeded["a1_folder"] / "06_Report").glob("*.md"))
    real = exporter.plan_entries

    def tamper_after_check(sel):
        planned = real(sel)
        report.write_bytes(report.read_bytes() + b"\nalterado durante la exportacion")
        return planned

    monkeypatch.setattr(exporter, "plan_entries", tamper_after_check)
    with pytest.raises(ExportError) as failed:
        _build(store, cstore, seeded, dest)
    assert failed.value.code == "seal_broken" and report.name in failed.value.message
    assert list(dest.iterdir()) == []  # no partial archive is left behind


def test_unsealed_audits_only_on_request_and_marked_draft(store, cstore, seeded, dest):
    result = _build(store, cstore, seeded, dest, include_unsealed=True)
    _, manifest = _open(result)
    states = {a["seq"]: (a["state"], a["sealed"], a["seal_sha256"]) for a in manifest["audits"]}
    assert states["A02"] == ("DRAFT", False, None) and states["A01"][0] == "SEALED"
    assert manifest["draft"] is True and "_case-DRAFT_" in result["file_name"]


def test_an_open_audit_never_goes_in_while_a_job_is_active_on_the_case(store, seeded):
    sel = _select(store, seeded, include_unsealed=True, busy=True)
    assert [a["id"] for a in sel.audits] == [seeded["a1"]]
    assert sel.excluded == [{"id": seeded["a2"], "seq": "A02", "reason": "job_running"}]
    with pytest.raises(ExportError) as busy:
        _select(store, seeded, scope="audit", seq="A02", include_unsealed=True, busy=True)
    assert busy.value.code == "job_running"
    with pytest.raises(ExportError) as unsealed:
        _select(store, seeded, scope="audit", seq="A02")
    assert unsealed.value.code == "not_sealed"


def test_accented_file_names_are_stored_as_utf8_and_match_the_manifest(store, cstore, seeded, dest):
    """Review Focus: Spanish names (accents, ñ) must open intact on Windows and macOS."""
    name = "06_Report/Conciliación año 2026 — señal.md"
    (seeded["a2_folder"] / name).write_text("borrador\n", encoding="utf-8")
    zf, manifest = _open(_build(store, cstore, seeded, dest, scope="audit", seq="A02", include_unsealed=True))
    arc = f"{seeded['a2_folder'].name}/{name}"
    assert arc in zf.namelist() and zf.getinfo(arc).flag_bits & 0x800  # the UTF-8 name flag
    assert arc in [f["path"] for f in manifest["files"]]


def test_two_exports_in_the_same_minute_never_share_a_file(store, cstore, seeded, dest):
    """Review Focus: a double click on "Exportar" builds twice within one minute."""
    first = _build(store, cstore, seeded, dest, export_id=1)
    second = _build(store, cstore, seeded, dest, export_id=2)
    assert first["file_name"] != second["file_name"] and Path(first["path"]).is_file()
    assert _open(first)[1]["export_id"] == 1 and _open(second)[1]["export_id"] == 2
    for result in (first, second):
        assert hashlib.sha256(Path(result["path"]).read_bytes()).hexdigest() == result["sha256"]


def test_a_consistent_swap_of_the_seal_and_a_file_between_verify_and_pack_fails(store, cstore, seeded, dest,
                                                                              monkeypatch):
    """The seal file packed must be the one the audit registered, not one re-sealed after the check."""
    folder = seeded["a1_folder"]
    report = next((folder / "06_Report").glob("*.md"))
    real = exporter.verify_seals

    def swap_after_verify(*args, **kw):
        verified = real(*args, **kw)
        report.write_bytes(report.read_bytes() + b"\nreemplazado")
        seal_path = folder / "SEALED.json"
        record = json.loads(seal_path.read_text(encoding="utf-8"))
        record["files"][f"06_Report/{report.name}"] = hashlib.sha256(report.read_bytes()).hexdigest()
        seal_path.write_text(json.dumps(record), encoding="utf-8")
        return verified

    monkeypatch.setattr(exporter, "verify_seals", swap_after_verify)
    with pytest.raises(ExportError) as failed:
        _build(store, cstore, seeded, dest)
    assert failed.value.code == "seal_broken" and "SEALED.json" in failed.value.message
    assert list(dest.iterdir()) == []


def test_a_failure_while_writing_the_sidecar_leaves_no_zip_part_or_sidecar(store, cstore, seeded, dest, monkeypatch):
    real = Path.write_bytes

    def broken_sidecar(self, data):
        if self.name.endswith(".sha256.part"):
            real(self, data[:5])  # a partial sidecar on disk, then the failure
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", broken_sidecar)
    with pytest.raises(OSError):
        _build(store, cstore, seeded, dest)
    assert list(dest.iterdir()) == []
