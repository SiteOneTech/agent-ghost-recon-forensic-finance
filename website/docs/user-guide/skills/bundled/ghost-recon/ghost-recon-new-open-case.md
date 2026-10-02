---
title: "New Open Case — Open a Ghost Recon case and run the full forensic audit"
sidebar_label: "New Open Case"
description: "Open a Ghost Recon case and run the full forensic audit"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# New Open Case

Open a Ghost Recon case and run the full forensic audit.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/new-open-case` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `forensic`, `audit`, `case`, `orchestrator` |
| Related skills | [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-block-auditor`](../../bundled/ghost-recon/ghost-recon-ghost-recon-block-auditor.md), [`ghost-recon-validation`](../../bundled/ghost-recon/ghost-recon-ghost-recon-validation.md), [`ghost-recon-report-pack`](../../bundled/ghost-recon/ghost-recon-ghost-recon-report-pack.md), [`rerun-case`](../../bundled/ghost-recon/ghost-recon-rerun-case.md), [`review-case`](../../bundled/ghost-recon/ghost-recon-review-case.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# New Open Case Skill

Orchestrates `/new-open-case <folder> [context.md] [--out <folder>] [--name "…"] [--currency USD] [--lang es]`: opens (or loads) the case anchored to an evidence folder and runs the **complete** Ghost Recon forensic cycle on it — intake with hashes, extraction swarm, reconstruction, findings, research, deliverable pack, independent validation and seal. It does not re-audit a case whose last audit is sealed: that is `/rerun-case`.

## When to Use

- The user invokes `/new-open-case` or asks to "audit this folder", "reconstruct the numbers", "open a case on these documents".
- A folder of raw evidence (statements, invoices, orders, contracts, chats, ZIPs) exists and no audit has been run on it yet.

## Prerequisites

- Plugin `ghost-recon` enabled (toolset `ghost_recon`: `gr_case_open`, `gr_audit_start`, `gr_swarm_plan`, `gr_finding_upsert`, `gr_criteria_add`, `gr_research`, `gr_report_build`, `gr_run_record`, `gr_audit_seal`).
- `delegate_task` available (swarm) and `web_search`/`web_extract` or `TAVILY_API_KEY` for research.
- The method skills are installed: `ghost-recon-forensic-audit`, `ghost-recon-forensic-techniques`, `ghost-recon-deliverables`, `ghost-recon-block-auditor`, `ghost-recon-validation`, `ghost-recon-report-pack`.

## How to Run

1. Parse the arguments: first token = evidence folder (quote paths with spaces), optional second token ending in `.md` = context file, flags `--out`, `--name`, `--currency`, `--lang`.
2. `gr_case_open(folder, context_md, name, base_currency, language, out_dir)` → read `next_step`. If the case already has a sealed audit, stop and tell the user to use `/rerun-case` (or `/review-case`).
3. `gr_audit_start(case_id, kind="initial", context_md)` → note `audit_id` and `folder` (the audit folder; every output goes there).
4. Follow the Procedure below. If the user is not present, do not stop to ask: take the most reasonable reading, state the assumptions at the top of `06_Report/report.md`, and continue to the seal.

## Quick Reference

| Step | Tool | Output |
|---|---|---|
| Intake | `gr_case_open`, `gr_audit_start`, `read_file` (context.md) | case, audit folder, evidence register |
| Criteria | `gr_criteria_add` | `CRIT-nn` |
| Extraction swarm | `gr_swarm_plan(mode="extraction")` → `delegate_task` (one call per wave) | `03_Extracted_Data/agents/out_*.json` |
| Model | `write_file` | `03_Extracted_Data/model.json` (kpis, audit_trail, …) |
| Findings | `gr_finding_upsert` | `EXC-nn`, `ANO-nn`, `Q-nn`, `FND-nn` |
| Research | `gr_research` (or `web_search`) | research notes with provenance |
| Narrative | `write_file` | `06_Report/report.md` (+ `methodology.md`) |
| Pack | `gr_report_build` | md + pdf + xlsx, LEEME, hashes |
| Validation | `gr_swarm_plan(mode="validation")` → `delegate_task`; `gr_run_record` | `validation/validation.json` |
| Seal | `gr_audit_seal` | `SEALED.json` |

## Procedure

1. **Load the method.** `skill_view` `ghost-recon-forensic-audit` (and `ghost-recon-forensic-techniques` when the mission type is known). Read the context file with `read_file`; register every rule the requester states verbatim with `gr_criteria_add`.
2. **Discovery.** `gr_evidence_index(audit_id)` lists every file with hash, block and type. Open with `read_file` / `terminal` (`pdftotext -layout`) / `vision_analyze` whatever is unclear; note gaps (missing months, numbering gaps) as `Q-nn` questions immediately.
3. **Business model and scope.** Write `03_Extracted_Data/case_profile.json` (entities, owners and percentages, accounts, period, currency, reason for the investigation, what is out of scope; UNKNOWN where unknown).
4. **Extraction swarm.** `gr_swarm_plan(audit_id, mode="extraction")`. For each wave, call `delegate_task` with that wave's `delegate_tasks` (goal + context + output_schema exactly as returned). Wait for every child; read every `out_<block>.json` with `read_file`; reconcile overlaps by document id; list the discrepancies the children reported.
5. **Reconstruction.** Build `03_Extracted_Data/model.json` following the method phases 5–16 (normalized transactions, revenue and collections, costs, cash reconstruction, balance items, owners and related parties, reconciliation graph, anomalies, dashboard). Keep `kpis` (≤ 4 headline numbers for the cover), `audit_trail` (one row per headline figure) and the five realities separate. Put generator scripts in `src/`.
6. **Findings.** Every unresolved item → `gr_finding_upsert` with kind, amount, counterparty, risk, confidence, label, `next_evidence` (exact document) and `owner` (who can supply it). Anomalies are signals, not conclusions.
7. **Research** only where it changes a conclusion (counterparty identity, registries, sanctions lists, documented exchange rates, freight benchmarks): `skill_view` `ghost-recon-research`, then `gr_research(..., audit_id, save=true)`. Web results are INFERENCE unless an official record.
8. **Narrative.** `skill_view` `ghost-recon-report-pack`; write `06_Report/report.md` (the answer in one page first; findings by materiality; money flow; owner position when relevant; questions with amounts; recommendations; scope note). Numbers come from `model.json`; never type a figure that is not in the model or the database.
9. **Pack.** `gr_report_build(audit_id)` → fix every warning (missing model, tool names). Render the PDF pages (`terminal`: `pdftoppm -r 60`) and check them with `vision_analyze`.
10. **Independent validation.** `gr_swarm_plan(audit_id, mode="validation", headline_figures=<kpis>)` → one `delegate_task` call with the three validators. Record each with `gr_run_record(kind="validation", role=A|B|C)`. Fix, rebuild the pack, repeat if any fix touched a figure. Do not continue with a material finding open.
11. **Seal.** `gr_audit_seal(audit_id)`; if `completion.missing` is not empty, complete it rather than forcing.
12. **Closing message.** Headline answers (earned / should have / attributable), evidence counts, what remains open and who must supply it, the pack location, and any temporary folder the user may delete.

## Pitfalls

- Writing anything inside the evidence folder; use only the audit folder returned by `gr_audit_start`.
- Passing the helper keys (`block`, `manifest`, `files`) to `delegate_task`: use `delegate_tasks` as returned.
- Sealing before validation, or validating before the pack exists (validators read the deliverables).
- Typing numbers into `report.md` that are not in `model.json`; mixing profit, cash and owner balances.
- Non-neutral wording (fraud, theft, diversion) or presenting an allegation as a fact.

## Verification

- `gr_case_status(case)` shows the audit `sealed` with `seal_ok: true`, three reports registered and `findings.open_by_risk` populated.
- `06_Report/` holds `LEEME.md`, `pack_hashes.txt`, the md, the pdf and the xlsx; `validation/validation.json` has at least two rounds with status `done`.
- The pdf renders with the cover tiles and "Página N de M"; `gr_report_build` reported no tool-name warning.
