---
title: "Review Case — Case chronology plus six-role diagnosis and recommendations"
sidebar_label: "Review Case"
description: "Case chronology plus six-role diagnosis and recommendations"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Review Case

Case chronology plus six-role diagnosis and recommendations.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/review-case` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `forensic`, `review`, `roles`, `diagnosis`, `orchestrator` |
| Related skills | [`ghost-recon-role-legal`](../../bundled/ghost-recon/ghost-recon-ghost-recon-role-legal.md), [`ghost-recon-role-tax`](../../bundled/ghost-recon/ghost-recon-ghost-recon-role-tax.md), [`ghost-recon-role-financial`](../../bundled/ghost-recon/ghost-recon-ghost-recon-role-financial.md), [`ghost-recon-role-auditor`](../../bundled/ghost-recon/ghost-recon-ghost-recon-role-auditor.md), [`ghost-recon-role-accounting`](../../bundled/ghost-recon/ghost-recon-ghost-recon-role-accounting.md), [`ghost-recon-role-mediator`](../../bundled/ghost-recon/ghost-recon-ghost-recon-role-mediator.md), [`ghost-recon-report-pack`](../../bundled/ghost-recon/ghost-recon-ghost-recon-report-pack.md), [`new-open-case`](../../bundled/ghost-recon/ghost-recon-new-open-case.md), [`rerun-case`](../../bundled/ghost-recon/ghost-recon-rerun-case.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Review Case Skill

Orchestrates `/review-case <folder>`: builds the consolidated **chronology** of every audit of the case (evidence batches, what changed, exceptions opened/closed/downgraded, criteria, validation rounds) and runs a **panel of six roles** — legal, tax, financial, auditor, accounting, conflict mediator — in parallel; then writes the **diagnosis** with prioritised recommendations and seals the review in `reviews/R0n_<date>/`.

## When to Use

- The requester asks for "the state of the case", an opinion, a diagnosis, "what should we do now", "prepare the meeting with the lawyer", or a cross-audit summary.
- At least one audit of the case is sealed.

## Prerequisites

- Plugin `ghost-recon` enabled; `delegate_task` available.
- Role skills installed: `ghost-recon-role-legal`, `-tax`, `-financial`, `-auditor`, `-accounting`, `-mediator`; `ghost-recon-report-pack`.

## How to Run

1. `gr_case_open(folder)` (loads the case; no audit is started).
2. `gr_review_plan(case_id)` → `review_id`, `folder`, `chronology_md`, `delegate_tasks` (six roles).
3. One `delegate_task` call with the six tasks; wait for all; `read_file` each `roles/<role>.md`.
4. Write `diagnosis.md`, build the pack, record a consistency validation, seal.

## Quick Reference

| Role | Skill | Lens |
|---|---|---|
| legal | `ghost-recon-role-legal` | proven facts vs declarations, exposure, what to request, attackable wording |
| tax | `ghost-recon-role-tax` | fiscal effects of reclassifications, filings, jurisdiction risks |
| financial | `ghost-recon-role-financial` | cash and profit position, sensitivities, owner balances, ranges |
| auditor | `ghost-recon-role-auditor` | evidence coverage, confidence levels, further procedures |
| accounting | `ghost-recon-role-accounting` | entries, policies, differences with the parties' books, controls |
| mediator | `ghost-recon-role-mediator` | interests, convergence, staged settlement proposal, communication |

## Procedure

1. `read_file` the chronology (`chronology.md`) and the latest sealed pack's md report so your synthesis rests on the same facts the roles see.
2. Dispatch the six roles exactly as returned in `delegate_tasks` (each child loads its skill with `skill_view`). Do not run them sequentially unless `delegation.max_concurrent_children` forces a second wave.
3. Read every role output. Where two roles disagree, keep both positions and say which evidence would settle it.
4. Write `diagnosis.md` in the review folder with: one-page answer; established facts (FACT) vs inferences vs allegations; what changed between audits (from the chronology); risk map by role ordered by materiality; recommendations (action · owner · deadline · what it resolves); the decisive items and who must provide which document; disclaimer (not formal legal or tax advice).
5. `gr_report_build(review_id)` → review md (diagnosis + role opinions + chronology), pdf and workbook (chronology sheets). Visual QA of the pdf.
6. `gr_run_record(review_id, kind="validation", role="B", status="done", summary=…)` after checking that every figure quoted in the diagnosis exists in the sealed packs.
7. `gr_audit_seal(review_id)`; closing message with the headline diagnosis and the top three actions.

## Pitfalls

- Recomputing the audit model inside the review: the review interprets sealed audits, it does not re-audit (new evidence → `/rerun-case`).
- Letting one role's conclusion answer another's question (profit ≠ cash ≠ owner balance ≠ legal entitlement).
- Quoting a figure that is not in a sealed pack or the database.

## Verification

- `gr_case_status` shows the review sealed with `seal_ok: true`; `reviews/R0n_<date>/roles/` holds six files; `06_Report/` holds the review md, pdf, workbook and the chronology workbook.
