# S26: do economically direct question links carry a tradeable edge after the open?

Committed before any S26 number is computed. Data: S14's cached panel (254 links, 253 sessions; out-of-sample = S14's
last 20% of sessions, from 2026-07-23). The analyst has seen S14's pooled results (no after-open relation over all links,
and hindsight-picked links fail out of sample) but no result broken down by the tiers below.

## Hypothesis
S14 selected links statistically. Selecting them economically, from the question text alone, may isolate links where the
prediction market prices news the linked asset has not yet absorbed. **H: on Tier A links the overnight odds move predicts
the linked asset's move from the open to the close (beta-adjusted to SPY), so trading in its direction at the open pays.**

## Tiers (tiers.py, from question text and ticker only; no outcome is read)
- **A, own underlying:** the question names the asset's own underlying (oil for oil ETFs and refiners; Fed, rates,
  recession or inflation for Treasury ETFs; gold; the dollar; Bitcoin for crypto stocks; the company itself).
- **B, country named:** a country ETF whose country or bloc is named.
- **C, everything else.**

## Signal, trade and costs (S14's definitions)
- x = oriented odds move in points from the previous close to 09:29 (S14 `x`).
- Outcome: `after`, the asset's open-to-close return in bp net of beta × SPY's (S14).
- Trade: at the 09:30 open, when |x| >= 5 points, hold sign(x) × the beta-hedged asset to the close. Cost 5 bp per trade
  (both legs, round trip); 2x = 10 bp. Several trades on a day are equally weighted; days with no trade return 0.
- Sharpe: daily book return × sqrt(252), over every session of the segment.

## Pass rule (primary: Tier A, out-of-sample)
1. Pooled after-open slope of Tier A on x, day-clustered (S14's `clustered_slope`): slope > 0 and t >= 2, out-of-sample.
2. The trade, out-of-sample at 1x: mean net bp per trade > 0 with a day-bootstrap 95% interval above 0, at least 30 trades.
3. Same trades at 2x: mean > 0.
All three: PASS. Otherwise NOT A PASS. In-sample, Tiers B and C, the opening gap and every number are reported regardless.
