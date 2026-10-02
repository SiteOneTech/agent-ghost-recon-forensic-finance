"""Tavily client (offline, through the opener seam), report builders' metadata contract, plugin registration."""
import json
import zipfile
from pathlib import Path

import pytest

from plugins.ghost_recon.core import casefolder as cf, research, service
from plugins.ghost_recon.core.reports import md as mdmod, pack
from plugins.ghost_recon.core.reports.pack import scan_tool_names


# ------------------------------------------------------------------------------------------ research

def test_tavily_client_builds_payloads_and_requires_key():
    calls = []

    def opener(url, payload, method):
        calls.append((url, payload, method))
        return {"results": [{"url": "https://example.org/a", "title": "A", "content": "x" * 50, "score": 0.9}]}

    with pytest.raises(research.TavilyError):
        research.TavilyClient("")
    c = research.TavilyClient("k", opener=opener)
    c.search("acme corp registro mercantil", topic="news", days=30, include_domains=["gov"])
    c.extract(["https://example.org/a"], extract_depth="advanced")
    c.crawl("https://example.org", max_depth=2)
    c.map("https://example.org")
    urls = [u for u, _, _ in calls]
    assert urls == [f"{research.DEFAULT_BASE_URL}/search", f"{research.DEFAULT_BASE_URL}/extract",
                    f"{research.DEFAULT_BASE_URL}/crawl", f"{research.DEFAULT_BASE_URL}/map"]
    assert calls[0][1]["days"] == 30 and calls[0][1]["include_domains"] == ["gov"]
    assert calls[1][1]["extract_depth"] == "advanced" and calls[2][1]["max_depth"] == 2
    with pytest.raises(research.TavilyError):
        c.run("bogus")


def test_save_result_registers_notes_with_provenance(store, demo_case):
    s = service.open_case(store, str(demo_case)); a = service.start_audit(store, s["case"]["id"], "initial")
    result = {"results": [{"url": "https://x", "title": "T", "content": "c", "score": 0.5}, {"url": "https://y", "title": "U", "content": "d"}]}
    out = research.save_result(store, a["audit"]["id"], "search", "quien es X", result)
    assert Path(out["saved_path"]).exists() and len(out["notes"]) == 2
    notes = store.list_research_notes(s["case"]["id"])
    assert {n["url"] for n in notes} == {"https://x", "https://y"} and all(n["sha256"] == out["sha256"] for n in notes)


# ------------------------------------------------------------------------------------------ reports

def test_markdown_parser_blocks():
    blocks = mdmod.parse_blocks("# T\n\npara **b**\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- x\n- y\n\n1. one\n\n> q\n")
    assert [b["type"] for b in blocks] == ["heading", "paragraph", "table", "bullets", "numbered", "quote"]
    assert blocks[2]["rows"] == [["1", "2"]]


def test_pack_metadata_and_signature(store, demo_case):
    pytest.importorskip("openpyxl", reason="plugin python_dependency, not in the core test group")
    pytest.importorskip("reportlab", reason="plugin python_dependency, not in the core test group")
    s = service.open_case(store, str(demo_case)); a = service.start_audit(store, s["case"]["id"], "initial")
    folder = Path(a["folder"])
    cf.write_json(folder, "03_Extracted_Data/model.json", {"kpis": {"Ingreso": 1000.5}, "audit_trail": [{"figure": "Ingreso", "value": 1000.5, "sheet": "07", "documents": ["d1"], "confidence": "CONFIRMED", "method": "m"}]})
    cf.write_text(folder, "06_Report/report.md", "## 1. Respuesta\n\nIngreso **1.000,50**.\n")
    res = pack.build_pack(store, a["audit"]["id"])
    files = {f["format"]: Path(f["path"]) for f in res["files"]}
    pdf = files["pdf"].read_bytes()
    assert b"Ghost Recon Audit Engine" in pdf and b"ReportLab" not in pdf and b"reportlab" not in pdf.lower()
    with zipfile.ZipFile(files["xlsx"]) as z:
        app = z.read("docProps/app.xml").decode()
        core = z.read("docProps/core.xml").decode()
    assert "Ghost Recon Audit Engine" in app and "openpyxl" not in core.lower() and "Ghost Recon" in core
    md = files["md"].read_text(encoding="utf-8")
    assert "Registro de excepciones" in md and "https://www.ghostrecon.ai/" in md
    assert (folder / "06_Report" / "LEEME.md").exists() and (folder / "06_Report" / "pack_hashes.txt").read_text().count("\n") == 3
    assert not res["warnings"]
    # second build is a new version; reports table keeps both
    res2 = pack.build_pack(store, a["audit"]["id"], formats=["md"])
    assert res2["version"] == "v2"


def test_scan_tool_names_ignores_case_root(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("evidence at /data/claude-cases/x — built by openpyxl", encoding="utf-8")
    hits = scan_tool_names([p], ignore=["/data/claude-cases/x"])
    assert hits == {"r.md": ["openpyxl"]}


# ------------------------------------------------------------------------------------------ plugin registration

class _Ctx:
    def __init__(self):
        self.tools, self.commands, self.cli, self.sections, self.hooks = {}, {}, {}, {}, {}

    def register_tool(self, name, toolset, schema, handler, **kw):
        self.tools[name] = (toolset, schema, handler)

    def register_command(self, name, handler, description="", args_hint="", **kw):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = (setup_fn, handler_fn)

    def register_system_prompt_section(self, sid, content, **kw):
        self.sections[sid] = content

    def register_hook(self, name, cb):
        self.hooks[name] = cb

    def get_config(self, key, default=None):
        return None


def test_register_wires_tools_commands_cli_and_prompt(gr_env):
    import plugins.ghost_recon as plugin
    ctx = _Ctx()
    plugin.register(ctx)
    assert {"gr_case_open", "gr_audit_start", "gr_swarm_plan", "gr_report_build", "gr_audit_seal", "gr_review_plan", "gr_research"} <= set(ctx.tools)
    assert all(ts == "ghost_recon" for ts, _, _ in ctx.tools.values())
    assert set(ctx.commands) == {"gr-help", "gr-cases", "gr-case", "gr-doctor"}
    assert "ghostrecon" in ctx.cli and "on_session_start" in ctx.hooks
    assert len(ctx.sections["ghost-recon-identity"]) <= 4000
    # tool handlers return JSON and surface errors as {"error": ...}
    out = json.loads(ctx.tools["gr_case_status"][2]({"case": "nope"}))
    assert "error" in out
    listing = json.loads(ctx.tools["gr_case_list"][2]({}))
    assert listing["cases"] == []
    assert "Ghost Recon" in ctx.commands["gr-help"]("")
    assert "doctor" in ctx.commands["gr-doctor"]("").lower()
