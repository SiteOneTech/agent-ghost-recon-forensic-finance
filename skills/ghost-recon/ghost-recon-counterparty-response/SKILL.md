---
name: ghost-recon-counterparty-response
description: "Audit a counterparty's reply claim by claim."
version: 1.1.0
author: Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ghost-recon, counterparty, dispute, legal-pack, validation]
    category: ghost-recon
    related_skills: [rerun-case, ghost-recon-evidence-pass, ghost-recon-role-legal, ghost-recon-validation, ghost-recon-deliverables]
---

# Ghost Recon Counterparty Response Skill

When the other party answers an audit with a document (PDF, workbook, email), this procedure checks every claim against the evidence, bridges the differences to the cent, separates what converges / differs by criterion / lacks a document / contradicts a document, and prepares the formal request for what is missing — plus the internal pack for the requester's lawyer. Full procedure, model sections, deliverables, language rules, validation rounds and 20 lessons in `references/counterparty-response.md`.

## When to Use

- A reply from the counterparty arrives (invoked through `/rerun-case <folder> reply-context.md`).
- The requester asks for a letter to the counterparty, a lawyer's pack, a "where is the money" executive, or a chronology from statements and chats.

## Prerequisites

- A sealed base audit; the reply files in the evidence folder; `vision_analyze` for embedded images; `read_file`/`terminal` for page-level extraction.

## How to Run

1. `read_file` `references/counterparty-response.md` fully.
2. Build `03_Extracted_Data/model_respuesta.json` with the mandatory sections; register claims (RA-nn), internal inconsistencies (II-nn) and declarations (DR-nn) also as case findings with `gr_finding_upsert(kind="finding", category="RA"|"II"|"DR")`.
3. Produce the internal pack with `gr_report_build`; produce counterparty-facing documents (letter + two-page annex) as separate files with neutral metadata and no internal codes.
4. Validation rounds A/B/C (C from the counterparty's lawyer/CPA position), then seal.

## Quick Reference

Classification of each claim: CONFIRMA · DIFIERE POR CRITERIO/CORTE · SIN SOPORTE · CONTRADICE EVIDENCIA · CONTRADICCION INTERNA · DECLARACION RELEVANTE · PENDIENTE DE DOCUMENTO · FUERA DE ALCANCE · OPINION. Proof scale applied to both parties: full statement (incorporate) > screenshot + contrasting document (probable) > ledger entry (pending) > declaration (pending); exceptions written into the scale.

## Procedure

1. Intake: hashes, email headers and file metadata as data (no interpretation); what the reply says it has vs what it attaches.
2. Convergence table (only cent-exact matches), bridge from the audit's position to the counterparty's with an assert, adjusted position, scenarios with the range computed over them.
3. Separate "no document" from "contradicted" inside the same item; symmetry for items favouring the requester.
4. Letter: two deadline tiers, reservations, no questions that expose the requester (leave them to the lawyer), no requests for documents the requester already holds, no internal codes in the annex.
5. Lawyer's pack: own model reading the audit models; LEEME with "for whom", decisions pending, privilege line.

## Pitfalls

- "Admite", "reclamo", "amenaza", "ficticio" outside quotation marks; calling validation passes "independent auditors".
- One date per fact across all documents (statement date beats chat date); verifying chat line references one by one.

## Verification

- Bridge asserts close to the cent; every RA/II/DR id exists in the database; counterparty-facing files contain no internal ids and neutral metadata (`pdfinfo`).
