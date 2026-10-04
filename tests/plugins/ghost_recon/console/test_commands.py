"""Order table: each order preloads its skill with the -q text that skill expects, options are validated, the
operator's notes become a combined context file beside the results (never among the evidence), and the copyable
command round-trips through the target shell."""
import hashlib
import json
import shlex
from pathlib import Path

import pytest

from plugins.ghost_recon.console.commands import (CONSOLE_DIR, ORDERS, SOURCE_TAG, CommandError, LaunchRequest,
                                                  display_command, plan, write_combined_context)
from plugins.ghost_recon.console.fsjail import configured_roots
from plugins.ghost_recon.core import service

AUDITS = "GhostRecon_Audits"


def hermes(args):
    return ["HERMES", *args]


@pytest.fixture
def plan_for(store, case_root):
    roots = configured_roots([str(case_root)])

    def _plan(command, folder, **fields):
        return plan(LaunchRequest(command=command, folder=str(folder), **fields), store=store, roots=roots,
                    audits_dirname=AUDITS, username="jean", profile_args=["-p", "default"], hermes=hermes)
    return _plan


@pytest.fixture
def fresh(case_root):
    folder = case_root / "Caso Logística Norte"
    (folder / "Bancos").mkdir(parents=True)
    (folder / "Bancos" / "extracto ñ.txt").write_text("x", encoding="utf-8")
    return folder


@pytest.mark.parametrize("command", sorted(ORDERS))
def test_each_order_preloads_its_skill_and_streams_json(plan_for, seeded, fresh, command):
    p = plan_for(command, fresh if command == "new-open-case" else seeded["root"])
    argv = p["argv"]
    assert argv[0] == "HERMES" and all(isinstance(a, str) for a in argv)
    assert argv[argv.index("--skills") + 1] == ORDERS[command].skill
    assert argv.index("chat") > argv.index("--skills") and argv[1:3] == ["-p", "default"]
    assert argv[argv.index("-q") + 1] == p["query"] and p["query"].startswith(f"/{command} ")
    assert argv[argv.index("--format") + 1] == "stream-json" and argv[argv.index("--source") + 1] == SOURCE_TAG


def test_folder_with_spaces_and_accents_is_quoted_intact(plan_for, fresh):  # Review Focus 2
    p = plan_for("new-open-case", fresh)
    assert p["folder"] == str(fresh.resolve()) and f'"{fresh.resolve()}"' in p["query"]


@pytest.mark.platforms("posix")
def test_a_folder_with_a_double_quote_is_rejected(plan_for, case_root):  # Review Focus 2
    folder = case_root / 'Caso "raro"'
    folder.mkdir()
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", folder)
    assert err.value.status == 422


@pytest.mark.parametrize("field,value", [("currency", "US"), ("currency", "usd1"), ("lang", "fr"),
                                         ("name", "a\nb"), ("name", 'Caso "x"'), ("name", "x" * 121)])
def test_invalid_options_are_422(plan_for, fresh, field, value):
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", fresh, **{field: value})
    assert (err.value.status, err.value.code) == (422, "invalid_argument")


def test_valid_options_reach_the_query_normalized(plan_for, fresh):
    p = plan_for("new-open-case", fresh, name="Logística Norte", currency="eur", lang="EN")
    assert '--name "Logística Norte"' in p["query"] and "--currency EUR" in p["query"] and "--lang en" in p["query"]
    assert p["args"]["currency"] == "EUR"


def test_a_sealed_case_refuses_a_new_audit_and_points_to_rerun(plan_for, seeded):
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", seeded["root"])
    assert (err.value.status, err.value.code) == (409, "use_rerun") and "Re-run" in err.value.message


def test_rerun_needs_a_case_and_review_needs_a_sealed_audit(plan_for, fresh, store):
    with pytest.raises(CommandError) as err:
        plan_for("rerun-case", fresh)
    assert err.value.code == "not_a_case"
    service.open_case(store, str(fresh))
    with pytest.raises(CommandError) as err:
        plan_for("review-case", fresh)
    assert err.value.code == "no_sealed_audit"
    assert plan_for("rerun-case", fresh)["case"]["source"] == "db"


def test_folders_outside_the_roots_are_403_and_no_roots_is_409(plan_for, gr_env, store, fresh):
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", gr_env / "db")
    assert (err.value.status, err.value.code) == (403, "outside_roots")
    with pytest.raises(CommandError) as err:
        plan(LaunchRequest("new-open-case", str(fresh)), store=store, roots=[], audits_dirname=AUDITS,
             username="jean", profile_args=[], hermes=hermes)
    assert (err.value.status, err.value.code) == (409, "no_case_roots") and "case_roots" in err.value.message


def test_without_notes_the_original_context_or_nothing_is_passed(plan_for, fresh):
    assert plan_for("new-open-case", fresh)["context_file"] == ""
    (fresh / "context.md").write_bytes(b"Objetivo: conciliar.\n")
    p = plan_for("new-open-case", fresh)
    assert p["context_file"] == str(fresh.resolve() / "context.md") and f'"{p["context_file"]}"' in p["query"]


def test_combined_context_has_the_literal_original_its_hash_and_signed_notes(plan_for, fresh):
    original = "Objetivo: conciliar ñ.\n\nLínea 2\n".encode("utf-8")
    (fresh / "context.md").write_bytes(original)
    p = plan_for("new-open-case", fresh, notes="El socio B aportó USD 5 000 en marzo.")
    path = write_combined_context(p, "jean", "2026-10-03T10:00:00Z")
    text = path.read_bytes().decode("utf-8")
    assert original.decode("utf-8") in text and hashlib.sha256(original).hexdigest() in text
    assert "El socio B aportó USD 5 000 en marzo." in text and "jean" in text and "CRIT-nn" in text
    assert str(path) == p["context_file"] and f'"{path}"' in p["query"]
    assert path.parent == fresh.resolve() / AUDITS / CONSOLE_DIR  # beside the results, never among the evidence


def test_the_combined_file_name_is_stable_so_the_preview_is_exact(plan_for, fresh):
    a = plan_for("new-open-case", fresh, notes="nota")
    b = plan_for("new-open-case", fresh, notes="nota")
    c = plan_for("new-open-case", fresh, notes="otra nota")
    assert a["argv"] == b["argv"] and a["context_file"] != c["context_file"]


def test_a_context_md_changed_between_the_plan_and_the_write_is_refused(plan_for, fresh):
    (fresh / "context.md").write_bytes(b"uno\n")
    p = plan_for("new-open-case", fresh, notes="nota")
    (fresh / "context.md").write_bytes(b"dos\n")
    with pytest.raises(CommandError) as err:
        write_combined_context(p, "jean", "2026-10-03T10:00:00Z")
    assert (err.value.status, err.value.code) == (409, "context_changed")


def test_a_mirror_only_case_never_takes_its_results_root_from_case_json(plan_for, fresh, gr_env):
    """case.json is folder content, not DB state: its ``out_dir`` must not decide where the console writes or what
    reaches the ``-q`` text."""
    hostile = str(gr_env / "elsewhere" / 'inj"ected')
    mirror = {"case": {"id": "GRC-espejo", "name": "Espejo", "meta": {"out_dir": hostile}}, "audits": []}
    (fresh / AUDITS).mkdir()
    (fresh / AUDITS / "case.json").write_text(json.dumps(mirror), encoding="utf-8")
    p = plan_for("rerun-case", fresh, notes="nota")
    assert p["case"]["source"] == "case.json"
    assert p["results_root"] == str(fresh.resolve() / AUDITS)
    assert Path(p["context_file"]).parent == fresh.resolve() / AUDITS / CONSOLE_DIR
    assert p["query"].count('"') % 2 == 0 and hostile not in p["query"]


def test_out_is_quoted_becomes_the_results_root_and_is_never_the_evidence(plan_for, fresh, case_root, gr_env):
    out = case_root / "Salidas Logística ñ"
    out.mkdir()
    p = plan_for("new-open-case", fresh, out=str(out), notes="nota")
    assert f'--out "{out.resolve()}"' in p["query"] and p["results_root"] == str(out.resolve())
    assert Path(p["context_file"]).parent == out.resolve() / CONSOLE_DIR
    (gr_env / "fuera").mkdir()
    with pytest.raises(CommandError) as err:
        plan_for("new-open-case", fresh, out=str(gr_env / "fuera"))
    assert (err.value.status, err.value.code) == (403, "outside_roots")
    for inside in (fresh, fresh / "Bancos"):
        with pytest.raises(CommandError) as err:
            plan_for("new-open-case", fresh, out=str(inside))
        assert (err.value.status, err.value.code) == (422, "out_in_evidence") and "evidencia" in err.value.message


def test_review_notes_travel_on_a_second_line(plan_for, seeded):
    p = plan_for("review-case", seeded["root"], notes="Reunión con el abogado el lunes.")
    first, second = p["query"].split("\n")
    assert first == f'/review-case "{seeded["root"].resolve()}"' and p["context_file"] in second


def test_display_command_round_trips_through_a_posix_shell():
    argv = ["/opt/h/.hermes/bin/hermes", "-p", "default", "chat", "-q", '/new-open-case "/casos/Caso ñ" --name "A B"']
    assert shlex.split(display_command(argv, windows=False)) == argv


@pytest.mark.platforms("windows")
def test_display_command_round_trips_through_windows_argv_parsing():
    import ctypes
    argv = ["C:\\h\\python.exe", "-q", '/new-open-case "C:\\Casos\\Caso ñ" --name "A B"']
    count = ctypes.c_int()
    to_argv = ctypes.windll.shell32.CommandLineToArgvW
    to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    parsed = to_argv(display_command(argv, windows=True), ctypes.byref(count))
    assert [parsed[i] for i in range(count.value)] == argv
