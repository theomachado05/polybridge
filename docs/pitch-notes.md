# PolyBridge pitch notes (findings talk track and demo cues)

Companion to `docs/demo.md` (same 5-minute shape: findings 3 min, live demo 90 s, ask 30 s). Every research claim is backed by `research/EVIDENCE.md`; product and demo claims come from `docs/demo.md` sections 2, 5 and 6; every number is copied from the source file in brackets. If a number is not in EVIDENCE.md, do not say it. Six pre-registered tests ran today; the four on new data failed or were NULL, and the two passes are on an already-seen panel. Say each finding with its scope in the same breath.

## 1. Findings talk track (3:00)

Order: principle, the three findings that cleared a test (each with its scope), the 380-closure relation (exploratory, not replicated), the six-test scoreboard, what didn't work, what the product does with it. Speak the bold words, skip the brackets.

**0:00 to 0:20, the principle.**
"**Stocks close. Prediction markets don't.** So a prediction market might tell a stock holder something while the stock can't trade. Our rule: **PolyBridge validates each market's signal out of sample before it lets that signal touch a position.** Most markets fail, and the product says so: every signal is labelled validated or unvalidated estimate."

**0:20 to 0:50, options at the open.**
"First finding, on fresh data, pre-registered. Over **1,535 events and 44 weekend and holiday closures**, at the Monday open options had repriced by only **0.44 of the prediction market's closure move**, confidence interval 0.33 to 0.57. But after option costs the leftover gap is **plus 0.79 points, interval minus 1.21 to plus 2.78**: not different from zero. So it is information, **not an arbitrage**, and the options were actually better calibrated." [`research/results/open_options/SUMMARY.md`]

**0:50 to 1:15, the expected gap.**
"Second. On the **US-recession market**, our expected-gap model held out of sample in time: fitted only on earlier closures, it got the sign of the SPY open right **64.2 percent** of the time, slope 1.28. Pooled, **141 of 235, p equals 0.003**. Scope: **one market**. The election market was 52 percent, and on 10 new markets it failed, **50.2 percent**." [`research/results/gap_model/SUMMARY.md`]

**1:15 to 1:40, staged hedge.**
"Third. Staging the equity hedge for the first tradable moment, 09:30, cut post-open variance **11.4 percent** against no hedge and **6.8 percent** against a same-size static hedge. It is **fragile**: drop five closures and the edge over static goes away. It works by timing, not direction, and it re-uses a panel we had already seen." [`research/results/closed_hedge/SUMMARY.md`]

**1:40 to 2:00, where it started.**
"All this came from an exploratory result: over 380 closures the prediction-market move lined up with the SPY gap, **7.5 basis points per point, p equals 0.001**, and **it did not replicate** on 10 rule-selected new markets: **0.63, p equals 0.126**. Same-window co-movement; we did not test it against futures." [`research/results/leadlag_closed/SUMMARY.md`; `research/results/leadlag_replication/SUMMARY.md`]

**2:00 to 2:20, the scoreboard.**
"Six pre-registered tests today, rules committed before the data. **Replication: failed. AI fit walk-forward: failed**, median minus 0.004, 19 markets better, 72 worse. **8-K out of sample: null**, 3 and 8 events. **Options at the open: null after costs.** The two passes, the expected gap and the staged hedge, are on the known panel, with the scope I gave." [`research/EVIDENCE.md`, "Six pre-registered tests run today"]

**2:20 to 2:35, what didn't work.**
"Also null: 8-K in-sample; market hours, **9 prediction-market-first, 9 equity-first, 2 tied, p equals 1.0**; the arbitrage scan, **5 verified, 0 executable**; and holding the prediction-market contract itself over a closure showed no evidence of reducing the gap." [`research/EVIDENCE.md`, "What didn't work"]

**2:35 to 3:00, what the product does with it.**
"So the product follows the evidence. Closed-market mode **defaults to staged equity orders**. The prediction-market contract hedge is **opt-in, labelled an estimate**. Options at the open is **research only**. And the AI fit is **configuration, not edge**: it picks from a compiled C++ library of **17 families, 1,386 presets**, and nothing trades until you approve. Let me show you." [`research/EVIDENCE.md`, "Product implications"; `engine/hedgecore/manifest.json`]

Time check: about 450 spoken words, about 2.5 minutes at 180 words per minute, which leaves room for pauses inside the 3:00. If long, cut in this order: "the options were better calibrated", the slope 1.28, the 7.5 basis points figure (keep "did not replicate" and 0.63). Never cut a scope clause, the word "fragile", "one market", "not an arbitrage" or "did not replicate".

## 2. Demo cues (90 s)

Same click path and times as `docs/demo.md` section 2 (servers up, http://localhost:3000, default replay is the recorded "Another Fed rate hike in 2026?" market, hedging TLT, about 67 s). Read live values (price, volume, preset, score, latency) off the screen rather than from notes: they change. The numbers these notes carry for this market are the precomputed fit (+0.257, `backend/app/data/fits.json`) and its own walk-forward row (test -0.245, `research/results/fit_oos/per_market.csv`).

| Time | Screen | Click | Say (only supported claims) |
|---|---|---|---|
| 0:00 | Landing | "Build a bridge" | "You hold a stock. A prediction market puts a live probability on an event that moves it. PolyBridge reads it and hedges the stock, only after you approve." |
| 0:05 | Build chat | Click the first row, "Another Fed rate hike in 2026?" (tagged "demo market"; or type `fed rate hike 2026`) | "Live Polymarket market. Search covers Polymarket and Kalshi; offline it falls back to a bundled list and says so." |
| 0:15 | Build chat | Pick **TLT** (1,000 shares held) | "A hike pushes bond prices down. This stock mapping is an AI estimate, labelled as one. It is not a measurement." Note: the chat names XHB as the biggest mover (-3.0 percent); pick TLT because it is the stock you hold (it lists first). |
| 0:22 | Build chat | Pick "a dynamic short hedge" | "The AI is fitting an algorithm now." On the **AI fit card** (expect equity_delta_bridge #75, score 0.257): "In-sample, on this market the hedge leaves about a quarter less variance than a fixed short of the same average size. It is the best of many presets on the same history, and we picked this market because it scores near the top, 4th of 122; the median is half a percent. It is configuration, not edge: on this market's own walk-forward test the picked preset scored **-0.245** on unseen data, and across 122 markets the picks did not beat a static hedge (median -0.0040). [`backend/app/data/fits.json`; `research/results/fit_oos/per_market.csv`; EVIDENCE.md section 6]" If the card reads differently, say what it reads. |
| 0:35 | Connect | "Connect brokerage", then "Run the AI pipeline" | "Orders go to the simulated account; Webull paper takes over when its keys are set. Real money is out of scope." Point at the "Simulated account" tag. |
| 0:42 | AI pipeline | Wait for "Approve the TLT bridge?" | "Classify, shortlist from the library, load real price history, tune presets on replay, explain, ready. Nothing runs until I approve." |
| 0:52 | AI pipeline | "Approve and open the bridge" | "The proposal is pinned to this exact algorithm and capped at the coverage I approved; the backend refuses to run anything else." |
| 0:55 | Bridge live | Watch ~25 s (first fill within seconds) | "A compiled C++ algorithm reads the replayed ticks. REPLAY badge: recorded, not live. Gates show why it acts or waits; most ticks are holds and a handful are rebalances; each trade says why. Coverage climbs toward my cap, never past it." |
| 1:20 | Library | Nav "Library" | "1,386 presets across 17 families (read the total off the screen). The AI only picks from what is compiled. The running preset is marked." |
| 1:28 | Portfolio | Nav "Portfolio" | "Holdings, exposure by event, hedge status." (A replay bridge trades in a sandbox, so Recent fills stays empty here by design; the Bridge trade log shows the fills. Do not claim account fills.) |

Close on the Bridge or Library screen. Replay fills are priced at today's market, not at the replayed time, and the trade log says so. Fallbacks (Wi-Fi, Gemini, Webull, Massive, backend) are in `docs/demo.md` section 4; do not claim a hedge was built if the broker refused orders.

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
| 8-K out of sample (frozen `344de99`, tag `method-freeze`): H1 NULL (3 events, untestable); H2 NULL (edge -0.0215 [-0.0759, +0.0203] at 21 sessions, -0.0138 [-0.0729, +0.0260] at 42; opposite sign to in-sample) | `research/results/oos/SUMMARY.md`, `research/results/RUN_LOG.md` row 8 |
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
- "The signal works" on the strength of the demo market. It was picked for its in-sample score (4th of 122) and scored -0.245 on its own walk-forward test.
- "The AI fit predicts returns", "the fit works out of sample", "the signal works on 86 markets", or any headline fit score other than the demo market's, stated as in-sample.
- The raw variance reduction (median 0.339) as the hedge's edge. Any static short earns it.
- "The scan found arbitrage" or "free money". 5 verified, 0 executable.
- "The 8-K signal works". NULL in-sample and out of sample; with 3 and 8 events, not proof of no effect either.
- "27 nanoseconds end to end". That is `on_tick` on a synthetic tape, not network or Python. Do not quote a range for the bridge screen's latency; read it off the screen.
- "1,284 algorithms" or "1,278 presets". The library reports 1,386 presets in 17 families.
- "Real orders" or a real broker. Simulated account (Webull paper when keyed).

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
