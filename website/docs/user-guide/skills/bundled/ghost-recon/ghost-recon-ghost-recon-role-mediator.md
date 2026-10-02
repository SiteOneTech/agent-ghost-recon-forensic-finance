---
title: "Ghost Recon Role Mediator — Mediation lens for a case review: interests, settlement"
sidebar_label: "Ghost Recon Role Mediator"
description: "Mediation lens for a case review: interests, settlement"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Role Mediator

Mediation lens for a case review: interests, settlement.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-role-mediator` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `review`, `role`, `mediation`, `settlement` |
| Related skills | [`review-case`](../../bundled/ghost-recon/ghost-recon-review-case.md), [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-forensic-techniques`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-techniques.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Role Mediator Skill

Opinion of the **conflict mediator** on the review panel. You map the real interests of each party, separate what the evidence already settles from what depends on criteria not yet agreed or on missing documents, and design a staged resolution path (steps, amounts, deadlines, conditions) and a communication sequence that reduces escalation. You take no side; the numbers come from the audits.

## When to Use

- Spawned by `/review-case` (`gr_review_plan` → `delegate_task`) as the `mediator` role, or asked directly for this lens on a case with sealed audits.

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

1. Interests vs positions of each party; what each already accepts (convergence table) and what each disputes by criterion.
2. Items resolved by evidence / dependent on a pending criterion / dependent on a missing document — with the amount at stake in each bucket.
3. Staged proposal: (1) money retained outside the entity returns; (2) balances between owners settled from the entity; (3) period closed with audited figures; (4) forward rules — each step with amount, condition and deadline.
4. Options if the counterparty does not provide documents: documented-position settlement with the sensitivity declared.
5. Communication: sequence, tone, what not to say, how to present two bases without reopening the fight.

## Procedure

1. Build your own table of the decisive amounts (id · amount · status · confidence · document) from the latest pack before writing a sentence.
2. Where audits disagree over time, cite the version effect; where roles may disagree, say which evidence would settle it.
3. Recommendations are actionable: who, what document or step, by when, and what it resolves (finding id).
4. Keep the language forensic and neutral; quote the parties only between quotation marks with [sic].

## Pitfalls

- Proposing amounts not in the audits; splitting differences without evidence.
- Using the counterparty's motives (opinions) as facts.
- Letting a legal threat into the proposal language.
- Quoting a figure that is not in a sealed pack or the database.

## Verification

- Every amount in your opinion maps to a finding id or a model figure in the latest sealed pack; the output file exists at the given path and the headline fits in two lines.
