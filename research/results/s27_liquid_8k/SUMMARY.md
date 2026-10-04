# S27: the 8-K hypotheses on liquid option names, 2022 (never used by any study)

Method committed before any 2022 data (`41a04a6`, 04:37:55). Run once (76 s). Files: `verdict.json`, `liquidity.csv`, `*_difference.csv`.

## Answer

**Primary (liquid names): INSUFFICIENT for both.** The top-20% liquidity cut is set over events and placebo days pooled (about 12 events against 120 placebo days per family). It kept 3 H1 events and 1 H2 event, below the 5 an interval needs. Events at the 100 largest stocks were not usually the most liquid days of their names.

**Secondary (all 2022 events, a fresh replication of the frozen study): NULL for both, with one significant headline horizon for H1.**

- **H1, protective put** (12 events):
  - Edge over ordinary days at 21 sessions: **+4.30% of the stock price, 97.5% CI [+0.54, +7.93]**.
  - 42 sessions: +0.79% [−3.51, +5.52]. Expiry: +1.54% [−6.33, +11.61].
  - One headline horizon clears zero; the rule needs two, so the verdict is NULL.
  - Gross Sharpe at 21 sessions: 2.57 on events against −0.04 for the same strategy on ordinary days for the same names in 2022.
- **H2, cash-secured put** (12 events): NULL. +0.48% [−1.72, +2.22] at 21 sessions. Sharpe 0.33 against −0.83.

## Reading

In 2022, a falling market, the protective put bought after slow-burning bad news beat the same put on ordinary days at 21 sessions. That is H1's predicted sign and the horizon H1 names (follow-through over weeks). In-sample (2024–2025) the same horizon gave +0.07%. It is one of three headline horizons on 12 events, it is not a pass, and nine horizons were reported. It is a lead consistent with H1's mechanism in a high-volatility year, for a test on a longer fresh window.
