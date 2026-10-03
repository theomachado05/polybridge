# Do Options Price Slow 8-K News Correctly? Two Pre-Registered Tests on the Top 100 US Stocks

PolyBridge · Gator Quant Hacks 2026 · Massive "Trade the 8-K" challenge

## 1. Hypothesis

An option chain prices how far a stock should move after a corporate event. We ask whether that price is wrong in a predictable direction for two kinds of 8-K filings, and we measure it with the parity ratio R, the realized move divided by the move the chain priced on the session before the filing, scaled to each horizon.

**H1 (hedge side).** After a litigation, regulatory investigation, cybersecurity incident or impairment 8-K, the stock keeps moving by more than the options priced over 21 to 63 sessions. Dealers mark implied volatility down once the headline passes, while the legal or accounting damage resolves over weeks. If true, a protective put bought at the close of the session after the filing earns more than the same position opened on an ordinary day.

**H2 (opportunity side).** After a restructuring, workforce reduction, facility closure or business-line exit 8-K, holders who must stay in the stock buy puts, and dealers charge for absorbing that one-sided demand (Gârleanu, Pedersen and Poteshman, 2009). If true, a cash-secured put sold at the close of the session after the filing earns more than one sold on an ordinary day.

Both hypotheses, the tag lists and the pass rule were committed to git before any event or price was downloaded (`research/HYPOTHESIS.md`, `HYPOTHESIS_TAGS.md`).

## 2. Method

**Universe and windows.** The starter's static top-100 list. In-sample 2024-01-01 to 2025-12-31; out-of-sample 2026-01-01 to 2026-08-31, frozen at 13:00 ET on 3 October and run once (tag `method-freeze`). The frozen branch did not contain the robustness additions or the INSUFFICIENT label below, which were committed to main at 10:59 ET, before the freeze. Under the frozen method H1's computed verdict is NULL; applying the INSUFFICIENT label afterwards marks it as untestable (3 events). Neither label is a pass.

**Events.** One event per company per filing date. Filings that carry tags from both families are dropped (5 in-sample). Every filing is treated as public after the close, so the trade enters at the close of the next session.

**Trade.** Options 90 to 180 days to expiry, put strike 5% below spot, legs marked from daily option bars, stock replaced by the synthetic position from put-call parity, as in the starter.

**Baseline.** 120 ordinary days per family for the same companies, at least 30 days from any of their events. The edge is the event mean minus the ordinary-day mean, per $1 of spot.

**Pass rule.** A 97.5% bootstrap interval on the edge (95% split across the two tests) above zero at 2 or more of 21 sessions, 42 sessions and expiry, with R moving in the predicted direction. A hypothesis with fewer than 2 headline horizons holding the 5 events an interval needs is reported as INSUFFICIENT. All eight fixed horizons and expiry are reported.

**Robustness.** Added after the in-sample NULLs were seen, as robustness only: a company-clustered bootstrap and, for H1, the put's own edge (protective put minus stock), because the stock leg dominates the protective put when a stock keeps falling. Neither can turn a NULL into a PASS, and the out-of-sample run predates both.

## 3. Results

Neither hypothesis passes, in-sample (both NULL) or out of sample (H1 computed NULL on 3 events, too few for an interval; H2 NULL with the sign reversed). The in-sample table gives the edge per $1 of stock with its 97.5% interval.

| Sessions | H1 protective put edge (n = 28–33) | H2 cash-secured put edge (n = 23–24) | H1 R, events / ordinary | H2 R, events / ordinary |
|---|---|---|---|---|
| 1 | −0.002 [−0.006, +0.002] | −0.003 [−0.005, −0.000] | 0.68 / 0.99 | 1.03 / 0.86 |
| 5 | −0.001 [−0.019, +0.018] | −0.001 [−0.005, +0.003] | 1.22 / 1.01 | 0.87 / 1.01 |
| 10 | −0.005 [−0.025, +0.018] | +0.000 [−0.006, +0.008] | 1.04 / 1.05 | 0.99 / 0.94 |
| **21** | +0.001 [−0.027, +0.029] | +0.001 [−0.007, +0.009] | 1.11 / 1.09 | 0.77 / 0.94 |
| **42** | +0.005 [−0.045, +0.058] | +0.002 [−0.009, +0.014] | 1.36 / 1.15 | 0.91 / 1.01 |
| 63 | +0.032 [−0.028, +0.091] | +0.007 [−0.003, +0.017] | 1.19 / 1.01 | 1.11 / 0.92 |
| **Expiry** | +0.033 [−0.030, +0.101] | +0.009 [−0.004, +0.023] | 1.18 / 1.06 | 1.06 / 0.88 |

Bold rows are the pre-registered headline horizons; horizons 2 and 3 are in `research/results/in_sample/`.

**Out of sample, 2026-01-01 to 2026-08-31, run once.**

| Horizon | H1 n (events / ordinary) | H1 edge | H2 n | H2 edge [97.5% CI] | H2 R, events / ordinary |
|---|---|---|---|---|---|
| 21 | 3 / 107 | not computable (n < 5) | 7 / 90 | −0.0215 [−0.0759, +0.0203] | 1.57 / 1.10 |
| 42 | 3 / 81 | not computable | 7 / 68 | −0.0138 [−0.0729, +0.0260] | 1.17 / 0.90 |
| Expiry | 1 / 65 | not computable | 4 / 51 | not computable | 0.79 / 1.11 |

**What the in-sample nulls bound.** In 2024 and 2025, a stock-plus-put position after an H1 filing did no better or worse than on ordinary days by more than about 3% of spot at 21 sessions, and short puts after H2 filings were not overpriced by more than about 0.9%. Out of sample there were too few events to recheck either bound, and H2's edge and parity ratio moved against its premise at 21 and 42 sessions on 7 events.

**The decay curve.** In-sample the H1 parity ratio was 0.68 one session after the filing and 1.36 at 42, against 0.92 to 1.15 on ordinary days. That is the shape H1 describes, but the event intervals overlap the placebo's at every horizon. Out of sample, on 3 events and with no interval, it went the other way (1.86 against 0.93 at one session, 0.61 against 0.92 at 42). We do not treat it as a finding.

**Costs.** The 5% premium haircut moves the edge by at most 0.04% of spot (net edge at 1x: H1 +0.0011, +0.0052, +0.0336; H2 +0.0011, +0.0024, +0.0095), and the quoted half-spread costs about 0.0029 per $1 of spot at 21 sessions. Median option leg volume was 33.5 (H1) and 48.5 (H2) contracts. We did no capacity analysis.

## 4. What would break it

The result rests on 24 to 36 events per family in-sample and 3 (H1) and 8 (H2, 7 priced at 21 and 42 sessions) out of sample, a static list that includes companies that were not top-100 throughout, spot inferred from put-call parity, and last-trade marks. Before the out-of-sample run we committed a forecast (`research/FORECAST.md`). It had the verdicts' direction right (no pass, H2 NULL) and the H2 event count right. It got the H1 event count wrong (3, not about 11), understated the out-of-sample interval width by a factor of 2 to 3, and got the one scorable sign wrong (H2's edge was negative at 21 and 42 sessions, where we gave a positive sign probability 0.60). For a 3-month sealed window the same forecast predicts INSUFFICIENT for both families.

## 5. How to trade it

We would not trade either rule. Our product, PolyBridge, lets a signal act on positions only after it passes a pre-registered out-of-sample test. Both 8-K families failed it, so 8-K tags are shown as untested and never size a hedge. H2 entry timing (selling the put a few sessions after the filing, after the first-day loss of −0.25%) remains a candidate for a fresh pre-registered window, but the out-of-sample short put lost to ordinary days.
