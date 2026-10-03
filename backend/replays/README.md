# Recorded sessions (Wi-Fi-free demos)

## fed-hike-25bps-oct-2026.jsonl

- Market: "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?" (Polymarket, resolved via gamma search)
- YES token id: `55159722761418013044126414276680602270318000841690689684819994448621694923050`
- Recorded: 2026-10-03 05:25:12Z to 05:45:11Z UTC (20 minutes), CLOB midpoint polled every 1 s
- Rows: 1200 ticks, 0 failed polls, one `{"ts_ns", "p"}` JSON object per line (51 KB)
- Note: the market was quiet during the window (midpoint constant at 0.175), so hedgecore sizes one initial hedge and then holds.

## Record another

    cd backend && uv run python scripts/record_ticks.py --token-id <YES token id> --out replays/<slug>.jsonl --minutes 20

Failed polls are skipped. Find a token id via `GET /markets/search?q=...` (`token_id` field).

## Replay

    POLYBRIDGE_REPLAY_PATH=replays/fed-hike-25bps-oct-2026.jsonl uv run --group engine uvicorn app.main:app
    # approve a hedge proposal, then:
    curl -X POST localhost:8000/bridges -H 'content-type: application/json' \
      -d '{"proposal_id":"<id>","source":"replay","market":{"source":"polymarket","id":"fed"},"gap_per_share":1.0}'
    curl -N localhost:8000/bridges/<bridge_id>/stream

Without `POLYBRIDGE_REPLAY_PATH`, `source: "replay"` looks for `replays/<market.id>.jsonl`. The same variable is the automatic
fallback when a live bridge loses its network connection. The replay keeps the recorded 1 s spacing (real time).
