# Forward recording: live order books over the weekend

Started Sat 2026-10-03 19:09:48 ET (23:09:48 UTC). Ends Sun 2026-10-04 09:30 ET (13:30 UTC). This is unseen data: no
strategy rule was written with it in view. Each strategy's METHOD.md is committed before its forward window is analysed.

## What is recorded

| universe | markets | cadence | folder |
|---|---|---|---|
| `twins` | the 33 verified Polymarket↔Kalshi pairs of `backend/app/data/kalshi_twins.json` (33 YES tokens, 33 Kalshi tickers) | every 15 s | `raw/twins/` |
| `thresholds` | open "close above $K" markets with listed options: Polymarket equity-tag events ending within 21 days, and Kalshi 16:00 ET closes of the S&P 500 and Nasdaq-100 (200 + 460 at the start; the list is refreshed every 30 minutes) | every 30 s | `raw/thresholds/` |

Sources, both public and keyless:
- Polymarket: `POST https://clob.polymarket.com/books` (one call for the whole batch).
- Kalshi: `GET https://api.elections.kalshi.com/trade-api/v2/markets/orderbooks` (one call per 50 tickers).

## Files

- `raw/<universe>/<YYYYMMDD>T<HH>.jsonl.gz`: one file per UTC hour. Each cycle is appended as its own gzip member, so a
  crash loses at most the cycle in flight. `gzip.open(path, "rt")` reads the whole file.
- `raw/<universe>/universe_<stamp>.json`: the market list in force from that time (question, twin, strike, fees).
- `recorder.log`, `heartbeat_<universe>.json`, `recorder.pid`: run state. Not committed.

## Row format (one JSON object per line)

| key | meaning |
|---|---|
| `t0`, `t` | local clock, epoch seconds UTC, when the request was sent and when the response arrived |
| `v` | venue: `pm` (Polymarket) or `k` (Kalshi) |
| `id` | Polymarket YES token id, or Kalshi ticker |
| `b` | YES bids, best first, up to 5 levels of `[price, size]` |
| `a` | YES asks, best first, up to 5 levels of `[price, size]` |
| `vts` | Polymarket only: the book's own timestamp, in ms |
| `ltp`, `h` | Polymarket only: last trade price and book hash |
| `err` | present instead of a book when a fetch failed |

Prices are dollars per $1 payoff. Sizes are shares (Polymarket) or contracts (Kalshi); both pay $1.

Kalshi publishes bids only: YES bids and NO bids. A NO bid at price `q` is a YES ask at `1 - q` for the same size, and
that is how `a` is built. Buying NO on either venue costs `1 - (YES bid)`.

## Run it

```
nohup research/forward/run_recorder.sh >/dev/null 2>&1 &
```

The wrapper restarts the recorder if it dies and holds a `caffeinate` so the Mac does not idle-sleep. Closing the lid
on battery still stops it.

## What the recording holds (checked Sun 2026-10-04 11:05 UTC)

- Forward window, 2026-10-04 00:00 to 11:00 UTC: 2,681 cycles with data for the twins and 2,669 for the thresholds,
  no failed fetch inside the window except during the gap below.
- **One gap: 02:56:58 to 03:13:52 UTC (16.9 minutes; thresholds 02:56:46 to 03:13:52).** Every connection from the
  machine failed (name resolution and timeouts, to Polymarket and to Kalshi alike). It recovered on its own.
- Size on disk at 11:01 UTC: 19 MB (twins), 39 MB (thresholds). Not committed (58 MB together). The forward results
  under `research/results/s1_twin_spread`, `s3_three_way` and `s6_monday_fade` are built from it.
