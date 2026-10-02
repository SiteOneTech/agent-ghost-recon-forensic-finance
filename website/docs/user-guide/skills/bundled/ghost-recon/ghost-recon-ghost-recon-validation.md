---
title: "Ghost Recon Validation — Independent validators: recompute, consistency, adversarial"
sidebar_label: "Ghost Recon Validation"
description: "Independent validators: recompute, consistency, adversarial"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Validation

Independent validators: recompute, consistency, adversarial.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-validation` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `validation`, `quality`, `adversarial`, `swarm` |
| Related skills | [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-deliverables`](../../bundled/ghost-recon/ghost-recon-ghost-recon-deliverables.md), [`new-open-case`](../../bundled/ghost-recon/ghost-recon-new-open-case.md), [`rerun-case`](../../bundled/ghost-recon/ghost-recon-rerun-case.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Validation Skill

Protocol for the independent validation passes that run before an audit is sealed. Three validators, each a separate `delegate_task` child with no access to the auditor's reasoning: **A** recomputes the headline figures from the raw documents, **B** checks consistency across every deliverable, **C** attacks the work as the counterparty's lawyer and CPA would. They report; they never edit deliverables.

## When to Use

- Your goal says you are Auditor A, B or C for an audit id (spawned from `gr_swarm_plan(mode="validation")`).
- The orchestrator wants a re-validation after fixes.

## Prerequisites

- `read_file`, `terminal` (`pdftotext`, python for recomputation and for dumping workbook cells), `search_files`, `write_file` to the output path.
- A: evidence root and the published headline figures only. B and C: the deliverables and the model.

## How to Run

1. Identify your role from the goal; `read_file` your inputs.
2. Produce the findings JSON at the output path (`validator`, `findings[]`, `verdict` OK | FIX_REQUIRED, `output_path`).
3. Finish with a ten-line summary; the orchestrator records it with `gr_run_record`.

## Quick Reference

| Validator | Looks for | Severity rule |
|---|---|---|
| A recompute | published vs recomputed figure, difference, evidence | material if it changes a headline or an owner balance |
| B consistency | figures differing between md / pdf / xlsx; duplicate ids; typed counts; stale version text; formulas as text; PDF internal arithmetic; placeholders; tool/provider names in text or metadata | material if a reader would reach a different number |
| C adversarial | claims exceeding the evidence (fact vs probable vs declaration); non-neutral wording; asymmetry between parties; requester's exposure; the ten best rebuttals and the document that settles each | material if a rebuttal stands without a document |

## Procedure

1. A: parse the documents yourself (statements to the cent, listings by declared count), recompute each published figure, tabulate figure · published · recomputed · difference · evidence. Check the temporal coverage of every dataset before declaring anything "not verifiable".
2. B: dump every deliverable to text (`pdftotext`; python + openpyxl for cells, including formulas), search for each headline figure and each exception id across all of them, verify counts against rows, check metadata with `pdfinfo` and the workbook `docProps`.
3. C: read as the opposing CPA; for each material claim write the attack, the evidence level actually available, and the wording that would survive it.
4. Rank findings by severity; `verdict = FIX_REQUIRED` if any material finding exists.

## Pitfalls

- Reading the auditor's reasoning (A must not open `model.json`).
- Reporting style preferences as findings; every finding names a location and an expected value.
- Softening a material finding because the fix is costly.

## Verification

- Output JSON validates against the schema in your goal; every finding has `location` (or `figure`), `expected`/`published`, `found`/`recomputed`, `severity`.
