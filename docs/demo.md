# PolyBridge demo script (v4)

Total: 5 minutes. Findings first (3 min), live demo (90 s), ask (30 s). The demo shows one thing end to end: a
prediction-market event becomes an approved, AI-fitted, compiled hedge that trades on a simulated account.

## 1. Pitch outline

### Findings (3 min)

Say what the evidence supports and no more. Full numbers are in the result files named here.

1. **Pre-registered 8-K study (the confirmatory test).** Two hypotheses, rules frozen at 2026-10-03 13:00 ET before a single out-of-sample run (`research/HYPOTHESIS.md`). In-sample both are NULL (`research/results/in_sample/hedge_verdict.txt`, `opportunity_verdict.txt`). Out-of-sample: <fill in after the single post-freeze run, whatever it returns>. A null is a result; we did not tune until something worked.
2. **Lead-lag in market hours: mixed to negative.** 28 usable stress events (`research/results/leadlag/SUMMARY.md`). Where both series moved: prediction market first in 9, equity first in 9, simultaneous in 2; sign test p = 1.0. The pooled test points the other way (equity to prediction market is significant, the reverse is not). So we do not claim the markets move first.
3. **Closed-market study: mixed** (`research/results/leadlag_closed/SUMMARY.md`). Over nights and weekends the prediction-market move and the SPY opening gap are positively related, but the same relation shows in closures with no news, and news closures show no extra response. Co-movement, not a proven lead.
4. **Options-arbitrage scan: 5 resolved gaps, 0 executable** (`research/results/arb/SUMMARY.md`). Descriptive, nothing traded; each of the 5 rests on a single small print (5 to 100 shares), too small to hedge cleanly with one contract.
5. **So what the product is:** not an alpha signal. A prediction-market price is a live, public read on event risk. PolyBridge turns it into a hedge you approve, sized to your position, with every decision explained and every limit enforced (coverage cap, fee gate).

### Live demo (90 s)

Click path in section 2.

### Ask (30 s)

Feedback on the pre-registration design, data access, or a pilot hedge book. Close on: "no edge found" is a result we can ship honestly, and the hedge tool is useful regardless.

## 2. Live demo: 90-second click path

Servers up (section 4). Open http://localhost:3000 (not 127.0.0.1). The default replay is a month of real Polymarket history for the Fed October 2026 hike market, played at 36000x (about 72 seconds). Everything below was walked through by `make e2e` (the screenshots are in `web/e2e/screens/`).

| Time | Screen | Click | Say |
|---|---|---|---|
| 0:00 | **Landing** | "Build a bridge" | "You hold a stock. A prediction market is putting a live probability on an event that moves it. PolyBridge reads that probability and hedges the stock, only after you approve." |
| 0:05 | **Build chat** | Type `fed october`, pick "the Fed increase interest rates by 25 bps after the October 2026 meeting" | "This is the live Polymarket market, 18 cents YES, about 450 thousand dollars traded today. The search hits Polymarket and Kalshi; with no network it falls back to a bundled list and says so." |
| 0:15 | Build chat | Pick **IWM** (400 shares held) | "Which stock does it move? This mapping is an AI estimate, labelled as one: a hike hits small caps, about 3 percent. It is an estimate, not a measurement." |
| 0:22 | Build chat | Pick "a dynamic short hedge" | "The engine hedges by shorting shares in proportion to the adverse probability. Behind the scenes the AI is already fitting an algorithm." The **AI fit card** appears: event class, family and preset, score, rationale, alternatives. "It classified the event as Macro Fed and tuned the preset on the market's own price history: Fig Stress, preset 54. That score is measured on the same history it then replays, so it is in-sample and not a forecast." |
| 0:35 | Build chat, **Connect** | "Connect brokerage", then "Run the AI pipeline" | "Orders go to the simulated account. Webull paper takes over when its keys are set; real money is out of scope." Point at the account tag: "Simulated account". |
| 0:42 | **AI pipeline** | Wait for "Approve the IWM bridge?" | "Six steps: classify, shortlist from the library, load real price history, tune presets on replay, explain, ready. Nothing runs until I approve." |
| 0:52 | AI pipeline | "Approve and open the bridge" | "This is the approval gate. The proposal is pinned to this exact algorithm and capped at the coverage I approved; the backend refuses to run anything else." |
| 0:55 | **Bridge live** | Watch ~25 s | "A compiled C++ algorithm is reading the replayed ticks. REPLAY badge: this is the recorded month, not live. The gates show why it acts or waits: most ticks are 'inside band' holds and only a handful are rebalances. Each trade says why, in plain words, and what it was filled at. Coverage climbs toward my cap, never past it." |
| 1:20 | **Library** | Nav "Library" | "1,278 presets across 16 families. The AI only picks from what is compiled. The running preset is marked." |
| 1:28 | **Portfolio** | Nav "Portfolio" | "Holdings, exposure by event, hedge status 'bridged'." |

Close the demo on the Bridge or Library screen. About 90 seconds; the replay is still finishing, which is fine.

Two things to know before you say "and here is the account":

- A replay bridge trades in a **replay sandbox** by default, so the Portfolio's "Recent fills" and positions stay empty after this demo. The Bridge screen's trade log is where its fills show. Orders reach the account (`GET /account`, `/positions`, `/orders`) only from a live bridge, or a replay started with `replay_to_account` (that is what `make e2e` does, to prove the broker path).
- Replay fills are priced at today's market from Massive, not at the replayed time; the trade log says so.

### Optional: voice

If `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` is set and the tunnel is up (see `docs/voice-agent.md`), say "protect my IWM against a Fed hike". Approval and starting a bridge need an explicit "yes" from you.

### Other recorded markets

`REPLAY=replays/<file> make dev` (path from the repo root) plays a different recording (the replay file is global, so pick the matching market in Build). See `replays/README.md`. Two fresh high-volume ones:

- Indiana data-center moratorium by end of 2027 (about 1.9 million dollars traded in 24 h): pick **VRT**, "tech_regulation" class. History: p moves 14.5c to 53.5c.
- US x Iran ceasefire through October 31: pick **XLE** (down on YES, 4 percent, AI estimate), "geopolitics_energy" class. History: p moves 36.5c to 70.5c.

## 3. Pre-flight checklist

- [ ] `cd backend && uv sync --locked --group engine` (builds hedgecore); `uv run python -c "import hedgecore"` works.
- [ ] `cd web && pnpm install`.
- [ ] `.env` in the repo root has `MASSIVE_API_KEY` (replay fills need a price; see fallbacks). `GEMINI_API_KEY` is optional.
- [ ] Ports 8000 and 3000 free: `lsof -i :8000 -i :3000`.
- [ ] Smoke test: `make e2e-api` (about 75 s, uses a throwaway simulated account, stops what it starts). It must print `RESULT   : PASS`.
- [ ] `make dev`; `curl localhost:8000/health` returns ok; open http://localhost:3000.
- [ ] Walk the click path once, then **restart the backend** before the talk: proposals and bridges are in memory, one bridge per proposal, so a rehearsed proposal re-attaches to its finished bridge instead of replaying.
- [ ] Optional full rehearsal with screenshots: `make e2e` (headless Chrome clicks the same path; about 3 minutes).
- [ ] Tabs pre-opened, browser zoom set for the room, notifications off.

## 4. Fallbacks (what each failure looks like, and what to say)

| If | What happens | What to do |
|---|---|---|
| **Wi-Fi off** (no network at all) | Market search uses the bundled list ("offline: cached market list"); `/map` is precomputed; the fit tunes on the recorded replay file (tag "replay ticks" instead of "real price history"); the bridge replays fine and the decisions, gates and reasons all work. **But the broker refuses every order**: replay fills need a Massive price and there is none, so the trade log shows rejected orders and the hedge stays at zero. (Known limitation, `make e2e` pins it with `--offline`.) | Prefer a phone hotspot. If you must go offline, narrate the decisions and gates, and say plainly that fills need market data. Do not claim a hedge was built. |
| **No Gemini key** | Rules-based classifier and a template rationale; the tag says "RULES-BASED FIT". The family and preset come from the same deterministic replay tuning. | Say "keyword rules today; Gemini refines the classification and the wording when a key is set". |
| **No Webull key** | The account is the simulator. The Connect screen shows the Webull card as a saved preference only, and the account tag reads "Simulated account". | Say "simulated account; Webull paper takes over when its keys are set". Never imply a real broker. |
| **No Massive key** | No live equity quote; replay fills are refused as above. The fit still runs on recorded bars. | Put the key in `.env` before the talk. |
| **Polymarket slow or down** | Search falls back to the bundled list; the fit uses the replay file; the bridge replay is unaffected. | As Wi-Fi off, but fills still work if Massive is reachable. |
| **Backend down** | The UI says "No engine bridge on the backend ... runs the prototype's simulator" and runs a labelled demo bridge. | Say it is the prototype simulator; restart the backend. |
| **Replay file missing** | The bridge falls back to the live Polymarket book. | Check `ls replays backend/replays`; `make dev` points at `backend/replays/fed-hike-25bps-oct-2026-history.jsonl`. |
| **Chrome or the screenshots hang** | The e2e script always kills Chrome on a deadline (the page's SSE connection never lets it exit by itself). | Re-run `make e2e`; screenshots land in `web/e2e/screens/`. |

## 5. Claims we make, and do not make

Make these:

- The hedge is human-approved, pinned to the approved algorithm and capped at the approved coverage; fills are on a simulated (or Webull paper) account.
- The library is compiled C++ (1,278 presets, 16 families); the AI picks and tunes from it, and falls back to rules without a key.
- Labels are honest: replay vs live, AI estimate vs measured, simulated vs paper, rules vs Gemini.
- The decision latency shown on the bridge screen is measured per tick (hundreds of nanoseconds to a few microseconds).

Do not make these:

- Not "prediction markets lead equities": market-hours lead-lag is mixed to negative and the closed-market study is mixed. The signal is the probability, not a head start.
- Not "the fit predicts returns": the preset score is hedge variance reduction on the same history it is tuned on (in-sample).
- Not "the arbitrage scan found money": 5 resolved gaps, 0 executable.
- Not "AI estimates are measurements": the stock mapping is a precomputed estimate.
- Not "real orders": nothing here touches real money. The landing page's "1,284 algorithms" is a design figure; the library reports 1,278 presets, so say 1,278.

## 6. Q&A crib

- **Why is NULL a valid result?** A pre-registered test that fails to reject bounds the effect size and prevents a false claim. Reporting it is the point of pre-registration.
- **No lookahead?** Features use only data stamped before the event; equity bars join only from the time a bar's close is known; the engine consumes ticks in order.
- **Out-of-sample run?** Rules and parameters froze at 2026-10-03 13:00 ET; the window is run once after the freeze, no re-runs and no tuning on it. Out-of-sample: <fill in after the single post-freeze run, whatever it returns>.
- **What stops it overtrading?** A fee gate holds any order whose expected benefit does not beat its cost, a band holds small rebalances, and a hard coverage cap (the approved `target_coverage`) clips every sell. The bridge's summary counts each reason.
- **Approval gate?** A proposal starts pending; `POST /bridges` is 409 until it is approved and 409 again for any algorithm other than the approved one. Opportunity (options) proposals never reach the hedge engine.
- **Where does book depth come from?** Live bridges read the top five levels per side from Polymarket or Kalshi. History replays are mid-price only (the spread and depth at the time are unknown and left empty, never invented); `replays/*-book.jsonl` carry real recorded depth.
- **What is exploratory?** The atlas and the AI stock mappings. They suggest where to look and carry no confirmatory weight; 96,390 variants were counted against any hit (`research/results/RUN_LOG.md`).
