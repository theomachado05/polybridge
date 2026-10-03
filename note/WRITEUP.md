# Do Options Price Slow 8-K News Correctly? Two Pre-Registered Tests on the Top 100 US Stocks

PolyBridge · Gator Quant Hacks 2026 · Massive "Trade the 8-K" challenge

## 1. Hypothesis

An option chain prices how far a stock should move after a corporate event. We ask whether that price is wrong in a predictable direction for two kinds of 8-K filings, and we measure it with the parity ratio R, the realized move divided by the move the chain priced on the session before the filing, scaled to each horizon.

**H1 (hedge side).** After a litigation, regulatory investigation, cybersecurity incident or impairment 8-K, the stock keeps moving by more than the options priced over 21 to 63 sessions. Dealers mark implied volatility down once the headline passes, while the legal or accounting damage resolves over weeks. If true, a protective put bought at the filing close earns more than the same put bought on an ordinary day.

**H2 (opportunity side).** After a restructuring, workforce reduction, facility closure or business-line exit 8-K, holders who must stay in the stock buy puts, and dealers charge for absorbing that one-sided demand (Gârleanu, Pedersen and Poteshman, 2009). If true, a cash-secured put sold at the filing close earns more than one sold on an ordinary day.

Both hypotheses, the tag lists and the pass rule were committed to git before any event or price was downloaded (`research/HYPOTHESIS.md`, `HYPOTHESIS_TAGS.md`).

## 2. Method

**Universe and windows.** The starter's static top-100 list. In-sample 2024-01-01 to 2025-12-31; out-of-sample 2026-01-01 to 2026-08-31, run once after the method freeze on 3 October.

**Events.** One event per company per filing date. Filings that carry tags from both families are dropped (5). Every filing is treated as public after the close, so the trade enters at the close of the next session.

**Trade.** Options 90 to 180 days to expiry, put strike 5% below spot, legs marked from daily option bars, stock replaced by the synthetic position from put-call parity, as in the starter.

**Baseline.** 120 ordinary days per family for the same companies, at least 30 days from any of their events. The edge is the event mean minus the ordinary-day mean.

**Pass rule.** A 97.5% bootstrap interval on the edge (95% split across the two tests) above zero at 2 or more of 21 sessions, 42 sessions and expiry, with R moving in the predicted direction. All eight fixed horizons and expiry are reported.

**Robustness.** A bootstrap that resamples whole companies, and for H1 the put's own P&L, since the stock leg hides the put's gain when the stock falls. Neither can change a verdict.

## 3. Results

Neither hypothesis passes in-sample. The table gives the edge per $1 of stock at every fixed horizon with its 97.5% interval.

| Sessions | H1 protective put edge (n = 28–33) | H2 cash-secured put edge (n = 23–24) | H1 R, events / ordinary | H2 R, events / ordinary |
|---|---|---|---|---|
| 1 | −0.002 [−0.006, +0.002] | −0.003 [−0.005, −0.000] | 0.68 / 0.99 | 1.03 / 0.86 |
| 5 | −0.001 [−0.019, +0.018] | −0.001 [−0.005, +0.003] | 1.22 / 1.01 | 0.87 / 1.01 |
| 10 | −0.005 [−0.025, +0.018] | +0.001 [−0.006, +0.008] | 1.04 / 1.05 | 0.99 / 0.94 |
| **21** | +0.001 [−0.026, +0.029] | +0.001 [−0.007, +0.009] | 1.11 / 1.09 | 0.77 / 0.94 |
| **42** | +0.005 [−0.045, +0.060] | +0.002 [−0.009, +0.014] | 1.36 / 1.15 | 0.91 / 1.01 |
| 63 | +0.032 [−0.028, +0.091] | +0.007 [−0.003, +0.017] | 1.19 / 1.01 | 1.11 / 0.92 |
| **Expiry** | +0.033 [−0.029, +0.100] | +0.009 [−0.004, +0.023] | 1.18 / 1.06 | 1.06 / 0.88 |
| Out-of-sample | [OOS] | [OOS] | [OOS] | [OOS] |

Horizons 2 and 3 are in `research/results/in_sample/`. Bold rows are the pre-registered headline horizons.

**What the nulls rule out.** After an H1 filing, a protective put earns no excess return over an ordinary day that we can detect; edges larger than about 3% of the stock price at 21 sessions are ruled out. After an H2 filing, short puts are not overpriced by more than about 0.9% at 21 sessions. For a portfolio manager this means post-headline insurance costs about what it is worth.

**The shape is the finding worth following.** For H1, R is 0.68 one session after the filing and 1.36 at 42 sessions, against 0.92 to 1.15 on ordinary days. The chain prices the first move generously and the slow follow-through cheaply, which is the mechanism H1 describes, but with 30 events the gap is inside the noise. For H2, the short put loses on the first session (−0.25%, interval excluding zero), consistent with put demand arriving after the headline. That is one of nine horizons and is not corrected for multiple comparisons.

**Costs.** At a 5% premium haircut per side the edges move by less than 0.3% of spot, and doubling the haircut changes no conclusion. Median option volume on the entry day was 34 contracts (H1) and 49 (H2), so capacity is a few contracts per event without moving the market.

## 4. What would break it

The result rests on 24 to 36 events per family, a static list that includes companies that were not top-100 throughout, spot inferred from put-call parity, and last-trade marks. A wave of litigation or cyber filings would give the test more power and could change the verdict. Before any sealed window was run we committed a forecast (`research/FORECAST.md`): a 3-month window gives about 4 H1 and 3 H2 events and should be reported as INSUFFICIENT, longer windows should return NULL, and we gave probabilities for four signs. A PASS on the sealed window would contradict our forecast.

## 5. How to trade it

We would not trade either rule as a standalone strategy. The usable rule is a cost statement: after these filings, buying protection at the close does not overpay, so a holder who wants the hedge can buy it without waiting. The lead worth a pre-registered follow-up is entry timing on the H2 side, selling the put a few sessions after the filing rather than at the first close, tested on a fresh window with a sample large enough to detect a 0.5% edge.
