---
title: "Rerun Case — Evidence pass on a case: new audit, sealed one untouched"
sidebar_label: "Rerun Case"
description: "Evidence pass on a case: new audit, sealed one untouched"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Rerun Case

Evidence pass on a case: new audit, sealed one untouched.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/rerun-case` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `forensic`, `evidence-pass`, `rerun`, `orchestrator` |
| Related skills | [`ghost-recon-evidence-pass`](../../bundled/ghost-recon/ghost-recon-ghost-recon-evidence-pass.md), [`ghost-recon-counterparty-response`](../../bundled/ghost-recon/ghost-recon-ghost-recon-counterparty-response.md), [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-validation`](../../bundled/ghost-recon/ghost-recon-ghost-recon-validation.md), [`ghost-recon-report-pack`](../../bundled/ghost-recon/ghost-recon-ghost-recon-report-pack.md), [`new-open-case`](../../bundled/ghost-recon/ghost-recon-new-open-case.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Rerun Case Skill

Orchestrates `/rerun-case <folder> [context.md] [--out <folder>]`: on a case that already has a sealed audit, finds the new evidence in the folder (and its ZIPs), deduplicates it against everything already audited, and produces a **new audit** (`A0n_<date>/`) with the complete deliverable pack and a version-effect table. The previous audit is never edited; its seal is verified.

## When to Use

- New documents arrived for an existing case ("here is new evidence", "the bank sent the wires listing", "the counterparty answered").
- A management clarification or criterion must be applied (it becomes `CRIT-nn`, never a fact).
- The requester asks to re-run, re-version or update an audit.

## Prerequisites

- Plugin `ghost-recon` enabled; the case was opened with `/new-open-case` and its last audit is sealed (`gr_case_status`).
- Skills `ghost-recon-evidence-pass`, `ghost-recon-forensic-audit`, `ghost-recon-validation`, `ghost-recon-report-pack` (and `ghost-recon-counterparty-response` when the new evidence is a counterparty's reply).

## How to Run

1. Parse arguments (folder, optional `.md` context, `--out`).
2. `gr_case_open(folder, context_md)` → if the last audit is not sealed, continue that audit instead of opening another (tell the user).
3. `gr_audit_start(case_id, kind="rerun", context_md)` → read `evidence` (NEW / DUP_PRIOR / DUP_INTERNAL / DUP_CONTENT / MODIFIED), `inherited_open_findings`, `parent_audit`, `folder`.
4. `skill_view` `ghost-recon-evidence-pass` and follow it inside the new audit folder.

## Quick Reference

| Situation | Action |
|---|---|
| 100 % duplicates | Still a pass: register, triage note, minimal pack, validation B, seal |
| `MODIFIED` files | Open an `EXC-nn` (evidence changed after being audited) and treat the new bytes as a new document |
| Counterparty reply | `skill_view` `ghost-recon-counterparty-response`; claims become `FND-nn` with category RA/II/DR |
| Management instruction | `gr_criteria_add` verbatim; apply, cite, keep "pending agreement" |
| Many new files | `gr_swarm_plan(mode="extraction")` (only new evidence) → `delegate_task` |

## Procedure

1. **Preparation.** `read_file` the previous audit's `06_Report/*.md` §00 and `Evidence_Pass/inherited_open_findings.json`; the pass is evaluated against the open exceptions. Record who supplied the batch and when with `gr_run_record(kind="intake")`.
2. **Triage.** For every `NEW` file, write `Evidence_Pass/triage.md`: block, period/version it feeds, and which open exception it may resolve.
3. **Extraction** with the engagement's parsers (copied by the plugin into `src/`): statements tie to the cent, listings match their declared row count, provenance on every row. Use the swarm when the batch is large.
4. **Cross-match** by exact key (date ± 2 days, amount, account, reference) in both directions; what does not match is an exception.
5. **Reclassification** under the critical rules: a proven beneficiary never establishes the nature of a payment; estimates are replaced by actuals with the difference shown; prior-year liabilities stay non-P&L.
6. **Model and version effect.** Re-run the whole chain into this audit's `03_Extracted_Data/model.json` with `version_effect` (item · previous · new · difference · document · sheet). Close, downgrade or create findings with `gr_finding_upsert` (ids continue the case series; history is kept by the database).
7. **Pack.** `06_Report/report.md` with §00 "what arrived / what changed / what stays open" first, then the full body; `gr_report_build(audit_id)`; visual QA of the pdf.
8. **Validation** A/B/C via `gr_swarm_plan(mode="validation")` → `delegate_task`; `gr_run_record` each; fix and rebuild if figures moved.
9. **Seal** with `gr_audit_seal`; then `gr_case_status` to confirm the previous audit still reports `seal_ok: true`.
10. **Closing message:** what arrived (new / duplicates), what it resolved, what changed (previous → new), what remains open and who supplies it.

## Pitfalls

- Editing the previous audit folder (the tools refuse; do not work around them).
- Copying deliverables from the previous audit instead of regenerating them from the new model.
- Counting a re-downloaded statement as new evidence (level-2 dedupe) or treating a management explanation as evidence.
- Changing an exception's risk without a document; closing one "because management says so".

## Verification

- `gr_case_status` lists both audits sealed, both `seal_ok: true`; the new audit's `summary.dedupe` matches `Evidence_Pass/dedupe.json`.
- The workbook has a `3x_VERSION_EFFECT` sheet and the md report opens with §00; exception ids continue the series (no reuse).
