---
title: "Ghost Recon Forensic Techniques — Forensic procedures by mission type for Ghost Recon audits"
sidebar_label: "Ghost Recon Forensic Techniques"
description: "Forensic procedures by mission type for Ghost Recon audits"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Forensic Techniques

Forensic procedures by mission type for Ghost Recon audits.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-forensic-techniques` |
| Version | `2.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `forensic`, `techniques`, `tracing`, `inventory`, `banking` |
| Related skills | [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-deliverables`](../../bundled/ghost-recon/ghost-recon-ghost-recon-deliverables.md), [`ghost-recon-research`](../../bundled/ghost-recon/ghost-recon-ghost-recon-research.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Forensic Techniques Skill

Library of specialized procedures applied according to the nature of the mission: partner and shareholder disputes (competing closings, symmetric error tables, owner position under two bases, liquidation proposals), funds tracing through intermediaries and currencies (pool method), physical flow and inventory, bank and card forensics, payroll and owner compensation, related parties and prior-period items, revenue-recognition tests, FX, anomaly analytics, period continuity, forecast modules, evidence-request lists, standards mapping, due-diligence / litigation / insolvency variants. Full text in `references/techniques.md`.

## When to Use

- A Ghost Recon audit hits one of those situations, or the user asks how to analyze partner positions, trace money, reconstruct inventory, reconcile statements, benchmark freight, set owner salaries or evaluate anomalies.

## Prerequisites

- `ghost-recon-forensic-audit` loaded (critical rules apply to every technique).
- `read_file`, `terminal` (parsers), `gr_finding_upsert`, `gr_research` for benchmarks.

## How to Run

1. Identify the mission type(s) from the case profile.
2. `read_file` the matching sections of `references/techniques.md` (section numbers in the Quick Reference) and apply them.
3. Put the outputs where the technique says (workbook sheet, report section, finding register).

## Quick Reference

| Need | Section |
|---|---|
| Two parties, two closings, owner balance | §1 Partner disputes |
| Money through an intermediary / another country | §2 Pool method |
| Units, lots, landed cost, backlog | §3 Physical flow |
| Statements, cards, unidentified outflows | §4 Bank and card forensics |
| Payroll, contractors, owner pay | §5 |
| Related parties, intercompany, prior year | §6 |
| Revenue recognition by business model | §7 |
| Foreign currency | §8 |
| Duplicates, gaps, concentration, Benford | §9 Anomaly analytics |
| Earlier year, continuity | §10 |
| Forecast / recommendations (outside audit) | §11 |
| Questions for the counterparty | §12 (`Q-nn`) |
| Methodology report standards | §13 |
| Due diligence, litigation, insolvency, whistleblower | §14 |

## Procedure

1. For each technique, state the method used (FIFO vs weighted average, pool period, thresholds) in `model.json` metadata so the report can cite it.
2. Every result lands in the workbook with its source rows and in the report with its confidence label.
3. Benchmarks and market rates come from `gr_research` with URL and date; they are INFERENCE.

## Pitfalls

- Back-solving an opening balance of a circuit; labelling a residual "immaterial" before separating the probable items.
- Presenting an owner's related-party invoices as opex without arm's-length evidence.
- Running Benford on small or heterogeneous populations.

## Verification

- Each technique's control holds (flow closes per model/period; pool reconciles to remittances + applications + residual; statements tie to the cent).
