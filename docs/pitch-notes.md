# PolyBridge pitch notes (findings talk track and demo cues)

Companion to `docs/demo.md` (same 5-minute shape: findings 3 min, live demo 90 s, ask 30 s). The story is **evidence-gated 24/7 hedging**: stocks close, prediction markets don't, and PolyBridge checks each market's signal out of sample before it lets that signal act on a position. Every research claim is backed by `research/EVIDENCE.md`; product and demo claims come from `docs/demo.md` sections 2, 5 and 6 and `docs/design.md`; every number is copied from the source file in brackets. If a research number is not in EVIDENCE.md, do not say it. Six pre-registered tests ran on Saturday; the four on new data failed or were NULL, and the two passes are on an already-seen panel. Say each finding with its scope in the same breath.

## 1. Findings talk track (3:00)

Order: principle and closed-market mode, the three findings that cleared a test (each with its scope), the 380-closure relation (exploratory, not replicated), the six-test scoreboard, what didn't work (led by the 8-K study), what the product does with it. Speak the bold words, skip the brackets.

**0:00 to 0:20, the principle.**
"**Stocks close. Prediction markets don't.** Overnight and at weekends a prediction market keeps repricing the risk while the stock can't trade, and PolyBridge hedges in that window. Our rule: **PolyBridge validates each market's signal out of sample before it lets that signal touch a position.** Most markets fail, and the product says so: every signal is labelled validated or unvalidated estimate."

**0:20 to 0:45, the expected gap.**
"First finding. On the **US-recession market**, our expected-gap model held out of sample in time: fitted only on earlier closures, it got the sign of the SPY open right **64.2 percent** of the time, slope 1.28. Pooled, **141 of 235, p equals 0.003**. Scope: **one market**. The election market was 52 percent, and on 10 new markets it failed, **50.2 percent**. It is the demo market, the only one whose badge reads validated." [`research/results/gap_model/SUMMARY.md`]

**0:45 to 1:10, staged hedge.**
"Second. Staging the equity hedge for the first tradable moment, 09:30, cut post-open variance **11.4 percent** against no hedge and **6.8 percent** against a same-size static hedge. It is **fragile**: drop five closures and the edge over static goes away. It works by timing, not direction, and it re-uses a panel we had already seen." [`research/results/closed_hedge/SUMMARY.md`]

**1:10 to 1:35, options at the open.**
"Third, on fresh data, pre-registered. Over **1,535 events and 44 weekend and holiday closures**, at the Monday open options had repriced by only **0.44 of the prediction market's closure move**, confidence interval 0.33 to 0.57. But after option costs the leftover gap is **plus 0.79 points, interval minus 1.21 to plus 2.78**: not different from zero. So it is information, **not an arbitrage**, and the options were actually better calibrated." [`research/results/open_options/SUMMARY.md`]

**1:35 to 1:55, where it started.**
"All this came from an exploratory result: over 380 closures the prediction-market move lined up with the SPY gap, **7.5 basis points per point, p equals 0.001**, and **it did not replicate** on 10 rule-selected new markets: **0.63, p equals 0.126**. Same-window co-movement; we did not test it against futures." [`research/results/leadlag_closed/SUMMARY.md`; `research/results/leadlag_replication/SUMMARY.md`]

**1:55 to 2:15, the scoreboard.**
"Six pre-registered tests, rules committed before the data. **Replication: failed. AI fit walk-forward: failed**, median minus 0.004, 19 markets better, 72 worse. **8-K out of sample: null**, 3 and 8 events. **Options at the open: null after costs.** The two passes, the expected gap and the staged hedge, are on the known panel, with the scope I gave." [`research/EVIDENCE.md`, "Six pre-registered tests run today"]

**2:15 to 2:35, what didn't work.**
"Our most rigorous study is a null. The **8-K study**, pre-registered, frozen and run once out of sample: **null in-sample and out of sample**. Also null: market hours, **9 prediction-market-first, 9 equity-first, 2 tied, p equals 1.0**; the arbitrage scan, **5 verified, 0 executable**; and holding the prediction-market contract itself over a closure showed no evidence of reducing the gap." [`research/EVIDENCE.md`, "What didn't work", section 3]

**2:35 to 3:00, what the product does with it.**
"So the product follows the evidence. Closed-market mode **defaults to staged equity orders**. The prediction-market contract hedge is **opt-in, labelled an estimate**. Options at the open is **research only**. And the AI fit is **configuration, not edge**: it picks from a compiled C++ library of **17 families, 1,386 presets**, and nothing trades until you approve. Let me show you a real weekend." [`research/EVIDENCE.md`, "Product implications"; `engine/hedgecore/manifest.json`]

Time check: about 500 spoken words, about 2.8 minutes at 180 words per minute, which leaves little room for pauses inside the 3:00. If long, cut in this order: "the options were better calibrated", the slope 1.28, the 7.5 basis points figure (keep "did not replicate" and 0.63). Never cut a scope clause, the word "fragile", "one market", "not an arbitrage" or "did not replicate".

## 2. Demo cues (90 s)

Same click path and times as `docs/demo.md` section 2. Segment 1 is the recorded tariff weekend (`make dev`'s default), http://localhost:3000, "US recession in 2025?" hedging SPY, Friday 2025-04-04 15:30 ET to Monday 2025-04-07 10:00 ET, about 67 s. Read live values off the screen rather than from notes. The P&L figures below are the recorded 1,000-share run (`backend/replays/README.md`; `make e2e-weekend` prints them); if the screen shows a different share count or plan size, say what the screen shows.

**Webull on a Sunday.** The Webull paper sandbox takes orders only from 09:30 to 16:00 ET (HTTP 417 outside, tested Saturday 2026-10-03). On Sunday the weekend replay fills in the simulator, the Connect screen shows the Webull paper account connected, and a staged order for Webull would execute at Monday's open.

| Time | Screen | Click | Say (only supported claims) |
|---|---|---|---|
| 0:00 | Landing | "Build a bridge" | "It's Sunday. The stock market is closed; prediction markets aren't. PolyBridge watches the move and hedges at the first moment the stock can trade, only after you approve." |
| 0:05 | Build chat | Type `US recession 2025`; click the row tagged "resolved · recorded replay" | "A real market and a real weekend: the April 2025 tariff weekend, picked by a fixed rule, not by eye." |
| 0:10 | Build chat | Type `SPY`, pick it; check it reads down on YES | Weekend mode card, badge "expected gap validated": "This is the evidence gate. On this market the expected gap held out of sample, 97 of 151 closures. Everywhere else the badge reads unvalidated estimate. Default: hedge B, a staged equity order. Hedge A, the prediction-market contract, is off and labelled an estimate." |
| 0:18 | Connect, AI pipeline | "Connect brokerage", "Run the AI pipeline", approve | "Webull paper is connected. Its sandbox takes orders only 9:30 to 4 Eastern, so this weekend replay fills in the simulator; a staged order for Webull would go in at Monday's open. Nothing runs until I approve." Without Webull keys: "simulated account". |
| 0:25 | Bridge live | Watch the closed-market panel | "Friday 4 pm, the market closes. The equity algo holds. The bridge tracks the prediction-market move and turns it into an expected open gap with its band: validated, 231 closures behind the rate." |
| about 0:50 | Bridge, Staged orders | **Approve plan** (before Monday 04:00 on the recording, about 61 s in) | "Sell SPY at the first tradable moment, sized on the expected gap. It cancels or resizes if the move reverts, and nothing is sent until I approve." |
| about 1:30 (the replay ends about 67 s after the bridge starts) | Bridge, hand-off timeline and P&L | Read | "Filled at the first fresh price, Monday 4:05 am pre-market, 488.45, in the simulator. At 9:30 the hand-off: the algo takes over. Friday close to Monday 10 am: no hedge **minus $10,870**, hedged **minus $8,276**, **$2,594 better**. Honestly: the staged order alone **lost $1,607**, because SPY rallied after the open. It works by timing, not direction, and cannot recover the gap. One weekend shows the mechanism; the evidence is the out-of-sample test." |

Optional segment 2 (only if time allows; no restart, it plays from the same `make dev` session at its own pace): the "Another Fed rate hike in 2026?" replay hedging TLT, for the AI fit card and the Library. The numbers these notes carry for it are the precomputed fit (+0.257, `backend/app/data/fits.json`) and its own walk-forward row (test -0.245, `research/results/fit_oos/per_market.csv`).

| Time | Screen | Click | Say (only supported claims) |
|---|---|---|---|
| 0:00 | Build chat | Click "Another Fed rate hike in 2026?" (tagged "demo market"; or type `fed rate hike 2026`) | "Live Polymarket market. Search covers Polymarket and Kalshi; offline it falls back to a bundled list and says so." |
| 0:10 | Build chat | Pick **TLT** (1,000 shares held) | "A hike pushes bond prices down. This stock mapping is an AI estimate, labelled as one. It is not a measurement." |
| 0:17 | Build chat | Pick "a dynamic short hedge" | On the **AI fit card** (expect equity_delta_bridge #75, score 0.257): "In-sample, on this market the hedge leaves about a quarter less variance than a fixed short of the same average size. It is the best of many presets on the same history, and we picked this market because it scores near the top, 4th of 122; the median is half a percent. It is configuration, not edge: on this market's own walk-forward test the picked preset scored **-0.245** on unseen data, and across 122 markets the picks did not beat a static hedge (median -0.0040). [`backend/app/data/fits.json`; `research/results/fit_oos/per_market.csv`; EVIDENCE.md section 6]" If the card reads differently, say what it reads. |
| 0:30 | Connect, AI pipeline | "Connect brokerage", "Run the AI pipeline", "Approve and open the bridge" | "Classify, shortlist from the library, load real price history, tune presets on replay, explain, ready. The proposal is pinned to this exact algorithm and capped at the coverage I approved." |
| 0:50 | Bridge live | Watch ~25 s | "A compiled C++ algorithm reads the replayed ticks. REPLAY badge: recorded, not live. Gates show why it acts or waits; each trade says why. Coverage climbs toward my cap, never past it." |
| 1:15 | Library | Nav "Library" | "1,386 presets across 17 families (read the total off the screen). The AI only picks from what is compiled." |

Close on the weekend P&L panel (or the Library after segment 2). A replay bridge trades in a sandbox, so the Portfolio's Recent fills stays empty by design; do not claim account fills. Fallbacks (Wi-Fi, Gemini, Webull, Massive, backend, the weekend backup path) are in `docs/demo.md` section 4; do not claim a hedge was built if the broker refused orders.

## 3. Ask (30 s)

"We would like feedback on the validation design, access to futures and tick-level prediction-market data so we can test the staged hedge and the expected gap on a fresh sample against futures, or a pilot hedge book. Stocks close, prediction markets don't: we built the tool that lets a hedger use that only where the evidence holds, and we report what the tests show, including the nulls."

## 4. Claims ledger (what you may say, and where it comes from)

| Claim | Source |
|---|---|
| Principle: each market's signal is validated out of sample before it touches a position; signals are labelled validated or unvalidated estimate; most markets fail | `research/EVIDENCE.md`, "Lead" and "Product implications" |
| R3 (fresh data, method `297727a`, amendment 1 `4877aa2` before any price): options reflected 0.44 [0.33, 0.57] of the PM's closure move at the Monday open; 1,535 events, 44 closures; net residual gap +0.79 pt [-1.21, +2.78] (NULL, not a tradable arbitrage); Brier PM 0.146, options 0.120 | `research/results/open_options/SUMMARY.md`, `stats.json` |
| R2 (method `fe7c181`, already-seen panel): recession market sign 97 of 151 (64.2%, p < 0.001), slope +1.28; pooled 141 of 235 (60.0%, p = 0.003), slope +1.25, permutation p < 0.001; election 44 of 84 (52.4%, p = 0.744); replication panel 441 of 878 (50.2%, p = 0.919), slope -0.23 (p = 0.203), 0 of 10 markets | `research/results/gap_model/SUMMARY.md`, `tests.json` |
| R1 hedge B at 09:30 (method `c9fc174`, already-seen panel, 346 of 380 closures): post-open variance reduction VR0 +11.42% [+5.10, +18.14] vs no hedge, VRS +6.82% [+0.50, +13.54] vs same-size static; partial under block bootstrap; VRS -0.78% after dropping 5 closures; timing, not direction | `research/results/closed_hedge/SUMMARY.md`, `results.json` |
| R1 hedge A (PM contract over the closure): no evidence, VR0 +4.76% [-0.80, +10.01], VRS +0.47% [-2.46, +3.27]; on the replication panel VR0 -3.79% [-8.19, -0.91] (increases variance; applied after the run, Amendment 2) | `research/results/closed_hedge/SUMMARY.md` |
| 380-closure relation (exploratory): slope +7.52 bp per pp (HC3 t +2.58, permutation p = 0.001, R-squared 0.042); 89 of 149 at 1 pp (60%, p = 0.021); recession 58 of 83, election 31 of 66 (p = 0.712); a re-reading of the placebo arm of a study whose verdict was "mixed" | `research/results/leadlag_closed/SUMMARY.md`, `tests.json` |
| Replication (method `7a780b5`): does not replicate; +0.63 bp per pp (HC3 t +1.20, date-permutation p = 0.126); sign test 310 of 620 (50%), p = 1.000 | `research/results/leadlag_replication/SUMMARY.md` |
| Fit walk-forward (method `e2f1600`): fails; median test vs_static -0.0040 (19 above 0, 72 below, 31 at 0; Wilcoxon p = 1.000); train +0.0138; chosen vs default 46 / 46 (p = 0.913) | `research/results/fit_oos/SUMMARY.md` |
| Demo market's own walk-forward row: picked #60 on train (+0.272), test -0.245; ITA train +0.631, test -0.418 | `research/results/fit_oos/per_market.csv` (`polymarket:4620900`, `polymarket:4713962`) |
| 8-K out of sample (frozen `344de99`, tag `method-freeze`): H1 INSUFFICIENT (3 events; the INSUFFICIENT label rule, see HYPOTHESIS.md change log); H2 NULL (edge -0.0215 [-0.0759, +0.0203] at 21 sessions, -0.0138 [-0.0729, +0.0260] at 42; opposite sign to in-sample) | `research/results/oos/SUMMARY.md`, `research/results/RUN_LOG.md` row 8 |
| 8-K H1 and H2 both NULL in-sample; 36 hedge and 24 opportunity events | `research/results/in_sample/SUMMARY.md`, `hedge_verdict.txt`, `opportunity_verdict.txt` |
| Market hours: 28 usable events; PM first 9, simultaneous 2, equity first 9; sign test p = 1.000; pooled test points the other way, HAC 0 of 4 | `research/results/leadlag/SUMMARY.md` |
| 5 verified gaps, 0 executable; each on a print of 5 to 100 shares | `research/results/arb/SUMMARY.md` |
| Atlas is exploratory; 96,390 variants counted | `research/results/atlas/README.md` |
| 17 families, 1,386 presets | `engine/hedgecore/manifest.json`, `engine/hedgecore/BENCH.md` (`docs/library.md` still says 16 / 1,278; it predates `closed_session_hedge`) |
| `on_tick` batch mean 27.1 to 34.6 ns across the first 16 families; `closed_session_hedge` 29.7 ns in a second run (synthetic tape, includes its own stamp) | `engine/hedgecore/BENCH.md` |
| Demo market "Another Fed rate hike in 2026?" -> TLT: equity_delta_bridge #75, score_vs_static +0.257 over 401 hourly ticks (raw 0.748 at average hedge ratio 0.42); 4th of 122, in-sample | `backend/app/data/fits.json` (`polymarket:4620900`), `backend/data_logs/precompute_fits.log`, `backend/replays/README.md` |
| Fit score distribution over the 122: median 0.0053; 86 above 0 and 36 at or below 0 (all negative); 53 above 0.01, 31 above 0.05, 14 above 0.1, 7 above 0.2; max 0.508, min -0.0596; raw median 0.339 at median hedge ratio 0.18 | `backend/app/data/fits.json`, our tally (`research/EVIDENCE.md` section 6) |
| Fit replay fills respect the equity session and a fresh close | `engine/hedgecore/include/hedgecore/replay.hpp`, `engine/hedgecore/src/replay.cpp` |
| Webull is sandbox only (`api.sandbox.webull.com`); other hosts refused, simulator used | `backend/app/broker/webull.py`, `backend/app/broker/__init__.py` |
| Human-approved, capped, simulated account; real money out of scope | `docs/demo.md` section 5 |
| Webull paper sandbox takes orders only 09:30-16:00 ET (HTTP 417 outside; tested Saturday 2026-10-03, 1-share SPY limit, refused); on Sunday the demo fills in the simulator, and a staged order for Webull executes at Monday's open | `docs/demo.md` section 2; `docs/design.md` section 5 |
| Demo weekend "US recession in 2025?" -> SPY, 2025-04-04 to 2025-04-07, picked by a fixed rule (largest adverse weekend move on the validated market); expected gap validated (own rate 10.73 bp/pp on 231 closures), peak -128.8 bp; staged sell 222 filled at 488.45 Monday 04:05 ET pre-market (simulator); hand-off at 09:30 | `backend/replays/README.md`, `backend/replays/us-recession-in-2025-weekend-2025-04-04.jsonl.meta.json`, `make e2e-weekend` |
| Demo weekend P&L, Friday close (506.56) to Monday 10:00 (495.69), 1,000 SPY shares, 50% cap: no hedge -$10,870; hedged -$8,276; +$2,594 vs no hedge; staged order alone -$1,607 (SPY rallied after the open); carried hedge +$3,022; algo after the open +$1,179. One weekend: mechanism, not evidence | `backend/replays/README.md`; `make e2e-weekend` output |

## 5. Do not say

- **"Prediction markets predict the open"** in general, "lead equities", "move first" or "a head start". Allowed, scoped: "options had repriced by 0.44 of the PM's closure move at the open (not an arbitrage after costs)"; "on the US-recession market the expected gap held out of sample in time (fails on the 10-market replication panel)"; "staging the equity hedge for 09:30 cut post-open variance (fragile, known panel)"; "on the original 380 closures the PM move lined up with the gap (exploratory, did not replicate)".
- "Options under-price the event" or "an arbitrage at the open". R3 is NULL after costs (+0.79 pt [-1.21, +2.78]); the options were better calibrated than the PM (Brier 0.120 vs 0.146).
- "The expected-gap model works" without "on the recession market". The election market is 52.4% and the replication panel 50.2%; 0 of 10 new markets pass.
- "The staged hedge reduces the gap" or "protects you overnight". Hedge B changes post-open risk, not the gap; it is fragile (VRS -0.78% after dropping 5 closures) and on an already-seen panel.
- "The prediction-market contract hedge protects the position". R1 found no evidence, and it increased variance on the replication panel.
- "The prediction market beats futures" or "the only live price overnight". SPY trades pre-market and futures trade nearly around the clock; we did not observe futures.
- "A pre-registered finding", "confirmed" or "replicated" for the 380-closure relation. It is a re-reading, and the replication failed (+0.63, p = 0.126).
- "Six tests, two passed" without saying the two passes are on the already-seen panel and the four on new data failed or were NULL.
- "News nights carry the signal" (interaction t +0.23, pairing placebo p = 0.075) or "it works on both markets" (election 31 of 66, p = 0.712).
- "The signal works" on the strength of the TLT demo market. It was picked for its in-sample score (4th of 122) and scored -0.245 on its own walk-forward test.
- "The AI fit predicts returns", "the fit works out of sample", "the signal works on 86 markets", or any headline fit score other than the demo market's, stated as in-sample.
- The raw variance reduction (median 0.339) as the hedge's edge. Any static short earns it.
- "The scan found arbitrage" or "free money". 5 verified, 0 executable.
- "The 8-K signal works". NULL in-sample and out of sample; with 3 and 8 events, not proof of no effect either.
- "27 nanoseconds end to end". That is `on_tick` on a synthetic tape, not network or Python. Do not quote a range for the bridge screen's latency; read it off the screen.
- "1,284 algorithms" or "1,278 presets". The library reports 1,386 presets in 17 families.
- "Real orders" or a real broker. Simulated account (Webull paper when keyed).
- "PolyBridge saved $2,594" as a result, or "the staged order made money". One recorded weekend; the staged order alone lost $1,607.
- "Webull filled the weekend order". The weekend replay fills in the simulator; the Webull sandbox takes no orders outside 09:30-16:00 ET.

## 6. If asked

- **Why is a null valid?** The rules were written before the data; a failed pre-registered test bounds the effect and prevents a false claim. Samples are small (8-K: 23 to 36 events per family in-sample, 3 and 8 out of sample), so a null is not proof of no effect.
- **You lead with passes; what failed?** All four tests on new data: replication, fit walk-forward, 8-K out of sample, and R3's pass/fail test (net residual gap). The two passes, R2 and R1 hedge B, are pre-registered re-analyses of the already-seen 380-closure panel; R2 fails on the replication panel and hedge B is fragile (`research/EVIDENCE.md`, six-test table).
- **If options only reflect 0.44 of the move, why not trade it?** After half the bid/ask band and commissions the residual is +0.79 pt [-1.21, +2.78]; after 09:45 the options do not keep moving toward the PM (-0.59 pt), the PM gives back part of its move (-3.48 pt), and a round trip toward the PM loses -22.83 pt. The source reads the before-cost gap as PM overshoot or noise as much as slow options (`research/results/open_options/SUMMARY.md`).
- **Why does the staged hedge help if it cannot touch the gap?** Timing: it is active after an adverse expected gap (69 closures), and the first 30 minutes after those closures were more volatile (sd 36.5 bp vs 24.8 bp); hedge size did not predict direction (correlation +0.00). Treat it as support for staging an order at the first tradable moment, not protection against the gap (`research/results/closed_hedge/SUMMARY.md`).
- **What does the fit score mean?** Plain variance reduction rewards any static short: a fixed short of a fraction h of the shares scores 1 - (1 - h)^2 with no signal. The fit ranks on the variance cut beyond a static hedge of the same average size; 0 is no better than static. Over 122 scored markets: median 0.0053, 36 at or below 0, 14 above 0.1. Out of sample the picked preset does not beat a static hedge (median -0.0040, Wilcoxon p = 1.000). It is configuration, not edge.
- **Could the replay book a stale price?** Not in the fit: with no live quote, an equity fill is rejected outside the US regular session and until the price has changed inside it (`engine/hedgecore/include/hedgecore/replay.hpp`).
- **Isn't your 380-closure result just a placebo arm?** Yes, and we say so. The pre-registered question was whether news closures are special; the answer was mixed. The 380 unselected closures carried the relation (+7.52, permutation p = 0.001), so we pre-registered a replication on 10 new markets: it did not replicate (+0.63, p = 0.126). The rule picked mostly geopolitical markets; the 2 US macro/policy markets in it were null too (p = 0.539).
- **What about futures?** We did not observe futures, so we make no claim that the prediction market beats them. 305 of the 380 closures are overnight, when futures trade.
- **Are the lead-lag events cherry-picked?** The 13 curated events were chosen from memory; the 15 scheduled FOMC statements are the unselected part and are reported separately (`research/results/leadlag/SUMMARY.md`, Caveats).
- **Why does the bridge screen show a bigger latency than 27 to 35 ns?** Both time the decision itself: the bridge shows the `step()` stamp, the same one as the benchmark's decision-logic figure (4.2 to 22.9 ns; 27 to 35 ns is `on_tick` with its own clock reads). The benchmark runs a million ticks in a hot loop; the bridge decides one tick at a time inside Python, with cold caches, and the clock tick is about 42 ns. No result file records the bridge values; read them off the screen (`engine/hedgecore/BENCH.md`).
- **Why did the staged order lose money on the demo weekend?** It sold at 488.45 in Monday's pre-market and SPY was 495.69 at 10:00: -$1,607. Hedge B works by timing, not direction, and executes after the gap, so it cannot recover it. The weekend total (+$2,594 vs no hedge) includes the hedge carried from Friday afternoon (+$3,022) and the algo after the open (+$1,179) (`backend/replays/README.md`).
- **Why the simulator and not Webull?** The Webull paper sandbox accepts orders only from 09:30 to 16:00 ET (HTTP 417 outside). A replay always fills in its own sandbox simulator; with Webull, a staged order executes at Monday's 09:30 open.
