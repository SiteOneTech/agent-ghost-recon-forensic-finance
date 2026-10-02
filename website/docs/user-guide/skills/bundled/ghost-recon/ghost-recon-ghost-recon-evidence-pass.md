---
title: "Ghost Recon Evidence Pass — Procedure for a new evidence batch on an audited case"
sidebar_label: "Ghost Recon Evidence Pass"
description: "Procedure for a new evidence batch on an audited case"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Evidence Pass

Procedure for a new evidence batch on an audited case.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-evidence-pass` |
| Version | `1.3.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `evidence-pass`, `dedupe`, `versioning`, `rerun` |
| Related skills | [`rerun-case`](../../bundled/ghost-recon/ghost-recon-rerun-case.md), [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-deliverables`](../../bundled/ghost-recon/ghost-recon-ghost-recon-deliverables.md), [`ghost-recon-validation`](../../bundled/ghost-recon/ghost-recon-ghost-recon-validation.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Evidence Pass Skill

Step-by-step procedure (v1.3, born on a real case) for processing a new batch of documents on a case that already has sealed deliverables: intake with hashes, two-level dedupe, triage against open exceptions, extraction with the engagement's parsers, exact cross-match, reclassification rules, model with version effect, full regeneration, independent validation, packaging, and the handling of late complements and management criteria (sub-versions). Full text and the list of 22 lessons in `references/evidence-pass.md`.

## When to Use

- Invoked by `rerun-case` after `gr_audit_start(kind="rerun")`.
- Any time a document, a listing or a management clarification arrives after an audit was sealed.

## Prerequisites

- The new audit folder (`Evidence_Pass/register.csv`, `dedupe.json`, `inherited_open_findings.json` written by the plugin; `src/` copied from the previous audit).
- `read_file`, `terminal`, `gr_finding_upsert`, `gr_criteria_add`, `gr_run_record`, `gr_report_build`, `gr_audit_seal`.

## How to Run

1. `read_file` `references/evidence-pass.md` sections 0–10 (and 11 when a late complement or a management criterion is involved).
2. Execute the ten steps inside the new audit folder; never touch the sealed one.
3. Seal and report with the closing message format of §10.

## Quick Reference

| Step | Output |
|---|---|
| 1 Intake | register with hashes (plugin) + who/when (`gr_run_record kind=intake`) |
| 2 Dedupe | `DUP_PRIOR` / `DUP_INTERNAL` / `DUP_CONTENT` / `NEW` / `MODIFIED` |
| 3 Triage | `Evidence_Pass/triage.md`: block, version fed, exception it may resolve |
| 4 Extraction | parsers with tie-outs; provenance |
| 5 Cross-match | exact key both directions; mismatches → exceptions |
| 6 Reclassification | beneficiary ≠ nature; estimates → actuals; prior-year stays non-P&L |
| 7 Model | `model.json` with `version_effect`; findings closed/downgraded/created via `gr_finding_upsert` |
| 8 Regeneration | full pack via `gr_report_build`; §00 addendum; vN notes on stale sections |
| 9 Validation | A / B / C via `gr_swarm_plan(mode="validation")` |
| 10 Closing | seal + message: arrived / resolved / changed / open / who |

## Procedure

Follow the reference; the non-obvious rules: a 100 % duplicate batch is still registered (the hash register is the proof it was reviewed); a management explanation is a declaration, not evidence; a beneficiary proven by the bank does not establish why the money moved; nothing is edited by hand in a deliverable; exception counts are computed; every section whose text went stale gets a vN note, not just a global "read Y for X" rule.

## Pitfalls

- The 22 lessons in the reference (double counting across scenarios, mixed bases, typed counts, stale v1 text, half-up rounding, temp-folder data loss, chat dates vs statement dates).

## Verification

- New audit sealed; previous audit `seal_ok: true`; `version_effect` present in model and workbook; every inherited open exception has an explicit disposition (closed / still open with reason / downgraded).
