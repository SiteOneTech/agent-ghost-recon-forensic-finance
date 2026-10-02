# Ghost Recon — Deliverables: build, sign, verify, deliver (full reference)

Every Ghost Recon cycle produces the same fixed set: (1) executive PDF, (2) evidence workbook, (3) Markdown report for other agents, (4) methodology-and-standards PDF, plus (5) case-specific documents. All are generated from **one model JSON** by archived scripts, so a figure never exists only in a report and a change in evidence flows to every document by re-running. On Hermes the base pack (md + executive pdf + workbook) is produced by `gr_report_build` from `06_Report/report.md` + `03_Extracted_Data/model.json` + the case database; this reference describes the full professional standard the narrative and any custom generator must meet.

## 1. Toolchain and environment

- Python: `openpyxl` (workbook), `reportlab` (PDF; `matplotlib` for charts), `pdfplumber`/`pdftotext` (extraction), OCR (`pytesseract`/`pdf2image`) or `vision_analyze` for scans, `pandas` for tabular work.
- Keep every generator in `src/`; when you change a generator for a new version, copy the previous one to `<name>_v1.py` first. Backups are part of the audit trail.
- Fonts: a Unicode TrueType family (DejaVu Sans is bundled with the plugin) so accents, "−", "→" and "·" render; never use Unicode sub/superscript characters in PDF generators.

## 2. The model JSON (single source of truth)

`03_Extracted_Data/model.json` holds every figure the deliverables use: units and revenue by customer/model/month, purchases and COGS by lot with method (FIFO / weighted average), freight, opex by category with basis (cash / accrual / estimated), payroll, cards, other income, non-P&L movements, collections by channel, intermediary pool and applications, closing stock by model, owner receipts and balances, exceptions summary, and metadata (version, date, cut-off, sources). Keys the plugin reads: `kpis` (cover tiles and dashboard), `audit_trail` (figure · value · sheet · documents · confidence · method), `version_effect` (reruns: item · previous · new · difference · document · sheet). Sub-agent outputs (`agents/out_*.json`, `manifest_*.json`) and the independent auditor outputs (`validation/out_auditor_*.json`) live beside it. All report builders read the JSON; none hard-codes a number.

## 3. Evidence workbook (XLSX)

Palette: NAVY header, light-grey bands, amber for "probable"/open, red for "unreconciled", green for "confirmed"/closed. Number formats MONEY `#,##0.00`, INT `#,##0`, PCT `0.0 %`. Guard: a string that *starts with "= "* (space) is a label and must be written as text, while real formulas (`=SUM(...)`) stay formulas. Freeze panes below headers; every sheet's first two rows are title and subtitle with the version.

Sheet catalog (adapt; never create empty sheets):

| Sheet | Content |
|---|---|
| 00_README | Scope, period, cut-off, base currency, version history, criteria register, limitations, sheet index, validation rounds summary, signature |
| 01_CASE_PROFILE | Entities, jurisdictions, owners and percentages, accounts, processors, cards, lenders, reason for the investigation |
| 02_DOCUMENT_INDEX | One row per file; hash; duplicate flag; OCR/visual status; confidence |
| 03_ENTITIES · 04_ACCOUNTS | Entity/relationship map; account map |
| 05_BANK_TRANSACTIONS · 06_CREDIT_CARDS | RAW and normalized; per-statement tie-out block (opening, inflows, outflows, closing, difference = 0.00) |
| 07_REVENUE · 08_BILLINGS · 09_COLLECTIONS · 10_AR | Recognition on delivery/performance; matches 1:1/1:n/n:1/n:m; advances; unbilled; credit notes |
| 11_PURCHASES · 12_AP · 13_COGS | By lot/shipment with unit cost method; unbilled receipts; in-transit; landed cost |
| 14_OPEX · 15_PAYROLL · 16_CAPEX · 17_LOANS · 18_TAXES | Categorized with basis; cards integrated once; principal vs interest |
| 19_INTERCOMPANY · 20_RELATED_PARTIES · 21_OWNER_MOVEMENTS | One block per owner; each movement typed and evidenced |
| 22_FX | Original amount, currency, executed rate, source, base amount |
| 23_NON_PNL · 24_PRIOR_PERIOD | Movements outside current-period profit; prior-period settlements |
| 25_RECONCILIATION · 26_PNL · 27_CASH · 28_BALANCE | Bridges by two methods; expected vs demonstrated cash; balance items where evidence allows |
| 29_ANOMALIES · 30_EXCEPTIONS | Registers with IDs, risk, status, who supplies evidence (from the DB) |
| 31_AUDIT_TRAIL | Every headline figure → sheet → documents → confidence → method |
| 3x_VERSION_EFFECT | One per evidence pass: item, previous, new, document that caused the change |
| 3x_PARTNER_POSITION | Ownership % as an input cell; formulas compute each owner's share, received, balance; two bases when a criterion is pending |
| 32_DASHBOARD | KPIs, the "numbers not to mix" table, exception counts (formulas), validation status |

Order the sheets for the reader. Set workbook properties (creator, title, subject, description, keywords) and a print footer on every sheet with the Ghost Recon signature and page numbers; `docProps/app.xml` must read as Ghost Recon (the plugin rewrites it). Counts of exceptions are formulas over the register, never typed.

## 4. Executive audit report (PDF)

Two page templates: `cover` (navy band, title shrink-to-fit, subtitle, meta lines, four KPI tiles, confidentiality line left and "Generado por Ghost Recon · www.ghostrecon.ai" right) and `normal` (header band with title · Confidential; footer with "Documento complementario: <workbook>" left, "Página N de M" right, signature line below). Text is never drawn at a width you have not measured: wrap and fit.

Page plan (8–10 pages; no near-empty page):

1. Cover with the four numbers that matter.
2. **The answer in one page**: lead paragraph; KPI tiles ("these numbers are different and must not be mixed"); the main table (the two competing versions vs evidence, or the P&L bridge); callout with the 3–4 figures that decide the rest; evidence base table (source, what it gives, control).
3–6. Findings by materiality, one per page: price/cost compression by shipment; physical flow of goods; money circuit (stacked bar source → applications → unexplained); consolidated cash reconciliation table (expected vs demonstrated); owner/partner position with chart and scenario table.
7. What remains open: numbered questions for the party who holds the evidence, each with the amount at stake; "does an earlier period need auditing" callout when applicable.
8–9. Risks ordered by materiality; immediate actions; 30/90-day plan; how the report was built and validated; indicators table; scope note (evidence-only; describes differences as unreconciled; attributes no intent).

Charts (matplotlib, transparent PNG, 200 dpi, one palette): waterfall from sales to profit; grouped bars for period comparison; stacked horizontal bar for money circuits; price vs cost lines per model; owner bars vs the 50 % line. Before finalizing, render the chart at page scale and check no label overlaps. Insert charts in the narrative Markdown as images only if your custom generator supports them; otherwise ship them as separate PNGs in `06_Report/charts/` and reference them.

Metadata: title, author "Ghost Recon (www.ghostrecon.ai)", subject, creator, producer "Ghost Recon Audit Engine", keywords; no library comments (the plugin blanks them).

## 5. Markdown audit report (for other agents and archives)

Structure: title block (entity, period, base currency, preparation date, companion workbook, version line, neutrality note — the plugin writes it); **§00 addendum for the latest version** (what evidence arrived, a table previous → new → why, cross-check against any manual audit supplied by a party, errors of each party, what stays open, a "where the rest of the report cites X read Y" note); §0 addendum of the prior version; then the numbered body: executive summary; scope; cut-off; documents reviewed; business model; revenue; purchases/cost; gross margin; opex; cost centers; payroll; collections; banks and intermediaries; FX flows; non-P&L movements; prior-period liabilities; profit (Result A); cash reconciliation (Result B); owner position (Result C); exceptions; missing evidence; risks; conclusions; recommended actions; special analyses; **annex: the answer in one page**; signature. Tables in GitHub-flavored Markdown; every amount with its source sheet; version addenda never rewrite history — they redirect. Write this body in `06_Report/report.md`; the plugin appends the DB annexes and the signature.

## 6. Methodology and standards report (PDF)

Written for the professional who will challenge the work. Sections: purpose and audience; nature of the engagement (a two-column "this IS / this is NOT" table: complete documentary reconstruction and factual findings vs. no ISA/GAAS opinion, no fraud investigation, no legal/tax advice, not a CPA firm); how Ghost Recon processes a case (stage · what the system does · control · verifiable output); **standards taken as reference** with issuer and *how each was applied here* (list in `ghost-recon-forensic-techniques` §13) — always phrased as "applied as reference for good practice, adapted to a non-statutory forensic engagement; no formal compliance or certification is claimed"; forensic principles with their concrete application; procedures by block with control of completion; evidence hierarchy and qualification table; traceability, chain of custody and reproducibility; quality assurance and independent validation (what the validators found and how it was fixed); AI governance and human oversight; **independence disclosure** (who commissioned the work, whether they develop the tool, safeguards, invitation to the other party to contradict with documents, no contingent fee); limitations (limitation · effect · mitigation); a step-by-step reviewer's guide; the Ghost Recon declaration; annex of deliverables with versions. Write it as `06_Report/methodology.md` and build it with `gr_report_build(report_md=..., title="Metodología y estándares — <caso>", formats=["pdf"])`.

## 7. Optional documents

- **Complementary long-form report**: methodology of the period, block-by-block detail, scenarios, the two competing closings line by line, exceptions, questions, validation rounds, sheet index.
- **Recommendations / forecast**: only when requested and always outside the audit; recompute any forecast supplied by a party from its own cost sheet, state the opex base used, present scenarios, benchmark inputs against public market data with sources (`gr_research`), and include governance rules, KPIs and a 90-day plan; disclaimer: not tax or legal advice.
- **Evidence-request list** for a counterparty: numbered, each with who answers, exact document, and amount at stake.
- **Continuity note** across periods and the case for auditing an earlier period.

## 8. Signing and metadata (every file, every time)

Footer/cover signature: "Generado por Ghost Recon · Sistema de auditoría asistida por IA · https://www.ghostrecon.ai/" (short form on covers: "Generado por Ghost Recon · www.ghostrecon.ai"). Metadata: author "Ghost Recon (www.ghostrecon.ai)", creator "Ghost Recon — Sistema de auditoría asistida por IA · https://www.ghostrecon.ai/", producer/application "Ghost Recon Audit Engine", title, subject/description, keywords. Final check on every delivered binary: no provider or library name (the plugin's `gr_report_build` scans and warns; fix before sealing).

## 9. Visual QA loop (mandatory before delivery)

Render every PDF page to PNG (`pdftoppm -r 60`) and look at them with `vision_analyze`. Check: cover text inside the margins; KPI tiles with no overlap; no page that is mostly empty; tables whose narrow columns wrap instead of overflowing; chart labels not colliding; footers with the right version numbers; version wording consistent across cover, footers and body; charts rebuilt from the current model. Fix, rebuild, re-render.

## 10. Consistency checks between deliverables

Before sealing, cross-check: headline figures in the model JSON = dashboard = executive PDF text = MD report = methodology annex; exception counts and highest EXC-id match across workbook, PDF and MD; version labels identical everywhere; the independent auditors' findings are all marked fixed/explained; no figure from a previous version survives in explanatory cells.

## 11. Delivery

The pack lives in `06_Report/` of the audit folder (next to the evidence, never inside it); `LEEME.md` states for whom each file is and `pack_hashes.txt` carries the SHA-256 of each deliverable. Seal with `gr_audit_seal`. Close with a short message: the headline answers, what changed with the last evidence, what remains open and who must provide it, and any temporary folder the user may delete.
