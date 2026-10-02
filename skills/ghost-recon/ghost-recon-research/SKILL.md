---
name: ghost-recon-research
description: "External research agent with forensic provenance rules."
version: 1.0.0
author: Jean C. Garcia (Sitio Uno / Ghost Recon) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ghost-recon, research, osint, tavily, counterparty, benchmarks]
    category: ghost-recon
    related_skills: [ghost-recon-forensic-audit, ghost-recon-forensic-techniques, new-open-case]
    config:
      - key: ghost_recon.research_max_results
        description: Default number of search hits per query
        default: 8
---

# Ghost Recon Research Skill

The investigation agent of Ghost Recon: external research that supports a forensic audit without contaminating it. It identifies counterparties and their relationships, checks public registries and sanctions/PEP lists, documents market references (exchange rates, freight, price benchmarks), finds official documents, and records every result with URL, date, hash and the confidence it deserves. A web result is INFERENCE unless it is an official record; it never replaces a document from the case file.

## When to Use

- A finding depends on who a counterparty is, whether two entities are related, what an official rate or tariff was, whether a company exists or is sanctioned, or what a public filing says.
- A benchmark is requested (freight per kg, price lists, interest rates) for the recommendations module.

## Prerequisites

- `TAVILY_API_KEY` in the Hermes `.env` (used by `gr_research`; `web_search`/`web_extract` also route through Tavily when `web.backend: tavily`).
- An `audit_id` to attach notes to (`gr_research(..., audit_id, save=true)`).

## How to Run

1. Write the research question as a hypothesis with the finding id it serves (e.g. "EXC-07: is Beneficiary X an entity linked to owner Y?").
2. `gr_research(action="search", query=…, options={search_depth: "advanced", topic: "general"|"news"|"finance", max_results, include_domains, time_range}, audit_id)`; follow with `action="extract"` on the 2–5 most relevant URLs; `crawl`/`map` for registries or document portals; `research` for a multi-step question when the account exposes it.
3. Record the conclusion in the finding (`gr_finding_upsert` → `evidence_refs` with the saved research file and URLs; `label: INFERENCE` unless an official document was obtained).

## Quick Reference

| Need | Query pattern | Source priority |
|---|---|---|
| Entity identity | legal name + jurisdiction + "registro mercantil" / "secretary of state" / "sunbiz" | official registry > press > directories |
| Relationship between entities | shared officers, addresses, domains, phone | registry filings > websites > social |
| Sanctions / PEP | name + "OFAC" / "sanctions" / official lists | official list only |
| Exchange rates | currency pair + date + central bank | central bank > reputable aggregator |
| Freight / price benchmarks | lane + period + "air cargo rate" / "LCL rate" | indices with date |
| Public filings, court records | name + docket / "demanda" / "lawsuit" | court portal > press |

## Procedure

1. Separate what the case file already proves from what research may add; never research to replace a missing bank document.
2. Prefer official and primary sources; `extract` them and save; cite URL and access date in the report.
3. Classify the result: official record obtained → FACT (with the document hash); consistent secondary sources → PROBABLE/INFERENCE; single unverified page → POSSIBLE.
4. Record negative results too ("no registry entry found for X in jurisdiction Y on <date>").
5. Keep personal data of third parties out of deliverables unless it is the subject of the finding.

## Pitfalls

- Treating a news article or a directory listing as proof of ownership.
- Researching the requester's own counterparty with queries that reveal the dispute unnecessarily.
- Forgetting to pass `audit_id`: unsaved research has no provenance.

## Verification

- Every research-based statement in the report has a `research_notes` row (URL, date, saved file) and a confidence label.
