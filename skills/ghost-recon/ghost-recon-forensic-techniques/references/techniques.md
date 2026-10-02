# Ghost Recon — Forensic techniques by mission type (full reference)

These procedures supplement the mission playbook (`ghost-recon-forensic-audit`). Pick the ones the case needs; each one ends with what to put in the workbook and the report. All of them obey the critical rules: evidence first, exact matches only, no invented rates or balances, factual language, symmetry between parties, confidence on every conclusion.

## 1. Partner and shareholder disputes

**Competing versions.** When each party supplies its own closing or manual audit, transcribe both to the cent into a comparison sheet (item · version A · version B · evidence · what the evidence says). Reconstruct the period independently first, then reconcile each version to the evidence line by line. Publish an "errors and omissions of each party" table with the same depth for both (double deductions, omitted opening stock or expenses, revenue recognized on orders instead of deliveries or on cash instead of deliveries, prior-year unit costs applied to current-year units, inventory without physical support, unreconciled bank balances, an item counted twice, supplier amounts above invoice). Never describe an error as intentional.

**Owner position.** For each owner: documented percentage; participation in the reconstructed profit of each period; what they received through the entity's accounts (documented) and through intermediaries (documented or probable); what was retained outside the entity's accounts in their sphere of control; loans both ways; salary/compensation only when evidenced as such; reimbursements; prior-period settlements (a payment in year N+1 that liquidates a balance of year N is not year N+1 profit); unclassified transfers. Balance = participation − received − retained, per period and cumulative.

**Two bases when a criterion is pending.** If a treatment the parties have not agreed changes the split (e.g., whether equipment stripped for a separately-run workshop is a company cost center), compute the position under each basis (e.g., "entity basis" including the cost center, "core-business basis" excluding it), show both in every deliverable, and mark the criterion "pending agreement". Recommend a basis only with the reason.

**Liquidation proposal.** Ordered steps subject to the open questions: (1) money retained outside the entity returns to the entity's account; (2) balances between owners are settled from the entity's account; (3) the period is closed with the audited figures; (4) forward rules (all collections to the entity's account, formal distributions, owner pay through payroll). Quantify each step and the amounts that could still move the numbers (unidentified outflows, unbilled purchases, in-transit goods).

**The "three questions" framing** (earned / should have / attributable to each) heads the executive report; never let one of them answer another.

## 2. Tracing funds through intermediaries, countries and currencies

Use the **pool method** per period: pool collected by the intermediary (from the customer's receipts/screenshots, in original currency with the executed rate) − remittances to the entity's accounts (matched 1:1 to bank credits) − documented applications paid from the pool (supplier invoices paid by the intermediary, other parties, owner payments) − probable applications (declared and consistent with documents, e.g. a supplier confirming no balance owed while shipments exceed invoices) = **retained without documented application**. Show the chain as a stacked bar: remitted · applied (documented) · applied (probable) · unexplained.

Each link carries amount, currency, date, sending and receiving account, document, confidence and relationship. Remittances without an identified originator but with the intermediary's characteristic fee or amount pattern are HIGHLY PROBABLE, not CONFIRMED. The opening balance of the circuit is UNKNOWN unless a statement proves it; say so and never back-solve it. The residual is reported as unreconciled with its share of the pool; label it "immaterial" only below 1 % and after the probable items are explicitly separated.

Ask for: the intermediary's statements for the period, a signed reconciliation between intermediary and customer, and wire advices for every outbound transfer from the entity's bank whose beneficiary is not printed on the statement.

## 3. Physical flow and inventory (product businesses)

Close the flow per model and period: opening stock + received from factory (third-party dispatch export or shipping documents, not invoices) + pilots/samples returned − units to parts/demo/development/substitution (management's destination report, applied as a cost center) − delivered to customers (delivery notes, packing lists, serials) = closing stock. Cross the received units against supplier invoices: **received-not-invoiced** (value at the adjacent lot prices, give the range, presume paid outside the entity's accounts only when a party confirms no balance is owed — and then it is an application of the pool in section 2) and **invoiced-not-received** (in transit or pending; value at invoice).

Cost per lot: FIFO for models with few lots and clear sequence; weighted average when lots blend; state the method per model. Landed cost = factory + attributable freight/customs; freight not attributable to sales goes to the cost center it served. Backlog = ordered and collected but not delivered (a customer advance, a liability, never revenue); reconcile with available stock — a backlog larger than the stock that could cover it is a finding.

Price vs cost by shipment: for each delivery, sale price, lot cost, freight/unit, opex/unit (period opex ÷ units) → net per unit; show margin compression when a fixed sale price met rising factory prices, and test whether the new price list restores margin.

Freight benchmarking (only when asked or when freight per unit is clearly off): compute the forwarder's implied $/unit and $/kg from invoices, compare with public air-cargo indices and sea LCL/FCL rates for the lane and period (cite the source and date — `gr_research`), add nationalization costs explicitly, and recommend quoting per kg, sea for predictable volume, Incoterm clarity and a freight-to-sales cap.

## 4. Bank and credit-card forensics

Parse each statement by section; prove opening + deposits − withdrawals − fees = closing to the cent before using it — a statement that does not tie is an exception, not a rounding. Classify every movement by exact amount + date + counterparty against invoices, orders, payroll registers and card statements; rules such as "fixed monthly amount to the same beneficiary" become a category only after the beneficiary is evidenced (rent, salary); until then they are "recurring, beneficiary unidentified". List every outflow above a threshold without a printed beneficiary; the fix is the bank's wire advices, request them explicitly with dates and amounts. Never count card-balance payments as expenses when card lines are already recognized. Flag personal-looking merchant categories on corporate cards for the owner reconstruction, without asserting they are personal.

Gaps: missing statement months, statements for accounts that appear only as counterparties, check numbers missing from the sequence.

## 5. Payroll, contractors and owner compensation

Reconstruct payroll from the provider's debits (wages, taxes, fees) and registers; contractors from invoices; never treat a transfer to a person as payroll without a register or invoice. Owner "license", "consulting" or "software" invoices paid to an owner's entity are related-party payments whose economic nature (distribution, compensation, settlement) must be established from agreements and both parties' closings; present them in the owner reconstruction, not in opex, unless evidenced as arm's-length services. When asked for a recommendation on owner salaries, apply the reasonable-compensation logic: a fixed salary through payroll sized to the role and to normalized profit (state the cap you use), reviewed quarterly, with the remainder distributed formally after a cash reserve (months of opex plus committed supplier prepayments); explain why "no salary" and "profit-sized salary" both distort the P&L and the partner balance; mark it as administrative guidance, not tax advice.

## 6. Related parties, intercompany and prior-period items

Identify every entity linked to an owner or executive (shared name, address, signatory, ownership statement, counterpart in agreements). Present each related-party flow separately: who paid, who received, why, documented purpose, accounting and economic treatment, evidence. Intercompany transfers cancel in consolidation but create receivables/payables/loans/capital movements in each entity; keep both views. Payments in the current period that settle prior-period liabilities (supplier invoices of last year, owner balances, taxes, loans) are non-P&L now; list them and reduce the prior-period balance accordingly.

## 7. Revenue-recognition tests by business model

Product: recognized on delivery (delivery note/packing list/serials), at order price; orders and invoices without delivery are backlog/advances; deliveries without invoice are unbilled revenue (liability to invoice, exposure). Services: on performance evidence (reports, acceptance, hours); retainers deferred. Subscriptions/SaaS: processor settlement reports are the collection source; revenue by service period; refunds and chargebacks netted; deferred revenue for prepaid periods. Projects: milestones/acceptance; WIP and billings in excess. Commissions/marketplace: gross vs net presentation decided by control. Test cut-off around period ends and credit notes issued after the cut-off.

## 8. Foreign currency

Keep original amount, currency, executed rate, rate source, conversion date and base amount on every item; use the receipt's own factor when the customer pays in local currency to an intermediary; never apply a market rate to a documented executed conversion; if no rate is documented, keep the original currency and open an exception. Track the drift of the factor over time and any FX gain/loss trapped in the intermediary rather than in the entity.

## 9. Anomaly analytics

Duplicates: same amount + date + reference or vendor; same invoice number with different amounts; same document supplied twice (hash). Round-amount outflows to individuals; sub-threshold splitting; weekend/holiday activity; new beneficiaries in the last months; numbering gaps in invoices, delivery notes or checks; vendors sharing an owner's address/phone; supplier price jumps between lots; margin shifts by shipment; refunds/reversals; deposits without a revenue counterpart; customers paying third parties. Benford's law only on large homogeneous populations and only as a screening signal. Concentration (customer, supplier, beneficiary) and monthly trends to find what single documents hide. Every anomaly enters the register (`gr_finding_upsert(kind="anomaly")`) with a benign explanation considered and the evidence that would settle it.

## 10. Continuity between periods and when to audit an earlier year

Link periods by closing/opening stock, backlog, receivables/payables, prior-period liabilities and the intermediary pool carry-over. Recommend auditing an earlier period when any of these lacks origin: opening stock with no purchase trail; a party invokes "balances from before"; large inflows or outflows in the earlier year's statements without documents; shipments without a payment trail; opening balances of the circuit. State the specific items and amounts that the earlier audit must resolve.

## 11. Forecast and management-recommendation module (outside the audit)

Only when requested. Recompute any forecast a party supplied from its own cost sheet (unit cost + freight + fees per line); show the party's figure and the recomputed one; scenarios by the dominant driver (freight per unit, factory price, volume); opex base from the audited periods (annualized when YTD); recurring service contracts shown separately with their renewal risk; KPIs (margin after landed cost, freight/sales, opex per unit, receivable days, cash retained outside the entity = 0, monthly close done); governance rules; 90-day plan with owners. Always: not tax/legal advice; validate with the entity's accountant.

## 12. Evidence-request lists (for the party who holds the evidence)

Numbered (`Q-nn` via `gr_finding_upsert(kind="question")`); each item: who answers, the exact document (account, month range, invoice numbers, beneficiary), what it resolves and the amount at stake; ordered by amount. Phrase as requests for evidence, never as accusations. Keep the same list in the workbook, the executive PDF and the MD report.

## 13. Standards mapping for the methodology report

Use as reference (never claim certification): ISA/NIA 200 (skepticism), 230 (documentation), 240 (fraud considerations — applied as attention, not as investigation), 315 Rev. 2019 (understanding the entity), 500 (evidence), 501 (inventory without physical count → derived flow, disclosed), 505 (confirmations through management are "probable"), 520 (analytics as detection, not proof), 550 (related parties), 580 (representations recorded as such); ISRS 4400 Rev. (factual findings, no opinion); AICPA SSFS No. 1 (forensic services principles); ACFE Fraud Examiners Manual (evidence-to-conclusion, chain of custody, neutral language); ISO/IEC 27037 and 27043 (digital evidence preservation and investigation process); COSO 2013 (control deficiencies and governance recommendations); GAAP/IFRS topics for revenue, inventory, related parties; IESBA Code (independence disclosure, no contingent fees); NIST AI RMF 1.0 (transparency, traceability, human oversight). For each, write one sentence of *how it was applied in this engagement*; a professional reader judges by that column.

## 14. Due-diligence, litigation and insolvency variants

Due diligence: same reconstruction, plus quality-of-earnings adjustments (non-recurring items, owner-related costs, unbilled/deferred revenue), working-capital normalization and debt-like items. Litigation/arbitration support: exhibit numbering tied to document IDs, chain-of-custody statement, separate "facts / calculations / inferences / allegations" appendix, alternative explanations for every red flag. Insolvency/dissolution: priority of claims, related-party preferences in the look-back window, asset tracing. Whistleblower allegations: test each allegation as ALLEGATION → evidence found → FACT/INFERENCE/UNRESOLVED, without expanding scope beyond what the evidence supports.
