---
name: ghost-recon-report-pack
description: "Write the narrative and build the md/pdf/xlsx pack."
version: 1.0.0
author: Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ghost-recon, reports, pack, markdown, pdf, xlsx]
    category: ghost-recon
    related_skills: [ghost-recon-deliverables, ghost-recon-forensic-audit, new-open-case, rerun-case, review-case]
---

# Ghost Recon Report Pack Skill

The report consultant: how to write `06_Report/report.md` (or `diagnosis.md` for reviews) so that `gr_report_build` turns it, together with `model.json` and the case database, into the signed pack — Markdown report with annexes, executive PDF with cover tiles, evidence workbook — plus `LEEME.md` and `pack_hashes.txt`. The plugin appends the database annexes (exceptions, anomalies, questions, criteria, evidence index, research) and the signature; you write the narrative and keep every number in the model.

## When to Use

- Phase 17 of an audit, the regeneration step of an evidence pass, or the synthesis of a review.
- The user asks for a report, an executive summary, a workbook or a pack from an existing audit.

## Prerequisites

- `03_Extracted_Data/model.json` with `kpis` (≤ 4 headline numbers, label → value), `audit_trail` and, on reruns, `version_effect`.
- Findings registered in the database (`gr_finding_upsert`); criteria registered (`gr_criteria_add`).

## How to Run

1. `write_file` `06_Report/report.md` using the structure below (Markdown: `##` headings, GitHub tables, bullet lists; the plugin adds the H1 header block).
2. `gr_report_build(audit_id, formats=["md","pdf","xlsx"])`; read `warnings`.
3. Render and inspect the pdf (`terminal`: `pdftoppm -r 60 -png <pdf> page`; `vision_analyze` on the PNGs); fix and rebuild. Each rebuild is a new version (v1, v2…); previous files stay in `06_Report/`, move superseded ones to `versions/` with `terminal`.

## Quick Reference

Structure of `report.md` (audit):

1. `## 0. Supuestos y alcance` (unattended assumptions, scope, cut-off, base currency, what is out of scope).
2. `## 1. La respuesta en una página` — the three questions (earned / should have / attributable), the "numbers not to mix" table, the 3–4 decisive figures.
3. `## 2. Evidencia y método` — evidence base table (source · what it gives · control), blocks processed, swarm and validation summary.
4. `## 3. Hallazgos por materialidad` — one subsection per finding: observation, evidence, amount, why it matters, benign explanations, missing evidence, confidence, finding id.
5. `## 4. Flujo del dinero` / `## 5. Posición de los socios` (when relevant; two bases if a criterion is pending).
6. `## 6. Lo que queda abierto` — numbered questions with amount at stake and who answers (ids `Q-nn`).
7. `## 7. Riesgos y recomendaciones` — ordered by materiality; immediate actions; 30/90-day plan.
8. `## 8. Cómo se construyó y validó` — rounds A/B/C, what was fixed.
9. `## 9. Nota de alcance` — evidence-only; differences described as unreconciled; no intent attributed; not legal/tax advice.

Reruns prepend `## 00. Adenda vN — qué llegó, qué cambió, qué queda abierto` with the previous → new table.

Reviews: `diagnosis.md` with one-page answer, facts vs inferences vs allegations, what changed between audits, risk map by role, recommendations (action · owner · deadline), decisive items and who provides what, disclaimer.

## Procedure

1. Pull every figure from `model.json` (format it in the text; do not round differently in two places).
2. Reference finding ids (`EXC-03`, `Q-02`) so the annex tables and the narrative agree.
3. Keep paragraphs short; tables for anything with more than three numbers; no placeholders.
4. Build; resolve warnings (`model.json not found`, tool names); inspect the pdf cover and one body page.
5. Methodology report: `06_Report/methodology.md` built with `gr_report_build(report_md=…, formats=["pdf"], title="Metodología y estándares — <caso>")` (content per `ghost-recon-deliverables` §6).

## Pitfalls

- A number in the narrative that is not in the model or the database.
- Headline figures under different bases in the cover tiles and the body.
- Leaving a previous version's text in a section after a re-run.

## Verification

- `gr_report_build` returns three files and no warnings; `LEEME.md` lists them with SHA-256; the cover shows the kpis; "Página N de M" on every body page.
