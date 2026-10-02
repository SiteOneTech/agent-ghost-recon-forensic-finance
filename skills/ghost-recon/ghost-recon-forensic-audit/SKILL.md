---
name: ghost-recon-forensic-audit
description: "Ghost Recon forensic audit method, phases and rules."
version: 2.0.0
author: Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ghost-recon, forensic, audit, method, reconstruction]
    category: ghost-recon
    related_skills: [ghost-recon-forensic-techniques, ghost-recon-deliverables, ghost-recon-evidence-pass, ghost-recon-block-auditor, ghost-recon-validation, new-open-case]
---

# Ghost Recon Forensic Audit Skill

The mission playbook of Ghost Recon: how to turn a folder of fragmented financial evidence into a traceable reconstruction of what economically happened, what money moved, what involved owners or related parties, what is proven, inferred or unexplained, and which document would resolve the rest. The full method (identity, five realities, 12 critical rules, 17 phases, evidence hierarchy, validation, deliverables, completion criteria) is in `references/method.md` — read it fully with `read_file` the first time a case starts and again whenever a phase is unclear.

## When to Use

- Any forensic audit, financial reconstruction, partner or shareholder dispute, "where did the money go", cash shortfall, due diligence from documents, related-party review, or "audit this folder" request.
- Loaded by `new-open-case` and `rerun-case`; block auditors and validators load their own skills instead.

## Prerequisites

- An open audit folder from `gr_audit_start` (the plugin inventories the evidence with SHA-256/MD5).
- `read_file`, `search_files`, `terminal`, `vision_analyze`, `delegate_task`; the `ghost_recon` toolset.

## How to Run

1. `read_file` `references/method.md` (≈ 15 minutes of reading; do not skim — the rules are the product).
2. Apply the phases in order (Quick Reference). Record criteria with `gr_criteria_add`, findings with `gr_finding_upsert`, runs with `gr_run_record`.
3. Keep every derived artefact inside the audit folder (`03_Extracted_Data/`, `src/`); session temp folders do not survive.

## Quick Reference

| Phase | What | Control |
|---|---|---|
| 1–2 Discovery, document index | read contents, not names; OCR with visual check | files on disk = rows (`gr_evidence_index`) |
| 3 Entity / account maps | relationships only when evidenced | no ownership inferred from money |
| 4–5 Extraction, normalization | RAW per source with provenance; statements tie to the cent | listings match declared counts |
| 6–8 Business model, revenue, costs | recognition on transfer of control; cards integrated once | no order+invoice+deposit triple count |
| 9–11 Cash, balance, owners | expected vs demonstrated cash; one reconstruction per owner | profit ≠ cash ≠ owner balance |
| 12–13 Matching, reconciliation | chains contract→…→deposit; bridges by two methods | every broken link = exception |
| 14–15 Anomalies, exceptions | signals, not conclusions; `EXC-nn` with next evidence and owner | counts computed, never typed |
| 16–17 Dashboard, deliverables | `model.json` kpis + audit_trail; `ghost-recon-deliverables` | every figure traceable |

Labels: FACT / CALCULATION / INFERENCE / ALLEGATION / UNKNOWN. Confidence: CONFIRMED / HIGHLY_PROBABLE / PROBABLE / POSSIBLE / UNRESOLVED. Language: unexplained, unreconciled, undocumented, unsupported — never fraud, theft, diversion.

## Procedure

1. Intake: establish entities, period, currency, owners, accounts, reason; ask once (one message) only what changes the work; unattended → state assumptions on top of the report.
2. Business model first; map where cash physically travels.
3. Phases 1–16 with the controls above; sub-agents for large blocks (`ghost-recon-block-auditor` via `gr_swarm_plan`).
4. One `model.json`; every deliverable reads it (`ghost-recon-report-pack`).
5. Independent validation (`ghost-recon-validation`) before sealing.
6. Closing message: headline answers, what changed, what is open and who supplies it.

## Pitfalls

- Answering "how much cash should there be" with a profit figure.
- Forcing matches on similar amounts; adjusting a figure so a reconciliation balances.
- Assuming the nature of a payment from the beneficiary; treating a transfer to a person as payroll without a register.
- Adopting a party's criterion silently instead of registering it as `CRIT-nn` and showing both bases.

## Verification

- Completion criteria of `references/method.md` §14 all met; `gr_audit_seal` reports `complete: true` without `force`.
