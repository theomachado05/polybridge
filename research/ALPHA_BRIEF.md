# Research brief: weekend and cross-venue alpha (Kalshi × Polymarket × options)

**Owner:** Theo, with Jacob. Written Sat 2026-10-03 at 18:20 ET. Devpost is due Sun 10:00 ET; the pitch is Sun 13:00.

**Goal:** find a strategy with a real, defensible edge and report it the way the Systematic Trading track scores it:
- an equity curve;
- Sharpe, max drawdown, worst month and turnover;
- costs in bp, with their source;
- capacity;
- in-sample vs out-of-sample;
- every variant tried, disclosed.

## Thesis

1. **Weekend edge.** US equities and options are closed from Friday 16:00 to Monday 09:30 ET. Polymarket and Kalshi keep trading. Their weekend move carries information that stocks and options only price in at the Monday open.
2. **Cross-venue arbitrage.** The same event is priced on Kalshi, on Polymarket and, for threshold questions such as "S&P above X on date", in listed options (call-spread implied probability). Fast, systematic trading of the gaps, net of every fee, is the edge.

## What we already know (read these first; do not repeat them)

| Evidence | Result | File |
|---|---|---|
| Options vs weekend PM move | At the Monday open, options reflect 0.44 of the weekend PM move (CI 0.33–0.57); the residual gap after costs is +0.79 pt [-1.21, +2.78]. NULL. Options are better calibrated (Brier 0.120 vs PM 0.146); the PM gives back 3.48 pt after the open. | `research/results/open_options/SUMMARY.md` |
| PM vs options arb scan | 5 verified gaps on resolved markets, 0 executable (single prints of 5–100 shares). Kalshi with real bid/ask: 0 of 500 survive costs. | `research/results/arb/SUMMARY.md`, `arb_gaps.csv` |
| Polymarket↔Kalshi twins | 33 verified pairs (resolution text, threshold, deadline and direction checked); 150 ambiguous, kept out. | `backend/app/data/kalshi_twins.json`, `backend/app/twins/` |
| Overnight gap | 380 closures, +7.52 bp/pp (p 0.001). Did not replicate on 10 new markets (+0.63, p 0.126). Holds out of sample only on the US-recession market. | `research/results/leadlag_closed`, `leadlag_replication`, `gap_model` |
| Pre-registered strategy method | Closed-market overlay backtest, METHOD committed (`3c6b280`), not yet run. | `research/strategy_backtest/METHOD.md` |
| Everything | Every result with numbers and caveats | `research/EVIDENCE.md` |

Reusable code:
- `research/arb/`: threshold matching, call-spread implied probability with bid/ask bounds, cost model.
- `research/open_options/`: weekend windows and Massive option bars.
- `research/leadlag*`: Polymarket gamma and CLOB `prices-history`, the Massive client, closure calendars.
- `backend/app/twins/`: the twin matcher.
- `backend/app/markets.py`: live CLOB `/book` and Kalshi orderbook clients.

## The three candidate strategies (each pre-registered separately)

**S1. Polymarket–Kalshi twin spread (the "HFT" leg).**
- Signal: on each verified twin pair, buy the cheaper venue's YES and sell (or buy NO on) the richer one when the gap clears all-in costs.
- Costs:
  - Kalshi taker fee formula, ceil(0.07·C·P·(1−P)) per their schedule (cite it);
  - Polymarket fees for that market type;
  - both half-spreads;
  - capital locked until resolution, as a carry cost.
- Exit: convergence, or held to resolution.
- History: Kalshi candlesticks carry real bid/ask; Polymarket `prices-history` is mid-only, so model its half-spread from live-book medians and say so.
- Many observations come from many pairs × many minutes, so Sharpe and t-stats can mean something.

**S2. Weekend PM move → Monday-open options trade.**
- Use the weekend PM move on threshold markets that map to listed options.
- Trade the option structure at 09:30–09:45, sized by the residual gap, and exit at a fixed time.
- Start from the R3 data. R3 says the net residual is not significant, so a pass needs a better structure: tighter selection fixed **ex ante** by a rule, or a cheaper leg. Never by looking at outcomes.

**S3. Three-way consistency.**
- Kalshi, Polymarket and the call-spread implied probability for the same threshold and date.
- Trade the venue that disagrees with the other two.
- Expect few observations. Report n honestly.

## Forward test (time-critical: start first)

Polymarket and Kalshi trade all weekend. **Start a recorder now** for the order books (top-5 levels, bid/ask, timestamps) of every verified twin pair and every threshold market with listed options. Record every 15–60 s until Sun 09:30 ET.
- Write to `research/forward/` and commit summaries, not raw dumps above about 50 MB.
- Freeze each strategy's rules (commit METHOD.md) **before** the forward window starts being analysed.
- Run S1 on the recorded books as a **paper forward test**: fills at recorded bid/ask, fees applied. This is genuinely unseen data. It is the strongest evidence we can show on Sunday, whatever it shows.

## Rules (non-negotiable; this is how the track judges)

- **Pre-register:** each strategy's METHOD.md is committed before any data is pulled for it. Fix markets, signals, thresholds, sizing, exits, costs, the IS/OOS split and the success criterion ex ante. Amendments are dated and appended, never rewritten.
- **Out of sample:**
  - The most recent 20% of history or 2 years, whichever is shorter.
  - Never used to design or tune.
  - The forward weekend recording is a second, independent OOS.
- **Report every variant tried.** Use a deflated Sharpe when more than one variant is tried (`research/polybridge_research/stats.py` has it).
- **A Sharpe above 3 on daily data means hunt for the bug** (look-ahead, stale prices, ignored fees, fills you could not get). Fills only at prices that existed, at sizes that existed.
- **Costs in bp with their source;** report at 1× and 2× costs.
- **Capacity:** the $ size before fills exceed X% of visible depth or volume.
- **Do not touch** the 8-K OOS window or `research/results/oos/`. `research/HYPOTHESIS.md` is append-only.
- **Report whatever comes out.** A clean null goes into "what didn't work"; do not reframe it as a win.
- **Git:**
  - Work on branch `r/alpha-weekend-arb`.
  - Commit early. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Open a PR to `main`. Never push to `main`.
- **Keys:** `.env` holds `MASSIVE_API_KEY` and Webull keys. Never print them. Kalshi and Polymarket public data need no key.

## Coordinate with Jacob (avoid duplicate work)

Suggested split, confirmed with him first:
- **This session:** the forward recorder, then S1 (twins), then the S1 forward test.
- **Jacob:** S2 (weekend → options, building on R3) plus the already pre-registered `research/strategy_backtest`.
- **Whoever finishes first:** S3.

Each strategy gets its own folder: `research/s1_twin_spread/`, `research/s2_weekend_options/`, `research/s3_three_way/`.

## Deliverables by Sun 08:00 ET

For each strategy:
- `research/results/<strategy>/SUMMARY.md`;
- `metrics.csv` (IS / OOS / forward × 1× / 2× costs);
- `equity_curve.png`;
- `drawdown.png`;
- `trades.csv`;
- `capacity.md`;
- `RUN_LOG.md`.

Then:
- a short addition to `research/EVIDENCE.md`;
- a notebook section that reproduces the headline numbers from committed results.

Post headline numbers to Theo as soon as each run finishes.
