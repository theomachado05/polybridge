# Fresh demo recordings (2026-10-03)

Recorded on Saturday 2026-10-03 from live Polymarket, for demos that work with Wi-Fi off. These are new files; the
original Fed recordings stay in `backend/replays/`. Every row is `{"ts_ns", "p", ...}`; a replay keeps whatever
MarketTick fields a row carries and fills the rest with NaN (never invented).

Markets were chosen by 24 h volume (`backend/scripts/record_book.py --list`) among the ones the AI mapping already covers.

| File | Market (Polymarket id) | What it is | Rows |
|---|---|---|---|
| `indiana-datacenter-2027-history.jsonl` | Will Indiana enact a data center moratorium by December 31, 2027? (5126779, about 1.9 M USD / 24 h) | Hourly price history, 2026-09-29 to 2026-10-03; p 0.145 to 0.535; `under_px` = VRT hourly close | 89 |
| `iran-ceasefire-oct-2026-history.jsonl` | US x Iran ceasefire continues through October 31? (4641065, about 120 K USD / 24 h) | Hourly price history, about 16 days; p 0.365 to 0.705; `under_px` = XLE hourly close | 377 |
| `indiana-datacenter-2027-book.jsonl` | same Indiana market | Live order book, top 5 levels per side, polled about every 1 s for 10 minutes; `under_px` = VRT last trade | 598 |
| `iran-ceasefire-oct-2026-book.jsonl` | same Iran ceasefire market | Live order book, top 5 levels per side, 10 minutes; `under_px` = XLE last trade | 598 |

## What is real, and what is not

- **History files** are price history only (Polymarket CLOB `prices-history`, hourly): a mid-price series. The spread and the
  depth at those times are unknown and are not in the file. `under_px` is the Massive hourly close of the last bar that had
  already ended at each row's time (no look-ahead).
- **Book files** carry real recorded depth (`bid_px_0..4`, `bid_qty_0..4`, `ask_px_0..4`, `ask_qty_0..4`, `yes_bid`, `yes_ask`).
  Both markets were quiet during the 10 minutes: the mid did not move (0.145 and 0.605) and the top-of-book spread is 1 cent. They show
  depth, not a price move; use the history files for a replay where the hedge grows.
- **`under_px` in the book files is the Massive last trade, refreshed every 15 s.** The recording was made on a Saturday with
  US equities closed, so it is Friday's last trade and is constant (VRT 252.00, XLE 62.82). It is not a live price.
- Replayed orders are still filled at today's market by the broker (labelled in the trade log), not at the recorded time or price.

## Play one

The replay file is global to the backend, so pick the matching market in Build (VRT for Indiana, XLE for the Iran ceasefire).

```bash
REPLAY=replays/iran-ceasefire-oct-2026-history.jsonl make dev                 # 377 hourly points, about 38 s at 36000x
REPLAY=replays/iran-ceasefire-oct-2026-book.jsonl SPEED=60 make dev           # 598 one-second rows in about 10 s
```

(`REPLAY` is relative to the repo root.)

Check one end to end (search, map, fit, propose, approve, bridge, SSE, account):

```bash
python3 scripts/e2e_demo.py --no-screens --query "Iran ceasefire October 31" --market-id 4641065 --ticker XLE \
  --replay replays/iran-ceasefire-oct-2026-history.jsonl
python3 scripts/e2e_demo.py --no-screens --query "Indiana data center moratorium" --market-id 5126779 --ticker VRT \
  --replay replays/indiana-datacenter-2027-history.jsonl
```

## Record more

```bash
cd backend
uv run --env-file ../.env python scripts/record_book.py --list 15                       # top markets by 24 h volume, with YES token ids
uv run --env-file ../.env python scripts/record_book.py --market slug=<gamma id or YES token> --equity <TICKER> \
    --outdir ../replays --minutes 10 --interval 1                                        # live book depth (+ equity last trade)
uv run --env-file ../.env python scripts/history_with_equity.py --market slug=<id> --equity <TICKER> \
    --out ../replays/slug-history.jsonl                                                  # a month of price history + equity bars
```

`--market` and `--equity` repeat and match by position; several markets record concurrently. Without `MASSIVE_API_KEY` the
`under_px` field is simply left out.
