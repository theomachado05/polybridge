# Parallel brief: sessions P1 to P4 (written Sat 2026-10-03 22:40 New York time)

PolyBridge, GatorQuant Hacks 2026, Systematic Trading track. Devpost closes **Sun 2026-10-04 10:00 New York time**.
**Your result must be committed and pushed by Sun 07:30 New York time (11:30 UTC).** A clear, honest answer by then
beats an unfinished larger one. Post the headline numbers to Theo as soon as your run finishes.

The track scores: equity curve, Sharpe, maximum drawdown, worst month, turnover; costs in bp with their source;
capacity; in-sample against out-of-sample (the most recent 20% of the history); every variant tried, disclosed.

## 1. What nine studies have established

The signal is real. Three independent tests say that the link between a prediction-market question and an asset
works:

| Study | Finding | Size |
|---|---|---|
| S4 | The linked stock or ETF opens where the odds moved overnight | +4.69 bp per point of odds, t = 4.01 |
| S5 | The same on 93 fresh markets, 27 tickers | +6.88 bp per point, t = 6.01; +137 bp after moves of 10+ points |
| S9 | On weekends Polymarket's own oil price markets move with oil-linked event odds | +0.86 points per point, t = 5.85 |

No trade has paid, for three reasons that are about **when and where the signal can be traded**, not about the link:

1. **The asset has already moved when it can be traded.** The gap is complete at the open and at 08:00 pre-market.
   After the open: −0.55 bp per point (t = −0.74). Buying the linked equity at the open lost 14 bp per trade (S5).
2. **Options are not cheap on Friday.** Friday straddles on tickers with a live event lost 17.7% of the premium, the
   same as ordinary weekends; at mid prices −1.0% against −2.0% (S7).
3. **On Polymarket the over-reaction is the size of the cost.** After a large move the odds give part of it back:
   2.63 points after an overnight move of 10+ points (S8, interval −3.90 to −1.47); 2.94 points after a weekend move
   of 5+ points in the price markets (S9, −4.66 to −1.14; oil 4.18). Crossing the spread twice and paying the fee
   twice costs 2.6 to 3.3 points. Net: −1.47 points per trade (S8), −0.01 (S9), and negative out-of-sample.

Also done: same-question gaps between Kalshi and Polymarket are real but tiny (S1: +$47.50 on $1,177, print-verified);
three-way consistency never fired (S3); taking the options' side against thin threshold markets on Monday has too few
verified trades (S6); the asset's opening move does not tell which odds moves reverse (S8).

Read before you start: `research/EVIDENCE.md` section 9, and the SUMMARY.md of S5, S8 and S9 under `research/results/`.

## 2. Doors still unopened (one per session)

- **P1, `s10_weekend_lag`:** inside the weekend, minute by minute, does the event question move before the oil price
  market? If the price market lags by minutes, that is a trade in a market that is open.
- **P2, `s11_bundles`:** related questions as one book: strike ladders, date ladders and one-of-many sets must be
  consistent with each other. Violations beyond costs, and a sibling that lags when one rung jumps.
- **P3, `s12_resting_orders`:** the give-back is real and a taker cannot keep it. Can a resting order? Fees are
  taker-only. Fills judged strictly against public trade prints.
- **P4, `s13_price_market_calibration`:** are the price markets overpriced against how they resolved, and against the
  touch probability implied by listed options on USO, GLD and SPY?

## 3. Data already on disk (do not pull again)

| What | Where | Notes |
|---|---|---|
| One-minute Polymarket odds, 148 event markets, 2025-10-01 to 2026-10-02 | `research/s5_big_moves/.cache/pm_<id>.npz` (`t` epoch s, `p`) | links: `s5_big_moves.run.merge_links()` |
| The same for S4's markets, from 2026-01-02 | `research/s4_linked_assets/.cache/pm_<id>.npz` | links: `s8_open_referee.run.links()` gives S5 + S4 agreed links, SPY dropped |
| Five-minute bars and daily bars, 48 tickers and SPY | `eq_<TICKER>.npz`, `day_<TICKER>.npz` in the two caches | regular session only |
| One-minute prices of 391 price markets, **weekend windows only** (Friday 19:00 to next session 10:10, New York) | `research/s9_weekend_price_markets/.cache/pm_<id>.npz` | universe, sign, fee, result: `s9_weekend_price_markets/universe.json` |
| Every market-weekend of S9 and every S9 trade | `research/results/s9_weekend_price_markets/weekends.csv`, `trades.csv` | |
| Every large overnight move of S8 and every S8 trade | `research/results/s8_open_referee/mornings.csv`, `trades.csv` | |
| 892 ranked event markets with event slugs | `research/s5_big_moves/candidates.json`, `universe.json` | catalogue metadata |
| Live order books since Sat 19:09 New York time (33 twin pairs every 15 s, 660 threshold markets every 30 s) | `research/forward/raw/`, format in `research/forward/README.md` | still recording; read only |

Helpers worth importing (run everything from `research/` with `.venv/bin/python -m <package>.<module>`):

- `s1_twin_spread.data as ds`: `Throttle`, `get_json`, `pm_history(meta, start, end, throttle)` (one-minute prices, 14-day
  chunks), `pm_trades(condition_id, oldest_needed, throttle, max_pages=2)` (public prints; the API serves only the
  latest 20,000 of a market), `GAMMA`, `CLOB`.
- `s1_twin_spread.engine.asof` (last reading at or before an instant, with a maximum age).
- `s4_linked_assets.engine as en`: `sessions_from`, `betas`, `clustered_slope`, `date_bootstrap`.
- `s6_monday_fade.run`: `verify` (is there a print that proves the fill), `closure_metrics`, `write_csv`.
- `s7_weekend_straddle.run`: `boot_mean`, `boot_diff`; and its option-quote code (`arbscan.datasrc.OptionSource`).
- `s9_weekend_price_markets.run`: `calendar()` (the weekend clock), `trade`, `universe`.
- Live books: `POST https://clob.polymarket.com/books` with `[{"token_id": ...}, ...]` (up to 100 per call).
- Only numpy, pandas, matplotlib and requests are installed. No scipy, no sklearn.

## 4. Rules (all of them bind)

- **Pre-register.** Write `METHOD.md` and `config.py` (every rule, every variant, the success criterion, what was
  already known) and commit them **before** pulling or reading any data for the test. Changes afterwards go under
  "Amendments", dated, never rewritten.
- **Fills only at prices and sizes that existed.** Polymarket's history is a mid price, not a quote. Either trade at
  real bid/ask from books, or move every fill by a stated half-spread plus the market's own fee and check entries
  against public prints. A stale mid in a thin market looks like a lag or a mispricing and is neither.
- Report at **1× and 2× costs**. Costs in points and in bp, with their source.
- **A Sharpe above 3 means hunt for the bug** before reporting.
- Report a null as a null, in "what didn't work". Lead the summary with whatever is significant and true. Never tune
  a rule after seeing the result; never pick the best variant and present it as the test.
- In-sample against out-of-sample: the most recent 20% of the history, by date or weekend. Intervals by bootstrap
  over dates or weekends (several markets on one date are one bet).
- Never touch `research/results/oos/` or the 8-K out-of-sample window. `research/HYPOTHESIS.md` is append-only.
- Never print or commit keys (`.env` holds `MASSIVE_API_KEY` and Webull keys).
- Plain language in everything Theo reads: short sentences, no jargon without a gloss.

## 5. Several sessions share this working tree

- Work in `/Users/theomachado/gatorquant` on branch **`r/weekend-options`**. Do not switch branches, create
  worktrees, stash, reset or check out files: other sessions' uncommitted work lives in the same tree, and the disk
  is nearly full.
- You own exactly two folders: `research/<your package>/` and `research/results/<your package>/`. Do not edit
  anything else. In particular leave `research/EVIDENCE.md`, `research/pyproject.toml`, `.gitignore`,
  `research/make_notebook.py` and other studies' code alone; the main session integrates your result. If you need a
  helper changed, copy the function into your package.
- Commit only your own paths, always with a pathspec:
  `git add research/<pkg> research/results/<pkg> && git commit -m "<message>" -- research/<pkg> research/results/<pkg>`
  then `git push origin r/weekend-options`. Never `git add -A` or `git commit -a`. If `index.lock` exists, wait five
  seconds and retry. Never push to `main`. End commit messages with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Caches go in `research/<pkg>/.cache/`; put a `.gitignore` containing `.cache/` inside your package folder. Keep
  committed results under 50 MB. About 7 GB of disk is free: keep caches small (store only what the test needs).
- **Rate limits are shared with a live recorder that must not be disturbed.** Do not call Kalshi at all.
  Polymarket (gamma, CLOB, data API): at most 3 requests a second. Massive: at most 5 a second.
- Do not stop or restart the recorder (`research/forward/recorder.py`) or read its files while writing your own
  there.
- Tests: `cd research && .venv/bin/python -m pytest <pkg>/tests -q`. Check the exit code, not a piped tail.

## 6. What to deliver, in your two folders

`METHOD.md`, `config.py`, code, tests; and in `research/results/<pkg>/`: `SUMMARY.md` (answer first, in plain
language, with the numbers), `metrics.csv`, `trades.csv`, `equity_curve.png`, `drawdown.png`, `capacity.md`,
`RUN_LOG.md` (times, commit hashes read from `git log`, data sources, anything that went wrong). Read every number in
your summary back from the result files before you write it.
