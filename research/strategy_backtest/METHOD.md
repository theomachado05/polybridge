# Strategy backtest: the PolyBridge closed-market overlay on a long SPY book (pre-registered)

**Question.** A $1,000,000 book is long SPY at all times. PolyBridge's closed-market mode watches prediction markets (PM) while US equities are closed and, at the first tradable moment, stages a short SPY hedge sized by the expected open gap (hedge B of `docs/design.md`; product code `backend/app/closed/staged.py`). Over January 2024 to the latest available session, net of costs, does the overlay give the long book a lower risk (maximum drawdown or volatility) than buy-and-hold SPY without lowering its Sharpe ratio, **in the out-of-sample segment**?

This file and `config.py` are committed **before any data for this study is fetched and before any backtest is run**. Every rule below is fixed. A later change goes under "Amendments" with the reason; the original stays in git history. The backtest is run once and reported whatever it shows. All variants are reported; the primary is fixed here.

## 0. What was known before this commit (honesty)

- **The 2024-2025 closure panels are not new data.** Their results are known to the author: R1 (`research/results/closed_hedge/SUMMARY.md`): hedge B at 09:30 (K = 100 bp, own-market expanding OLS rate) cut the 09:30-10:00 P&L variance by 11.4% (CI +5.1% to +18.1%) but hedges only 2.3% of the book on average and is active on 20% of closures; mean P&L effect slightly negative. R2 (`research/results/gap_model/SUMMARY.md`): the through-origin expected gap is accurate out of sample for the US-recession-2025 market (sign 64% of 151) but not for the election market and not for the 10-market replication panel (pooled sign 50.2%, slope -0.23). The pooled full-sample slope on panel A is +7.52 bp per pp.
- So the **in-sample segment (2024 to about early 2026) overlaps data whose closure-level relation is known**; the gating rule (section 3) was written knowing that, in 2025, probably only the recession market would pass. This bias is stated, not removed.
- **Not seen:** any prediction-market price dated 2026, any SPY price dated 2026, any strategy-level equity curve, drawdown or Sharpe on these data. The replication panel was clipped at 2025-12-31; its markets' 2026 prices (for example `will-china-invade-taiwan-before-2027`) have never been fetched. The OOS segment (section 6) falls inside 2026.
- Files read before this commit: the METHOD and SUMMARY of R1 and R2, the first rows of `closures_all.csv` and `leadlag_replication/results.csv`, the metadata list `leadlag_replication/markets.json` (slugs, signs, start and end dates, volume; no prices), and the product sizing code (`size_hedge`, defaults `target_coverage = 0.5`, `full_size_gap_bp = 50`, `min_gap_bp = 10`).
- 8-K disclosure data, `research/results/oos/` and `HYPOTHESIS.md` are not touched. The earlier rule "nothing dated 2026 is requested" in the replication study protected the 8-K holdout; this study uses only PM prices and SPY bars (no 8-K data), which the task brief allows.

## 1. Universe, closures and data

- **Primary universe (12 markets, the markets of the existing closure panels):** the two panel-A markets of `research/leadlag_closed/events.yaml` (Trump-wins 2024, sign +1; US recession in 2025, sign -1) and the ten selected markets of `research/leadlag_replication` (ranks 1-10 of `markets.json`, signs as frozen there). Signs are never changed.
- **Market life:** replication markets: `start`/`end` from `markets.json`. Panel-A markets: `startDate` and `closedTime` (else `endDate`) from the gamma `/markets?slug=` metadata (no prices read from gamma). An end after the last session is clamped to it.
- **Backtest span:** return days from the first session after 2024-01-02 to the **last session with complete SPY minute bars at run time** (the run records it). The book is bought at the 2024-01-02 close.
- **Closures:** every closure (overnight, weekend, holiday; calendar `polybridge_research.calendar`) whose close day is in the span. A market **participates** in closure t if its life covers the closure (nominal 16:00 close >= start and 09:30 open <= end), unlike the earlier studies, which clipped to fixed panel windows. No closure is removed by hand (the election night and the news closures stay in).
- **Prices.** PM: Polymarket CLOB `prices-history`, fidelity 1 minute, one request per market x closure covering [close - 300 min, open + 30 min] (the fetcher of `leadlag.data`). SPY: Massive 1-minute aggregates (extended hours, split-adjusted) for the whole span, Massive daily aggregates for closes and volume, Massive cash dividends for SPY. Only what is not already cached is fetched.
- **PM as-of rule:** the price at instant T is the last CLOB point with timestamp <= T, and only if it is at most 30 minutes old; otherwise missing (never imputed).
- **Instants (America/New_York):** `T_close` = end of the last regular-session minute bar of the close day (handles early closes). `T_sig` = 09:29:00 of the open day (one minute before the order goes in; the strictest as-of). `T_sig_pre` = 07:59:00 (pre-market variant).
- **Oriented move** of market m over closure t: `x = sign_m x (PM(T_sig) - PM(T_close))` in pp; positive = equity-bullish. Missing if either PM price is missing; the market then does not contribute to closure t and adds no training record.

## 2. Training records and look-ahead rule

- After the open of closure t, each participating market with an oriented move gets a **record** `(market, x, gap)` with `gap` = SPY first regular bar open / previous regular close - 1 (bp; first bar must start within 5 minutes of 09:30). It is **known at** the 09:30 open of t's open day.
- The rate and gate for closure t use only records known at or before `T_close` of t, i.e. records of closures whose open day is on or before t's close day. Enforced in code by a store that filters on `known_at` and by a synthetic test.

## 3. Evidence gate (walk-forward, per market)

A market contributes to closure t only if its **own** records available at t pass all of:
1. at least **20 records with x != 0**;
2. the through-origin rate `rate = sum(x g) / sum(x^2)` is **> 0**;
3. its HC3 t-statistic `rate / se >= 1.96` (HC3 for the through-origin fit as in `research/gap_model/model.py`: `h_i = x_i^2 / sum(x^2)`, `se^2 = sum(x_i^2 (e_i/(1-h_i))^2) / (sum(x^2))^2`).

The gate is re-evaluated at every closure, so a market can enter and leave. No market is chosen by hindsight: the universe is fixed in section 1 and trust is earned only from earlier closures.

## 4. Sizing, execution, unwind (the product's rule)

- Expected gap of a trusted market: `E_m = rate_m x x_m` (bp), with `x_m` measured to `T_sig`.
- Hedge fraction per market (product `size_hedge` with its defaults): `f_m = 0` if `E_m > -10 bp`; else `f_m = 0.5 x min(1, -E_m / 50)`.
- **Several trusted markets:** `f = max_m f_m`. This is the product's behaviour: all bridges on one position share one coverage cap and each tops up to its own target, so the combined hedge is the largest single target. **Cap: 50% of the long position's market value.**
- **Primary execution:** sell short `f x` (long market value at the entry price) at the **09:30 open** (open of the first regular minute bar), **cover at 10:00 ET** (close of the 09:59 bar), the same window as R1. If either price is missing, no trade that day (logged). The long SPY position is never traded.
- Hedge P&L (dollars) = `-f x shares x (P_exit - P_entry) - costs`.

## 5. Costs

- **Base case (1x), regular session: 1.0 bp of traded notional per side** (entry and exit each): half-spread 0.5 bp plus commissions and fees 0.5 bp. Sources and reasoning: SPY's quoted spread is normally one tick ($0.01) on a $470-$700 price, about 0.15-0.2 bp full spread, i.e. about 0.1 bp half-spread in continuous trading (the brief's ~0.3 bp spread figure); the open and the first minute are wider, so 0.5 bp half-spread is a conservative allowance. Commission: Interactive Brokers Pro tiered at most $0.0035 per share (about 0.06 bp); SEC Section 31 fee $27.80 per $1M of sales in FY2025 (0.28 bp on the short sale); FINRA TAF negligible; rounded up to 0.5 bp.
- **Pre-market variant entry: 3.0 bp** (pre-market SPY spreads are several ticks and depth is thin); its exit at 10:00 is 1.0 bp.
- **Stress case (2x):** every cost doubled.
- No borrow fee (the short is opened and covered the same morning), no financing; hedge P&L is held as cash earning 0. Risk-free rate for the Sharpe ratio: **0** (stated; both books hold the same cash, so a non-zero rate shifts both).

## 6. Books, segments and metrics

- **Benchmark:** buy-and-hold: $1,000,000 of SPY bought at the 2024-01-02 close (fractional shares), held; cash dividends credited on the ex-date as cash.
- **Strategy:** the same long position plus the cumulative net hedge P&L in cash. Daily equity = shares x official daily close + dividend cash + hedge cash.
- **IS / OOS by date:** with N return days in the span, the OOS length is `L = min(ceil(0.2 N), number of return days in the last 730 calendar days)`; OOS = the last L return days, IS = the rest. The walk-forward state (records, gates) runs continuously across the boundary; nothing is refitted or tuned on OOS. Both segments are reported.
- **Metrics per segment and book (from daily returns `r_t = equity_t/equity_{t-1} - 1`):** annualized return `(prod(1+r))^(252/n) - 1`; annualized volatility `sd(r, ddof 1) x sqrt(252)`; Sharpe `mean(r)/sd(r) x sqrt(252)` (rf 0); maximum drawdown of the equity within the segment (rebased at the segment start); worst calendar month (month return from month-end equity within the segment); turnover = total traded hedge notional (entry + exit) / mean equity / years; hedge hit rate = share of days with a hedge whose net hedge P&L > 0; number of hedge days, mean hedge fraction, total hedge P&L.
- **Grid reported (`metrics.csv`):** {IS, OOS, full} x {1x, 2x} x {primary, variants} plus buy-and-hold.
- Charts: `equity_curve.png` (hedged vs buy-and-hold, IS/OOS boundary marked), `drawdown.png`.

## 7. Variants (all reported; the primary is fixed above)

- **V1 pre-market:** move to `T_sig_pre` (07:59), entry at the 08:00 SPY price (close of the last minute bar ending at or before 08:00, at most 15 minutes before), cover at 10:00. Rates and gates as primary (trained on moves to 09:29).
- **V2 no gating:** the gap-model rate rule without the significance test: own rate if the market has >= 20 records with x != 0, else the pooled rate over all markets' available records if that has >= 20, else nothing; the rate is used whatever its sign. Same sizing.
- **V3 unwind at the close:** primary entry, cover at the close of the last regular bar of the open day.
- **V4 expanded universe:** all 45 candidates of the frozen `markets.json` ranking plus the two panel-A markets, each kept only if at least 40 of its closures in the span have a PM quote at both ends (the replication study's coverage rule). Primary rules otherwise.

## 8. Success criterion (fixed now; primary, OOS, 1x costs)

**Pass** if both hold: (a) the strategy's OOS maximum drawdown is at least 1% (relative) shallower than buy-and-hold's, **or** its OOS volatility is at least 1% (relative) lower; and (b) its OOS Sharpe is not lower than buy-and-hold's. Otherwise **Fail**. If the overlay never trades in OOS the books are identical and the verdict is Fail (no effect). IS and 2x results are reported next to it, not part of the verdict.

## 9. Sanity checks and capacity

- Any Sharpe above 3 (either book, any segment) is investigated and reported.
- **Reconciliation with R1:** on the panel-A closures that overlap R1's `closures_hedged.csv`, compare this study's gap, open-to-10:00 return and oriented move with R1's columns, and recompute R1's hedge-B P&L (`-f_B x ret30 - 4 f_B`) with this study's price legs.
- **Capacity (`capacity.md`):** per hedge day, hedge notional vs SPY 20-day trailing average daily dollar volume (prior days only) and vs the dollar volume of the five regular-session minute bars 09:30-09:34 (volume x bar close). The book size at which the **maximum** hedge (50% of book) stays below 1% of the opening 5-minute dollar volume: median and 5th percentile over all sessions; the book size at which 95% of actual hedges stay below 1%. Pre-market variant: the same against the 08:00-08:04 dollar volume.

## 10. Outputs

`research/results/strategy_backtest/`: `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`, `trades.csv` (every hedge day of every variant: date, trusted markets, E, f, prices, notional, gross and net P&L), `capacity.md`, `RUN_LOG.md` (commit, wall time, network requests, last session, split date, exit status), `daily.csv`, `records.csv`. Code: `research/strategy_backtest/`; synthetic tests: `research/strategy_backtest/tests/`.

## 11. Caveats stated in advance

- **Small overlay.** R1 hedged 2.3% of the book on average on 20% of closures; with the gate even fewer days trade. Book-level metrics may differ from buy-and-hold only in the second decimal. The 1% materiality threshold in section 8 is there so that a rounding-size difference cannot pass.
- **Hedge B cannot recover the gap**; it trades only the 09:30-10:00 move (or to the close in V3). Its book-level value depends on post-open moves after adverse PM signals.
- **Thin OOS.** Few markets in the universe live into 2026 (from the metadata: `will-china-invade-taiwan-before-2027`, the Supreme Court tariff market until 2026-02-20, and markets ending around 2026-01-01). The OOS may have no trusted market and no trades; V4 widens the universe for that reason.
- **Fills simulated** at minute-bar prices plus a fixed cost; the opening auction price can differ from the first minute bar's open.
- **Known panel in IS** (section 0).

## Amendments

1. **Crash of the first invocation and rerun (2026-10-03, before any result).** The first invocation (`d32365f`, 22:14Z) crashed with a pandas `TypeError` while parsing the SPY daily bars in `data.fetch_daily` (a `tz_convert` on a Series instead of its dates). At that point only SPY minute and daily bars had been requested; no prediction-market price had been fetched, no closure, record, trade or metric had been computed, and nothing was written except the crash entry in `RUN_LOG.md`. The parse is fixed in `71d2445` (with fetch tests on synthetic payloads); no rule changes. The study is rerun once from the same code otherwise. Two earlier pre-run fixes, made before any invocation, are in `404f23c` (on 13:00 early-close days the regular session ends at 13:00, so post-market bars are not read as the close, as section 1 intends; and a cleaner traded-notional expression with identical values).
2. **Second invocation stopped by hand (2026-10-03, before any result).** The second invocation (`f7d1f4d`, 22:23Z) printed 0 closures for both panel-A markets: gamma `/markets?slug=` returns nothing for closed markets unless `closed=true` is passed, so their life (section 1) came back empty and was cached as empty. The process was killed during the prediction-market fetch, before any walk-forward, trade or metric was computed and before any output file was written. Fixed in `2ff3d7e`: the lookup retries with `closed=true`, never caches empty metadata, and the runner refuses to continue if a primary-universe market has no closure in the span. Life is still `startDate` and `closedTime` (else `endDate`) as written in section 1. No rule changes; rerun once.
