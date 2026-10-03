# PolyBridge pitch notes (findings talk track and demo cues)

Companion to `docs/demo.md` (same 5-minute shape: findings 3 min, live demo 90 s, ask 30 s). Every research claim is backed by `research/EVIDENCE.md`; product and demo claims come from `docs/demo.md` sections 2, 5 and 6; every number is copied from the source file in brackets. If a number is not in EVIDENCE.md, do not say it. Read the out-of-sample line aloud only if the run has happened.

## 1. Findings talk track (3:00)

Say it plainly; a null is a result. Speak the bold words, skip the brackets.

**0:00 to 0:20, the thesis and the stance.**
"Our thesis is that prediction markets put a live price on event risk, and that might give a hedger a head start. We tested that honestly, with the rules written down before the data. Short version: we did not find a head start. What we found is that the prediction-market price is a live public read of event risk, so we built the execution and risk control around it."

**0:20 to 0:55, the pre-registered 8-K study.**
"First study: after an 8-K filing, do options misprice what comes next? We froze two hypotheses before fetching any event data. In-sample, 2024 to 2025, 36 hedge events and 24 opportunity events: both are **null**. No confidence interval excludes zero at any headline horizon. [`research/results/in_sample/SUMMARY.md`, `hedge_verdict.txt`, `opportunity_verdict.txt`] The out-of-sample window is run once after the freeze, and we report whatever it shows: **<fill in after the single post-freeze run, whatever it returns; if it has not run, say "frozen, run once, not yet run">**. The exploratory atlas counted 96,390 variants, so no single hit in it counts as a finding. [`research/results/atlas/README.md`]"

**0:55 to 1:35, lead-lag in market hours.**
"Second: in stress events, does the prediction market move before the equity? 28 usable events, 20 where both moved. Prediction market first in 9, equity first in 9, simultaneous in 2. The sign test says p equals 1.0. The pooled test points the other way: equity to prediction market is significant, the reverse is not, though weakly; the robust versions are not significant. So we **do not claim the markets move first**. [`research/results/leadlag/SUMMARY.md`] And the answer is sensitive to how you define the first move: with a looser or a stricter threshold, equities lead more often. We kept the counts either way."

**1:35 to 2:05, when equities are closed.**
"Third: when news breaks at night or on a weekend, does the prediction-market move line up with the next morning's SPY gap? Across 17 news closures the two are positively related: slope plus 10.43 basis points of gap per point of prediction-market change, permutation p equals 0.005. [`research/results/leadlag_closed/SUMMARY.md`] But the same relation shows up in 380 closures with no flagged news, news closures show no extra response, and the move before 8 a.m. does not predict the rest of the gap. So the verdict is **mixed**: it is co-movement, a live public read of event risk while equities are shut, not a proven lead."

**2:05 to 2:25, options arbitrage.**
"Fourth: does the prediction market disagree with option prices by more than costs? We scanned thousands of thresholds. After costs and a trade-print check, **5 gaps survive and 0 are executable**: each rests on a single print of 5 to 100 shares, too small to hedge with one option contract. Nothing was traded. [`research/results/arb/SUMMARY.md`] We also corrected an earlier version of that report that had overstated it, and the correction is in the file."

**2:25 to 3:00, so what we built.**
"So the value is not alpha. It is execution and risk control. A prediction-market price is a live public read on event risk. PolyBridge turns it into a hedge you approve, sized to your position, with every decision explained and every limit enforced. The hedging brain is a compiled C++ library: **16 families, 1,278 presets**. [`docs/library.md`] A decision takes **27.1 to 34.6 nanoseconds** on our benchmark, including its own timing stamp. [`engine/hedgecore/BENCH.md`] The AI never writes trading code; it only picks and tunes from that tested catalog. Its fit score is what the prediction-market signal adds beyond a plain fixed hedge of the same size, measured on the same history it was tuned on: in-sample, and small on most markets. Let me show you."

Time check: about 540 spoken words including the stage directions' quoted text, which is 3 minutes only at a brisk pace (about 180 words per minute). The fit-score sentence in the last paragraph was added after that count, so re-time it. Rehearse with a timer; if long, cut the 0:55 sensitivity sentence, the atlas sentence and the correction sentence first.

## 2. Demo cues (90 s)

Same click path and times as `docs/demo.md` section 2 (servers up, http://localhost:3000, default replay is the recorded "Another Fed rate hike in 2026?" market, hedging TLT, about 67 s). Read live values (price, volume, preset, score) off the screen rather than from notes: they change. The one number these notes carry is the precomputed fit for this market (+0.257, `backend/app/data/fits.json`), so you can say it if the card agrees.

| Time | Screen | Click | Say (only supported claims) |
|---|---|---|---|
| 0:00 | Landing | "Build a bridge" | "You hold a stock. A prediction market puts a live probability on an event that moves it. PolyBridge reads it and hedges the stock, only after you approve." |
| 0:05 | Build chat | Click the first row, "Another Fed rate hike in 2026?" (tagged "demo market"; or type `fed rate hike 2026`) | "Live Polymarket market. Search covers Polymarket and Kalshi; offline it falls back to a bundled list and says so." |
| 0:15 | Build chat | Pick **TLT** (1,000 shares held) | "A hike pushes bond prices down. This stock mapping is an AI estimate, labelled as one. It is not a measurement." Note: the chat names XHB as the biggest mover (-3.0 percent); pick TLT because it is the stock you hold (it lists first). |
| 0:22 | Build chat | Pick "a dynamic short hedge" | "The AI is fitting an algorithm now." On the **AI fit card** (expect equity_delta_bridge #75, score 0.257): "On this market the signal adds 25.7 percent over a static hedge in-sample: the hedge leaves about a quarter less variance than a fixed short of the same average size. It is measured on the same history it then replays, it is the best of many presets, and we picked this market because it scores near the top, 4th of 122. Across 122 markets it adds more than 10 percent on 14 and nothing on 36; the median is half a percent. So it is a good case, not a typical one, and not a forecast. [`backend/app/data/fits.json`; EVIDENCE.md section 6]" If the card reads differently, say what it reads. |
| 0:35 | Connect | "Connect brokerage", then "Run the AI pipeline" | "Orders go to the simulated account; Webull paper takes over when its keys are set. Real money is out of scope." Point at the "Simulated account" tag. |
| 0:42 | AI pipeline | Wait for "Approve the TLT bridge?" | "Classify, shortlist from the library, load real price history, tune presets on replay, explain, ready. Nothing runs until I approve." |
| 0:52 | AI pipeline | "Approve and open the bridge" | "The proposal is pinned to this exact algorithm and capped at the coverage I approved; the backend refuses to run anything else." |
| 0:55 | Bridge live | Watch ~25 s (first fill within seconds) | "A compiled C++ algorithm reads the replayed ticks. REPLAY badge: recorded, not live. Gates show why it acts or waits; most ticks are holds and a handful are rebalances; each trade says why. Coverage climbs toward my cap, never past it." |
| 1:20 | Library | Nav "Library" | "1,278 presets across 16 families. The AI only picks from what is compiled. The running preset is marked." |
| 1:28 | Portfolio | Nav "Portfolio" | "Holdings, exposure by event, hedge status." (A replay bridge trades in a sandbox, so Recent fills stays empty here by design; the Bridge trade log shows the fills. Do not claim account fills.) |

Close on the Bridge or Library screen. Replay fills are priced at today's market, not at the replayed time, and the trade log says so. Fallbacks (Wi-Fi, Gemini, Webull, Massive, backend) are in `docs/demo.md` section 4; do not claim a hedge was built if the broker refused orders.

## 3. Ask (30 s)

"We would like feedback on the pre-registration design, access to better prediction-market and options data, or a pilot hedge book. 'No edge found' is a result we can ship honestly, and the hedge tool is useful regardless."

## 4. Claims ledger (what you may say, and where it comes from)

| Claim | Source |
|---|---|
| 8-K H1 and H2 both NULL in-sample; 36 hedge and 24 opportunity events | `research/results/in_sample/SUMMARY.md`, `hedge_verdict.txt`, `opportunity_verdict.txt` |
| Out-of-sample not yet run as of RUN_LOG; runs once after the freeze | `research/results/RUN_LOG.md` (fill in the number after the run) |
| Atlas is exploratory; 96,390 variants counted | `research/results/atlas/README.md` |
| 28 usable lead-lag events; PM first 9, simultaneous 2, equity first 9; sign test p = 1.000 | `research/results/leadlag/SUMMARY.md` |
| Pooled test points the other way (equity to PM significant, PM to equity not), weakly; the HAC-robust versions are not significant (0 of 4) | `research/results/leadlag/SUMMARY.md` |
| Closed-market study mixed: slope +10.43 bp per pp, permutation p = 0.005; same relation in placebo closures; no extra news response | `research/results/leadlag_closed/SUMMARY.md` |
| 5 verified gaps, 0 executable; each on a print of 5 to 100 shares | `research/results/arb/SUMMARY.md` |
| 16 families, 1,278 presets | `docs/library.md`, `engine/hedgecore/manifest.json` |
| `on_tick` batch mean 27.1 to 34.6 ns (synthetic tape, includes its own stamp) | `engine/hedgecore/BENCH.md` |
| Demo market "Another Fed rate hike in 2026?" -> TLT: equity_delta_bridge #75, score_vs_static +0.257 over 401 hourly ticks (raw 0.748 at average hedge ratio 0.42); 4th of 122; same pick and score when refitted offline on `backend/replays/another-fed-hike-2026-history.jsonl` | `backend/app/data/fits.json` (`polymarket:4620900`), `backend/data_logs/precompute_fits.log`, `backend/replays/README.md` |
| AI fit scores are in-sample replays; 133 markets, 122 scored, 11 unsupported (no fit) | `backend/app/data/fits.json`, `backend/data_logs/precompute_fits.log` |
| Fit ranking score = variance cut beyond a static hedge of the same average size (what the signal adds); raw variance reduction rewards any static short and is not ranked | `engine/hedgecore/include/hedgecore/replay.hpp`, `docs/library.md`, `research/EVIDENCE.md` section 6 |
| Fit score distribution over the 122: median 0.0053; 86 above 0 and 36 at or below 0 (all negative); 53 above 0.01, 31 above 0.05, 14 above 0.1, 7 above 0.2; max 0.508, min -0.0596 | `backend/app/data/fits.json` `summary.score_vs_static`, our tally of the entries (`research/EVIDENCE.md` section 6) |
| Median raw variance reduction of the picks 0.339 at a median average hedge ratio of 0.18 (most of it is hedge size) | `backend/app/data/fits.json`, our tally (`research/EVIDENCE.md` section 6) |
| Fit replay fills respect the equity session and a fresh close (no stale-close fills) | `engine/hedgecore/include/hedgecore/replay.hpp`, `engine/hedgecore/src/replay.cpp` |
| Webull is sandbox only (`api.sandbox.webull.com`); other hosts refused, simulator used | `backend/app/broker/webull.py`, `backend/app/broker/__init__.py` |
| Human-approved, capped, simulated account; real money out of scope | `docs/demo.md` section 5 |

## 5. Do not say

- "Prediction markets lead equities" or "a head start". Market-hours lead-lag found none; the closed-market study is mixed and shows co-movement.
- "The signal works" on the strength of the demo market. It was picked because its fit scores near the top (4th of 122); say "on this market, in-sample", and give the 14-of-122 and 36-of-122 counts with it.
- "The AI fit predicts returns", "the signal works on 86 markets", or any headline fit score other than the demo market's, stated as in-sample. Scores are in-sample, best-of-many-presets replays; the median is 0.0053 and only 14 of 122 are above 0.1 (EVIDENCE.md section 6).
- The raw variance reduction (median 0.339) as the hedge's edge. Any static short earns it; the ranking score is what the signal adds beyond that.
- "The scan found arbitrage" or "free money". 5 verified, 0 executable.
- "The 8-K signal works", or any out-of-sample claim before the run. In-sample is null.
- "27 nanoseconds end to end". That is `on_tick` on a synthetic tape, not network or Python.
- "1,284 algorithms". The library reports 1,278 presets.
- "Real orders" or a real broker. Simulated account (Webull paper when keyed).

## 6. If asked

- **Why is a null valid?** The rules were written before the data; a failed pre-registered test bounds the effect and prevents a false claim (`docs/demo.md` Q&A). In-sample samples are 23 to 36 events per family, so the CIs are wide: a null here is not proof of no effect.
- **What does the fit score mean, and why did it change?** Plain variance reduction rewards any static short: a fixed short of a fraction h of the shares scores 1 - (1 - h)^2 with no signal at all. The fit now ranks on the variance cut beyond a static hedge of the same average size, which is what the PM signal adds; 0 is no better than static and negative is worse. Over the 133 precomputed markets, 122 are scored: median 0.0053, 36 at or below 0 (all negative), 53 above 0.01, 14 above 0.1. Each is the best of many presets on the history it is scored on, so values of a few thousandths are noise; the signal adds a material amount on roughly 14 to 31 markets at most (`research/EVIDENCE.md` section 6). Do not describe it as returns or out-of-sample.
- **Could the replay book a stale price?** Not in the fit: with no live quote, an equity fill in the engine's replay is rejected outside the US regular session and until the price has changed inside it, so the opening gap is not booked as hedge P&L (`engine/hedgecore/include/hedgecore/replay.hpp`).
- **Why not trade the closed-market relation?** It appears in closures with no flagged news too, news closures show no extra response, and the timing test is null; an intra-closure timing design was not tested (`research/results/leadlag_closed/SUMMARY.md`, Caveats).
- **Are the lead-lag events cherry-picked?** The 13 curated events were chosen from memory; the 15 scheduled FOMC statements are the unselected part and are reported separately (`research/results/leadlag/SUMMARY.md`, Caveats).
- **Why does the bridge screen show hundreds of nanoseconds to microseconds when you said 27 to 35 ns?** Both time the decision itself: the bridge shows the `step()` stamp, the same one as the benchmark's decision-logic figure (4.2 to 22.9 ns; 27 to 35 ns is `on_tick` with its own clock reads). The benchmark runs a million ticks in a hot loop; the bridge decides one tick at a time inside Python, with cold caches, and the clock tick is about 42 ns (`engine/hedgecore/BENCH.md`; `docs/demo.md` section 5).
