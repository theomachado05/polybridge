# Closed-market lead-lag method (pre-registered)

Question. The wave-1 study (`research/leadlag/`, results in `research/results/leadlag/SUMMARY.md`) found no evidence that Polymarket (PM) leads US equities **while equities trade**. This study tests a narrower claim:

> When news breaks while the US equity market is **closed** (nights, weekends, holidays), the prediction market is the only liquid price. So its move during the closure should predict the equity **opening gap** at the next open.

Status of the evidence: **hand-picked case studies plus an unselected placebo panel. Supporting evidence at best, not proof.** Co-movement over the same window is not the same as one price leading the other; section 8 says what this design can and cannot show.

This file, `config.py` and `events.yaml` were written and committed **before any event-window price series (PM or equity) was fetched or any statistic was computed**. Every threshold below is fixed. A later change goes in "Amendments" at the bottom, with the reason; the original stays in git history.

What was looked at before this commit, for honesty:
- Market metadata only (gamma API: slug, token id, start date, volume). One finding from it: the "U.S. Recession in 2024?" market was created on 2024-08-05 03:07 UTC, so it has no price at the Friday 2024-08-02 close. The 2024-08-04/05 sell-off weekend therefore has no usable pre-set market and is **excluded**.
- One endpoint probe of CLOB `prices-history` on two quiet dates that are not in the event list or the date ranges of any event (2025-08-12/14 and 2024-08-13/14, PM only, no equity bars). It showed that `fidelity=1` returns one point per minute even over a 42-hour request, so no coarser fidelity is needed.
- The author knows from memory the rough outcome of many listed events (for example that SPY gapped up on 2024-11-06 and down on 2025-04-03). No price series for them has been looked at. Section 8 lists this as hindsight selection.

## 1. Definitions

- **Regular trading hours (RTH)**: 09:30-16:00 America/New_York on NYSE trading days (calendar: `polybridge_research.calendar.TradingCalendar`). Early-close days (13:00 ET) are handled by taking the end of the last RTH bar actually present.
- **Closure**: the span from the end of the last RTH bar of one trading day (usually 16:00 ET) to the start of the first RTH bar of the next trading day (09:30 ET). Types: `overnight` (consecutive weekdays), `weekend` (Friday close to Monday open), `holiday` (any longer span that includes a market holiday).
- The equity ETF still trades in extended hours (04:00-20:00 ET) during a closure. "Closed" here means the **regular session** is closed. SPY pre-market and after-hours prints exist but are thin; the gap defined below is measured against the regular-session close and open. Section 8 states what this implies.
- **Sample ETF**: SPY is the primary instrument for every event and every closure. QQQ is computed as a secondary column; it never replaces SPY in a headline.
- **News event**: an item in `events.yaml` with a news timestamp (ET) that lies inside a closure, i.e. outside 09:30-16:00 on a trading day or on a weekend/holiday. The event's closure is the closure that contains the news timestamp (the test suite checks this).

## 2. Event selection rule (fixed in `events.yaml`)

1. News timestamp falls in a closure (section 1).
2. The news is a macro, political or geopolitical item broad enough to move the whole US equity market, so SPY is the mapped ETF.
3. **PM market fixed by rule, not by event.** Political and election events of Jul-Nov 2024 use the Trump-wins market (`will-donald-trump-win-the-2024-us-presidential-election`, about $1.5B volume, Yes-price up = +1, bullish for SPY). All macro, tariff, geopolitical and policy events of 2025 use `us-recession-in-2025` (about $11.7M volume, created 2025-01-08, Yes-price up = -1, bearish). The sign is a property of the market, set once, not of the event. This removes the choice of a favourable market per event. The cost: the market is sometimes only loosely related to the news (for example the 2025-10-01 shutdown). Those events stay in, and the loose fit is a reported caveat, not a reason to drop them.
4. High volume: both markets exceed $10M lifetime volume.
5. Candidates were taken from the families in the brief (weekend tariff announcements, overnight election call, weekend geopolitical strikes, Sunday-night policy news, overnight shutdown deadline). 17 events, listed in `events.yaml` with an approximate news time (ET) and a precision note. The news time only decides which closure the event belongs to; no statistic uses it.
6. Overnight Fed-adjacent news: no event satisfied rules 3-4 with a defensible sign (no Fed market maps to SPY without a sign argument for each event), so none is included. Stated as a gap, not hidden.
7. Dropped before data: 2024-08-04/05 (market does not exist yet), 2024-10-25/26 Israel strike on Iran (no pre-set liquid market for H2-2024 macro news), 2025 DeepSeek weekend is **kept** (a test of whether the recession market prices tech news).

## 3. Measures (per closure)

All times are the exact ET instants; "close" and "open" are the closure's first and last instants.

- `pm_close` = PM Yes-price (in percentage points) at the closure start: last CLOB point with timestamp <= close. `pm_open` = same at the closure end (open). Requires a point within 30 minutes before the instant, else the closure is `no PM quote` and is excluded from every test (never imputed).
- **PM change** `dpm = pm_open - pm_close` (pp). Oriented: `dpm_o = sign * dpm`, with sign = +1 (Trump market) or -1 (recession market). Positive `dpm_o` means "PM moved in the equity-bullish direction".
- **Equity open gap** `gap_bp = 1e4 * (open / prev_close - 1)`, `open` = open of the first RTH bar of the next session (must start within 5 minutes of 09:30, else NA), `prev_close` = close of the last RTH bar of the previous session. Minute bars: Massive `/v2/aggs/ticker/<T>/range/1/minute`, adjusted, via the existing client.
- **First 30 minutes**: `ret30_bp = 1e4 * (px_1000 / open - 1)`, `px_1000` = close of the 09:59 bar. NA if that bar is missing.
- **Residual gap** (secondary): `px_0800` = close of the last bar that ends at or before 08:00 ET (within 15 minutes, else NA). `resid_bp = 1e4 * (open / px_0800 - 1)` and `dpm_early_o = sign * (pm_0800 - pm_close)`. This asks whether the PM move up to 08:00 ET predicts the equity move from 08:00 to the open, i.e. whether pre-market SPY had already absorbed it.

## 4. Tests (all thresholds fixed here; two-sided, alpha = 0.05, no multiplicity adjustment)

Applied to the **news events** (primary) and, separately, to the **placebo closures** (section 5).

- **T1 sign agreement.** Among closures with `|dpm_o| >= 1.0 pp` and `gap_bp != 0`: agree = `sign(dpm_o) == sign(gap_bp)`. Exact two-sided binomial test against p = 0.5. Sensitivity thresholds 0.5 pp and 2.0 pp are reported but are not headline.
- **T2 regression.** OLS `gap_bp = a + b * dpm_o + e` on all news events with a valid PM change and gap (no threshold). HC3 standard errors. Reported: `b` (bp of gap per pp of PM change), HC3 t, R-squared, and a **permutation p-value** (10,000 shuffles of the gap vector, seed 20261003, two-sided on |b|). The permutation p-value is the primary one because n is small and the PM changes are heavy-tailed. Also reported: Spearman rank correlation with its permutation p.
- **T3 first 30 minutes.** Same T1 and T2 with `ret30_bp` as the outcome, plus the `gap_bp` to `ret30_bp` sign relation (reversal vs continuation) as description. Secondary.
- **T4 residual gap.** T2 with `resid_bp` on `dpm_early_o`. Secondary.
- **Decision rule for the headline (written now, applied later).** "Supports the closed-market claim" requires **all three**: (i) T1 on events is significant at 5% with agreement above 50%; (ii) T2 on events has `b > 0` with permutation p < 0.05; (iii) the placebo-pairing test (section 5, P2) rejects at 5% for the agreement count. "Mixed" if one or two hold. Otherwise "no evidence". The words of the result follow this rule. A weak or null result is reported as is.

## 5. Placebo (closures with no flagged news)

- **Panels.** For each of the two PM markets, every closure in a fixed date range, with the closure's start date inside the range: Trump market, 2024-04-01 to 2024-11-04; recession market, 2025-01-10 to 2025-12-30. Each uses the market's own sign. The closure containing a listed news event is removed from the placebo set. Nothing else is removed. In particular, scheduled releases that land in a closure (CPI and jobs at 08:30 ET) and unlisted news stay in the placebo set. So the placebo is "no *selected* news", not "no news", and it is a conservative comparison: a PM-gap relation that appears here too would mean general co-movement, not an event effect.
- **P1** The same T1 and T2 statistics on the placebo set (HC3 and permutation p as above; for the panel the permutation uses 10,000 shuffles too).
- **P2 pairing placebo.** For each news event with a valid PM change and `|dpm_o| >= 1.0 pp`, replace its gap by the gap of a uniformly random placebo closure from the same panel, redraw 10,000 times (seed 20261003), and record the agreement count and the T2 slope. P-value = share of draws at least as extreme as the observed event statistic (agreement count at least as high; slope at least as high). This asks whether pairing the event's PM move with **its own** gap does better than pairing it with any gap.
- **P3 interaction.** Pooled events plus placebo: `gap_bp = a + b * dpm_o + c * news + d * (dpm_o * news) + e`, HC3. `d` is the extra response per pp on news closures. Reported with its t statistic.
- Also reported, no test: counts and medians of closure types (overnight, weekend, holiday), and the same T1/T2 on overnight-only and weekend-or-holiday-only subsets of the news events.

## 6. Usability rules

1. No PM quote at close or at open (section 3): closure excluded, with reason `no PM quote`.
2. Gap or `prev_close` NA (missing RTH bars at either end): excluded from tests with that outcome, with reason `no equity bar`.
3. Both HTTP sources must succeed; a failed fetch is recorded as `fetch failed` and the event is excluded, never imputed.
4. Excluded events stay in the event table with the reason.

## 7. Data

- PM: CLOB `prices-history?market=<Yes token>&startTs&endTs&fidelity=1`, one request per closure covering `[close - 2 h, open + 30 min]`. Cached on disk.
- Equity: Massive minute bars (SPY and QQQ), adjusted, extended hours included, fetched in calendar-month chunks. Cached on disk by the existing client.
- No 8-K disclosure data is fetched and no option data. The study uses prices only. Equity bars and PM prices for 2025 and 2024 only; nothing dated 2026 is requested.
- Key handling: `MASSIVE_API_KEY` is read from the environment or `.env` and is never printed or written. A missing key logs a message and exits with status 2.

## 8. Caveats stated in advance

- **Hindsight selection.** The 17 events were chosen by the author after the fact, knowing that these were big news days. Famous days are famous partly because the market moved a lot, so the gap is likely large on them. This biases toward a visible relation if one exists, and it does nothing about direction. The unselected placebo panel is the guard against it, not a cure.
- **Shared markets.** All 13 events of 2025 use one PM market; the four political events (Jul-Nov 2024) use another. Events are not independent draws. Standard errors and the binomial test assume independence and are therefore somewhat too optimistic.
- **Co-movement, not lead.** The PM change and the gap cover the same window. A positive relation says the PM and the equity open moved together over the closure. It does not show the PM was first. The residual-gap test (T4) is the only piece that looks at timing, and it is secondary.
- **Equity prices during the closure exist.** SPY trades after hours and pre-market. By 09:30 the open already reflects that trading plus futures (not observed here). So the PM is not literally the only price, and "the gap" is a measure against regular-session prints.
- **Level-dependent PM changes.** A move of 1 pp means little at 50% and a lot at 2%. The recession market sits low (mostly 10-60% early in 2025, then falling toward 1-5% by late 2025), which shrinks late-2025 changes. The pp threshold therefore filters out late-2025 events; T1 counts report how many events pass.
- **Loose market-to-news fit** for some events (shutdown, DeepSeek, Iran strikes) and a fixed sign per market even where the economic channel is ambiguous.
- **Small n.** About 10-16 events. A binomial test on 12 events needs 10 of 12 agreeing for p < 0.05. A null result here is weak evidence of no effect.
- **Event time and market-hours edge cases**: approximate news times are not used in any statistic. Early-close days use the last RTH bar present.

## Amendments

(none yet)
