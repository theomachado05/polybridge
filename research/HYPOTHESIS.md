# PolyBridge · Pre-registered hypothesis

**Committed:** 2026-10-02, before any 8-K event, option price or stock price was downloaded or examined.
The git timestamp of this file is the proof. Any later change is a new commit with its reason, listed in
the change log at the bottom, and disclosed in the quant note.

## 1. Framework: Prediction–Price Parity, options edition

Markets put a price on an event before it resolves. A prediction market prices its probability; an
option chain prices its move. For an 8-K event:

- **Priced move:** the implied move on the pre-event session `t_pre`, i.e. (ATM call + ATM put) ÷ spot,
  scaled to each horizon by √time (Massive starter, section 7).
- **Realized move:** |synthetic spot at exit ÷ synthetic spot at entry − 1|.
- **Parity ratio:** `R = realized ÷ priced`. R ≈ 1 means the market priced the event correctly.

The direction of the gap picks the side of the trade:

| Parity gap | Meaning | Side | Strategy |
|---|---|---|---|
| R above ordinary days | Event underpriced | **Hedge** | Protective put |
| R below ordinary days | Event overpriced | **Opportunity** | Cash-secured put |

## 2. Confirmatory hypotheses (exactly two)

### H1 · Hedge side: the chain underprices slow-burning bad news

> We expect **top-100 US stocks after a litigation, investigation, cybersecurity-incident or impairment
> 8-K** to **keep moving by more than the options priced** over **21–63 sessions**, because **dealers and
> holders mark implied volatility down once the headline passes, while the legal, regulatory or
> accounting damage is still being resolved**. The edge persists because **these filings are long,
> ambiguous and costly to parse, damage estimates arrive over weeks, and few desks warehouse single-name
> event risk for months**. If true, we should see **R above the placebo's and protective-put P&L above
> the placebo's**. It fails if **the event-minus-placebo protective-put edge is not positive, or R is no
> higher than on ordinary days**.

- **Family (in words):** material litigation and legal proceedings; regulatory or government
  investigations, subpoenas and enforcement; cybersecurity incidents (Item 1.05); material impairments
  and write-downs (Item 2.06).
- **Excluded on purpose:** restatement / non-reliance (Item 4.02). It is too rare in the top 100 to
  estimate, and it is decided now, not after seeing counts.
- **Economic class:** behavioral underreaction + implied-volatility mean reversion.

### H2 · Opportunity side: holders overpay for protection after restructurings

> We expect **top-100 US stocks after a restructuring, workforce-reduction or exit-cost 8-K** to **move
> by less than the options priced** over **21–63 sessions**, because **holders who must stay in the name
> buy puts after the headline, and dealers charge for absorbing that one-sided demand**. The edge persists
> because **hedging demand after these filings is predictable and price-insensitive, and few traders can
> carry short-put tail risk through a drawdown**. If true, we should see **R below the placebo's and
> cash-secured-put P&L above the placebo's**. It fails if **the event-minus-placebo cash-secured-put edge
> is not positive, or R is no lower than on ordinary days**.

- **Family (in words):** restructuring plans, workforce reductions and layoffs, exit or disposal costs
  (Item 2.05), and strategic reviews that announce a restructuring.
- **Economic class:** liquidity provision / demand-based option pricing (Gârleanu, Pedersen and
  Poteshman, 2009).
- **Known risk, stated up front:** short puts earn the variance risk premium on ordinary days, so a
  positive raw P&L is the default, not a finding. Only the gap over the placebo counts.

## 3. Fixed specification (identical for H1 and H2)

| Item | Pre-registered value |
|---|---|
| Universe | `TOP_100` as shipped in the Massive starter (static; survivorship bias disclosed) |
| Windows | In-sample 2024-01-01 → 2025-12-31 · Out-of-sample 2026-01-01 → 2026-08-31 · sealed window set by the judges |
| Event unit | One event per filer per filing date, pooled across the family (per-tag results are secondary) |
| Timing | `t_0` = first session on or after filing; filings accepted after 16:00 ET move to the next session (EDGAR acceptance time) |
| Entry | `"post"`: close of `t_0`. `"pre"` is reported only as a pricing statement, never as a trade |
| Expiry bucket | 3–6 months (90–180 DTE, target 120) |
| Strike | Put 5% out of the money (first listed strike at or below spot × 0.95) |
| Horizons reported | All of 1, 2, 3, 5, 10, 21, 42, 63 sessions and expiry |
| Headline horizons | 21, 42 and expiry |
| Placebo | Starter method: ordinary sessions for the same tickers, at least `PLACEBO_GAP_DAYS` from any event |
| Costs | 5% of each option premium per side (starter default); every headline also shown at 2× |

## 4. Pass rule (decided before results)

Each hypothesis **passes in-sample** only if both of these hold:

1. The event-minus-placebo edge of its strategy has a **97.5% bootstrap CI excluding zero in the
   predicted direction** at **2 or more** of the 21-session, 42-session and expiry horizons. That is 95%
   with a Bonferroni split across the two confirmatory tests.
2. The mean parity ratio R differs from the placebo's in the predicted direction (H1 above, H2 below)
   at the same horizons.

Otherwise it is reported as a **null result**, with its decay curve. The out-of-sample window is run
**once**, after the method freeze, and reported whatever it shows, with its sample size. A hypothesis
that passes in-sample and keeps its sign out of sample is our headline. One that fails is reported as a
failure, not dropped.

## 5. Exploratory atlas (not confirmatory)

The parity ratio and all five strategies are computed for **every** tertiary tag in the taxonomy, across
the full sensitivity grid (expiry bucket × OTM distance × entry × horizon). This is the PolyBridge
signal library: buckets of event types sorted by which side of the parity gap they fall on.

- Labeled **exploratory** everywhere it appears.
- Every variant is counted. The note reports the total, Benjamini–Hochberg q-values across tags, and a
  deflated Sharpe for anything we discuss.
- **No exploratory result becomes a headline or replaces H1 or H2.** At most, the atlas names candidates
  for future pre-registered tests and seeds the live engine's preset library.

## 6. Category-to-tag mapping procedure

The exact Massive `tertiary_category` names are not public without an API key. Once the key is available:

1. Download **only** the taxonomy (`/stocks/taxonomies/vX/disclosures`): names and descriptions, no events.
2. Assign tags to the H1 and H2 families using the descriptions and the wording of sections 2 above.
   Tags that fit neither stay in the atlas only.
3. Commit the list as `research/HYPOTHESIS_TAGS.md` **before** any event is fetched.

## 7. Main-track portfolio overlay (pre-registered with the same rules)

- **Book:** equal-weight `TOP_100`, daily bars (Webull OpenAPI, or a cited public source if the key is
  not approved).
- **Rule:** on an H1 event in a holding, buy the H1 protective put; on an H2 event, sell the H2
  cash-secured put from a cash sleeve. Positions are sized as a fraction of ADV and option leg volume.
- **Compared against:** the unhedged book, and the same number of hedges placed on random ordinary days.
- **Validation:** walk-forward folds with a purge gap inside in-sample. The locked period is the most
  recent 20% of history or the most recent 2 years, whichever is shorter; it is run once.
- **Reported:** annualized return, volatility, Sharpe, max drawdown, worst month, skew, turnover and the
  equity curve, net of costs at 1× and 2×.

## 8. What we will disclose regardless of outcome

Total variants tried, every look at out-of-sample data, every change to this file, survivorship bias in
the static universe, parity-recovered spot error, last-trade marks without spreads, and small samples.

## Change log

- 2026-10-02: initial registration.
