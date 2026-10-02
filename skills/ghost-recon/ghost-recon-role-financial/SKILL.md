---
name: ghost-recon-role-financial
description: "Financial lens for a case review: cash, profit, ranges."
version: 1.0.0
author: Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ghost-recon, review, role, financial, scenarios]
    category: ghost-recon
    related_skills: [review-case, ghost-recon-forensic-audit, ghost-recon-forensic-techniques]
---

# Ghost Recon Role Financial Skill

Opinion of the **financial analyst** on the review panel. You read the reconstructed economic profit, the cash position (expected vs demonstrated), the balance items, the owner positions under each basis, and how they moved between audits; you quantify sensitivities and the defensible settlement range; you propose the cash-governance rules going forward. Financial lens, not investment advice.

## When to Use

- Spawned by `/review-case` (`gr_review_plan` → `delegate_task`) as the `financial` role, or asked directly for this lens on a case with sealed audits.

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

1. Headline figures per audit and their evolution (version effect): economic profit, expected vs demonstrated cash, unreconciled amount, retained outside the entity, owner balances.
2. Sensitivities: which pending items (concept pending, two bases, estimated months) move the conclusions and by how much; the only sensitivity that would change the sign.
3. Settlement range: documented position, adjusted position, scenarios computed over the scenarios (never assumed).
4. Working-capital and cash-governance indicators: receivable days, cash retained outside the entity (target 0), monthly close, formal distributions, owner pay through payroll.
5. What the lawyer and the mediator can use as numbers without risk (same base in every headline).

## Procedure

1. Build your own table of the decisive amounts (id · amount · status · confidence · document) from the latest pack before writing a sentence.
2. Where audits disagree over time, cite the version effect; where roles may disagree, say which evidence would settle it.
3. Recommendations are actionable: who, what document or step, by when, and what it resolves (finding id).
4. Keep the language forensic and neutral; quote the parties only between quotation marks with [sic].

## Pitfalls

- Mixing profit, cash and owner balance in one figure.
- Presenting a scenario as the position.
- Projections inside the audit figures (keep forecasts outside and labelled).
- Quoting a figure that is not in a sealed pack or the database.

## Verification

- Every amount in your opinion maps to a finding id or a model figure in the latest sealed pack; the output file exists at the given path and the headline fits in two lines.
