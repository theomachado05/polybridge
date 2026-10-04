# Fresh-market accuracy: options vs Polymarket on equity-threshold markets no earlier study touched

Run 2026-10-04T00:23Z at commit `fe02fd6`. Pre-registered method: [`research/fresh_accuracy/METHOD.md`](../../fresh_accuracy/METHOD.md) (committed with the frozen market list before any price, quote or outcome was fetched). Numbers: [`stats.json`](stats.json). Rows: [`rows.csv`](rows.csv). Chart: [`accuracy_chart.png`](accuracy_chart.png). Log: [`RUN_LOG.md`](RUN_LOG.md).

## Answer

**Verdict: PASS.** PASS: on fresh markets the option-implied probability was a more accurate forecast than the Polymarket price, on both Brier and log score.

Sample: 7,111 scored (market, snapshot) rows from 4,561 markets, 570 ticker-date ladders, 89 resolution dates (the clusters). Difference = PM minus options, positive = options more accurate; 95% resolution-date cluster bootstrap, 10,000 draws, seed 20261004.

- Brier: Polymarket 0.0938 vs options 0.0831, difference **+0.0108 [+0.0064, +0.0158]**.
- Log score: Polymarket 0.3044 vs options 0.2726, difference **+0.0318 [+0.0170, +0.0471]**.

In words: the Polymarket price is a worse forecast than the option-implied probability measured at the same instant. This does not say Polymarket traders know less; the PM price PolyBridge reads is a per-minute series that can be a stale last price or the midpoint of a thin book, and that is the mechanism.

**Freshness.** The markets and outcome dates are fresh (none in R3's pairs or on R3's resolution dates, none in the arb scan's window). The hypothesis and its direction were already seen in the arb scan and in R3/T4, so this is a frozen-rule confirmation on new data, not a new hypothesis. The T4 overshoot (PM give-back) is not tested here.

**Equal weight per date (pre-registered check).** Mean of per-date means: Brier +0.0129 [+0.0087, +0.0173], log +0.0405 [+0.0283, +0.0530]. The verdict computed under this weighting would be PASS, which matches the primary verdict; the primary verdict stands either way and is not rescued or changed by it.

## Secondary (reported, never used for the verdict)

| subset | rows | clusters | Brier PM vs options, diff [95% CI] | log score PM vs options, diff [95% CI] |
|---|---|---|---|---|
| primary (date clusters) | 7111 | 89 | 0.0938 vs 0.0831, diff +0.0108 [+0.0064, +0.0158] | 0.3044 vs 0.2726, diff +0.0318 [+0.0170, +0.0471] |
| event clusters (ticker x date) | 7111 | 570 | 0.0938 vs 0.0831, diff +0.0108 [+0.0082, +0.0133] | 0.3044 vs 0.2726, diff +0.0318 [+0.0211, +0.0407] |
| snapshot=S1 | 4404 | 87 | 0.1036 vs 0.0917, diff +0.0119 [+0.0064, +0.0183] | 0.3316 vs 0.2985, diff +0.0332 [+0.0136, +0.0530] |
| snapshot=S2 | 2707 | 89 | 0.0779 vs 0.0690, diff +0.0089 [+0.0044, +0.0143] | 0.2601 vs 0.2305, diff +0.0296 [+0.0167, +0.0445] |
| kind=daily | 3501 | 82 | 0.1039 vs 0.0932, diff +0.0107 [+0.0068, +0.0155] | 0.3340 vs 0.3009, diff +0.0330 [+0.0215, +0.0466] |
| kind=weekly | 3610 | 29 | 0.0840 vs 0.0732, diff +0.0108 [+0.0035, +0.0194] | 0.2757 vs 0.2451, diff +0.0306 [+0.0060, +0.0562] |
| trade_print | 1017 | 88 | 0.1101 vs 0.1067, diff +0.0034 [+0.0004, +0.0069] | 0.3486 vs 0.3364, diff +0.0123 [+0.0027, +0.0230] |
| no_trade_print | 6094 | 89 | 0.0911 vs 0.0791, diff +0.0120 [+0.0072, +0.0176] | 0.2970 vs 0.2619, diff +0.0351 [+0.0184, +0.0519] |

Encompassing logit of the result on logit(options) and logit(PM), date-clustered: options coefficient +0.849 [+0.626, +1.072], PM coefficient +0.300 [+0.150, +0.449].

Favourite-longshot slope (PM minus options on options minus 0.5, date-clustered): -0.1048 [-0.1331, -0.0765] (predicted negative). Mean |PM - options| 0.0570; coarse rows (narrow and wide spread differ by more than 5 pt) 13.7%.

## Costs (from data; no trade is claimed)

Option reference: mean half-band (p_hi - p_lo)/2 0.0663 (median 0.0230) per $1 of payoff; commission 0.0036 per $1 (median 0.0026). Polymarket historical spreads are not observable. An accuracy gap is not an executable edge: the arb scan found 0 executable gaps (5 verified), and R3's net gap was +0.79 pt [-1.21, +2.78].

## H3: Kalshi index equivalence (gated)

Pending: run only if the primary is PASS and finished before 01:30 ET.

## Funnel

Frozen markets 9,349. Snapshots dropped by the listing and end rules: {'snapshot_before_listing': 165}. Row status: {'scored': 7111, 'pm_extreme': 6510, 'no_clean_expiry': 3551, 'no_chain': 779, 'pm_stale': 299, 'pm_placeholder': 283}. Scored rows at the coverage gate: 7,111 on 89 dates. Rows without a resolved outcome: 0. Tickers in the scored sample: {'TSLA': 902, 'META': 854, 'SPY': 786, 'GOOGL': 781, 'AMZN': 699, 'NVDA': 696, 'AAPL': 681, 'MSFT': 634, 'PLTR': 544, 'MU': 171, 'OPEN': 158, 'NFLX': 109, 'SPCX': 81, 'RKLB': 10, 'ABNB': 5}.

## Caveats

- The call spread averages the density over [K1, K2]; Polymarket settles on the Pyth 16:00 print, options on the official close; SPY and single-name options are American.
- Rows within a date share one market move; inference clusters on date and the equal-weight and event-cluster versions are shown.
- The fresh frame is earlier in Polymarket's life than the arb window and has more midweek dailies and weeklies.
- The arb's informative filter (PM in [0.02, 0.98]) is kept unchanged although it is asymmetric.
- Hypothesis and direction were known before the run (freshness above).
