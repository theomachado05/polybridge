# PolyBridge demo script

Total: 5 minutes. Findings first (3 min), live demo (90 s), ask (30 s).

## 1. Pitch outline

### Findings (3 min)
1. Hypothesis was pre-registered before any data was looked at: one confirmatory test (H1), one out-of-sample (OOS) run, frozen rules.
2. Result: NULL on H1 and NULL on the out-of-sample check. Show the price-gap curve: the gap between event-implied and realized move does not beat the placebo band (CIs straddle zero; see `research/results/in_sample/hedge_pass_check.csv`, `pnl_ok` is False at every horizon).
3. Honest framing: a null is the finding. We did not tune until something "worked".
4. The atlas is exploratory only. It generated hypotheses, not claims. Every variant tried is counted: 96,390 variants, so any single hit is discounted accordingly (see `research/results/RUN_LOG.md`).
5. What survives: not a signal, but a hedging tool. Prediction-market prices are a live, public read on event risk; PolyBridge turns that into a human-approved, fee-gated hedge.

### Live demo (90 s)
Click path in section 2.

### Ask (30 s)
State the ask (feedback on the pre-registration design, data access, or a pilot hedge book). Close on: "no edge found" is a result we can ship honestly, and the hedge tool is useful regardless.

## 2. Live demo click path (90 s)

Servers must already be up (section 4). Open http://localhost:3000.

1. Go to `/build`. Search: "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?" (Polymarket).
2. The precomputed AI mapping appears (from `backend/app/data/ai_map.json`): SPY (down on YES, 2.0%), IWM (down on YES, 3.0%), XHB (down on YES, 3.0%).
3. Pick a stock, for example SPY.
4. Read the verdict card (the honest result: no confirmed edge; this is a hedge, not a bet).
5. Open the hedge menu and choose a hedge.
6. Click Propose, then Approve (the approval gate: nothing runs without it).
7. Click Start bridge on the live source. You land on `/bridge/<id>`: ticks, decisions, positions stream in. `/portfolio` shows the position.
8. If live is flat (it often is) or the network is down, restart the bridge on the historical replay: the real one-month price history, 15.5c to 70.5c, replayed at 3600x (one tick per second, about 12 minutes). Narrate the hedge growing as the price climbs. If live fails mid-run, the bridge falls back to replay automatically (`POLYBRIDGE_REPLAY_PATH`).

## 3. The 8-K path

1. `/build`, choose the 8-K filing route and a filing tagged as litigation (for example a material-litigation 8-K).
2. The confirmatory H1 verdict is NULL: "no edge found, try another event or stock". Point at the evidence from `research/results/in_sample/hedge_pass_check.csv` (placebo-adjusted P&L difference with CIs spanning zero).
3. Message: the product refuses to dress a null up as a trade. A hedge can still be proposed and approved, but no alpha is claimed.

## 4. Pre-flight checklist

- [ ] Backend: `cd backend && uv sync --locked --group engine` (engine group installed; `uv run python -c "import hedgecore"` works).
- [ ] Backend up: `POLYBRIDGE_REPLAY_PATH=replays/fed-hike-25bps-oct-2026-history.jsonl POLYBRIDGE_REPLAY_SPEED=3600 uv run uvicorn app.main:app --port 8000`; `curl localhost:8000/health` returns ok.
- [ ] Web up: `cd web && pnpm dev`; http://localhost:3000 loads. Ports 8000 and 3000 free (`lsof -i :8000 -i :3000`).
- [ ] Replay env vars set as above; the replay file exists (`ls backend/replays`).
- [ ] Wi-Fi-off rehearsal: turn Wi-Fi off, run the full click path on replay once. Turn it back on only if you want the live source.
- [ ] Fresh state: restart the backend before the talk (one bridge per proposal; proposals are in-memory).
- [ ] Tabs pre-opened on `/build`, `/portfolio`; browser zoom set for the room.

## 5. Q&A crib

- Why is NULL a valid result? A pre-registered test that fails to reject is information: it bounds the effect size and prevents a false claim. Reporting it is the point of pre-registration.
- No lookahead? Features use only data timestamped before the event; the engine consumes ticks in order and never sees future prices; placebo events are drawn with the same constraint.
- OOS run once after freeze? Rules and parameters were frozen, then the out-of-sample run was executed a single time. No re-runs, no tuning on it.
- Fees gate? The engine only sends an order when the expected gap per share beats fees (decision reason `below_fees` otherwise); try a tiny `gap_per_share` to show it.
- Approval gate? Proposals start pending; the bridge endpoint returns 409 unless the proposal is approved, and opportunity-family proposals never reach the hedge engine. Fills are simulated.
- What is exploratory? The atlas and the AI stock mappings. They suggest where to look and carry no confirmatory weight; 96,390 variants were counted against any hit.
