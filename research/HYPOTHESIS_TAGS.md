# PolyBridge · Pre-registered tag mapping (addendum to HYPOTHESIS.md §6)

**Committed:** 2026-10-02, after downloading **only** the Massive disclosure taxonomy
(`/stocks/taxonomies/vX/disclosures`: 119 tertiary tags with names and descriptions) and **before any
8-K event, option price or stock price was fetched**. Tags were assigned from their descriptions and the
family wording in HYPOTHESIS.md §2, with no event counts or results in view.

## H1 · Hedge side: slow-burning bad news → protective put

| Tag | Massive description (abridged) | Family wording it matches |
|---|---|---|
| `material_litigation` | Significant litigation updates, outcomes or judgments not covered by settlement_agreement | material litigation and legal proceedings |
| `class_action_filing` | Class action lawsuit filed against the company | material litigation and legal proceedings |
| `regulatory_investigation` | SEC, DOJ or other regulatory investigation, Wells notice or enforcement action | regulatory or government investigations, enforcement |
| `cybersecurity_incident` | Material cybersecurity incident, data breach, ransomware | cybersecurity incidents (Item 1.05) |
| `goodwill_impairment` | Goodwill impairment charge | material impairments and write-downs (Item 2.06) |
| `asset_impairment` | Long-lived or intangible asset impairment or write-down | material impairments and write-downs (Item 2.06) |
| `investment_impairment` | Other-than-temporary impairment on investments or securities | material impairments and write-downs (Item 2.06) |

## H2 · Opportunity side: restructurings → cash-secured put

| Tag | Massive description (abridged) | Family wording it matches |
|---|---|---|
| `restructuring_plan` | Restructuring or cost-reduction initiative with expected charges and savings | restructuring plans |
| `workforce_reduction` | Significant layoffs, RIFs or voluntary separation programs | workforce reductions and layoffs |
| `facility_closure` | Facility closures, consolidations or relocations with charges | exit or disposal costs (Item 2.05) |
| `business_line_exit` | Decision to exit or discontinue a business line or segment | exit or disposal costs (Item 2.05) |

## Considered and left out (atlas only)

| Tag | Reason, decided from the description |
|---|---|
| `settlement_agreement` | Resolves a dispute. It is the end of the slow burn, not the start, which is the opposite of H1's mechanism |
| `financial_restatement` | Excluded in HYPOTHESIS.md §2 before the taxonomy was seen (too rare in the top 100) |
| `accounting_error_correction`, `internal_control_weakness` | Accounting quality, not litigation, investigation, cyber or impairment; not in the H1 wording |
| `material_charge_or_gain` | Mixes charges and gains, so it has no single predicted sign |
| `strategic_initiative` | Covers any change in strategy, including market entry; the H2 wording covers only strategic reviews *that announce a restructuring*, which carry `restructuring_plan` anyway |
| All other tags | Not in either family's wording. They appear only in the exploratory atlas (HYPOTHESIS.md §5) |

## Rules fixed before any events are loaded

1. **Event unit:** one event per filer per filing date. A filing with several tags in the same family
   counts once for that family.
2. **Cross-family filings:** a filing carrying tags from **both** H1 and H2 (for example a restructuring
   that books an impairment) is **excluded from both confirmatory tests**, because its parity side is
   ambiguous. The count of excluded filings is reported.
3. **Primary result is pooled per family.** Per-tag results are secondary and descriptive.
4. **The family membership above is final.** Any change is a new commit with its reason and is disclosed
   in the quant note.
