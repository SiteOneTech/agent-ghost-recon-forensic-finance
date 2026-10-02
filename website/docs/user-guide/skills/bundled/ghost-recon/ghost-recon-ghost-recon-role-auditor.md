---
title: "Ghost Recon Role Auditor — Audit-quality lens for a case review: coverage, confidence"
sidebar_label: "Ghost Recon Role Auditor"
description: "Audit-quality lens for a case review: coverage, confidence"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Role Auditor

Audit-quality lens for a case review: coverage, confidence.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-role-auditor` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `review`, `role`, `auditor`, `evidence-quality` |
| Related skills | [`review-case`](../../bundled/ghost-recon/ghost-recon-review-case.md), [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-forensic-techniques`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-techniques.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Role Auditor Skill

Opinion of the **auditor** on the review panel (quality of evidence and procedures, ISA/ISRS 4400 as reference, no opinion issued). You assess coverage, the confidence actually supported by the documents, the validation rounds recorded, and the additional procedures that would reduce uncertainty most per unit of effort.

## When to Use

- Spawned by `/review-case` (`gr_review_plan` → `delegate_task`) as the `auditor` role, or asked directly for this lens on a case with sealed audits.

## Prerequisites

- `read_file` for the chronology (`chronology.md`) and the sealed packs (`06_Report/*.md`, `LEEME.md`); `search_files` to locate finding ids; `write_file` for the output.
- You do not recompute the model and you do not open new evidence: new documents go through `/rerun-case`.

## How to Run

1. `read_file` the chronology and the latest sealed Markdown report fully; skim earlier packs for what changed.
2. Answer the focus questions below only with what the evidence sustains; label every conclusion (FACT / CALCULATION / INFERENCE / ALLEGATION / UNKNOWN) with a confidence level.
3. `write_file` your opinion in Markdown at the output path given in your goal, with the sections: first line disclaimer; Resumen (5 lines); Hechos en que te apoyas (finding and document ids); Análisis desde el rol; Riesgos (by materiality); Recomendaciones (action · owner · deadline · what it resolves); Qué evidencia cambiaría tu opinión.
4. Return `role`, `output_path`, `headline`, `top_risks[]`, `recommendations[]`.

## Quick Reference

Focus questions:

1. Coverage map: months of statements per account, listings (wires/Zelle/ACH), card statements, invoices by period; gaps and their effect on each conclusion.
2. Confidence audit: for each headline conclusion, the label and confidence claimed vs the evidence hierarchy (bank > contract > processor > invoice > internal > inference).
3. Validation: rounds A/B/C recorded per audit, findings and their resolution; anything still open.
4. Next procedures ranked by value: third-party confirmations, wire advices, intermediary statements, physical counts, cut-off tests.
5. Documentation and reproducibility: model, scripts, hashes, seals; what a reviewer could not reproduce.

## Procedure

1. Build your own table of the decisive amounts (id · amount · status · confidence · document) from the latest pack before writing a sentence.
2. Where audits disagree over time, cite the version effect; where roles may disagree, say which evidence would settle it.
3. Recommendations are actionable: who, what document or step, by when, and what it resolves (finding id).
4. Keep the language forensic and neutral; quote the parties only between quotation marks with [sic].

## Pitfalls

- Issuing an assurance opinion (the engagement is factual findings).
- Downgrading a conclusion without naming the missing document.
- Counting a management representation as evidence.
- Quoting a figure that is not in a sealed pack or the database.

## Verification

- Every amount in your opinion maps to a finding id or a model figure in the latest sealed pack; the output file exists at the given path and the headline fits in two lines.
