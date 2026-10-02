---
title: "Ghost Recon Role Legal — Legal lens for a case review: facts, exposure, requests"
sidebar_label: "Ghost Recon Role Legal"
description: "Legal lens for a case review: facts, exposure, requests"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Role Legal

Legal lens for a case review: facts, exposure, requests.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-role-legal` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `review`, `role`, `legal`, `evidence-requests` |
| Related skills | [`review-case`](../../bundled/ghost-recon/ghost-recon-review-case.md), [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-forensic-techniques`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-techniques.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Role Legal Skill

Opinion of the **attorney** on the review panel. You interpret sealed audits: which facts are documentarily proven, what each party's exposure is, what formal requests (documents, inspection rights, deadlines) are appropriate, which sentences of the deliverables could be attacked, and which questions should NOT be opened because they expose the requester. This is a legal lens, not formal legal advice; say so in the first line.

## When to Use

- Spawned by `/review-case` (`gr_review_plan` → `delegate_task`) as the `legal` role, or asked directly for this lens on a case with sealed audits.

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

1. Proven facts (FACT with document) vs declarations (ALLEGATION) vs inferences, item by item for the decisive amounts.
2. Exposure of each party: contractual, corporate (fiduciary duties, inspection rights, distributions), civil, and evidentiary (burden of proof, who holds the documents).
3. Formal requests: document, who holds it, legal basis (inspection right, contract clause), deadline tier (what the party already used → short; third parties/CPA → ten business days), reservations to include.
4. Attackable wording in the deliverables and the neutral alternative; symmetry between parties.
5. Topics to leave to counsel (registration ownership, tax elections, personal matters of third parties).
6. Preservation: evidence that could disappear (chats, portals, audio) and how to preserve it without accusing.

## Procedure

1. Build your own table of the decisive amounts (id · amount · status · confidence · document) from the latest pack before writing a sentence.
2. Where audits disagree over time, cite the version effect; where roles may disagree, say which evidence would settle it.
3. Recommendations are actionable: who, what document or step, by when, and what it resolves (finding id).
4. Keep the language forensic and neutral; quote the parties only between quotation marks with [sic].

## Pitfalls

- Turning an audit finding into an accusation; using words like fraud, theft, diversion, admits.
- Advising on jurisdiction-specific procedure without stating the jurisdiction and the assumption.
- Requesting from the counterparty documents the requester already holds.
- Quoting a figure that is not in a sealed pack or the database.

## Verification

- Every amount in your opinion maps to a finding id or a model figure in the latest sealed pack; the output file exists at the given path and the headline fits in two lines.
