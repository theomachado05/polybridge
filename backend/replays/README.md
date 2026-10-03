# Recorded sessions (Wi-Fi-free demos)

## fed-hike-25bps-oct-2026.jsonl

- Market: "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?" (Polymarket, resolved via gamma search)
- YES token id: `55159722761418013044126414276680602270318000841690689684819994448621694923050`
- Recorded: 2026-10-03 05:25:12Z to 05:45:11Z UTC (20 minutes), CLOB midpoint polled every 1 s
- Rows: 1200 ticks, 0 failed polls, one `{"ts_ns", "p"}` JSON object per line (51 KB)
- Note: the market was quiet during the window (midpoint constant at 0.175), so hedgecore sizes one initial hedge and then holds.

## fed-hike-25bps-oct-2026-history.jsonl (default demo replay)

Historical replay (real Polymarket price history, time-compressed at replay). Same market and YES token as above.
721 hourly points (about 30 days, 2026-09-02 to 2026-10-03) from `clob.polymarket.com/prices-history`
(`interval=1w&fidelity=1` is rejected by the API, so the script falls back to `interval=1m&fidelity=60`).
p ranges 0.155 to 0.705 (the largest range among the Fed October 2026, Iran, and Russia/EU candidates checked;
tied with the "no change" market at 0.55). Regenerate:

    cd backend && uv run python scripts/history_to_replay.py --token-id <YES token id> --out replays/<slug>-history.jsonl

Demo setting: replay at 36000x (ten ticks per second, about 72 seconds for the month), via `POLYBRIDGE_REPLAY_SPEED=36000`.
This is safe because staleness is judged on the wall clock (ticks are stamped at delivery), not on the recorded 1 h gaps
(tested in `tests/test_bridges.py::test_high_speed_replay_of_hourly_history_is_never_stale`). Replayed ticks are stamped
with the current time, preserving spacing divided by the speed.

## Record another

    cd backend && uv run python scripts/record_ticks.py --token-id <YES token id> --out replays/<slug>.jsonl --minutes 20

Failed polls are skipped. Find a token id via `GET /markets/search?q=...` (`token_id` field).

## Replay

    POLYBRIDGE_REPLAY_PATH=replays/fed-hike-25bps-oct-2026-history.jsonl POLYBRIDGE_REPLAY_SPEED=36000 uv run --group engine uvicorn app.main:app
    # approve a hedge proposal, then:
    curl -X POST localhost:8000/bridges -H 'content-type: application/json' \
      -d '{"proposal_id":"<id>","source":"replay","market":{"source":"polymarket","id":"2589813"},"gap_per_share":1.0}'
    curl -N localhost:8000/bridges/<bridge_id>/stream

Each recording has a sidecar `<file>.meta.json` (`{"source", "id", "token_id"}`) naming the market it records; both
Fed files here record `polymarket:2589813`. A replay bridge for another market answers 422 instead of replaying this
history under that market's title. A file with no sidecar (market unknown) is replayed only when the request names it
(`"replay_file": "<file name>"`, or a market id equal to the file's stem). Add a sidecar next to any new recording.

Without `POLYBRIDGE_REPLAY_PATH`, `source: "replay"` looks for `replays/<market.id>.jsonl`. The same variable is the automatic
fallback when a live bridge loses its network connection. With the 1 s recording, leave `POLYBRIDGE_REPLAY_SPEED` unset (real time).
