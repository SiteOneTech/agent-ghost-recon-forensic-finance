"""Ghost Recon skill set: the orchestrators, method, swarm, validation, research, report and role skills exist,
follow the modern section order, and cross-reference the plugin tools and each other consistently."""
import re
from pathlib import Path

import pytest
import hermes_yaml as yaml

REPO = Path(__file__).resolve().parents[2]
SK = REPO / "skills" / "ghost-recon"
EXPECTED = {
    "new-open-case", "rerun-case", "review-case",
    "ghost-recon-forensic-audit", "ghost-recon-forensic-techniques", "ghost-recon-deliverables",
    "ghost-recon-evidence-pass", "ghost-recon-counterparty-response", "ghost-recon-block-auditor",
    "ghost-recon-validation", "ghost-recon-research", "ghost-recon-report-pack",
    "ghost-recon-role-legal", "ghost-recon-role-tax", "ghost-recon-role-financial", "ghost-recon-role-auditor",
    "ghost-recon-role-accounting", "ghost-recon-role-mediator",
}
SECTIONS = ["## When to Use", "## Prerequisites", "## How to Run", "## Quick Reference", "## Procedure", "## Pitfalls", "## Verification"]


def _fm(name):
    text = (SK / name / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"\n---\s*\n", text[3:])
    return yaml.safe_load(text[3: m.start() + 3]), text


def test_skill_set_is_complete():
    present = {p.parent.name for p in SK.glob("*/SKILL.md")}
    assert EXPECTED <= present
    assert (SK / "DESCRIPTION.md").exists()


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_section_order_and_category(name):
    fm, text = _fm(name)
    positions = [text.find(s) for s in SECTIONS]
    assert all(p >= 0 for p in positions), f"{name}: missing section"
    assert positions == sorted(positions), f"{name}: sections out of order"
    assert fm["metadata"]["hermes"]["category"] == "ghost-recon"


def test_orchestrators_reference_plugin_tools_and_skills():
    for name, tools in {"new-open-case": ["gr_case_open", "gr_audit_start", "gr_swarm_plan", "gr_report_build", "gr_audit_seal"],
                        "rerun-case": ["gr_audit_start", "gr_report_build", "gr_audit_seal"],
                        "review-case": ["gr_review_plan", "gr_report_build", "gr_audit_seal"]}.items():
        fm, text = _fm(name)
        for t in tools:
            assert re.search(rf"`{t}[`(]", text), f"{name} must name {t}"
        assert fm["metadata"]["hermes"].get("requires_toolsets") == ["ghost_recon"]
        assert "`delegate_task`" in text


def test_method_skills_ship_their_references():
    for name, ref in {"ghost-recon-forensic-audit": "method.md", "ghost-recon-forensic-techniques": "techniques.md",
                      "ghost-recon-deliverables": "deliverables.md", "ghost-recon-evidence-pass": "evidence-pass.md",
                      "ghost-recon-counterparty-response": "counterparty-response.md"}.items():
        assert (SK / name / "references" / ref).exists()
        _, text = _fm(name)
        assert f"references/{ref}" in text


def test_role_skills_match_the_review_plan_roles():
    from plugins.ghost_recon.core.review import ROLES
    for role in ROLES:
        assert role["skill"] in EXPECTED and (SK / role["skill"] / "SKILL.md").exists()
        _, text = _fm("review-case")
        assert f"`{role['skill']}`" in text


def test_swarm_goals_point_to_existing_skills():
    from plugins.ghost_recon.core.prompts import TEMPLATES
    for key in ("extraction_goal", "validation_context"):
        for m in re.finditer(r"skill_view\(name='([a-z-]+)'\)", TEMPLATES[key]):
            assert (SK / m.group(1) / "SKILL.md").exists(), m.group(1)
