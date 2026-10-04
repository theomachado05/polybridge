# Do Options Price Slow 8-K News Correctly? Two Pre-Registered Tests on the Top 100 US Stocks

PolyBridge · Gator Quant Hacks 2026 · Massive "Trade the 8-K" challenge · Jacob Crainic and Theo Machado

**Hypotheses** (committed before any event or price was downloaded, `research/HYPOTHESIS.md`). We measure whether the option chain misprices the move after two kinds of 8-K filing, using the parity ratio R (realized move over the move the chain priced the session before, scaled to each horizon). **H1:** after litigation, investigation, cybersecurity or impairment 8-Ks, the stock keeps moving by more than the options priced, because implied volatility is marked down once the headline passes while the damage resolves over weeks; a protective put opened at the close of the session after the filing should beat the same position on an ordinary day. **H2:** after restructuring, layoff, facility-closure or exit 8-Ks, holders who must stay in the stock buy puts and dealers charge for absorbing that demand (Gârleanu, Pedersen and Poteshman, 2009); a cash-secured put sold then should beat one sold on an ordinary day.

**Method.** Top-100 US stocks; in-sample 2024-01-01 to 2025-12-31; out-of-sample 2026-01-01 to 2026-08-31, frozen at 13:00 ET on 3 October and run once. One event per company per filing date; every filing treated as public after the close. Options 90 to 180 days out, put 5% out of the money, legs marked from daily bars. Baseline: 120 ordinary days per family for the same companies. Pass rule: a 97.5% bootstrap interval on the event-minus-ordinary-day edge above zero at 2 or more of 21 sessions, 42 sessions and expiry, with R moving the predicted way.

**Results.** Neither hypothesis passes. Edge per $1 of stock, 97.5% intervals (other horizons in `research/results/in_sample/`):

| | Sessions | n events / ordinary | Edge | 97.5% CI |
|---|---|---|---|---|
| H1 in-sample | 21 / 42 / expiry | 32 / 30 / 28 | +0.001 / +0.005 / +0.033 | [−0.027, +0.029] / [−0.045, +0.058] / [−0.030, +0.101] |
| H2 in-sample | 21 / 42 / expiry | 24 / 24 / 23 | +0.001 / +0.002 / +0.009 | [−0.007, +0.009] / [−0.009, +0.014] / [−0.004, +0.023] |
| H1 out of sample | 21 / 42 | 3 / 3 | not computable (n < 5) | |
| H2 out of sample | 21 / 42 | 7 / 7 | −0.022 / −0.014 | [−0.076, +0.020] / [−0.073, +0.026] |

Out of sample, H1's computed verdict under the frozen method is NULL on 3 events, too few for an interval. H2 is NULL with its sign reversed. In 2024 and 2025 a stock-plus-put position after an H1 filing did no better or worse than on ordinary days by more than about 3% of spot at 21 sessions, and short puts after H2 filings were not overpriced by more than about 0.9%. The in-sample H1 parity ratio (0.68 one session after the filing, 1.36 at 42, ordinary days 0.92 to 1.15) had the shape H1 predicts, but its intervals overlap the placebo at every horizon and the out-of-sample points went the other way. Costs: the 5% premium haircut moves the edge by at most 0.04% of spot; median option leg volume was 33.5 (H1) and 48.5 (H2) contracts.

**What would break it, and the forecast.** 24 to 36 events per family in-sample and 3 and 8 out of sample, a static top-100 list, spot inferred from put-call parity, last-trade marks. Before the out-of-sample run we committed a forecast (`research/FORECAST.md`). It had "no pass" and H2's count right, and got H1's count (3, not about 11), the interval width (2 to 3 times wider) and the one scorable sign wrong. For a 3-month sealed window it predicts too few events for an interval in both families.

**How to trade it.** We would not. PolyBridge shows 8-K tags as untested and never lets them size a hedge.
