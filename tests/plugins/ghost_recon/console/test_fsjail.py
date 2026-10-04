"""Folder jail: only paths inside case_roots, never via '..', UNC, relative paths, symlinks or other drives."""
import ctypes
import hashlib
import os
from pathlib import Path

import pytest

from plugins.ghost_recon.console import fsjail
from plugins.ghost_recon.console.fsjail import FsJailError
from plugins.ghost_recon.core import service

AUDITS = "GhostRecon_Audits"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "Raiz"
    (r / "Caso A" / "Bancos").mkdir(parents=True)
    (r / "Caso A" / "Bancos" / "extracto.txt").write_text("x", encoding="utf-8")
    (r / "Nueva B").mkdir()
    for i in range(3):
        (r / "Nueva B" / f"f{i}.csv").write_text("x", encoding="utf-8")
    (r / ".oculta").mkdir()
    return r


def _code(fn, *args, **kwargs):
    with pytest.raises(FsJailError) as err:
        fn(*args, **kwargs)
    return err.value.code


def test_only_absolute_paths_inside_a_root_resolve(root, tmp_path):
    roots = fsjail.configured_roots([str(root)])
    assert fsjail.resolve(str(root / "Caso A"), roots) == (root / "Caso A").resolve()
    outside = tmp_path / "fuera"
    outside.mkdir()
    assert _code(fsjail.resolve, str(outside), roots) == "outside_roots"
    assert _code(fsjail.resolve, str(root / "no-existe"), roots) == "outside_roots"
    assert _code(fsjail.resolve, str(root / "Caso A" / ".." / "Nueva B"), roots) == "bad_path"  # even inside
    assert _code(fsjail.resolve, "Caso A", roots) == "bad_path"
    assert _code(fsjail.resolve, "", roots) == "bad_path"
    assert _code(fsjail.resolve, str(root), []) == "outside_roots"


def test_configured_roots_skip_missing_and_repeated_entries(root, tmp_path):
    assert fsjail.configured_roots([str(root), str(tmp_path / "no-existe"), str(root)]) == [root.resolve()]


@pytest.mark.platforms("posix")
def test_symlink_escaping_a_root_is_rejected_and_not_listed(root, tmp_path, store):
    secret = tmp_path / "secreto"
    secret.mkdir()
    os.symlink(secret, root / "enlace", target_is_directory=True)
    roots = fsjail.configured_roots([str(root)])
    assert _code(fsjail.resolve, str(root / "enlace"), roots) == "outside_roots"
    names = [i["name"] for i in fsjail.list_dir(str(root), roots, store=store, audits_dirname=AUDITS)["items"]]
    assert "enlace" not in names


@pytest.mark.platforms("posix")
def test_a_context_md_that_links_outside_the_roots_is_not_read(root, tmp_path, store):
    secret = tmp_path / "secreto.md"
    secret.write_text("no", encoding="utf-8")
    os.symlink(secret, root / "Nueva B" / "context.md")
    roots = fsjail.configured_roots([str(root)])
    info = fsjail.inspect(str(root / "Nueva B"), roots, store=store, audits_dirname=AUDITS, defaults={})
    assert info["context"] is None


@pytest.mark.platforms("windows")
def test_unc_paths_and_other_drives_are_rejected(root):
    roots = fsjail.configured_roots([str(root)])
    assert _code(fsjail.resolve, r"\\localhost\c$\Windows", roots) == "outside_roots"
    other = next((f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                  if d != root.drive[0].upper() and Path(f"{d}:\\").exists()), "Z:\\")
    assert _code(fsjail.resolve, other, roots) == "outside_roots"


@pytest.mark.platforms("windows")
def test_windows_hidden_folders_are_not_listed(root, store):
    hidden = root / "Sistema"
    hidden.mkdir()
    assert ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2)  # FILE_ATTRIBUTE_HIDDEN
    roots = fsjail.configured_roots([str(root)])
    names = [i["name"] for i in fsjail.list_dir(str(root), roots, store=store, audits_dirname=AUDITS)["items"]]
    assert "Sistema" not in names and "Caso A" in names


def test_listing_marks_cases_counts_files_and_hides_results_and_hidden(root, store):
    case = service.open_case(store, str(root / "Caso A"), name="Caso A")["case"]
    roots = fsjail.configured_roots([str(root)])
    listing = fsjail.list_dir(str(root), roots, store=store, audits_dirname=AUDITS)
    items = {i["name"]: i for i in listing["items"]}
    assert set(items) == {"Caso A", "Nueva B"}
    assert items["Caso A"]["case"]["id"] == case["id"] and items["Nueva B"]["case"] is None
    assert items["Nueva B"]["files"] == 3 and not items["Nueva B"]["capped"]
    inside = fsjail.list_dir(items["Caso A"]["path"], roots, store=store, audits_dirname=AUDITS)
    assert [i["name"] for i in inside["items"]] == ["Bancos"]  # the results folder is not evidence
    assert [c["path"] for c in inside["breadcrumb"]] == [str(root.resolve()), items["Caso A"]["path"]]
    assert inside["parent"] == str(root.resolve()) and listing["parent"] is None


def test_search_is_bounded_in_depth_results_and_time(root):
    (root / "n1" / "n2" / "n3" / "objetivo-4" / "n5" / "objetivo-6").mkdir(parents=True)
    for i in range(fsjail.MAX_SEARCH_RESULTS + 5):
        (root / "Nueva B" / f"lote-{i:03d}").mkdir()
    roots = fsjail.configured_roots([str(root)])
    assert [i["name"] for i in fsjail.search("objetivo", roots)["items"]] == ["objetivo-4"]  # depth 4 is the limit
    many = fsjail.search("lote", roots)
    assert len(many["items"]) == fsjail.MAX_SEARCH_RESULTS and many["truncated"]
    ticks = iter(range(0, 1000, 2))
    slow = fsjail.search("lote", roots, clock=lambda: next(ticks))
    assert slow["timed_out"] and len(slow["items"]) < fsjail.MAX_SEARCH_RESULTS
    assert _code(fsjail.search, "a", roots) == "bad_query"


def test_inspect_counts_types_warns_and_hashes_the_context(root, store):
    folder = root / "Nueva B"
    for i in range(fsjail.MANY_IMAGES):
        (folder / f"foto{i}.png").write_bytes(b"\x89PNG")
    (folder / "lote.zip").write_bytes(b"PK")
    original = "Objetivo: conciliar ñ.\n".encode("utf-8")
    (folder / "context.md").write_bytes(original)
    roots = fsjail.configured_roots([str(root)])
    info = fsjail.inspect(str(folder), roots, store=store, audits_dirname=AUDITS,
                          defaults={"currency": "USD", "lang": "es"})
    assert info["files"] == sum(t["count"] for t in info["by_type"]) == 3 + fsjail.MANY_IMAGES + 2
    assert info["zips"] == 1 and info["images"] == fsjail.MANY_IMAGES
    assert info["context"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert {w["code"] for w in info["warnings"]} == {"many_images"}
    assert info["suggested_command"] == "new-open-case" and info["case"] is None
    assert info["results_root"] == str(folder.resolve() / AUDITS)
    assert info["defaults"] == {"name": "Nueva B", "currency": "USD", "lang": "es"}


def test_inspect_of_a_sealed_case_suggests_rerun_and_flags_active_jobs(seeded, case_root, store):
    roots = fsjail.configured_roots([str(case_root)])
    folder = str(seeded["root"].resolve())
    info = fsjail.inspect(folder, roots, store=store, audits_dirname=AUDITS, defaults={},
                          active_jobs=[{"id": 7, "folder": folder}])
    assert info["case"]["id"] == seeded["case_id"] and info["case"]["sealed"] == 1
    assert info["suggested_command"] == "rerun-case" and info["active_jobs"] == [7]
    assert {"sealed_case", "active_job"} <= {w["code"] for w in info["warnings"]}


@pytest.mark.platforms("windows")
def test_directory_junctions_escaping_root_are_not_listed_or_walked(root, tmp_path, store):
    """Windows junctions can point outside the root; they must not leak folder names, paths, or file counts."""
    import subprocess
    secret = tmp_path / "secreto"
    secret.mkdir()
    (secret / "hidden.txt").write_text("x", encoding="utf-8")
    junction = root / "Nueva B" / "junction_to_secret"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(secret)], check=True)
    roots = fsjail.configured_roots([str(root)])
    # Junction should not be listed
    names = [i["name"] for i in fsjail.list_dir(str(root / "Nueva B"), roots, store=store, audits_dirname=AUDITS)["items"]]
    assert "junction_to_secret" not in names
    # Junction should not be found by search
    results = fsjail.search("secret", roots)
    assert not any(i["name"] == "secreto" for i in results["items"])
    # Junction's files should not be counted in Nueva B
    info = fsjail.inspect(str(root / "Nueva B"), roots, store=store, audits_dirname=AUDITS, defaults={})
    assert info["files"] == 3  # only the original 3 .csv files, not the hidden.txt from junction


@pytest.mark.platforms("posix")
def test_symlinked_files_are_not_counted_or_stat_d(root, tmp_path, store):
    """Symlinked files pointing outside the root must not leak their size or existence."""
    secret_file = tmp_path / "secreto.txt"
    secret_file.write_bytes(b"x" * 10000)
    link = root / "Nueva B" / "link_to_secret.txt"
    os.symlink(secret_file, link)
    roots = fsjail.configured_roots([str(root)])
    # File count should not include the symlinked file (only 3 csv files, not 3 + 1)
    info = fsjail.inspect(str(root / "Nueva B"), roots, store=store, audits_dirname=AUDITS, defaults={})
    assert info["files"] == 3  # only the 3 .csv files, symlink not counted
    assert info["size"] == 3  # 1 byte per .csv file, symlink's 10000 bytes not counted
