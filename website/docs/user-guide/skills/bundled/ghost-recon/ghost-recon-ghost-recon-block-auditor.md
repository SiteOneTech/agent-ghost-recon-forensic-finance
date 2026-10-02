---
title: "Ghost Recon Block Auditor — Swarm child protocol: extract one evidence block"
sidebar_label: "Ghost Recon Block Auditor"
description: "Swarm child protocol: extract one evidence block"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ghost Recon Block Auditor

Swarm child protocol: extract one evidence block.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/ghost-recon/ghost-recon-block-auditor` |
| Version | `1.0.0` |
| Author | Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ghost-recon`, `swarm`, `subagent`, `extraction`, `provenance` |
| Related skills | [`ghost-recon-forensic-audit`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-audit.md), [`ghost-recon-forensic-techniques`](../../bundled/ghost-recon/ghost-recon-ghost-recon-forensic-techniques.md), [`new-open-case`](../../bundled/ghost-recon/ghost-recon-new-open-case.md), [`rerun-case`](../../bundled/ghost-recon/ghost-recon-rerun-case.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ghost Recon Block Auditor Skill

Protocol for a swarm child spawned by `delegate_task` from a `gr_swarm_plan(mode="extraction")` plan. You receive one manifest (a block of evidence files with absolute paths and hashes), extract every transaction and document attribute with provenance, apply the mandatory tie-outs, and write one JSON output. You do not consolidate, you do not conclude, you do not write reports.

## When to Use

- Your goal names a block (`banking`, `commercial`, `supply`, `related_parties`, `correspondence`, `ocr_vision`, `other`) and a manifest path.

## Prerequisites

- `read_file` (text, CSV, JSON), `terminal` (`pdftotext -layout`, python with pdfplumber/openpyxl), `vision_analyze` (images, scans), `write_file`.
- Never `web_search` in this task; never touch the evidence files (read only); write only to the output path and the working-copies folder named in your context.

## How to Run

1. `read_file` the manifest; read the case context file if it exists.
2. Process every file in the manifest (content, not file names). Unreadable files go to `files_unreadable` with the reason.
3. `write_file` the output JSON at `output_path`; answer with the summary fields of the output schema.

## Quick Reference

Output JSON keys: `block`, `files_processed`, `files_unreadable[]`, `transactions[]` (id, date, posting_date, account, entity, counterparty, description, amount_original, currency, debit, credit, amount_base, category, related_party, source_doc, page_or_row, confidence), `documents[]` (rel, doc_type, doc_date, entity, counterparty, reference, currency, amount, period, review_status, confidence, notes), `tie_outs[]` (document, opening, inflows, outflows, closing, difference), `discrepancies[]` (file, description, amount, why), `summary`.

| Block | Mandatory control |
|---|---|
| banking | each statement: opening + inflows − outflows − fees = closing to the cent; listings: parsed rows = declared rows; card statements: parsed charges = "new charges" total |
| commercial | invoice ↔ order ↔ delivery note linked by number; credit notes separated; advances flagged |
| supply | received units from dispatch documents, not invoices; freight/customs attributable per shipment |
| related_parties | every document: who pays, who receives, documented purpose, date, amount; nature stays "pending" without agreement |
| correspondence | facts with line/date reference; declarations quoted literally with [sic]; no interpretation |
| ocr_vision | OCR plus visual verification; mark which method read each figure |

## Procedure

1. Open each file fully; for PDFs use `terminal` with `pdftotext -layout <file> -` and fall back to `vision_analyze` on page images when text is empty or garbled.
2. Extract RAW as seen: original currency, executed rate when printed, page or row.
3. Classify only what the document proves; everything else `confidence: UNRESOLVED` and a discrepancy entry.
4. Run the block control; a failed control is a discrepancy, never a rounding.
5. Write the output; keep text extractions in the working-copies folder for the consolidator.

## Pitfalls

- Guessing a counterparty from a similar name; netting transfers between accounts; counting a card payment as an expense.
- Inventing an opening balance or an exchange rate.
- Summarising instead of extracting ("about 40 invoices") — every row counts.

## Verification

- `files_processed + len(files_unreadable) == len(manifest.files)`; every transaction has `source_doc` and `page_or_row`; every statement has a tie-out row.
