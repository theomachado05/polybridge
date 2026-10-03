# PolyBridge demo script (v4)

Total: 5 minutes. Findings first (3 min), live demo (90 s), ask (30 s). The demo shows one thing end to end: a
prediction-market event becomes an approved, AI-fitted, compiled hedge that trades on a simulated account.

## 1. Pitch outline

### Findings (3 min)

Say what the evidence supports and no more, each finding with its scope in the same breath. Full numbers are in `research/EVIDENCE.md` and the result files named here; the spoken track is `docs/pitch-notes.md` section 1.

1. **Principle: evidence gating.** PolyBridge validates each market's signal out of sample before it lets that signal touch a position. Most markets fail, and the product says so: "validated" vs "unvalidated estimate".
2. **Options at the open** (fresh data, pre-registered R3; `research/results/open_options/SUMMARY.md`). At the Monday open options had repriced by only 0.44 of the PM's closure move (95% CI 0.33 to 0.57; 1,535 events, 44 closures). Same breath: net of option costs the residual gap is +0.79 pt [-1.21, +2.78], so R3 is NULL; information, not a tradable arbitrage.
3. **Expected gap on the US-recession market** (R2; `research/results/gap_model/SUMMARY.md`). Walk-forward in time: sign right in 64.2% of 151 closures, slope +1.28; pooled 141 of 235 (60.0%, p = 0.003), slope +1.25, permutation p < 0.001. Same breath: one market; election 52.4% (p = 0.744); fails on the 10-market replication panel (50.2% of 878, slope -0.23); already-seen panel.
4. **Staged equity hedge at 09:30** (R1 hedge B; `research/results/closed_hedge/SUMMARY.md`). Post-open variance cut +11.42% [+5.10, +18.14] vs no hedge, +6.82% [+0.50, +13.54] vs a same-size static hedge. Same breath: fragile (partial under block bootstrap; -0.78% vs static after dropping 5 closures), timing not direction, does not touch the gap, already-seen 380 panel.
5. **The 380-closure relation, exploratory** (`research/results/leadlag_closed/SUMMARY.md`, Placebo). +7.52 bp per pp, permutation p = 0.001, and it did not replicate on 10 rule-selected new markets (+0.63, p = 0.126; `research/results/leadlag_replication/SUMMARY.md`). A re-reading of the placebo arm of a study whose verdict was mixed; same-window co-movement; not compared with futures.
6. **Six pre-registered tests run today** (`research/EVIDENCE.md`, "Six pre-registered tests run today"). Replication: does not replicate (method `7a780b5`). AI fit walk-forward: fails, median -0.0040, 19 above 0, 72 below, Wilcoxon p = 1.000 (`e2f1600`). 8-K out of sample: H1 NULL (3 events, untestable), H2 NULL with sign opposite to in-sample (`344de99`). R1: hedge A no evidence and increases variance on the replication panel; hedge B passes, fragile (`c9fc174`). R2: passes on the panel via the recession market only; fails on the replication panel (`fe7c181`). R3: NULL after costs (`297727a`). Say plainly: the four on new data failed or were NULL; the two passes are on the known panel.
7. **What didn't work.** 8-K parity NULL in-sample (`research/results/in_sample/hedge_verdict.txt`, `opportunity_verdict.txt`). Market hours: PM first 9, equity first 9, simultaneous 2, sign test p = 1.0 (`research/results/leadlag/SUMMARY.md`). Options arbitrage: 5 verified, 0 executable, each on a single print of 5 to 100 shares (`research/results/arb/SUMMARY.md`). AI fit scores are in-sample only.
8. **Product implications.** Closed-market mode defaults to staged equity orders (hedge B); the PM-contract hedge (A) is opt-in and labelled an estimate; options-at-open is research-only; the AI fit is configuration, not edge. Every hedge is approved by the holder, sized and capped.

### Live demo (90 s)

Click path in section 2.

### Ask (30 s)

Feedback on the validation design, futures and prediction-market tick data to test the staged hedge and the expected gap on a fresh sample against futures, or a pilot hedge book. Close on: "Stocks close, prediction markets don't. We built the tool that lets a hedger use that only where the evidence holds, and we report what the tests show, including the nulls."

## 2. Live demo: 90-second click path

Servers up (section 4). Open http://localhost:3000 (not 127.0.0.1). The default replay is about 17 days of real Polymarket history (401 hourly points, 2026-09-16 to 2026-10-03) for **"Another Fed rate hike in 2026?"**, hedging **TLT**, played at 21600x (about 67 seconds). We demo this market because on it the fit's prediction-market signal measurably beats a static hedge in-sample (score +0.257, `backend/app/data/fits.json`; on its own walk-forward test the picked preset scored -0.245 on unseen data, `research/results/fit_oos/per_market.csv`); on the Fed October 25 bps market we used before, the fit scores no better than a static hedge (-0.011 on its replay) and the bridge places one order. Everything below was walked through by `make e2e` (the screenshots are in `web/e2e/screens/`).

| Time | Screen | Click | Say |
|---|---|---|---|
| 0:00 | **Landing** | "Build a bridge" | "You hold a stock. A prediction market is putting a live probability on an event that moves it. PolyBridge reads that probability and hedges the stock, only after you approve." |
| 0:05 | **Build chat** | Click the first row, "Another Fed rate hike in 2026?" (tagged **demo market**, top of the held-market list; or type `fed rate hike 2026` and pick it) | "This is the live Polymarket market: read the YES price and volume off the row (about 72 cents YES on 2026-10-03). The search hits Polymarket and Kalshi; with no network it falls back to a bundled list and says so." |
| 0:15 | Build chat | Pick **TLT** (1,000 shares held) | "Which stock does it move? This mapping is an AI estimate, labelled as one: a hike pushes long yields up and bond prices down, about 2.5 percent on TLT. It is an estimate, not a measurement." Note: the chat names XHB as the biggest mover (-3.0 percent); pick TLT because it is the stock you hold (it lists first). |
| 0:22 | Build chat | Pick "a dynamic short hedge" | "The engine hedges by shorting shares in proportion to the adverse probability. Behind the scenes the AI is already fitting an algorithm." The **AI fit card** appears: event class, family and preset, score, rationale, alternatives. Expect Macro Fed, equity_delta_bridge preset #75, score 0.257 (a fresh fit on live history; it can move if the history has). "On this market the signal adds 25.7 percent over a static hedge, in-sample: the hedged position's variance is about a quarter lower than with a fixed short of the same average size. That is measured on the same history it then replays, it is the best of many presets, and we chose this market for the demo because it scores near the top: 4th of 122. Across 122 markets it adds more than 10 percent on 14 and nothing on 36, which score at or below zero; the median is half a percent. So it is not a forecast, and it is not typical. It is configuration, not edge: on this market's own walk-forward test the preset picked on the first 60 percent scored -0.245 on unseen data, and across 122 markets the picks did not beat a static hedge (median -0.0040)." (`research/results/fit_oos/per_market.csv`, `polymarket:4620900`) |
| 0:35 | Build chat, **Connect** | "Connect brokerage", then "Run the AI pipeline" | "Orders go to the simulated account. Webull paper takes over when its keys are set; real money is out of scope." Point at the account tag: "Simulated account". |
| 0:42 | **AI pipeline** | Wait for "Approve the TLT bridge?" | "Six steps: classify, shortlist from the library, load real price history, tune presets on replay, explain, ready. Nothing runs until I approve." |
| 0:52 | AI pipeline | "Approve and open the bridge" | "This is the approval gate. The proposal is pinned to this exact algorithm and capped at the coverage I approved; the backend refuses to run anything else." |
| 0:55 | **Bridge live** | Watch ~25 s (the first fill lands within a few seconds) | "A compiled C++ algorithm is reading the replayed ticks. REPLAY badge: this is the recorded history, not live. The gates show why it acts or waits: most ticks are 'below sigma' or 'inside band' holds and only a handful are rebalances (4 orders over the whole replay in our run). Each trade says why, in plain words, and what it was filled at. Coverage climbs toward my cap, never past it." |
| 1:20 | **Library** | Nav "Library" | "1,386 presets across 17 families" (the screen reads the live catalog total; say what it shows). "The AI only picks from what is compiled. The running preset is marked." |
| 1:28 | **Portfolio** | Nav "Portfolio" | "Holdings, exposure by event (TLT against this market), hedge status 'bridged'." |

Close the demo on the Bridge or Library screen. About 90 seconds; the replay is still finishing, which is fine.

Two things to know before you say "and here is the account":

- A replay bridge trades in a **replay sandbox** by default, so the Portfolio's "Recent fills" and positions stay empty after this demo. The Bridge screen's trade log is where its fills show. Orders reach the account (`GET /account`, `/positions`, `/orders`) only from a live bridge, or a replay started with `replay_to_account` (that is what `make e2e` does, to prove the broker path).
- Replay fills are priced at today's market from Massive, not at the replayed time; with no network or no Massive key they use the recorded replay price instead. The trade log says which.
- The bridge places fewer orders than the engine's own replay of the same preset (TLT: 4 vs 17; 3 vs 11 at a 50% cap), with the same decisions. The engine replay counts every send and refuses a fill at a stale recorded close (nights, weekends, before a new bar), so it re-sends the same order hour after hour; the sim broker fills each order when it arrives. 361 of the 401 ticks are 'below sigma' holds in both. Details: `docs/contracts.md`, "Bridge vs engine replay".

### Optional: voice

If `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` is set and the tunnel is up (see `docs/voice-agent.md`), say "protect my TLT against another Fed rate hike" (the replay file only plays for the market it records, so a bridge on another market is refused with a 422). Approval and starting a bridge need an explicit "yes" from you.

### Optional: the Opportunity division (20 seconds)

The same event can also be **traded against listed options** instead of hedged: when the prediction market's
probability and the options-implied probability of the same threshold disagree, `binary_vs_spread_arb` buys or sells
the call spread. Today only one recording carries option history, a resolved market:
**"Will NVIDIA (NVDA) close above $230 end of September?"** (resolved NO; 353 hourly points, 66 of them with an
options estimate; `backend/replays/README.md`). No restart: with `make dev` as is, an opportunity bridge on this market
finds its own recording through the replay index.

Timing: at 21600x the replay runs about 59 s, and the options family first trades about 38 s in (Sep 25), then
again in the last 5 seconds or so (Sep 29 and expiry day). Start this bridge before the segment (during the findings,
or right after the hedge demo) and come back to it: the Bridge screen keeps the whole trade log.

| Time | Screen | Click | Say |
|---|---|---|---|
| 0:00 | **Build chat** | Type `NVIDIA close above $230 end of September`; click the row tagged **resolved · recorded replay** | "A resolved market we recorded: its price and the options-implied estimate, hour by hour." |
| 0:04 | Build chat | No mapping exists, so type `NVDA` and pick it; the **Hedge vs Opportunity** choice appears | "Besides a hedge, PolyBridge can offer an options trade on the same threshold." The Opportunity row reads "AI fit · replay score -0.956 (estimate)", Binary Vs Spread Arb preset #6. |
| 0:08 | Build chat | Click **Opportunity**: the options fit card | "The family, the preset, the replay score and the risk caps I approve: at most 10 spreads open, $10,000 at risk. The score is negative: on this history it lost money, in-sample. We show the mechanism, not an edge." The card also says the division's top pick (No Bid Seller) trades prediction-market legs and never runs on a bridge, and that a resolved market has no live options estimate. |
| 0:12 | Build, then **Bridge** | "Approve & start options bridge" (or open the bridge you started earlier) | Tags: REPLAY, RECORDED OPTION DATA, SIMULATED FILLS. "PM YES is measured; the options-implied number is a risk-neutral estimate from the option legs' bar closes; the gap is the difference, and the sparkline its history. Nights and weekends show no estimate, by design: a stale close is not a price." On the trades: "Each order is a two-leg call spread, 227.5 / 232.5, filled all-or-none by the simulator at the recorded leg closes plus an assumed 2% half-spread, because these contracts have expired. Eleven orders, and the last spread, bought an hour before expiry, is closed at its settlement value: NVDA closed at 228.38, so the 227.5 call is worth 88 cents and the 232.5 call nothing." |

Labels to keep (all on screen): simulated option fills; in-sample replay estimate (best of 36 presets, still
-0.956: 11 orders, -$276.15 net of fees, max drawdown $288.95); options-implied = estimate, not a measured probability;
the PM price is the hourly mid (spread unknown). The bridge's simulated round trips come to -$294.77: a different fill
model from the engine replay's, same eleven decisions; both value the last spread at its expiry settlement (intrinsic
at the official close), labelled on the closing fill. Checked over HTTP by `make e2e-opportunity` (22 checks, also
with `--offline`).

### Other recorded markets

`REPLAY=<path from the repo root> make dev` plays a different recording (the replay file is global, so pick the matching market in Build; a replay bridge for any other market is refused with a 422 when the file's `.meta.json` sidecar names a different market). See `backend/replays/README.md` and `replays/README.md`.

- Russia military action against an EU country by end of 2026: `REPLAY=backend/replays/russia-eu-military-2026-history.jsonl SPEED=18000 make dev`, type `Russia military action EU`, pick **ITA** (not a held stock, so the bridge sizes 500 shares; up on YES, 3 percent, AI estimate), "geopolitics_energy" class. The strongest in-sample fit of the 122 (energy_geo_hedge #54, +0.508, best of 122, from the precompute at 1,000 shares; the score depends on share count, so say the number the fit card shows and quote +0.508 only if the card matches). Say with it: on its own walk-forward test it scored train +0.631, test -0.418 (`research/results/fit_oos/per_market.csv`). A busier bridge: with closed-market mode on (the default; the equity algo holds outside regular hours) it places 9 orders uncapped at 1,000 shares and 5 at a 50% cap or at the 500 shares the UI sizes for an unheld stock; trading at any hour (`session_hold=false`) it would be 31 and 17 (`backend/replays/README.md`). Read the count off the Bridge screen. History: p trades between 6.5c and 28.5c over 347 hourly points (about 69 s); the 48.5c first point is the market's opening print, not a traded swing.
- The previous default, the Fed October 2026 25 bps hike: `REPLAY=backend/replays/fed-hike-25bps-oct-2026-history.jsonl SPEED=36000 make dev`, type `fed october`, pick **IWM** (400 shares held). Its fit scores no better than a static hedge (-0.011) and the bridge places about one order; use it to show an honest null.

Two fresh high-volume ones in `replays/` (`REPLAY=replays/<file> make dev`):

- Indiana data-center moratorium by end of 2027 (about 1.9 million dollars traded in 24 h): pick **VRT**, "tech_regulation" class. History: p moves 14.5c to 53.5c.
- US x Iran ceasefire through October 31: pick **XLE** (down on YES, 4 percent, AI estimate), "geopolitics_energy" class. History: p moves 36.5c to 70.5c.

## 3. Pre-flight checklist

- [ ] `cd backend && uv sync --locked --group engine` (builds hedgecore); `uv run python -c "import hedgecore"` works.
- [ ] `cd web && pnpm install`.
- [ ] `.env` in the repo root has `MASSIVE_API_KEY` (live equity quotes for fills and the Portfolio exposure; see fallbacks). `GEMINI_API_KEY` is optional.
- [ ] Ports 8000 and 3000 free: `lsof -i :8000 -i :3000`.
- [ ] Smoke test: `make e2e-api` (about 75 s, uses a throwaway simulated account, stops what it starts). It must print `RESULT   : PASS`.
- [ ] If you show the Opportunity segment: `make e2e-opportunity` (about 60 s, API only). It must print `RESULT   : PASS`.
- [ ] `make dev`; `curl localhost:8000/health` returns ok; open http://localhost:3000.
- [ ] Walk the click path once, then **restart the backend** before the talk: proposals and bridges are in memory, one bridge per proposal, so a rehearsed proposal re-attaches to its finished bridge instead of replaying.
- [ ] Optional full rehearsal with screenshots: `make e2e` (headless Chrome clicks the same path; about 3 minutes).
- [ ] Tabs pre-opened, browser zoom set for the room, notifications off.

## 4. Fallbacks (what each failure looks like, and what to say)

| If | What happens | What to do |
|---|---|---|
| **Wi-Fi off** (no network at all) | Market search uses the bundled list ("offline: cached market list"); `/map` is precomputed; the fit tunes on the recorded replay file (tag "replay ticks" instead of "real price history"); the bridge replays fine and the decisions, gates and reasons all work. Orders fill in the sandbox at the **recorded price** from the replay file (each fill is marked "recorded price"), so the hedge builds as usual. `make e2e` checks this with `--offline` (26/26 pass). The Opportunity segment works offline too (the fit and the option legs use the recording; `make e2e-opportunity` with `--offline`, 22/22). With an AI fit the approval button reads "Approve and open the bridge" (the algo's fee gate prices orders from the recorded price); only if the fit did not answer (tag "scripted demo steps") does it read "Approve without the fee gate", because the default spec then runs with no quote to price fees. | Prefer a phone hotspot. If offline, say the fills are priced from the recorded replay, not a live quote. |
| **No Gemini key** | Rules-based classifier and a template rationale; the tag says "RULES-BASED FIT". The family and preset come from the same deterministic replay tuning. | Say "keyword rules today; Gemini refines the classification and the wording when a key is set". |
| **No Webull key** | The account is the simulator. The Connect screen shows the Webull card as a saved preference only, and the account tag reads "Simulated account". | Say "simulated account; Webull paper takes over when its keys are set". Never imply a real broker. |
| **No Massive key** | No live equity quote; replay fills use the recorded price from the replay (each fill is marked "recorded price"), and the Portfolio exposure is empty (no spot price). The fit still runs on recorded bars, so the approval button reads "Approve and open the bridge"; it reads "Approve without the fee gate" only if the fit did not answer and the default spec runs. | Put the key in `.env` before the talk. |
| **Polymarket slow or down** | Search falls back to the bundled list; the fit uses the replay file; the bridge replay is unaffected. | As Wi-Fi off; fills use a Massive quote if Massive is reachable, else the recorded price. |
| **Backend down** | The UI says "No engine bridge on the backend ... runs the prototype's simulator" and runs a labelled demo bridge. | Say it is the prototype simulator; restart the backend. |
| **Replay file missing** | The bridge falls back to the live Polymarket book. | Check `ls replays backend/replays`; `make dev` points at `backend/replays/another-fed-hike-2026-history.jsonl`. |
| **Chrome or the screenshots hang** | The e2e script always kills Chrome on a deadline (the page's SSE connection never lets it exit by itself). | Re-run `make e2e`; screenshots land in `web/e2e/screens/`. |

## 5. Claims we make, and do not make

Make these:

- The hedge is human-approved, pinned to the approved algorithm and capped at the approved coverage; fills are on a simulated (or Webull paper) account (Webull means its sandbox, `api.sandbox.webull.com`; any other `WEBULL_BASE_URL` is refused and the simulator is used).
- The library is compiled C++ (1,386 presets, 17 families); the AI picks and tunes from it, and falls back to rules without a key.
- Labels are honest: replay vs live, AI estimate vs measured, simulated vs paper, rules vs Gemini.
- The fit ranks presets by how much variance they remove beyond a static hedge of the same average size (what the signal adds), not by raw variance reduction, which any static short earns. Say it is an in-sample replay.
- The decision latency shown on the bridge screen is measured per tick (the `step()` stamp, decision logic only). No result file records its values: read the value off the screen.

Do not make these:

- Not "prediction markets predict the open" in general, and not "prediction markets lead equities": market-hours lead-lag is mixed to negative and the closed-market study is mixed. Allowed, scoped: options repriced by 0.44 of the PM's closure move at the open (NULL after costs, not an arbitrage); on the US-recession market the expected gap held out of sample in time (fails on the replication panel); staging the equity hedge for 09:30 cut post-open variance (fragile, known panel).
- Not "the staged hedge reduces the gap" or "the PM-contract hedge protects you": hedge B changes post-open risk only; hedge A showed no evidence and increased variance on the replication panel.
- Not "the closed-hours relation is confirmed" or "replicated": the pre-registered replication on 10 new markets did not replicate (+0.63 bp per pp, permutation p = 0.126). It is exploratory.
- Not "the fit predicts returns": the preset score is the hedge variance reduction beyond a static hedge of the same size, on the same history it is tuned on (in-sample), and the best of many presets. Out of sample (walk-forward, pre-registered) the picked preset does not beat a static hedge (median -0.0040).
- Not "the demo market shows the signal works": "Another Fed rate hike in 2026?" was chosen for the demo because its fit scores near the top (+0.257, 4th of 122), in-sample and the best of many presets; on its own walk-forward test the picked preset scored -0.245. Say it is a good case in-sample, not a typical one.
- Not "the fit shows the signal works": over the 133 precomputed markets the median score is 0.0053, 36 of 122 scored fits are at or below zero (all negative), and only 53 are above 0.01 (`backend/app/data/fits.json`, our tally of the entries). Do not quote the raw variance reduction (median 0.339) as the hedge's edge: most of it is hedge size (median average hedge ratio 0.18).
- Not "the arbitrage scan found money": 5 resolved gaps, 0 executable.
- Not "the options trade makes money": on the NVDA replay `binary_vs_spread_arb` scores -0.956 in-sample and the bridge's simulated round trips lose $294.77. Do not quote the division's top pick, `no_bid_seller` (+11.149): it trades prediction-market legs only, and its replay sells NO at the recorded mid with the spread unknown.
- Not "AI estimates are measurements": the stock mapping is a precomputed estimate.
- Not "real orders": nothing here touches real money. Not "1,284 algorithms" or "1,278 presets": 1,284 appears only in the design handoff; the landing page and Library screen show the live catalog total (1,386 presets, 17 families).

## 6. Q&A crib

- **Why is NULL a valid result?** A pre-registered test that fails to reject bounds the effect size and prevents a false claim. Reporting it is the point of pre-registration.
- **No lookahead?** Features use only data stamped before the event; equity bars join only from the time a bar's close is known; the engine consumes ticks in order.
- **Out-of-sample run?** Rules and parameters froze at 2026-10-03 13:00 ET; the window is run once after the freeze, no re-runs and no tuning on it. Out-of-sample: NULL for both hypotheses (H1 3 events, too few to compute an edge; H2 8 events, edge -0.0215 at 21 sessions and -0.0138 at 42, CIs span zero, opposite sign to in-sample; `research/results/oos/SUMMARY.md`). Very little power, so not proof of no effect.
- **What stops it overtrading?** A fee gate holds any order whose expected benefit does not beat its cost, a band holds small rebalances, and a hard coverage cap (the approved `target_coverage`) clips every sell. The bridge's summary counts each reason.
- **Approval gate?** A proposal starts pending; `POST /bridges` is 409 until it is approved and 409 again for any algorithm other than the approved one. Opportunity (options) proposals never reach the hedge engine.
- **Where does book depth come from?** Live bridges read the top five levels per side from Polymarket or Kalshi. History replays are mid-price only (the spread and depth at the time are unknown and left empty, never invented); `replays/*-book.jsonl` carry real recorded depth.
- **What does the fit score mean?** Plain variance reduction rewards any static short: a fixed short of a fraction h of the shares scores `1 - (1 - h)^2` even if the prediction market never moves. So the fit ranks on `hedge_var_reduction_vs_static`, the variance cut beyond a static hedge of the same average size, i.e. what the PM signal adds (0 = no better than static, negative = timing hurt). It is in-sample (tuned and scored on the same history, best of many presets), so a few thousandths is noise. Over the 133 precomputed markets: 122 scored, median 0.0053, 86 above 0 but only 53 above 0.01, 31 above 0.05, 14 above 0.1, 7 above 0.2; 36 at or below 0, all negative. The signal adds a material amount on roughly 14 to 31 markets at most (`backend/app/data/fits.json`; `research/EVIDENCE.md` section 6).
- **Do fit fills use stale prices?** No. In the engine's replay an equity order with no live quote is rejected outside the US regular session and until the price has changed inside the session, so the opening gap is never booked as hedge P&L (`engine/hedgecore/include/hedgecore/replay.hpp`). A night-time PM move is hedged at the next fresh in-session price.
- **What is exploratory?** The atlas and the AI stock mappings. They suggest where to look and carry no confirmatory weight; 96,390 variants were counted against any hit (`research/results/RUN_LOG.md`).
