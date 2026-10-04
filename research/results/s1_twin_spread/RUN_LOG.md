# S1 run log

All times UTC. Sat 2026-10-03 23:00 UTC is 19:00 ET. Commands are run from `research/`.

## Timeline

| Time | What | Result |
|---|---|---|
| 10-03 23:09:48 | Forward recorder started (`research/forward/run_recorder.sh`) | 33 twin pairs every 15 s, 660 threshold markets every 30 s |
| 23:15:57 | `METHOD.md` and `config.py` committed (`8260548`) | Before any S1 price history was pulled |
| 23:16 | API format probe on one pair (`KXIPO-26-ANTHROPIC`): candle fields, range limits | Kalshi serves at most 5,000 candles a request; Polymarket refuses 1-minute ranges over about 15 days |
| 23:18:00 | Cut-off `T1` of the history pull: `python -m s1_twin_spread.data` | 402 s; 32 pairs; 1 failed on Kalshi's rate limit |
| 23:25 | `python -m s1_twin_spread.data KXPRESNOMD-28-GN` (same cut-off, 3 requests a second) | 47 s; all 33 pairs pulled |
| 23:26 | Data-quality check: Kalshi candles against the recorder's live books (no strategy quantity) | Candles are written only when the top of the book changes: 792 of 792 old-candle snapshots equal the live book |
| 23:27:19 | Amendments 1 and 2 committed (`460ffca`) | Before any backtest was run |
| 23:28 | **Debug run 1**, partial calibration slice (73 of the final 202 snapshots per market), no print check | Code test. Sharpe ratios of 3 to 9 seen: bug hunt started |
| 23:30 | **Debug run 2**, same partial slice, with the print check | 15 of 99 out-of-sample entries print-verified: the artifact identified |
| 23:33 | Forward code smoke test on the calibration slice (outside the forward window) | Code path ran; only the count of trade objects was looked at (3) |
| 23:46:51 | Amendment 3 committed (`68b49ff`) | Before the forward window opened |
| 10-04 00:00:00 | Calibration slice closed | 202 snapshots per market; 32 of 33 Polymarket books usable |
| 00:00:18 | **Official run:** `python -m s1_twin_spread.run --rate 0.0417 --rate-date 2026-10-01` | 24 s. The numbers in `SUMMARY.md` and `metrics.csv` |
| 00:00:50 | `python -m s1_twin_spread.report` | `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`, `capacity.md` |

## The two debug runs, stated plainly

The official run had to wait for the calibration slice to close at 00:00. Before that, the code was run twice on the
partial slice to test it, and its results were seen. They are within a few dollars of the official ones (the modelled
half-spread moved for three markets). **No trading rule, threshold, variant or criterion was changed after them.**
What did change, all in reporting and plumbing:

- Trade prints are fetched 10,000 at a time, which raised the reach from about 10,500 to 20,000 prints per market
  (the data API refuses an offset above 10,000). This can only verify more entries, never fewer.
- An equity path for the print-verified entries, the edge-at-entry total and the new-market diagnostics were added.
- The pair bootstrap sorts its pairs, so its interval no longer depends on the order of the trade list.

## Data

- **Window:** 2025-10-03 23:22 to 2026-10-03 23:18; in-sample to 2026-07-22 23:18, out-of-sample after (the most
  recent 20%, 73 days).
- **Kalshi:** 1-minute candles, bid and ask closes, per pair from `max(T1 − 365 d, open)`.
- **Polymarket:** CLOB `prices-history`, `fidelity=1`, in 14-day requests.
- **Pairs used: 31 of 33.** `KXPRESNOMD-28-TW`: Polymarket's book was one-sided in every calibration snapshot.
  `KXPRESNOMR-28-COWE`: Kalshi shows a two-sided quote in 0.001% of minutes, never together with a fresh Polymarket
  point.
- **Modelled Polymarket half-spread:** 0.5¢ (the floor) for 23 of the 31 pairs used, 0.65¢ to 3.5¢ for the other 8.
- **Coverage** (minutes with both venues fresh) is in `pairs.csv`: median 44% under the registered 15-minute rule, 94%
  under the 6-hour sensitivity.
- **Trade prints:** full history reached for 22 of the 24 traded markets. Two hit the 20,000-print cap: `KXALIENS-27`
  (reach back to 2026-04-15) and `KXTRUMPOUT27-27-DJT` (2026-03-09). Entries before the reach are counted as
  unverified.
- **Rate:** 3-month Treasury constant maturity, 4.17% on 2026-10-01 (Alpha Vantage `TREASURY_YIELD`, FRED DGS3MO).
- **Kalshi fee schedule:** the PDF could not be fetched tonight (HTTP 429, twice). The formula is the published
  general taker formula as already implemented in `research/arb/arbscan/costs.py`; Kalshi's API confirms `fee_type`
  quadratic and `fee_multiplier` 1 for all 33 series.

## Sharpe above 3: the pre-registered checks

| Check | Outcome |
|---|---|
| Fills at the second observation | Enforced in code; `test_a_gap_of_one_minute_is_never_traded`, `test_entry_fills_at_the_second_observation`, `test_signal_does_not_reach_back_before_the_segment_start` |
| Quote ages at entry | Kalshi median 60 s, maximum 660 s; Polymarket median 48 s. Inside the 15-minute rule |
| Polymarket points that are the middle of an empty or wide book | **The cause.** 84 of 99 out-of-sample entries have no trade print at the modelled price; 18 fall in the first 48 hours of a Polymarket market; 17 have a Polymarket "price" between 0.45 and 0.55 with Kalshi far away |
| Fees on every leg | Yes: 218 bp of capital per entry on average |
| Empty Kalshi sides | Never used (amendment 2; `test_build_pair_drops_empty_kalshi_sides`) |
| Both clocks in UTC | Yes. Candle quotes equal the recorder's live book in 1,542 of 1,584 snapshots |
| Pair direction | All 33 pairs are `direction: same` |

Conclusion: no coding bug. The Sharpe ratio comes from a 0.5¢ spread modelled around history points that were not
tradable prices. The print-verified subset is the part that survives.

## Recorder incidents during this work

- The history pull shared Kalshi's rate limit with the recorder. Three recording cycles failed on Kalshi (23:18:49
  twins; 23:22:49 and 23:23:19 thresholds), and the threshold list could not be refreshed from 23:23:29 to 23:24:44.
- 23:23:22 to 23:23:28: the recorder was restarted to add a retry inside the cycle.
- All of this is inside the calibration slice, before the forward window. No failed cycle since 23:24:44.

## Tests

`python -m pytest s1_twin_spread/tests s3_three_way/tests -q`: 38 passed. `python -m pytest tests/test_notebook.py -q`:
4 passed.

## Still to run

- `python -m s1_twin_spread.forward --rate 0.0417` after Sun 2026-10-04 11:00 UTC (07:00 ET), then
  `python -m s1_twin_spread.report`. A labelled update with `--final` after 13:30 UTC.
