# Recorded sessions (Wi-Fi-free demos)

## Demo recordings at a glance

| File | Market (Polymarket id) -> ticker | Rows, span | p range | Fit on this replay (engine, 1,000 shares) | Replay speed |
|---|---|---|---|---|---|
| `another-fed-hike-2026-history.jsonl` (**default demo**) | Another Fed rate hike in 2026? (4620900) -> TLT, down on YES | 401 hourly, 2026-09-16 19:00Z to 2026-10-03 11:33Z | 0.705 to 0.92 | equity_delta_bridge #75, score_vs_static +0.257 (17 orders in the engine replay) | 21600x, about 67 s |
| `russia-eu-military-2026-history.jsonl` | Russia military action against an EU country by December 31, 2026? (4713962) -> ITA, up on YES | 347 hourly, 2026-09-19 01:00Z to 2026-10-03 11:33Z | 0.065 to 0.285 (opening print 0.485) | energy_geo_hedge #54, score_vs_static +0.508 (136 orders in the engine replay) | 18000x, about 69 s |
| `fed-hike-25bps-oct-2026-history.jsonl` | Will the Fed increase interest rates by 25 bps after the October 2026 meeting? (2589813) -> IWM | 721 hourly, 2026-09-02 to 2026-10-03 | 0.155 to 0.705 | IWM: equity_delta_bridge #15, score_vs_static -0.011 (no better than a static hedge; fits.json scores SPY at -0.004) | 36000x, about 72 s |
| `fed-hike-25bps-oct-2026.jsonl` | same Fed October market | 1200 one-second polls, 20 min | constant 0.175 | (quiet: one initial hedge) | real time |

The two new files (recorded 2026-10-03 with `scripts/history_with_equity.py`) carry `{"ts_ns", "p", "under_px"}` per
row: `p` is the CLOB `prices-history` mid (hourly, `interval=1m&fidelity=60`; spread and depth unknown, never
invented) and `under_px` is the Massive hourly close of the last bar that had already ended at that time (no
look-ahead). Their YES token ids are in the `.meta.json` sidecars; `app/data/replay_index.json` points the fit's
offline fallback at them, and `app/data/equity_bars/TLT.json` / `ITA.json` hold the same bars for an offline fit.
"Fit on this replay" is `POST /pipeline/fit` with no network (ticks from the recording): the same pick and score as
`app/data/fits.json`. It is in-sample (tuned and scored on this history, the best of many presets), and these two
markets were chosen for the demo because they score near the top of the 122 scored markets (most add little: median
+0.0053, 36 at or below 0; see `docs/demo.md` section 5). A bridge on the replay placed fewer orders than the engine replay
counts (4 for TLT, 31 for ITA with no coverage cap in our 2026-10-03 runs; 3 and 17 at a 50% cap). The bridge fills
through the broker (today's Massive quote) while the engine replay uses its own fill model; the gap was not
investigated further, so read the order count off the Bridge screen rather than from this table.

    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py \
        --market another-fed-hike-2026=4620900 --equity TLT --out replays/another-fed-hike-2026-history.jsonl
    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py \
        --market russia-eu-military-2026=4713962 --equity ITA --out replays/russia-eu-military-2026-history.jsonl
    cd backend && uv run --env-file ../.env python scripts/record_equity_bars.py ITA --replay russia-eu-military-2026-history.jsonl

## fed-hike-25bps-oct-2026.jsonl

- Market: "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?" (Polymarket, resolved via gamma search)
- YES token id: `55159722761418013044126414276680602270318000841690689684819994448621694923050`
- Recorded: 2026-10-03 05:25:12Z to 05:45:11Z UTC (20 minutes), CLOB midpoint polled every 1 s
- Rows: 1200 ticks, 0 failed polls, one `{"ts_ns", "p"}` JSON object per line (51 KB)
- Note: the market was quiet during the window (midpoint constant at 0.175), so hedgecore sizes one initial hedge and then holds.

## fed-hike-25bps-oct-2026-history.jsonl (the previous default; now an alternative)

Historical replay (real Polymarket price history, time-compressed at replay). Same market and YES token as above.
721 hourly points (about 30 days, 2026-09-02 to 2026-10-03) from `clob.polymarket.com/prices-history`
(`interval=1w&fidelity=1` is rejected by the API, so the script falls back to `interval=1m&fidelity=60`).
p ranges 0.155 to 0.705 (the largest range among the Fed October 2026, Iran, and Russia/EU candidates checked;
tied with the "no change" market at 0.55). Regenerate:

    cd backend && uv run python scripts/history_to_replay.py --token-id <YES token id> --out replays/<slug>-history.jsonl

Setting: replay at 36000x (ten ticks per second, about 72 seconds for the month), via `POLYBRIDGE_REPLAY_SPEED=36000`.
(The default demo, `another-fed-hike-2026-history.jsonl`, plays at 21600x: six hourly points per second.)
This is safe because staleness is judged on the wall clock (ticks are stamped at delivery), not on the recorded 1 h gaps
(tested in `tests/test_bridges.py::test_high_speed_replay_of_hourly_history_is_never_stale`). Replayed ticks are stamped
with the current time, preserving spacing divided by the speed.

## Record another

    cd backend && uv run python scripts/record_ticks.py --token-id <YES token id> --out replays/<slug>.jsonl --minutes 20

Failed polls are skipped. Find a token id via `GET /markets/search?q=...` (`token_id` field).

## Replay

    POLYBRIDGE_REPLAY_PATH=replays/another-fed-hike-2026-history.jsonl POLYBRIDGE_REPLAY_SPEED=21600 uv run --group engine uvicorn app.main:app
    # approve a hedge proposal, then:
    curl -X POST localhost:8000/bridges -H 'content-type: application/json' \
      -d '{"proposal_id":"<id>","source":"replay","market":{"source":"polymarket","id":"4620900"},"gap_per_share":1.0}'
    curl -N localhost:8000/bridges/<bridge_id>/stream

Each recording has a sidecar `<file>.meta.json` (`{"source", "id", "token_id"}`) naming the market it records: both
Fed October files record `polymarket:2589813`, `another-fed-hike-2026-history.jsonl` records `polymarket:4620900` and
`russia-eu-military-2026-history.jsonl` records `polymarket:4713962`. A replay bridge for another market answers 422 instead of replaying this
history under that market's title. A file with no sidecar (market unknown) is replayed only when the request names it
(`"replay_file": "<file name>"`, or a market id equal to the file's stem). Add a sidecar next to any new recording.

Without `POLYBRIDGE_REPLAY_PATH`, `source: "replay"` looks for `replays/<market.id>.jsonl`. The same variable is the automatic
fallback when a live bridge loses its network connection. With the 1 s recording, leave `POLYBRIDGE_REPLAY_SPEED` unset (real time).
