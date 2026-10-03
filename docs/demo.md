# PolyBridge demo script

Total: 5 minutes. Findings first (3 min), live demo (90 s), ask (30 s).

## 1. Pitch outline

### Findings (3 min)
1. Rules pre-registered and frozen at 2026-10-03 13:00 ET before the single out-of-sample run; in-sample runs and one disclosed starter-notebook check happened before the freeze (see research/HYPOTHESIS.md).
2. Two confirmatory tests: H1 (hedge family) and H2 (opportunity family). Both are NULL in-sample (`research/results/in_sample/hedge_verdict.txt`, `opportunity_verdict.txt`). Show the price-gap curve: the gap between event-implied and realized move does not beat the placebo band (CIs straddle zero; see `research/results/in_sample/hedge_pass_check.csv`, `pnl_ok` is False at every horizon).
   Out-of-sample: <fill in after the single post-freeze run, whatever it returns>
3. Honest framing: a null is the finding. We did not tune until something "worked".
4. The atlas is exploratory only. It generated hypotheses, not claims. Every variant tried is counted: 96,390 variants, so any single hit is discounted accordingly (see `research/results/RUN_LOG.md`).
5. What survives: not a signal, but a hedging tool. Prediction-market prices are a live, public read on event risk; PolyBridge turns that into a human-approved, fee-gated hedge.

### Live demo (90 s)
Click path in section 2.

### Ask (30 s)
State the ask (feedback on the pre-registration design, data access, or a pilot hedge book). Close on: "no edge found" is a result we can ship honestly, and the hedge tool is useful regardless.

## 2. Live demo click path (90 s)

Servers must already be up (section 4). Open http://localhost:3000 (not 127.0.0.1).

1. Go to `/build`. Search "Fed October 2026" and pick the market "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?" (Polymarket). If the network is down, the list still appears from the bundled market list, marked "offline: cached market list".
2. The precomputed AI mapping appears (from `backend/app/data/ai_map.json`, labelled as an AI estimate): SPY (down on YES, 2.0%), IWM (down on YES, 3.0%), XHB (down on YES, 3.0%).
3. Pick the mapped ticker IWM (the seeded portfolio holds 400 IWM; set Shares held to 400).
4. The verdict card, if one shows, belongs to that stock's own filings; this path makes no research claim.
5. Optionally open the hedge menu to show ranked, fee-aware protection.
6. Click Propose. This is the market-event path: the proposal reads "Product hedge — no confirmatory claim" (family hedge, protective put; no filing tags). Click Approve (the approval gate: nothing runs without it).
7. The tick source is preset to "Historical replay (real Polymarket history)". Click Start bridge. You land on `/bridge/<id>` with the Replay badge: the real one-month price history of this market, 15.5c to 70.5c, time-compressed at 36000x (about 72 seconds). Narrate the hedge growing as the price climbs; the trade log shows orders only by default, with plain-word reasons (untick to see the holds).
8. Open `/portfolio`: every seeded holding with its value, related markets and recent filings; IWM shows its remaining exposure to the Fed hike market (shares × spot × 3% × (1 − YES price), AI estimate) and its hedge status "bridging". The total exposure is labelled if it includes fuzzy-matched mappings.

## 3. The 8-K path

1. `/build`, choose the 8-K filing route and a filing tagged as litigation (for example a material-litigation 8-K).
2. The confirmatory H1 verdict is NULL: "no edge found, try another event or stock". Point at the evidence from `research/results/in_sample/hedge_pass_check.csv` (placebo-adjusted P&L difference with CIs spanning zero).
3. Message: the product refuses to dress a null up as a trade. A hedge can still be proposed and approved, but no alpha is claimed.

## 4. Pre-flight checklist

- [ ] Backend: `cd backend && uv sync --locked --group engine` (engine group installed; `uv run python -c "import hedgecore"` works).
- [ ] Backend up: `cd backend && POLYBRIDGE_REPLAY_PATH=replays/fed-hike-25bps-oct-2026-history.jsonl POLYBRIDGE_REPLAY_SPEED=36000 uv run --group engine uvicorn app.main:app --port 8000`; `curl localhost:8000/health` returns ok.
- [ ] Web up: `cd web && pnpm dev`; open http://localhost:3000 (not 127.0.0.1). Ports 8000 and 3000 free (`lsof -i :8000 -i :3000`).
- [ ] Replay env vars set as above; the replay file exists (`ls backend/replays`).
- [ ] Rehearse on Sunday morning (the filings cache is keyed by date, so a Saturday rehearsal does not warm Sunday's cache).
- [ ] Wi-Fi-off rehearsal: turn Wi-Fi off, run the full click path on replay once (market search falls back to the bundled list; options data shows "options data unavailable").
- [ ] Fresh state: restart the backend before the talk (one bridge per proposal; proposals are in-memory).
- [ ] Tabs pre-opened on `/build`, `/portfolio`; browser zoom set for the room.

## 5. Q&A crib

- Why is NULL a valid result? A pre-registered test that fails to reject is information: it bounds the effect size and prevents a false claim. Reporting it is the point of pre-registration.
- No lookahead? Features use only data timestamped before the event; the engine consumes ticks in order and never sees future prices; placebo events are drawn with the same constraint.
- OOS run once after freeze? Rules and parameters are frozen at 2026-10-03 13:00 ET; the out-of-sample window is run once after the freeze, with no re-runs and no tuning on it. Out-of-sample: <fill in after the single post-freeze run, whatever it returns>.
- Fees gate? The engine only sends an order when the expected benefit (gap per share, from spot × the mapped impact, times the probability move) beats fees; otherwise it holds with reason `below_fees`, counted in the stage pills and visible in the trade log with "Orders only" unticked.
- Approval gate? Proposals start pending; the bridge endpoint returns 409 unless the proposal is approved, and opportunity-family proposals never reach the hedge engine. Fills are simulated.
- What is exploratory? The atlas and the AI stock mappings. They suggest where to look and carry no confirmatory weight; 96,390 variants were counted against any hit.
