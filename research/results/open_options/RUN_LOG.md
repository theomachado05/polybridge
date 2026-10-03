# Run log: R3, do options catch up at the Monday open?

- Method: `research/open_options/METHOD.md`, committed (297727a) before any data was fetched; amendment 1 (4877aa2, drop Kalshi) committed after only market listings had been downloaded, before any price or quote.
- Final run started 2026-10-03T17:08:48 UTC; wall time 663 s. Request failures after retries: 0.
- Commands (from `research/`):
  ```
  uv run --no-project --env-file ../.env --with pandas --with numpy --with requests --with matplotlib --with pyyaml python -m open_options.run --skip-kalshi
  uv run --no-project --with pandas --with numpy --with matplotlib python -m open_options.report
  uv run --no-project --with pandas --with numpy --with requests --with pytest --with pyyaml python -m pytest open_options/tests -q
  ```
- HTTP requests by host (cache misses on the final run): {"gamma-api.polymarket.com": 118, "clob.polymarket.com": 6326, "data-api.polymarket.com": 875}; Massive: {"api.massive.com": 11423}. On-disk cache `research/open_options/.cache` (about 415 MB, not committed).
- The API key is read from `.env` (`MASSIVE_API_KEY`) and never printed or written anywhere.
- No 8-K disclosure data and no EDGAR request. Option quotes are on threshold-market underlyings only.

## Passes (disclosed)

1. **Aborted pass 1 (Kalshi listing).** Stopped while it was still downloading Kalshi market listings (about 2 MB per 1,000 markets). The listing pages showed every Kalshi 16:00 event created the day before settlement, so none can span a closure (eligibility rule 1). Amendment 1 recorded this before any price or quote was fetched; the Kalshi listing pages were deleted from the cache.
2. **Pass 2, incomplete universe (discarded before analysis).** Ran end to end (627 events) but the Polymarket gamma event listing returned HTTP 422 at a deep offset, so the listing was truncated at 2,177 events (3,886 in-scope markets). Only the run counters and the failure list were looked at (no slope, gap or verdict was computed). Fix: the listing now pages through 14-day end-date chunks. The data-api trades stage also hit 36 HTTP 429s with 8 workers; it now uses 2.
3. **Pass 3, final.** 7,772 events, 15,112 in-scope markets, 0 failures. `report.py` was run once on it.

## Counters (final run)
```
{
 "closures": 55,
 "pm_events": 7772,
 "pm_markets_seen": 37218,
 "pm_excluded_out_of_scope_type": 16136,
 "pm_excluded_not_above_threshold": 5970,
 "pm_in_scope": 15112,
 "pair_listed_after_close": 8763,
 "pair_resolves_before_reopen_close": 688,
 "pairs_life_ok": 7715,
 "pair_no_clean_expiry": 2694,
 "pairs_eligible": 5021,
 "status_f1_pm_close_extreme": 1836,
 "status_pass_f1_f3": 2091,
 "status_f3_move_below_3pt": 907,
 "status_f2_placeholder_050": 141,
 "status_f1_no_pm_price": 46,
 "status_f4_noarb_violation": 91,
 "status_event": 1535,
 "status_f4_opt_close_extreme": 183,
 "status_f4_no_option_spread": 282
}
```

## Tests
Synthetic, no network: `research/open_options/tests/test_oo_measure.py` (9 tests: closure calendar incl. midweek holidays and early closes, eligibility, PM as-of lookup and filters, catch-up metrics on Black-Scholes chains with full and zero catch-up, cost side, the 09:30 quote floor, fixed-pair pricing, trade-print states, cluster bootstrap slope recovery). Run together with `arb/tests`: 34 passed.
