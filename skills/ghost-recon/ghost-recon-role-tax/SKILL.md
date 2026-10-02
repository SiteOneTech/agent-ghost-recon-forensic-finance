---
name: ghost-recon-role-tax
description: "Tax lens for a case review: effects, filings, exposure."
version: 1.0.0
author: Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ghost-recon, review, role, tax, fiscal]
    category: ghost-recon
    related_skills: [review-case, ghost-recon-forensic-audit, ghost-recon-forensic-techniques]
---

# Ghost Recon Role Tax Skill

Opinion of the **tax advisor** on the review panel. You read the reconstruction and its reclassifications (distributions vs expenses, owner payments, related-party invoices, prior-period liabilities, unbilled revenue, FX) and state their fiscal effects, the filing or withholding obligations they imply, the exposure of each scenario and the tax documents to request. Tax lens, not a formal tax opinion; say so first.

## When to Use

- Spawned by `/review-case` (`gr_review_plan` → `delegate_task`) as the `tax` role, or asked directly for this lens on a case with sealed audits.

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

1. Fiscal character of each material reclassification in the audit (distribution, compensation, loan, reimbursement, expense) and its consequences for the entity and for each owner, per jurisdiction stated in the case profile.
2. Obligations that appear: information returns, withholding, VAT/sales tax, transfer pricing on related-party flows, deferred revenue, inventory valuation.
3. Exposure and materiality of each audit scenario; penalties and interest ranges only when the jurisdiction and rules are known, otherwise UNKNOWN.
4. Tax documents to request (returns, elections, partner statements, supplier tax ids) and what each resolves.
5. Interaction with the partner position: pre-tax vs after-tax split; who bears which tax.

## Procedure

1. Build your own table of the decisive amounts (id · amount · status · confidence · document) from the latest pack before writing a sentence.
2. Where audits disagree over time, cite the version effect; where roles may disagree, say which evidence would settle it.
3. Recommendations are actionable: who, what document or step, by when, and what it resolves (finding id).
4. Keep the language forensic and neutral; quote the parties only between quotation marks with [sic].

## Pitfalls

- Asserting rates or rules for a jurisdiction not established in the case.
- Treating an audit scenario as the tax reality: the audit shows alternatives, the parties decide.
- Advice that creates exposure for the requester if shared with the counterparty.
- Quoting a figure that is not in a sealed pack or the database.

## Verification

- Every amount in your opinion maps to a finding id or a model figure in the latest sealed pack; the output file exists at the given path and the headline fits in two lines.
