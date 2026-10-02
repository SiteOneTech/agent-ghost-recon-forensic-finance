---
title: "Ghost Recon Deliverables — Build, sign and QA the Ghost Recon deliverable set"
sidebar_label: "Ghost Recon Deliverables"
description: "Build, sign and QA the Ghost Recon deliverable set"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Deliverables

Build, sign and QA the Ghost Recon deliverable set.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-deliverables` |
| Version | `2.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `deliverables`, `pdf`, `xlsx`, `markdown`, `signing` |
| Related skills | [`ghost-recon-report-pack`](../../bundled/ghost-recon/ghost-recon-ghost-recon-report-pack.md), [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-validation`](../../bundled/ghost-recon/ghost-recon-ghost-recon-validation.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Deliverables Skill

The professional standard for the fixed deliverable set — executive PDF, evidence workbook (XLSX), Markdown report for other agents, methodology-and-standards PDF, optional documents — including the model JSON as single source of truth, sheet catalog, page plan, charts, signing and metadata, visual QA and cross-deliverable consistency checks. Full text in `references/deliverables.md`. The base pack is produced by `gr_report_build` (see `ghost-recon-report-pack`); this skill tells you what the narrative and any custom generator must contain.

## When to Use

- An audit reaches the reporting phase, or the user asks to update, re-version, re-brand, fix the layout of, or add metadata/signatures to deliverables.
- You write custom generators in `src/` (charts, partner-position sheets with formulas, methodology report).

## Prerequisites

- `03_Extracted_Data/model.json` with `kpis`, `audit_trail` (and `version_effect` on reruns).
- `openpyxl`, `reportlab` (plugin dependencies), `matplotlib` for charts, `pdftoppm` for visual QA.

## How to Run

1. `read_file` `references/deliverables.md` §2 (model), §5 (Markdown structure) before writing `06_Report/report.md`.
2. Write the narrative; build with `gr_report_build`; for the methodology report write `06_Report/methodology.md` and build it with `gr_report_build(report_md=…, formats=["pdf"], title=…)`.
3. Custom sheets or charts: scripts in `src/` that read `model.json`; outputs into `06_Report/`; register them by rebuilding the pack (the plugin hashes everything in `06_Report/`).

## Quick Reference

| Deliverable | Source | Must contain |
|---|---|---|
| Executive PDF | `report.md` + kpis | the answer in one page; findings by materiality; questions with amounts; validation note |
| Workbook | DB + model | README, document index, registers, audit trail, version effect, dashboard with formulas |
| Markdown report | `report.md` + DB annexes | §00 addendum (reruns), numbered body, one-page answer annex |
| Methodology PDF | `methodology.md` | IS / IS NOT table, standards with "how applied here", independence disclosure, limitations |

Signature: "Generado por Ghost Recon · Sistema de auditoría asistida por IA · https://www.ghostrecon.ai/". Metadata: author "Ghost Recon (www.ghostrecon.ai)", producer "Ghost Recon Audit Engine". No tool or provider names anywhere.

## Procedure

1. Model first: no figure lives only in a report.
2. Narrative in Markdown with GitHub tables; every amount with its source sheet; version labels identical everywhere.
3. Build; render pdf pages with `terminal` (`pdftoppm -r 60 -png`) and inspect with `vision_analyze`; fix overflows, empty pages, colliding labels.
4. Cross-check headline figures model = dashboard = PDF = MD; exception counts and highest id match; validators' findings all fixed/explained.
5. `LEEME.md` says for whom each file is; `pack_hashes.txt` carries SHA-256.

## Pitfalls

- Labels starting with "= " written as formulas; formulas stored as text; truncated cells.
- Charts rebuilt from an old model after a re-run (stale numbers).
- Headline figures under different bases for different parties.

## Verification

- `gr_report_build` returns no warnings; `pdfinfo` shows Ghost Recon as creator/producer; the workbook `docProps/app.xml` reads Ghost Recon Audit Engine.
