# S19 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 night in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 03:59 to 04:01 | Catalogue searches and a probe of the data API | 1,000 crypto price events found. The probe asked one Bitcoin market for prints above a cash size, to learn that the API can filter: row counts and dates were read, no price was set against a result |
| 04:01:48 | `python -m s19_crypto_price_markets.universe` (catalogue only) | 653 daily events left out; 336 weekly or longer events with 4,039 eligible markets; 1,265 drawn at random, four per event, seed 0 |
| 04:02:11 | `METHOD.md`, `config.py`, `universe.py`, `universe.json` committed (`f5fe8e5`) | Before any print of these markets was pulled |
| 04:03:14 | Runner and tests committed (`be1e0f2`) | Before any print was pulled |
| 04:03 to 04:15 | `python -m s19_crypto_price_markets.run --pull` | 720 s at 2 requests a second, with a guard on the live recorder (no failed fetch). 1,265 markets, every one served in full; 353,401 prints of $50 or more seen, 31,189 inside a first-48-hours window kept |
| 04:15 | `python -m s19_crypto_price_markets.run` | The sellers' and buyers' tests and the two books. The numbers in `SUMMARY.md` |
| 04:15 | `python -m s19_crypto_price_markets.report` | `SUMMARY.md`, charts, `capacity.md` |

The run was made once. No rule was changed after it.

## Data

- **Sample:** 1,265 markets in 336 events: 354 Bitcoin, 351 Ethereum, 307 Solana, 253 XRP; 695 weekly, 402 monthly or
  longer, 168 other date ranges; listed from 2024-10-01 to 2026-10-01. Out-of-sample is the most recent 68 events,
  listed from 2026-06-15.
- **Prints:** Polymarket data API with a cash floor of $50. No market was left out: with the floor, the API reached
  the listing time of every one (2 needed a second page).
- 101 markets have no print of $50 or more in their first 48 hours; 1,132 have a taker sale of YES and 880 a taker
  purchase.

## Limits

- Prints under $50 are not seen.
- Four markets per event, not all of them.
- Personal fields the API attaches to a print (names, wallet addresses) are not kept: only time, price, side, token
  and size are written to disk.
