# touch_fresh: does the S21 seller rule hold on "will it hit" markets no earlier study used?

Pre-registered Sun 2026-10-04, about 01:55 New York time. This file, `config.py`, `universe.py` and `universe.json` are
committed **before any trade print, any result and any option or stock quote of these markets is pulled**. Changes
afterwards go under "Amendments", dated, never rewritten. The run is made once and reported whatever it shows.

## 1. What is being tested

S21 (`research/results/s21_options_anchor/SUMMARY.md`) found that selling YES at the first-weekend traded bid on stock and
S&P 500 "will it hit $X" markets, when the bid is 5 or more points above an options-derived touch probability, earned
+22.27 points per contract [+10.35, +33.14] on 60 markets in 33 events, almost all in-sample (2 out-of-sample markets).
Three caveats were raised (`cx5_strategy_selection/SUMMARY.md`, `cx6_judging/ASSESSMENT.md`): the anchor converts a
terminal probability into a touch probability without matching horizons; the option expiry lies at or after the ticket's
window; the rule was chosen after its results were seen. This study reruns S21's rule on markets no earlier study touched,
with the horizon matched explicitly.

## 2. The fresh sample (metadata only; `universe.py`, output `universe.json`)

- **Frame:** every closed event under Polymarket's `hit-price` tag (gamma `/events?tag_slug=hit-price&closed=true`, paged
  to the end). Event titles naming crypto, commodities, the dollar index, or non-S&P indices are left out
  (`config.EXCLUDE_TITLE_RE`, `config.NOT_STOCK`). **S&P 500:** "S&P 500" in the title (SPY or SPX). **Stock:** one
  ticker in parentheses in the title, not on the exclusion list. "All time high" events are left out.
- **Not fresh:** any market id in S9's, S15's or S19's `universe.json`, in S18's `prints_markets.csv` or `entries.csv`, or
  in S21's `anchors.csv`.
- **S21's eligibility rules, unchanged:** S15's floors (market volume at least $10,000; event volume at least $100,000),
  S21's parser (`s21_options_anchor.engine.parse_market`: one ticker, level, direction, window end), closed.
- **Entry weekend:** the first weekend start (20:00 New York on the last session day before a weekend, holidays in
  `config.HOLIDAYS`) strictly after the market's listing time, on or after 2025-10-01. The market must not have closed
  before that instant and its window must end after that Friday (S21 allowed the window to end on the Friday itself; a
  window that is over is not a live ticket, so this study requires it to be later).
- **Counted before this commit, from metadata only:** 142 markets in 85 events pass every rule except the event floor;
  **32 markets in 4 events pass every rule including it** (ABNB 13, SPY 10, COIN 9).

**Minimum (fixed): 30 markets on 15 events. The S21-eligible fresh sample has 4 events, so the primary fresh test is
INSUFFICIENT, and this is the verdict of record for the S21-eligible population.**

**Secondary sample R (pre-registered here, labelled as such in every output):** S21's rules without the $100,000 event
floor; the $10,000 market floor stays. 142 markets in 85 events (73 in weekly "Week of" events, 69 in monthly events; first
weekends from 2026-03-27 to 2026-09-25; every market charges a 4% taker fee rate). It is a broader and thinner population
than S21's (mostly weekly events whose single strikes traded $10,000 or more), so it tests whether the rule generalises,
not whether S21's exact population repeats. It runs through section 3 with the same rule and the same pass line; its
verdict is reported as "sample R", never as the verdict of the S21-eligible test.

## 3. The test (sample R; and the 32 S21-eligible markets reported descriptively, no verdict)

**Prints (S18's rule, `s18_price_market_calibration.prints`):** public trade prints from the data API between the entry
instant and 48 hours later (Friday 20:00 to Sunday 20:00 New York), at most two pages. `sell_price` = the size-weighted
YES price of takers who sold YES (the traded bid); `buy_price` = of takers who bought. A market whose size-weighted price
of all its window prints lies outside 2% to 98% is left out (S18's entry band). Results (1 or 0) from gamma's
`outcomePrices`, pulled after this commit. Seller P&L per contract held to the result, in points:
100 × (sell_price − fee − result), fee = c × rate × (p(1 − p))^exponent with the market's own schedule, c = 1 and 2.

**Anchor (S21's, horizon matched):**
- Instant: 15:55 New York on the entry Friday (12:55 on a half session). Option data from Massive only.
- **Expiry:** the listed expiry **nearest** the window's last session day, in calendar days, either side, within 45 days,
  after the anchor day; ties go to the later one. Candidates are tried in that order; an expiry counts only if it gives two
  usable legs; at most three expiries with listed contracts are tried.
- Strikes, legs, usable quotes, step-out, zero bids, the finish-beyond probability `p_T` (`p_mid`, with `p_lo`, `p_hi`):
  S21's code (`s21_options_anchor.engine.finish_beyond`, `arbscan.implied.Spread`), unchanged.
- **The barrier/terminal conversion, stated:** under a driftless lognormal model the probability of finishing beyond a
  level at horizon T is Φ(−z_T) with z_T = |ln(K/S)| / (σ√T), and the probability of touching it by horizon τ is
  2 Φ(−z_T √(T/τ)) (reflection principle). From the spread, z_T = Φ⁻¹(1 − p_T); so the **central anchor** is
  `touch = min(1, 2 Φ(−Φ⁻¹(1 − p_T) √(T/τ)))`, with T = calendar days from the anchor day to the expiry and τ = calendar
  days from the anchor day to the window's last session day. When T = τ this is S21's 2 × p_T exactly. No spot price or
  volatility enters: the spread's own probability fixes the distance in standard deviations. The band uses `p_lo`, `p_hi`.
  Approximations: no drift; American options read as European (as in S21); for a window that starts after the entry
  (monthly events listed before their month, weekly events listed before their week) the touch is counted from the anchor,
  which overstates the probability of a touch inside the window; such markets are flagged (`forward_start`).
- Also reported, not used by the rule: S21's unmatched 2 × p_T at the same expiry.
- A market with no usable anchor is counted by reason and dropped. No modelled price is substituted.

**Primary book B0 (S21's rule unchanged):** sell YES at `sell_price` when it is 5 or more points above the central
(matched) anchor; hold to the result. Statistic: mean P&L per contract with the event-clustered bootstrap 95% interval
(`s7_weekend_straddle.run.boot_mean`, 2,000 draws, seed 0).

**Pass line (sample R):** the interval at fee 1× lies above zero **and** the interval at fee 2× lies above zero, with at
least 10 markets in 5 events in B0. Fewer: INSUFFICIENT. Otherwise FAIL, stating the numbers.

**Also reported (no pass line):** U, selling YES at `sell_price` on every anchored market with a taker sale; B0 taken minus
U-left (`boot_diff`); B0 with S21's unmatched anchor; B0 restricted to markets without `forward_start`; B0 in weekly and
monthly events separately.

**Secondary 1, hedged B0.** At the anchor instant the seller is short a touch digital. Hedge with the underlying: hold Δ
shares of underlying per contract, Δ = ∂touch/∂S of the matched formula at S₀ = the underlying's NBBO mid at the anchor
instant (σ√τ = |ln(K/S₀)|/z_τ, z_τ = z_T √(T/τ); Δ = sign × 2 φ(z_τ) / (S₀ σ√τ), positive for an up level). The hedge is
held to the result: exit at the level K if the market resolved YES (the underlying touched K), otherwise at the
underlying's daily close on the window's last session day (Massive daily bars). Cost: Δ × the underlying's NBBO
half-spread at the anchor instant, paid at entry and again at exit. Hedged P&L = seller P&L + 100 × (Δ(S_exit − S₀) − cost).
Markets with no underlying quote, or with the level already on the far side of S₀, get no hedge and are counted. Reported
with its event-bootstrap interval, fee 1× and 2×.

**Secondary 2, market exposure.** Least squares of B0's and U's seller P&L (fee 1×, points) on the underlying's move over
the ticket window in the level's direction, m = sign × ln(close on the window's last session / S₀), errors clustered by
event (`s21_options_anchor.engine.ols_cluster`). Reported: intercept (P&L at zero move), slope, their intervals.

## 4. Operations

- Polymarket (public, no key): data API prints at most 3 requests a second; gamma results one request per market.
- Massive: one worker, at most 2 requests a second (S21's `Src`, its own cache in `research/touch_fresh/.cache/`),
  hard stop at 05:00 New York; what is not pulled by then is reported as not pulled. Streamed, one market at a time.
- If option or stock quotes are not served for these dates, the study stops and reports the error.

## 5. The forward test

`FORWARD.md` and `forward_config.py` commit the rule for markets listed from 2026-10-05, whatever this run shows.

## 6. Deliverables

`research/results/touch_fresh/`: `SUMMARY.md`, `markets.csv` (one row per market: prints, anchor or the reason dropped,
result, P&L, hedge), `books.csv`, `exposure.csv`, `RUN_LOG.md`, `.done`.

## Amendments

- **2026-10-04 02:05 New York, after the run, clerical.** The pull and the run were made once as written; no rule,
  threshold or sample changed. Found after the run and not repaired: S21's parser takes 2026-06-19 (Juneteenth, a market
  holiday) as the last session of the "Week of June 15" events, so 2 markets have no daily close (both in B0; they leave
  the exposure regression and their hedge exits at the level because both resolved YES).
