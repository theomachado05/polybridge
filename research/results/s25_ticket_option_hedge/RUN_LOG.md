# S25 run log

Sun 2026-10-04. Branch `r/weekend-options`. Commit hashes and times read from `git log` (New York time); pull times are UTC.

## Commits

| Time | Commit | What |
|---|---|---|
| 01:47:44 | `9519ff4` | S25 (ticket sold, option spread bought): pre-registration. METHOD.md, config.py, the pure functions, the pull and the tests, committed before any Mond |

The commit that carries this file is not listed in it; it is recorded by the next commit.

## The pull (from the pull's own log)

- `2026-10-04T05:47:49Z recorder `fetch failed` lines before the pull: 51`
- `2026-10-04T05:47:49Z pull started: 277 markets, 62 events, 14 tickers`
- `2026-10-04T05:47:56Z error (I:SPX raw): /v2/aggs/ticker/I:SPX/range/1/day/2025-10-27/2026-10-02 HTTP 403 {"status":"NOT_AUTHORIZED","request_id":"8e1b6264e3195b422326ee950237dba0","message":"You are not entitled to this data. Please upgrade`
- `2026-10-04T05:47:57Z error (I:SPX adj): /v2/aggs/ticker/I:SPX/range/1/day/2025-10-27/2026-10-02 HTTP 403 {"status":"NOT_AUTHORIZED","request_id":"78f3ed2929ecc95ff252fb814d14ef93","message":"You are not entitled to this data. Please upgrade`
- `2026-10-04T05:48:10Z closes and splits done: 41 requests, 2 errors`
- `2026-10-04T05:52:40Z leg quotes done: 554 served, 0 failed, 574 requests, 2 errors, stopped early: False`
- `2026-10-04T05:57:09Z pull finished: 1107 requests in 559s, 2 errors, final rate 2.0 rps, leg volumes 554, stopped early: False, recorder `fetch failed` lines now 51 (before: 51)`
- `2026-10-04T05:57:09Z error: /v2/aggs/ticker/I:SPX/range/1/day/2025-10-27/2026-10-02 HTTP 403 {"status":"NOT_AUTHORIZED","request_id":"78f3ed2929ecc95ff252fb814d14ef93","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}`
- `2026-10-04T05:57:09Z error: /v2/aggs/ticker/I:SPX/range/1/day/2025-10-27/2026-10-02 HTTP 403 {"status":"NOT_AUTHORIZED","request_id":"8e1b6264e3195b422326ee950237dba0","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}`

## Data sources

- **Polymarket side: nothing pulled.** Traded bids, held-to-result P&L, results, sizes and segments are S18's `prints_markets.csv`; entry and result times are S18's `entries.csv`. No call to Polymarket or Kalshi.
- **Option contracts, strikes, expiries and the Friday 15:55 quotes:** S21's `anchors.csv` (read only; S21's cache was not touched).
- **Monday 09:35 quotes:** Massive `/v3/quotes/<option>` (`timestamp.lte` = 09:35:00 New York on the hedge day, newest first, limit 1).
- **Closes:** Massive `/v2/aggs/ticker/<ticker>/range/1/day/2025-10-27/2026-10-02`, `adjusted=false` and `adjusted=true`. **Splits:** `/v3/reference/splits`.
- **Option volume on the hedge day (capacity only):** Massive daily bar of each leg.
- Cache: `research/s25_ticket_option_hedge/.cache/cache.jsonl`, 1105 lines. Not committed.
- **The session clock:** SPY five-minute bars in `s5_big_moves/.cache/eq_SPY.npz`.

## The recorder

`fetch failed` lines in `research/forward/recorder.log` (read only): see the first and last lines of the pull's log above; at the time of the run: 51. The recorder was not touched.

## Markets dropped

| Reason | Markets |
|---|---|
| the underlying's closes or splits are not served | 20 |
| a split between the first weekend and the expiry | 4 |
| no usable quote at Monday 09:35 (from before the open, or no offer) | 1 |

## What went wrong, and what could not be verified

1. **The index close is not served.** `/v2/aggs/ticker/I:SPX/range/1/day/...` answered `HTTP 403 NOT_AUTHORIZED: You are not entitled to this data` (both requests, see the pull's log). By METHOD.md section 5 the 20 index (SPX) markets are dropped, 6 of them in the rule subset. Their Monday option quotes were pulled and are not used. No other source was substituted.
2. **A listed split on Opendoor.** Massive lists a 30-for-31 split of OPEN executed 2025-11-18 (by its ratio, an adjustment for a distribution; what it was is not verified here). 4 OPEN markets sold on the weekend of 2025-10-31 with a 2025-11-28 expiry are dropped by rule 1, 2 in the rule subset. Netflix's 10-for-1 split (2025-11-17) dropped nothing here: the 6 Netflix markets S21 kept were all sold after it.
3. **One market without a usable Monday quote** (1): a HOOD call whose last quote before Monday 09:35 was from before the open. Dropped, as registered. No modelled price was used anywhere.
4. **Stale opening quotes were bought at the offer.** 17 hedged markets (6 in the rule subset) had a leg quote more than 60 seconds old at 09:35, some of them placeholders such as 0 bid, 15.00 offered. The registered rule accepts them, so the primary includes them; 3 hedges cost more than the spread can pay and 15 sold a short leg for a zero bid. The after-the-run look L1 shows the primary without them. This was not foreseen in METHOD.md.
5. **The unhedged benchmark moved with the drops.** S21's B0 book (60 markets) had no losing month. On the 52 markets that could be hedged the unhedged book has one (June 2026), because three winning S&P index tickets of that month were dropped. METHOD.md section 8 said the hedged book could at best tie the unhedged worst month; on these markets that no longer applied, and the hedged worst month is worse anyway.
6. **The first run was on a cache without option volumes.** `run.py` was first run at 01:52 New York, after every Monday quote and close was in the cache and while the capacity-only pull of option volumes was still running. Volumes enter no P&L. Everything was rerun after the pull finished.
7. **The book holds fractions of an option contract.** One listed spread is 100 shares; the book holds up to 100 tickets per market. The numbers are an accounting per ticket, not an order that could be sent as is (see capacity.md).
8. **Not verified:** Massive's NBBO and daily closes against a second source (the closes are tied to Polymarket's results only by the fact that no market finished beyond its level without a recorded touch); early exercise of the short leg and dividends (the spread is read as European, as S21 read it); the $0.65 commission (an assumption); the taker side of S18's prints; whether a hedge could have been bought in the size of the weekend's ticket sales.
9. **Clerical:** METHOD.md's header says "about 02:00"; the pre-registration commit was made at 01:47:44 (amendment 1).

