# Run log: options-arbitrage scan
- Run started (UTC): 2026-10-03T09:11:43.139558+00:00; scan wall time 52 s on the second pass (first pass 674 s, mostly uncached; both passes use the on-disk cache in `research/arb/.cache`, not committed).
- Window of resolved markets: 2026-08-15 to 2026-10-12. Rows written: 6921.
- Commands (from `research/arb`):
  ```
  uv run --no-project --env-file ../../.env --with pandas --with numpy --with requests --with matplotlib python -m arbscan.run --workers 8
  uv run --no-project --with pandas --with numpy --with matplotlib python -m arbscan.report
  uv run --no-project --with pandas --with numpy --with requests --with matplotlib --with pytest pytest tests -q
  ```
  Re-run the live part on a trading day (US options open) to test executability: the same `arbscan.run` command, which re-reads the live books.
- The API key is read from the environment or `.env` (`MASSIVE_API_KEY`); it is never printed or written to any output. A missing key makes the runner exit with a message and no output.
- HTTP requests by host (cache misses only): {"gamma-api.polymarket.com": 1, "api.elections.kalshi.com": 130, "clob.polymarket.com": 200}; Massive: {"api.massive.com": 1097}.
- Request failures after retries: 0.
- First pass (uncached) request totals: Massive 16,572; Polymarket CLOB 3,136; Kalshi 1,173; gamma 15. Failures after retries: 2.
- The first pass logged 2 Kalshi candlestick requests that stayed at HTTP 429 after retries (both rows counted as `no_pm_price`); the second pass fetched them. Rows with errors never abort the scan; they are counted in `row_errors` (0).
- First pass, then amendment 3: the pre-registered scoring produced 247 resolved Polymarket `gap_robust` rows and was then tightened with trade-print verification; the second pass scored the same markets again with the verification stage (the Massive and gamma data were served from the cache, so the two passes share one set of quotes; live books were re-read, so live rows differ slightly). After the review that found the snapshot-timezone bug (the verification window was 4 hours early), the run and the verification were repeated: the candidate count went from 247 to 224 because the live books were re-read and the assumed half-spread moved from 0.045 to 0.050.
- Out-of-scope data: no 8-K disclosure data and no EDGAR request was made. Live raw books are saved in `raw_live/` (JSON).

## Counters
```
{
 "pm_events": 1457,
 "pm_markets_seen": 9814,
 "pm_excluded_out_of_scope_type": 5612,
 "pm_excluded_not_above_threshold": 1066,
 "pm_in_scope": 3136,
 "kalshi_KXINXU_settled_markets": 14611,
 "kalshi_excluded_not_1600_close": 97071,
 "kalshi_KXINXU_open_markets": 420,
 "kalshi_KXNASDAQ100U_settled_markets": 95460,
 "kalshi_KXNASDAQ100U_open_markets": 2800,
 "kalshi_INXU_settled_markets": 0,
 "kalshi_INXU_open_markets": 0,
 "kalshi_NASDAQ100U_settled_markets": 0,
 "kalshi_NASDAQ100U_open_markets": 0,
 "kalshi_KXINXAB_settled_markets": 0,
 "kalshi_KXINXAB_open_markets": 0,
 "kalshi_INXAB_settled_markets": 0,
 "kalshi_INXAB_open_markets": 0,
 "kalshi_hist_selected": 544,
 "kalshi_live_candidates": 460,
 "pm_live_markets": 200,
 "pm_live_no_two_sided_book": 44,
 "kalshi_live_no_two_sided_book": 111,
 "pm_resolved_or_ended": 2936,
 "kalshi_no_bid_ask_candle": 16,
 "verify_candidates": 224,
 "verify_markets": 218,
 "verified_poly": 5
}
```
- Assumed Polymarket half-spread for resolved rows: 0.0500 (median over 154 live two-sided books).

## Row statuses
```
venue       live   status     
kalshi      False  no_pm_price      16
                   pm_extreme       28
                   scored          500
            True   pm_extreme       44
                   scored          305
polymarket  False  no_chain        400
                   pm_extreme     1822
                   scored         3650
            True   no_chain          2
                   pm_extreme        2
                   scored          152
```
