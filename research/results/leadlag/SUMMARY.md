# Lead-lag evidence: do prediction markets move before equities in stress?

Case studies plus a pooled time-series test. **Supporting evidence, not proof.** Parameters were fixed in [METHOD.md](../../leadlag/METHOD.md) and committed before any data was fetched.

## Headline

- Events: 32 candidates, **28 usable**, 4 dropped (reasons below).
- Where both series had a significant move (20 events): **PM first 9, simultaneous (within 1 min) 2, equity first 9**. Median lead -1.0 min, mean +3.0 min (positive = PM first).
- Descriptive only: the first PM move and the first equity move went in the same (pre-set, oriented) direction in 14 of 20 events (8 of 9 PM-first events). A PM-first event whose first PM move points the other way may be a stray tick rather than a lead (or the pre-set sign may be wrong, or the market may be reacting to something else).
- Exact two-sided sign test, PM first vs equity first (9 of 18): p = 1.000.
- No significant move detected in one of the two series: 8 usable events (lead not defined, still in the pooled test).
- Pooled test verdict (rule fixed in advance, classical F): **points the other way**. Granger F (p=10, event fixed effects): PM to equity F=0.71 (p=0.716); equity to PM F=7.72 (p=2.07e-12). Only equity to PM is significant.
- Robustness: HAC-robust statistics (Newey-West, 30 lags), all pre-declared in METHOD.md section 6. Granger HAC Wald, all usable events (p=10: PM to equity p=0.879, equity to PM p=0.071; p=30: PM to equity p=0.722, equity to PM p=0.218): 0 of 4 significant at 5%. All usable events, Regression A (PM to equity): cumulative response -0.083 (t=-1.21), joint Wald p=0.736; Regression B (equity to PM): cumulative response +0.203 (t=+2.29), joint Wald p=0.136. Subsets, FOMC (scheduled): Reg A Wald p=0.348 (cumulative -0.130, t=-1.31), Reg B Wald p=0.399 (cumulative +0.005, t=+0.05); curated: Reg A Wald p=0.003 (cumulative -0.042, t=-0.45), Reg B Wald p=0.002 (cumulative +0.414, t=+3.16).
- Plain reading: **no HAC statistic supports prediction markets leading equities**. The PM-to-equity joint Wald tests that are significant (curated, Reg A (PM to equity) joint Wald, p=0.003, cumulative response -0.042 with t=-0.45) do not show a positive, expected-direction response; the lag pattern is not the one a PM lead would produce. In the other direction some HAC statistics are significant: all usable, Reg B (equity to PM) cumulative response (t=+2.29); curated, Reg B (equity to PM) joint Wald (p=0.002); curated, Reg B (equity to PM) cumulative response (t=+3.16). So the data are more consistent with equities leading the PM than the reverse, but the HAC Granger tests are not significant at 5%, so this is weak and not uniform across tests. The 30-lag HAC Wald tests can be oversized (as found per event, see below), so even these significant joint tests deserve caution. The classical F is also unreliable here because PM changes are jumpy.
- Exploratory, sign-free, added after the first run (METHOD.md Amendment 2): per-event Granger tests (p=10, classical F, 5% level) are significant PM to equity in 1 of 28 events and equity to PM in 15 of 28 (about 1.4 expected by chance if the classical F were correctly sized, which it likely is not here); (the per-event HAC Wald columns in `granger_per_event.csv` are not used: with about 200 rows, 20 regressors and 30 HAC lags they are badly oversized, 24 of 28 events 'significant' PM to equity, which is not credible). Fisher-combined p (classical F) = 0.044 (PM to equity) and <0.001 (equity to PM); Fisher's method is driven by the few smallest p-values, so read it with the counts.

## Event table (primary instrument per event)

Lead = equity first-move time minus PM first-move time, in minutes; positive means the prediction market moved first. xcorr lag = peak of the 1-minute-change cross-correlation (positive = PM leads), with rho in brackets; `*` marks |rho| > 2/sqrt(n). Descriptive columns (not part of the pre-set rule): `PM vs anchor` and `Eq vs anchor` are each first move minus the event anchor time in `events.yaml` (statement time or news time), in minutes, so a negative value means the first move came before the event; `Eq session` is RTH (regular hours, 09:30-16:00 ET) or ext (pre/after-hours) at the equity move time.

| Event | Date | Instr. | PM move (UTC) | Equity move (UTC) | Lead (min) | Class | PM vs anchor (min) | Eq vs anchor (min) | Eq session | xcorr lag [rho] | Chart |
|---|---|---|---|---|---|---|---|---|---|---|---|
| FOMC statement 2024-09-18 | 2024-09-18 | SPY | 18:02 | 18:01 | -1 | simultaneous | +2 | +1 | RTH | -4 [-0.41*] | [png](charts/fomc-2024-09-18.png) |
| FOMC statement 2024-11-07 | 2024-11-07 | SPY | 19:14 | none | n/a | NA | +14 | n/a | n/a | +24 [+0.18*] | [png](charts/fomc-2024-11-07.png) |
| FOMC statement 2024-12-18 | 2024-12-18 | SPY | 19:03 | 19:01 | -2 | equity first | +3 | +1 | RTH | -2 [+0.16*] | [png](charts/fomc-2024-12-18.png) |
| FOMC statement 2025-01-29 | 2025-01-29 | SPY | 19:03 | 18:02 | -61 | equity first | +3 | -58 | RTH | -2 [+0.17*] | [png](charts/fomc-2025-01-29.png) |
| FOMC statement 2025-03-19 | 2025-03-19 | SPY | 18:02 | none | n/a | NA | +2 | n/a | n/a | -5 [-0.24*] | [png](charts/fomc-2025-03-19.png) |
| FOMC statement 2025-05-07 | 2025-05-07 | SPY | 18:44 | 18:07 | -37 | equity first | +44 | +7 | RTH | +1 [+0.17*] | [png](charts/fomc-2025-05-07.png) |
| FOMC statement 2025-06-18 | 2025-06-18 | SPY | none | 18:05 | n/a | NA | n/a | +5 | RTH | -1 [+0.17*] | [png](charts/fomc-2025-06-18.png) |
| FOMC statement 2025-07-30 | 2025-07-30 | SPY | 17:45 | 18:39 | +54 | PM first | -15 | +39 | RTH | -25 [+0.17*] | [png](charts/fomc-2025-07-30.png) |
| FOMC statement 2025-09-17 | 2025-09-17 | SPY | 17:43 | 18:01 | +18 | PM first | -17 | +1 | RTH | +29 [-0.25*] | [png](charts/fomc-2025-09-17.png) |
| FOMC statement 2025-10-29 | 2025-10-29 | SPY | 18:10 | 18:36 | +26 | PM first | +10 | +36 | RTH | -1 [+0.21*] | [png](charts/fomc-2025-10-29.png) |
| FOMC statement 2025-12-10 | 2025-12-10 | SPY | 19:03 | 19:01 | -2 | equity first | +3 | +1 | RTH | -14 [+0.20*] | [png](charts/fomc-2025-12-10.png) |
| FOMC statement 2026-01-28 | 2026-01-28 | SPY | 19:41 | 21:01 | +80 | PM first | +41 | +121 | ext | -10 [-0.28*] | [png](charts/fomc-2026-01-28.png) |
| FOMC statement 2026-06-17 | 2026-06-17 | SPY | 18:17 | 18:01 | -16 | equity first | +17 | +1 | RTH | -18 [-0.38*] | [png](charts/fomc-2026-06-17.png) |
| FOMC statement 2026-07-29 | 2026-07-29 | SPY | 18:02 | 18:01 | -1 | simultaneous | +2 | +1 | RTH | -1 [+0.31*] | [png](charts/fomc-2026-07-29.png) |
| FOMC statement 2026-09-16 | 2026-09-16 | SPY | 18:02 | 18:33 | +31 | PM first | +2 | +33 | RTH | +29 [+0.22*] | [png](charts/fomc-2026-09-16.png) |
| Powell Jackson Hole speech 2024 | 2024-08-23 | SPY | 14:16 | 13:37 | -39 | equity first | +16 | -23 | RTH | -5 [+0.22*] | [png](charts/jh-2024-08-23.png) |
| Powell Jackson Hole speech 2025 | 2025-08-22 | SPY | 13:43 | 14:01 | +18 | PM first | -17 | +1 | RTH | -1 [+0.58*] | [png](charts/jh-2025-08-22.png) |
| Global growth scare / yen carry unwind, US open | 2024-08-05 | SPY | none | 12:24 | n/a | NA | n/a | -66 | ext | -27 [+0.33*] | [png](charts/crash-2024-08-05.png) |
| Iran missile attack on Israel | 2024-10-01 | SPY | 16:35 | none | n/a | NA | n/a | n/a | n/a | +29 [+0.15*] | [png](charts/iran-2024-10-01.png) |
| 2024 US election night (after-hours session only) | 2024-11-05 | SPY | 23:41 | 00:24 | +43 | PM first | -19 | +24 | ext | -22 [+0.19*] | [png](charts/election-2024-11-05.png) |
| SCOTUS upholds TikTok divest-or-ban law | 2025-01-17 | META | 15:02 | 14:33 | -29 | equity first | +2 | -27 | RTH | +21 [-0.40*] | [png](charts/tiktok-2025-01-17.png) |
| Liberation Day tariff announcement (after-hours session) | 2025-04-02 | SPY | 21:33 | 20:14 | -79 | equity first | +93 | +14 | ext | -22 [+0.19*] | [png](charts/tariff-2025-04-02.png) |
| China retaliation plus Powell remarks on tariffs | 2025-04-04 | SPY | none | 14:54 | n/a | NA | n/a | -156 | RTH | +18 [+0.11*] | [png](charts/tariff-2025-04-04.png) |
| Unconfirmed 90-day tariff-pause report, then White House denial | 2025-04-07 | SPY | 14:13 | 14:11 | -2 | equity first | n/a | n/a | RTH | -6 [+0.24*] | [png](charts/tariff-2025-04-07.png) |
| Tariff pause announced | 2025-04-09 | SPY | 16:41 | 17:20 | +39 | PM first | -39 | +0 | RTH | -8 [+0.19*] | [png](charts/tariff-2025-04-09.png) |
| Reports Trump may move to fire Powell | 2025-07-16 | SPY | 14:57 | 15:17 | +20 | PM first | n/a | n/a | RTH | -2 [+0.31*] | [png](charts/powell-2025-07-16.png) |
| Funding deadline, partial shutdown risk | 2026-01-30 | SPY | 16:35 | none | n/a | NA | n/a | n/a | n/a | +4 [-0.16*] | [png](charts/shutdown-2026-01-30.png) |
| Trump names Kevin Warsh as Fed Chair pick | 2026-01-30 | GLD | none | none | n/a | NA | n/a | n/a | n/a | -30 [+0.10*] | [png](charts/warsh-2026-01-30.png) |

Anchor check (descriptive): of the 9 PM-first events, 5 have the first PM move before the event anchor (so it cannot be a reaction to the event); of the 9 equity-first events, 3 have the first equity move before the anchor and 1 falls in extended hours. A move before the anchor is not information about the event, so the lead count for those events says little about who reacts first to news. Equity moves in extended hours, or right at the 16:00 ET close or the 04:00/20:00 ET session seams, can reflect thin trading or the session boundary rather than the event.

## Events where equities moved first (kept, as required)

- **Liberation Day tariff announcement (after-hours session)** (2025-04-02, SPY): equity moved at 20:14Z, PM at 21:33Z, lead -79 min.
- **FOMC statement 2025-01-29** (2025-01-29, SPY): equity moved at 18:02Z, PM at 19:03Z, lead -61 min.
- **Powell Jackson Hole speech 2024** (2024-08-23, SPY): equity moved at 13:37Z, PM at 14:16Z, lead -39 min.
- **FOMC statement 2025-05-07** (2025-05-07, SPY): equity moved at 18:07Z, PM at 18:44Z, lead -37 min.
- **SCOTUS upholds TikTok divest-or-ban law** (2025-01-17, META): equity moved at 14:33Z, PM at 15:02Z, lead -29 min.
- **FOMC statement 2026-06-17** (2026-06-17, SPY): equity moved at 18:01Z, PM at 18:17Z, lead -16 min.
- **FOMC statement 2024-12-18** (2024-12-18, SPY): equity moved at 19:01Z, PM at 19:03Z, lead -2 min.
- **FOMC statement 2025-12-10** (2025-12-10, SPY): equity moved at 19:01Z, PM at 19:03Z, lead -2 min.
- **Unconfirmed 90-day tariff-pause report, then White House denial** (2025-04-07, SPY): equity moved at 14:11Z, PM at 14:13Z, lead -2 min.

## Simultaneous (within 1 minute)

- FOMC statement 2024-09-18 (2024-09-18): lead -1 min
- FOMC statement 2026-07-29 (2026-07-29): lead -1 min

## No significant move in one series

- FOMC statement 2024-11-07 (2024-11-07): no significant move in SPY.
- FOMC statement 2025-03-19 (2025-03-19): no significant move in SPY.
- FOMC statement 2025-06-18 (2025-06-18): no significant move in PM.
- Global growth scare / yen carry unwind, US open (2024-08-05): no significant move in PM.
- Iran missile attack on Israel (2024-10-01): no significant move in SPY.
- China retaliation plus Powell remarks on tariffs (2025-04-04): no significant move in PM.
- Funding deadline, partial shutdown risk (2026-01-30): no significant move in SPY.
- Trump names Kevin Warsh as Fed Chair pick (2026-01-30): no significant move in PM and GLD.

## Pooled time-series tests

Primary instrument of each usable event, z-scaled per event, PM oriented by the pre-set expected sign, event fixed effects, per-event Newey-West (30 lags). Regression A: equity return on PM changes lagged 1..30. Regression B: the reverse. Granger F tests use own lags plus the other series' lags.

| Subset | Events | Rows | Reg A: cum. response (t) | Reg A Wald p | Reg B: cum. response (t) | Reg B Wald p | Granger PM to eq (p=10) F [p] | Granger eq to PM (p=10) F [p] | Granger PM to eq (p=30) F [p] | Granger eq to PM (p=30) F [p] |
|---|---|---|---|---|---|---|---|---|---|---|
| all usable | 28 | 7260 | -0.083 (-1.21) | 0.736 | +0.203 (+2.29) | 0.136 | 0.71 [0.716] | 7.72 [<0.001] | 1.07 [0.363] | 3.32 [<0.001] |
| FOMC (scheduled) | 15 | 3150 | -0.130 (-1.31) | 0.348 | +0.005 (+0.05) | 0.399 | 0.30 [0.981] | 2.03 [0.027] | 0.59 [0.964] | 1.51 [0.036] |
| curated | 13 | 4110 | -0.042 (-0.45) | 0.003 | +0.414 (+3.16) | 0.002 | 1.26 [0.249] | 9.98 [<0.001] | 1.25 [0.165] | 4.83 [<0.001] |

- Regression A (all usable): largest |t| at lag 28 min (beta +0.029, t +1.89); lags with |t| > 2: 0 of 30. All 30 coefficients: `regression_lags.csv`.
- Regression B (all usable): largest |t| at lag 2 min (beta +0.061, t +2.52); lags with |t| > 2: 2 of 30.
- A positive coefficient means: when the prediction market moved in the equity-bullish direction, the equity rose over the following minutes (units: equity z per PM z).
- Leave-one-event-out, Regression A cumulative response: range -0.108 (without fomc-2026-07-29) to -0.060 (without fomc-2025-12-10); 0 of 28 are positive.

## Sensitivity of the first-move rule (primary instrument; headline uses k = 4)

| k | events with both moves | PM first | simultaneous | equity first | median lead (min) |
|---|---|---|---|---|---|
| 3 | 27 | 7 | 2 | 18 | -15.0 |
| 4 | 20 | 9 | 2 | 9 | -1.0 |
| 5 | 16 | 3 | 2 | 11 | -4.5 |

## Sensitivity of the simultaneity band (k = 4; descriptive, not headline)

The CLOB points are snapshots stamped a few seconds after the minute, while an equity bar closed at :59 of the same minute, so the PM series is on average about 45-55 seconds staler than equity at each grid point (METHOD.md Amendment 3). Widening the simultaneous band from 1 to 2 minutes shows how much of the 'equity first' count could come from that phase offset.

| simultaneous band | events with both moves | PM first | simultaneous | equity first |
|---|---|---|---|---|
| within 1 min (headline) | 20 | 9 | 2 | 9 |
| within 2 min | 20 | 9 | 5 | 6 |

## Dropped events

- **FOMC statement 2026-03-18** (2026-03-18, `will-there-be-no-change-in-fed-interest-rates-after-the-april-2026-meeting`): PM too flat (1 minutes with a price change, need 10)
- **FOMC statement 2026-04-29** (2026-04-29, `will-there-be-no-change-in-fed-interest-rates-after-the-june-2026-meeting`): PM too flat (3 minutes with a price change, need 10)
- **Trump-Zelensky Oval Office meeting breaks down** (2025-02-28, `russia-x-ukraine-ceasefire-in-2025`): thin equity data for ITA (valid 100%, bar coverage 61%)
- **Trump-Putin Alaska summit** (2025-08-15, `russia-x-ukraine-ceasefire-in-2025`): thin equity data for ITA (valid 34%, bar coverage 87%)

## Not in the candidate list, and why

- 8-K disclosures and any 2026 option data: out of scope for this study (the 8-K study's sealed window); none fetched.
- Events where the important PM move happened while US equities were closed (election results after 01:00 UTC on 2024-11-06, the Sunday-night Senate vote that ended the Nov 2025 shutdown, Israel's strike on Iran on 2025-06-13, the weekend US strikes of Jun 2025): a window with no equity prices cannot say who moved first. The election event covers the after-hours session only.
- 2025-01-27 DeepSeek sell-off, 2025-10-10 China tariff threat, 2025-11-05 Supreme Court tariff argument, regional-bank stress of Oct 2025 and Mar 2023: no suitable high-volume Polymarket market with a clear sign was found by search.
- CPI and jobs-report days: the sign of the equity response to a data surprise is ambiguous in advance (bad news can be dovish), so no sign could be pre-registered.

## Caveats

- Events are not independent: the 2025 recession market appears in four tariff windows, the Russia-Ukraine ceasefire market twice, and consecutive FOMC markets overlap. Fixed effects and per-event HAC handle serial correlation within an event, not dependence across events.
- PM history is one point per minute at most, stale in quiet minutes, and moves in 0.1 to 1 point ticks. Detection times are coarse, and PM-to-equity correlations are biased toward zero.
- Thin PM markets print isolated 1 to 2 point ticks that can pass the first-move rule without any news behind them, which can bias the first-move lead toward 'PM first'. The concordance line, the cross-correlation and the pooled regression are less exposed to this than the lead count; the sensitivity table shows the effect of a stricter k.
- Sampling phase: cached CLOB points are snapshots stamped about 4-17 seconds past each minute; they are assigned to the next minute-end grid point, while the equity value at that grid point includes trades up to :59. So the PM series is about 45-55 seconds staler than equity on average. This is not look-ahead, but it biases first-move leads against the PM (3 of the 9 'equity first' events are at -2 minutes). See the simultaneity-band table and METHOD.md Amendment 3.
- Several first moves are unrelated to the event: some PM moves precede the scheduled anchor (a market cannot be reacting to a statement that has not happened), and some equity moves sit in after-hours trading, for example the SPY move in the 2026-01-28 FOMC event that falls about two hours after the statement and after the 16:00 ET close. The `vs anchor` and `Eq session` columns and the anchor check line make this visible; the pre-set rule does not filter on it.
- Equity ETF prices in these windows are also driven by futures and options that this study does not observe. 'Equity moved first' means first relative to the PM series only.
- The curated events were chosen from memory of famous dates; the scheduled FOMC set is the unselected part of the sample and is reported separately.
- The first-move rule (k = 4, 3-minute change, 5-minute persistence) is a convention. See the sensitivity table for how much the counts move.

## Files

`events_metrics.csv` (every event and mapped instrument), `xcorr_by_event.csv`, `regression_lags.csv`, `pooled_tests.csv`, `leave_one_out.csv`, `dropped.csv`, `data/` (aligned minute series), `charts/` (one PNG per usable event), `RUN_LOG.md`.
