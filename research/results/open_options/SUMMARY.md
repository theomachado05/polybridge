# R3: do options catch up with the prediction market at the Monday open?

Run 2026-10-03T17:08 UTC. Pre-registered method: [`research/open_options/METHOD.md`](../../open_options/METHOD.md) (committed before any price or quote was fetched; amendment 1 drops Kalshi before any price was fetched). Rows: [`events.csv`](events.csv). Chart: [`catchup_chart.png`](catchup_chart.png). Numbers: [`stats.json`](stats.json). Log: [`RUN_LOG.md`](RUN_LOG.md).

## Answer

**Verdict against the pre-registered criterion: NULL.** 1535 events from 44 closures (needs >= 30 events and >= 8 closures; success = mean net residual gap with a 95% cluster-bootstrap CI above 0).

- **Catch-up slope:** options' Monday-09:45 repricing reflected **0.44** of the PM's closure move (95% CI 0.33 to 0.57; 1 = full catch-up, 0 = none).
- **Residual gap at the open, before costs** (signed by the PM move, Friday basis netted out): +7.34 pt [+5.27, +9.31].
- **Residual gap net of option costs** (half the bid/ask band on the traded side + $0.65/leg commission): +0.79 pt [-1.21, +2.78]; equal weight per closure +0.83 pt [-1.12, +2.99].
- Median option cost at the open: 2.60 pt half-band + 0.26 pt commission.

Read: after costs there is no residual gap distinguishable from zero. Per the plan, no 'Opportunity at the open' claim; the card can only be shown as an unvalidated estimate, if at all.

## Funnel

Closures in the window (reopening 2025-10-01 .. 2026-09-28, weekends and holidays): 55. Polymarket equity events: 7772; markets seen 37218; 'close above $K' thresholds in scope 15112. Kalshi: not run (amendment 1).

| step | count |
|---|---|
| pair listed after close | 8763 |
| pair resolves before reopen close | 688 |
| pairs life ok | 7715 |
| pair no clean expiry | 2694 |
| pairs eligible | 5021 |
| status: f1_no_pm_price | 46 |
| status: f1_pm_close_extreme | 1836 |
| status: f2_placeholder_050 | 141 |
| status: f3_move_below_3pt | 907 |
| status: f4_no_option_spread | 282 |
| status: f4_opt_close_extreme | 183 |
| status: f4_noarb_violation | 91 |
| status: event | 1535 |

'pairs life ok' = (market, closure) pairs where the market was listed 15+ minutes before the close and resolves at or after 16:00 ET of the reopening day; 'eligible' additionally has a listed option expiry on the resolution date.

## Secondary (reported, not used for the verdict)

| subset | events | closures | slope [CI] | net residual gap [CI] |
|---|---|---|---|---|
| all (primary) | 1535 | 44 | 0.44 [0.33, 0.57] | +0.79 pt [-1.21, +2.78] |
| Polymarket trade print inside the closure | 1175 | 44 | 0.50 [0.37, 0.64] | +1.56 pt [-0.40, +3.51] |
| |dPM| >= 5 points | 1196 | 44 | 0.44 [0.32, 0.57] | +2.52 pt [+0.29, +4.73] |
| same strike pair and width_sens <= 0.05 | 1065 | 44 | 0.45 [0.32, 0.59] | +1.67 pt [-0.52, +3.89] |
| kind = daily | 730 | 33 | 0.60 [0.45, 0.75] | +1.80 pt [-1.20, +5.07] |
| kind = monthly | 632 | 20 | 0.17 [0.08, 0.30] | -1.18 pt [-4.64, +1.69] |
| kind = weekly | 173 | 5 | 0.08 [-0.02, 0.10] | +3.72 pt [+0.25, +8.77] |
| weekends only | 1201 | 34 | 0.49 [0.35, 0.64] | +0.14 pt [-2.28, +2.60] |

**Follow-through on the reopening day** (same strike pair, 09:45 to 15:55 ET), signed by the PM move:

- Option move after the open, F: -0.59 pt [-2.43, +0.88] (n=1123).
- Round trip of the option trade (buy at the ask band, sell at the bid band, two commissions): -22.83 pt [-26.47, -19.44].
- PM after the open (positive = PM kept moving its way, negative = gave it back): -3.48 pt [-5.40, -1.62].

Interpretation: options reprice by less than the PM over a closure, but the difference is not a lag the options close later. After 09:45 the options do not keep moving toward the PM, the PM itself gives back part of its closure move, and a trade that buys the options toward the PM loses the spread. The before-cost gap looks more like PM overshoot or noise over the weekend than slow options.

Outcome check on 1535 resolved events (descriptive): Brier score PM at 09:30 0.146, options at 09:45 0.120 (lower is better).

Largest net residual gaps:

| market | closure | PM Fri -> Mon 09:30 | options Fri -> Mon 09:45 | G | G net |
|---|---|---|---|---|---|
| Will Tesla (TSLA) close above $390 on June 29? | 2026-06-26 | 0.47 -> 0.12 | 0.19 -> 0.60 | +75.6 | +72.7 |
| Will Google (GOOGL) close above $345 on June 29? | 2026-06-26 | 0.49 -> 0.17 | 0.20 -> 0.59 | +71.5 | +66.4 |
| Will NVIDIA (NVDA) close above $215 on August 24? | 2026-08-21 | 0.49 -> 0.69 | 0.50 -> 0.08 | +61.9 | +61.5 |
| Will Meta (META) close above $700 on September 21? | 2026-09-18 | 0.10 -> 0.05 | 0.02 -> 0.61 | +64.3 | +61.0 |
| S&P 500 (SPY) closes above $755 on June 15? | 2026-06-12 | 0.51 -> 0.20 | 0.03 -> 0.29 | +58.0 | +56.8 |
| Will NVIDIA (NVDA) close above $200 on July 27? | 2026-07-24 | 0.50 -> 0.95 | 0.87 -> 0.74 | +58.0 | +56.4 |
| Will Tesla (TSLA) close above $400 on July 13? | 2026-07-10 | 0.69 -> 0.82 | 0.77 -> 0.33 | +57.0 | +56.1 |
| Will Amazon (AMZN) close above $235 on June 29? | 2026-06-26 | 0.48 -> 0.41 | 0.36 -> 0.91 | +61.0 | +55.2 |
| Will Google (GOOGL) finish week of December 29 above $320? | 2025-12-31 | 0.18 -> 0.13 | 0.06 -> 0.60 | +59.5 | +54.7 |
| Will Tesla (TSLA) close above $400 on June 29? | 2026-06-26 | 0.48 -> 0.04 | 0.04 -> 0.15 | +55.3 | +54.7 |
| Will Google (GOOGL) finish week of November 10 above $290? | 2025-11-07 | 0.52 -> 0.18 | 0.17 -> 0.40 | +56.2 | +54.5 |
| Will NVIDIA (NVDA) finish week of December 22 above $195? | 2025-12-24 | 0.50 -> 0.06 | 0.03 -> 0.13 | +54.6 | +54.1 |

## Caveats

- Polymarket prices are the per-minute `prices-history` series, which can be the midpoint of a thin book; the trade-print subset is the check. No PM cost is charged because only the options are traded.
- The call spread approximates the digital; settlement prints differ slightly (official close vs the PM's source); SPY and single-name options are American.
- One NBBO snapshot per leg at 09:45 ET (quotes must be stamped after 09:30:00); options can also lag the stock inside those 15 minutes.
- Strike ladders on one underlying and one closure are counted as separate events; the bootstrap resamples whole closures for that reason.
- Selection: only markets alive across a closure, listed before Friday's close, with a listed option expiry on the resolution date. Kalshi's 16:00 markets are listed the day before settlement, so they never qualify.
- No 8-K filing data was used.
