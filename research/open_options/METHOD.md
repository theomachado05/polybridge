# R3: do options catch up at the Monday open? (method, committed before any data for this study was fetched)

Question: when equities are closed (a weekend or a holiday) and a prediction-market (PM) threshold contract ("NVDA closes above $230 on Oct 5", "S&P 500 above 7,795 at 4pm") moves, how much of that move is in the listed options of the same underlying once they reopen, and is there a residual PM-vs-options gap at the open that survives costs?

This decides one product feature: the "Opportunity at the open" card (plan `docs/superpowers/plans/2026-10-03-closed-market-mode.md`, Product behaviour item 6, task U5). If the residual gap is not shown to survive costs, the card is not claimed as an opportunity; at most it is shown as an unvalidated estimate.

Status: a descriptive event study, pre-registered. Nothing is traded. A null result is an acceptable answer. Everything below is fixed before the run; later changes go in **Amendments** at the bottom, dated and marked pre- or post-data.

What was already known when this was written: the composition of the arb scan's universe (`research/results/arb/`: Polymarket daily, weekly and month-end "close above" markets on equities, Kalshi S&P 500 and Nasdaq-100 16:00 markets, Aug 15 to Oct 12 2026), and the arb scan's level gaps at weekday snapshots. No PM price over a closure and no option quote at a Monday open has been looked at for this study.

Data scope: no 8-K filing data is used. Option data: Massive (`research/polybridge_research/massive.py`), NBBO quotes. PM data: Polymarket gamma, CLOB `prices-history` and data-api trades; Kalshi public markets and candlesticks. Option-implied probabilities reuse `research/arb/arbscan` unchanged (threshold matching, call-spread probability with bid/ask bounds, cost constants).

## 1. Closures (the sample frame)

- A **closure** runs from the close of one NYSE session to the open of the next session, when the gap between them contains at least one whole calendar day with no session. That is every weekend, every holiday-extended weekend, and every midweek holiday. Ordinary weeknights are excluded.
- **Close instant:** 16:00 ET; 13:00 ET on the early-close days 2025-11-28 and 2025-12-24. **Open instant:** 09:30 ET of the next session. Calendar: `polybridge_research.calendar.TradingCalendar`.
- **Window:** closures whose reopening session falls between 2025-10-01 and 2026-09-28 inclusive (2026-09-28 is the last Monday open before the run date, Saturday 2026-10-03).

## 2. Markets and eligibility

- **Polymarket:** events with the `Equities` tag (id 102676) and an end date in 2025-10-01 .. 2026-10-12, markets matched by `arbscan.parse.parse_pm_question` (daily, weekly and month-end "close above $K"). Ticker and strike as in the arb scan.
- **Kalshi:** the arb scan's series (`KXINXU`, `KXNASDAQ100U`, `INXU`, `NASDAQ100U`, `KXINXAB`, `INXAB`), "greater" strikes only, 16:00 ET settlement only (`arbscan.parse.kalshi_is_close`), underlying SPX or NDX. Settled markets with close time in the window, all strikes (no volume cap).
- A (market, closure) pair is **eligible** when:
  1. the market was listed at least 15 minutes before the close instant (Polymarket `startDate`; Kalshi `open_time`);
  2. it resolves at or after 16:00 ET of the reopening session (the market is still alive through the open and the first trading day);
  3. the **clean option expiry** exists: a listed call expiry on exactly the market's resolution date (America/New_York), as in the arb scan. Index options use the PM-settled roots (SPXW, NDXP). Pairs whose resolution date has no listed expiry are dropped and counted.

## 3. Measurements per eligible pair

PM probability (YES mid):
- Polymarket: last `prices-history` point (fidelity 1 minute) at or before the instant, at most 15 minutes old.
- Kalshi: mid of `yes_bid` and `yes_ask` closes of the last 1-minute candle ending at or before the instant that carries both, at most 15 minutes old.

| symbol | what | instant |
|---|---|---|
| `pm_close` | PM at the close | close instant |
| `pm_open` | PM at the open (everything the PM learned over the closure) | open instant (09:30 ET) |
| `pm_0945` | PM at the option measurement time | 09:45 ET |
| `pm_eod` | PM at the end of the reopening day | 16:00 ET |
| `opt_close` | option-implied probability (narrow call spread, mid and bounds) | close instant minus 5 minutes (15:55 ET; 12:55 ET on early closes) |
| `opt_open` | option-implied probability at the Monday open window | 09:45 ET; every leg quote must be stamped at or after 09:30:00 ET of the reopening session |
| `opt_eod` | option-implied probability at the end of the reopening day | 15:55 ET |

Option-implied probability: `arbscan.implied.pick_spread` (narrow rule: neighbours of K if K is listed, else the strikes just below and above; a leg with no valid quote steps one strike outward, at most twice), `p = e^{rT} (C(K1) - C(K2)) / w`, r = 4%, T to 16:00 ET on the expiry date. Bounds `p_lo` (sell the spread: bid1 - ask2) and `p_hi` (buy the spread: ask1 - bid2). Leg quotes are the last NBBO at or before the instant (`/v3/quotes`), valid only if bid > 0, ask >= bid and at most 10 minutes old (15 minutes for `opt_open`, which together with the 09:30:00 floor confines it to the open window). NBBO quotes are used rather than minute or hour bars because bars carry no bid and ask, so they give neither bounds nor costs. A wide spread (one more strike each side) is computed at the close and the open for the robustness subset.

### Sample filters (applied in this order, each counted)

1. `pm_close` and `pm_open` both present, and `pm_close` in [0.05, 0.95].
2. Neither `pm_close` nor `pm_open` is exactly 0.500 (the unquoted-book placeholder found in the arb scan, amendment 3 there).
3. **Closure move** `|pm_open - pm_close| >= 0.03` (3 points). This is X in the plan.
4. `opt_close` and `opt_open` both valid, `opt_close` mid in [0.02, 0.98], no no-arbitrage violation (raw mid outside [0, 1]) at either.

Option quotes are fetched only for pairs that pass filters 1 to 3.

## 4. Primary analysis

Per event i (an eligible pair passing every filter):

- `dPM = pm_open - pm_close`, `dOpt = opt_open.mid - opt_close.mid`, `s = sign(dPM)`.
- **Catch-up slope** `beta`: OLS of `dOpt` on `dPM` with an intercept. `beta = 1` means the options' open repricing reflects the whole PM closure move; `beta = 0` means none of it.
- **Residual gap at the open** `G = s * (dPM - dOpt)`, in probability points, positive when the options moved less than the PM in the PM's direction. Equivalently, the PM-minus-options level gap at the open minus the same gap at Friday's close, signed by the PM move (Friday's basis is netted out).
- **Net of costs** `G_net = G - c`, where `c` is what it costs to trade the options toward the PM at the open: the half-width of the `opt_open` bounds on the side traded (`p_hi - mid` when s > 0, buy the spread; `mid - p_lo` when s < 0, sell the spread) plus the option commission per $1 of payoff (`arbscan.costs.commission_per_share(w)`, $0.65 per contract per leg). No PM cost is charged because the PM is only the signal here.

Inference: closures are the clusters (strike ladders on one underlying over one weekend are strongly dependent). 95% CIs from a cluster bootstrap that resamples closures with replacement, 10,000 draws, seed 20261003, percentile intervals. Reported for `beta`, mean `G`, mean `G_net`.

**Success criterion (fixed now):** the mean `G_net` has a 95% cluster-bootstrap CI whose lower bound is above 0, with at least 30 events from at least 8 distinct closures. If the sample is below 30 events or 8 closures, the answer is "sample too small" and no claim is made in either direction, whatever the point estimate. A CI that includes 0 is a null: no Opportunity claim.

The slope `beta` and its CI are reported alongside as the plain-language answer ("options reflected about Y% of the PM move at the open"); it is not the pass/fail test.

## 5. Secondary and robustness (reported, never used to rescue the primary)

1. **Follow-through on the reopening day:** `F = s * (opt_eod.mid - opt_open.mid)`, and the round-trip P&L of the option trade `s * (exit - entry)` with entry at the `opt_open` bound on side s and exit at the opposite `opt_eod` bound, minus two commissions. Also the PM side: `s * (pm_eod - pm_open)` (does the PM give back its move?). A positive `G_net` with no follow-through means the gap is PM noise or a persistent basis, not options lagging.
2. **Equal weight per closure:** mean of per-closure means of `G_net`, same bootstrap.
3. **Subsets:** Polymarket events with at least one data-api trade print in the closure (close instant to open instant); `|dPM| >= 0.05`; same strike pair at close and open and narrow-vs-wide disagreement <= 0.05 at both; by venue; by market kind (daily, weekly, month-end, Kalshi).
4. **Outcome check** for resolved markets: Brier score of `pm_open` vs `opt_open.mid` against the realized result, descriptive only.

## 6. Caveats the report must carry

- PM prices: Polymarket `prices-history` is a per-minute series that can be the midpoint of a thin book; the trade-print subset is the check. Kalshi candles carry real bid and ask.
- The call spread approximates the digital (average density over [K1, K2]); options and PM may settle on slightly different prints (official close vs Pyth or index level), and SPY or single-name options are American.
- 09:45 is fifteen minutes into the session; options can lag the stock over those minutes too, and the measurement is one NBBO snapshot per leg.
- A Monday-expiry option at 09:45 has hours to run, so its call spread can be very wide relative to the move; the costs absorb that.
- Overlapping strikes on the same underlying and closure count as separate events; the bootstrap clusters on the closure for that reason, and the per-closure-weighted mean is reported.
- Selection: only markets the venues listed, and only closures where a market was alive across the closure and had a clean expiry. The sample may be small; the report states its size first.

## 7. Outputs

- `research/results/open_options/events.csv`: one row per eligible pair, with filter status, every measurement above, `dPM`, `dOpt`, `G`, `G_net`, follow-through fields.
- `research/results/open_options/SUMMARY.md`: answer first (sample size, `beta` with CI, mean `G_net` with CI, verdict against section 4), funnel, secondaries, caveats.
- `research/results/open_options/catchup_chart.png`: `dOpt` vs `dPM` with the 45-degree line and the fitted slope.
- `research/results/open_options/RUN_LOG.md` and `run_meta.json`: command, timings, request counts, failures.
- Synthetic tests in `research/open_options/tests` (no network), added to `research/pyproject.toml` testpaths.

## Amendments

1. **2026-10-03, before any PM price or option quote was fetched** (only the Polymarket and Kalshi market listings had been downloaded). Kalshi is dropped from the run. The Kalshi listing pages show each 16:00 ET event created at about 05:00 UTC the day before its settlement date (for example `KXNASDAQ100U-26AUG27...` created 2026-08-26T05:00Z), so no Kalshi 16:00 market is listed before the close that starts a weekend or holiday closure, and every Kalshi pair fails eligibility rule 1 by construction. Downloading a year of Kalshi listings (about 2 MB per 1,000 markets, several hundred thousand markets) only to drop them all is not worth the disk; the runner is invoked with `--skip-kalshi` and the report says so. Nothing else changes.
