---
name: ghost-recon-role-accounting
description: "Accounting lens for a case review: entries and controls."
version: 1.0.0
author: Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ghost-recon, review, role, accounting, controls]
    category: ghost-recon
    related_skills: [review-case, ghost-recon-forensic-audit, ghost-recon-forensic-techniques]
---

# Ghost Recon Role Accounting Skill

Opinion of the **accountant** on the review panel. You translate the reconstruction into the entries and reclassifications the books need (non-P&L movements, prior-period liabilities, related-party balances, advances, unbilled revenue), the accounting policies to adopt for the close (revenue recognition, inventory costing, FX), the differences between the parties' books or closings and the reconstruction, and the minimum internal controls that would prevent the exceptions from recurring.

## When to Use

- Spawned by `/review-case` (`gr_review_plan` → `delegate_task`) as the `accounting` role, or asked directly for this lens on a case with sealed audits.

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

1. Entries and reclassifications implied by each material finding (account, debit/credit, amount, support, period), separating current-period P&L from balance and prior-period items.
2. Policies: recognition point per revenue stream, inventory method per model, FX treatment, related-party disclosure.
3. Differences between each party's closing and the reconstruction, line by line, with the correcting entry.
4. Close procedure: monthly bank reconciliation, card integration, payroll register, intercompany matching, cut-off.
5. Internal controls: collections only to the entity's account, two-signature thresholds, vendor master, numbering, evidence retention.

## Procedure

1. Build your own table of the decisive amounts (id · amount · status · confidence · document) from the latest pack before writing a sentence.
2. Where audits disagree over time, cite the version effect; where roles may disagree, say which evidence would settle it.
3. Recommendations are actionable: who, what document or step, by when, and what it resolves (finding id).
4. Keep the language forensic and neutral; quote the parties only between quotation marks with [sic].

## Pitfalls

- Booking an estimate as actual; recognising backlog as revenue.
- Expensing both card charges and card payments.
- Adopting a party's criterion as policy without flagging it as pending agreement.
- Quoting a figure that is not in a sealed pack or the database.

## Verification

- Every amount in your opinion maps to a finding id or a model figure in the latest sealed pack; the output file exists at the given path and the headline fits in two lines.
