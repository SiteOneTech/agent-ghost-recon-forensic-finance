"""stream-json → console events: phases follow the tool table, generic tools are grouped, the agent's text is kept
for the summary only, and truncated or failed tool outputs never break the feed."""
import json
import re

from plugins.ghost_recon.console.events import KINDS, PHASES, Normalizer, phase_for

T0 = 1_790_000_000_000
CASE = {"case": {"id": "GRC-acme-20261003", "name": "Acme"}, "created": True, "corpus_files": 214}
AUDIT = {"audit": {"id": "GRC-acme-20261003/A01", "summary": {"evidence_new": 214}}, "folder": "/x/A01"}


def rec(kind, step=0, **fields):
    return {"type": kind, "timestamp": T0 + step * 1000, **fields}


def call(name, args, output, step, *, is_error=False):
    text = output if isinstance(output, str) else json.dumps(output)
    return [rec("tool_use", step, name=name, tool_call_id=f"c{step}", input=args),
            rec("tool_result", step, name=name, tool_call_id=f"c{step}", output=text, duration_ms=3, is_error=is_error)]


def run(records):
    n = Normalizer()
    events = [e for r in records for e in n.feed_line(json.dumps(r))] + n.flush()
    return n, events


def full_audit():
    """A complete /new-open-case run as the parent agent streams it."""
    return [rec("system", 0, subtype="init", model="m", session_id="s-1"),
            *call("gr_case_open", {"folder": "/x"}, CASE, 1),
            *call("gr_audit_start", {"case_id": "GRC-acme-20261003"}, AUDIT, 2),
            *call("read_file", {"path": "/x/context.md"}, "texto", 3),
            *call("gr_criteria_add", {"audit_id": "a", "author": "G", "text": "t"}, {"id": "CRIT-01"}, 4),
            *call("gr_swarm_plan", {"audit_id": "a", "mode": "extraction"},
                  {"mode": "extraction", "tasks": [{}, {}, {}], "waves": 1}, 5),
            *call("delegate_task", {"tasks": [{}, {}]}, "ok", 6),
            *call("delegate_task", {"tasks": [{}]}, "ok", 7),
            *call("gr_finding_upsert", {"audit_id": "a"}, {"findings": [{"id": "EXC-01"}]}, 8),
            *call("gr_research", {"query": "q"}, {"action": "search"}, 9),
            *call("gr_report_build", {"audit_id": "a"}, {"files": [{}, {}], "warnings": []}, 10),
            *call("gr_swarm_plan", {"audit_id": "a", "mode": "validation"}, {"mode": "validation", "tasks": [{}, {}]}, 11),
            *call("delegate_task", {"tasks": [{}, {}]}, "ok", 12),
            *call("gr_run_record", {"audit_id": "a", "kind": "validation", "role": "A"},
                  {"kind": "validation", "status": "done"}, 13),
            *call("gr_audit_seal", {"audit_id": "a"}, {"sealed": True, "file_count": 40}, 14),
            rec("text", 15, text="Resumen "), rec("text", 15, text="final."),
            rec("result", 16, session_id="s-1", exit_code=0, text="Resumen final.",
                tokens={"input": 10, "output": 5, "total": 15}, duration_ms=99)]


def test_phases_follow_the_tool_table_in_order():
    n, events = run(full_audit())
    assert [e["phase"] for e in events if e["kind"] == "phase"] == [p for p, _ in PHASES]
    assert n.phase == PHASES[-1][0]


def test_events_have_known_kinds_increasing_seq_and_utc_stamps():
    _, events = run(full_audit())
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert {e["kind"] for e in events} <= set(KINDS)
    assert all(e["ts"].endswith("Z") for e in events)


def test_session_tokens_and_text_come_from_the_stream():
    n, events = run(full_audit())
    assert n.session_id == "s-1" and n.result["exit_code"] == 0 and n.result["tokens"]["total"] == 15
    assert n.text == n.result["text"]
    assert events[-1]["kind"] == "result" and events[-1]["level"] == "info"


def test_session_id_falls_back_to_the_result_record():
    n, _ = run([rec("system", 0, subtype="init", model="m", session_id=""),
                rec("result", 1, session_id="s-9", exit_code=0, text="")])
    assert n.session_id == "s-9"


def test_agent_text_is_accumulated_not_emitted():
    n, events = run([rec("text", 0, text="a"), rec("text", 1, text=" b")])
    assert events == [] and n.text == "a b"


def test_consecutive_generic_tools_collapse_into_one_counted_event():
    records = [r for i in range(4) for r in call("read_file", {"path": f"/x/f{i}.txt"}, "x", i)]
    records += call("terminal", {"command": "ls"}, "x", 9, is_error=True)
    _, events = run(records)
    reads = [e for e in events if "read_file" in e["title"]]
    assert len(reads) == 1 and "4" in reads[0]["title"]
    terminal = [e for e in events if "terminal" in e["title"]]
    assert len(terminal) == 1 and terminal[0]["level"] == "warning"


def test_swarm_progress_counts_delegated_blocks_against_the_plan():
    _, events = run(full_audit())
    titles = [e["title"] for e in events if e["kind"] == "tool_result" and e["phase"] == "swarm"]
    progress = [tuple(map(int, m.groups())) for m in (re.search(r"(\d+)/(\d+)", t) for t in titles) if m]
    assert progress == [(2, 3), (3, 3)]  # done = delegated tasks so far, total = tasks in the extraction plan


def test_truncated_gr_output_still_names_the_case_and_the_audit():  # Review Focus 1
    big_case = json.dumps({**CASE, "audits": [{"notes": "x" * 9000}]})[:5000] + "..."
    big_audit = json.dumps({**AUDIT, "inherited_open_findings": [{"d": "y" * 9000}]})[:5000] + "..."
    _, events = run(call("gr_case_open", {"folder": "/x"}, big_case, 1)
                    + call("gr_audit_start", {"case_id": "c"}, big_audit, 2))
    results = [e["title"] for e in events if e["kind"] == "tool_result"]
    assert len(results) == 2 and "GRC-acme-20261003" in results[0] and "A01" in results[1]


def test_blocked_commands_become_warnings_with_the_reason():
    _, events = run(call("terminal", {"command": "pip install x"},
                         '{"error": "BLOCKED: approval required (approvals.single_query_mode: deny)"}', 1))
    assert any(e["level"] == "warning" and "BLOCKED" in (e["detail"] or "") for e in events)


def test_gr_tool_errors_and_refused_seals_are_warnings():
    _, events = run(call("gr_case_open", {}, {"error": "evidence folder not found"}, 1)
                    + call("gr_audit_seal", {}, {"sealed": False, "completion": {"missing": ["report_pdf"]}}, 2))
    warnings = [e for e in events if e["level"] == "warning"]
    assert len(warnings) == 2
    assert "evidence folder not found" in warnings[0]["detail"] and "report_pdf" in warnings[1]["detail"]


def test_failed_run_ends_with_an_error_event():
    _, events = run([rec("result", 0, session_id="s", exit_code=1, text="", error="credentials or agent init failed")])
    assert events[-1]["kind"] == "result" and events[-1]["level"] == "error"
    assert "credentials" in events[-1]["detail"]


def test_unparseable_lines_are_warnings_not_crashes():
    n = Normalizer()
    events = n.feed_line("not json") + n.feed_line('["a list"]') + n.feed_line("   ")
    assert [e["level"] for e in events] == ["warning", "warning"]


def test_reading_the_context_file_marks_the_intake_phase():
    for path in ("/x/context.md", "C:\\x\\GhostRecon_Audits\\_console\\context_ab12cd34ef56.md"):
        assert phase_for("read_file", {"path": path}) == "intake"
    assert phase_for("read_file", {"path": "/x/Bancos/a.txt"}) is None
    assert phase_for("delegate_task", {}, "swarm") == "swarm" and phase_for("terminal", {}) is None


def test_malformed_field_values_never_raise():  # Finding 1: guard against exceptions
    n = Normalizer()
    # result with non-numeric exit_code
    events1 = n.feed_line(json.dumps(rec("result", 0, session_id="s", exit_code="abc", text="")))
    assert len(events1) == 1 and events1[0]["level"] == "warning"
    # record with absurd timestamp (causes OverflowError in _iso)
    events2 = n.feed_line(json.dumps(rec("result", 1, session_id="s", exit_code=0, text="", timestamp=1e20)))
    assert len(events2) == 1 and events2[0]["level"] == "warning"
    # tool_result for gr_audit_seal with completion as non-dict (causes AttributeError on .get("missing"))
    events3 = n.feed_line(json.dumps(rec("tool_use", 2, name="gr_audit_seal", tool_call_id="c2", input={})))
    events3 += n.feed_line(json.dumps(rec("tool_result", 2, name="gr_audit_seal", tool_call_id="c2",
                                          output='{"sealed": false, "completion": ["x"]}', duration_ms=1, is_error=False)))
    assert any(e["level"] == "warning" for e in events3)
    # normal line afterwards is still normalized
    events4 = n.feed_line(json.dumps(rec("result", 3, session_id="s", exit_code=0, text="ok")))
    assert len(events4) == 1 and events4[0]["kind"] == "result" and events4[0]["level"] == "info"


def test_truncated_gr_swarm_plan_uses_task_count_from_args_as_fallback():  # Finding 2: swarm total survives truncation
    truncated_plan = json.dumps({"mode": "extraction", "tasks": [{}] * 5})[:5000] + "..."
    # delegate_task calls should show progress against the fallback total from args
    _, events_with_delegates = run(
        call("gr_swarm_plan", {"audit_id": "a", "mode": "extraction", "tasks": [{}, {}, {}, {}, {}]}, truncated_plan, 1)
        + call("delegate_task", {"tasks": [{}, {}]}, "ok", 2)
        + call("delegate_task", {"tasks": [{}]}, "ok", 3))
    swarm_progress = [e["title"] for e in events_with_delegates if e["kind"] == "tool_result" and e["phase"] == "swarm"]
    # should show "2/5" and "3/5", not "2/0"
    assert any("2/5" in t for t in swarm_progress), f"Expected '2/5' in progress titles, got {swarm_progress}"
    assert any("3/5" in t for t in swarm_progress), f"Expected '3/5' in progress titles, got {swarm_progress}"


def test_deeply_nested_and_non_string_ids_never_raise():  # Finding 1: comprehensive exception coverage
    n = Normalizer()
    # deeply nested JSON that causes RecursionError in json.loads
    events1 = n.feed_line('[' * 100000)
    assert len(events1) == 1 and events1[0]["level"] == "warning"
    # deeply nested JSON object
    events2 = n.feed_line('{"a":' * 100000)
    assert len(events2) == 1 and events2[0]["level"] == "warning"
    # gr_audit_start with non-string audit id (causes AttributeError in _seq)
    events3 = n.feed_line(json.dumps(rec("tool_use", 1, name="gr_audit_start", tool_call_id="c1", input={})))
    events3 += n.feed_line(json.dumps(rec("tool_result", 1, name="gr_audit_start", tool_call_id="c1",
                                          output='{"audit": {"id": 7}}', duration_ms=1, is_error=False)))
    assert any(e["level"] == "warning" for e in events3)
    # gr_review_plan with non-string review_id (causes AttributeError in _seq)
    events4 = n.feed_line(json.dumps(rec("tool_use", 2, name="gr_review_plan", tool_call_id="c2", input={})))
    events4 += n.feed_line(json.dumps(rec("tool_result", 2, name="gr_review_plan", tool_call_id="c2",
                                          output='{"review_id": 3}', duration_ms=1, is_error=False)))
    assert any(e["level"] == "warning" for e in events4)
    # normal line afterwards is still normalized
    events5 = n.feed_line(json.dumps(rec("result", 3, session_id="s", exit_code=0, text="ok")))
    assert len(events5) == 1 and events5[0]["kind"] == "result" and events5[0]["level"] == "info"
