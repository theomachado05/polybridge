# PolyBridge

**Tagline:** Stocks close, prediction markets don't. PolyBridge turns live Polymarket and Kalshi prices into stock hedges you approve, run by a compiled C++ library of 1,386 presets. Each market's signal must pass an out-of-sample test before it touches a position; most fail, and the app says so.

> **For judges**
> - **Run it offline:** `cp .env.example .env`, then `cd backend && uv sync --locked --group engine && cd .. && make setup-web && make setup-research && make dev`. Open http://localhost:3000 (not 127.0.0.1). It replays about 17 days of real Polymarket history for "Another Fed rate hike in 2026?", hedging TLT. Every key is optional.
> - **Verify:** `make test` runs every lane (research, backend, C++ ctest, engine bindings, web). `make e2e` drives the full flow over HTTP, clicks the real UI in headless Chrome and saves 8 screenshots.
> - **Read the evidence first:** `research/EVIDENCE.md`. Rules were written before the data (`research/HYPOTHESIS.md`). Accounts are simulated or Webull paper only; fills are simulated.

## Inspiration
Prediction markets put a live price on event risk: a Fed decision, a tariff, an election. Our thesis was that this price might reach a hedger before the stock reprices. A hedger has no good way to turn that price into a position, so we built that bridge. We also decided to test the thesis with the rules written down before the data, and to report whatever came back.

## What it does
PolyBridge has two divisions on one signal stack (prediction-market price, delta, implied probability, order books, the Polymarket-Kalshi gap, the 8-K signal).

- **Hedge:** systematic stock hedging driven by Polymarket and Kalshi prices. You pick a market and a position; the AI fit proposes an algorithm and preset; you approve; a bridge runs it on a simulated or Webull paper account. Nothing starts without your approval.
- **Opportunity:** options versus prediction-market probability, plus an 8-K signal. It proposes an options trade on the same threshold. The demo shows the mechanism, not an edge: on the NVDA replay the preset scores -0.956 in-sample, and we show that negative score on screen.

## How we built it
- **C++20 library (`hedgecore`):** 17 families, 1,386 presets, built from 37 reusable header-only blocks. A decision takes 27.1 to 34.6 ns per `on_tick` on a synthetic 1,000,000-tick tape (Apple M5) across the first 16 families, including its own timing stamp (`closed_session_hedge`, the 17th, measured 29.7 ns in a second run). Decision logic alone averages 4.2 to 22.9 ns. Scoring the first 16 families' 1,278 presets over 20,000 ticks takes 1.68 s on one thread (`closed_session_hedge` was timed separately in a slower second run). This is `on_tick` only, not end-to-end latency.
- **AI fit pipeline:** classify the market (Gemini, with a keyword-rules fallback), shortlist families, build ticks from real price history aligned to Massive bars, run `replay_grid`, pick the best preset. Hedge presets are ranked by the variance cut beyond a static hedge of the same average size, which is what the signal adds. Raw variance reduction is shown but never ranked, because any static short earns it. The AI never writes trading code; it only picks from the compiled catalog.
- **FastAPI** control plane (markets, mapping, proposals, bridges over SSE, broker, portfolio) and a **Next.js** UI (Build chat, AI pipeline, Bridge live, Library, Portfolio, Connect, Profile).
- **Accounts:** a deterministic SimBroker ($1,000,000 start) and a Webull paper-trading client with the same interface. The Webull client talks only to the sandbox host and refuses any other.
- **ElevenLabs voice agent** whose tools call our API (search, fit, propose, approve, start a bridge). **Massive** supplies equity quotes and bars, options chains and research data.
- Missing keys mean a graceful fallback, never a crash.

## Challenges
- Our first fit score rewarded hedge size, not signal: a fixed short of a fraction h of the shares scores 1 - (1 - h)^2 even when the prediction market never moves. We re-ranked on the gain over a static hedge and discarded the earlier numbers.
- A timezone bug in the options scan produced one "verified" gap. We fixed it, documented the correction in the report, and the count dropped.
- Keeping every label honest: replay vs live, simulated vs Webull paper, estimate vs measured, case study vs proof.

## Accomplishments
- A tested C++ library (GoogleTest per block and per family) that the AI can only pick from.
- A fit pipeline that ran end to end over 133 real markets (120 Polymarket, 13 Kalshi): 122 scored, 11 unsupported.
- Nine studies, all reported: four earlier pre-registered studies plus six pre-registered tests run today (replication, fit walk-forward, 8-K out of sample, closed-market hedge R1, expected-gap model R2, options at the open R3). The four on new data failed or were NULL; the two passes are on an already-seen panel and are reported with their scope.
- A full approve-then-bridge flow, checked over HTTP and in headless Chrome.

## What we learned
**Stocks close, prediction markets don't.** Our principle: PolyBridge validates each market's signal out of sample before it lets that signal touch a position. Most markets fail, and the product says so: every signal is labelled "validated" or "unvalidated estimate". The findings that cleared a test, each with its scope:

- **Options at the open (fresh data, pre-registered R3).** At the Monday open, options had repriced by only 0.44 of the prediction market's closure move (95% CI 0.33 to 0.57; 1,535 events over 44 weekend and holiday closures). Scope: after option costs the residual gap is +0.79 pt [-1.21, +2.78], so R3's verdict is NULL: information, not a tradable arbitrage. The options were also better calibrated than the PM (Brier 0.120 vs 0.146).
- **Expected gap on the US-recession market (R2).** Walk-forward in time inside the panel, the model got the SPY gap's sign right in 64.2% of 151 closures (slope +1.28); pooled over both panel markets 141 of 235 (60.0%, p = 0.003), slope +1.25, permutation p < 0.001. Scope: one market. The election market is 52.4% (p = 0.744), and on the 10-market replication panel it fails (50.2% of 878, slope -0.23). R2 re-analyses an already-seen panel.
- **Staged equity hedge at 09:30 (R1 hedge B).** It cut post-open variance by +11.42% [+5.10, +18.14] against no hedge and +6.82% [+0.50, +13.54] against a static hedge of the same size. Scope: fragile (only partial under a block bootstrap; the gain over static is -0.78% after dropping 5 closures), it works by timing not direction, it does not touch the gap, and it re-uses the already-seen 380-closure panel.
- **The 380-closure relation is exploratory.** Over 380 unselected closures in two markets, the prediction-market move lined up with the next SPY opening gap (+7.52 bp per pp, permutation p = 0.001), and it did not replicate on 10 rule-selected new markets (+0.63, p = 0.126). It was the placebo arm of a pre-registered study whose verdict was "mixed", it is same-window co-movement, and we did not compare it with futures.

**Six pre-registered tests run today** (each method committed before its run; full table in `research/EVIDENCE.md`):

| Test | Verdict | Key numbers |
|---|---|---|
| Replication on 10 new markets (method `7a780b5`) | does not replicate | +0.63 bp per pp, HC3 t +1.20, permutation p = 0.126 |
| AI fit walk-forward on 122 markets (`e2f1600`) | fails | median test vs_static -0.0040; 19 above 0, 72 below; Wilcoxon p = 1.000 |
| 8-K out of sample, 2026-01 to 2026-08 (`344de99`) | H1 NULL (3 events, untestable); H2 NULL, sign opposite to in-sample | H2 edge -0.0215 [-0.0759, +0.0203] at 21 sessions, -0.0138 [-0.0729, +0.0260] at 42 |
| R1 closed-market hedge (`c9fc174`) | A: no evidence (increases variance on the replication panel); B at 09:30: passes, fragile | A VR0 +4.76% [-0.80, +10.01]; replication VR0 -3.79% [-8.19, -0.91]; B as above |
| R2 expected-gap model (`fe7c181`) | passes on the panel via the recession market only; fails on the replication panel | as above |
| R3 options at the open (`297727a`) | NULL | net residual +0.79 pt [-1.21, +2.78]; slope 0.44 [0.33, 0.57] |

**What didn't work.** 8-K parity (H1, H2) is NULL in-sample (2024 to 2025; 36 hedge events, 24 opportunity events). Market hours: of 28 usable events, prediction market first 9, equity first 9, simultaneous 2 (sign test p = 1.000). Options arbitrage: 5 verified gaps, 0 executable, each on a single print of 5 to 100 shares. AI fit scores are in-sample only: median 0.0053, 36 of 122 at or below zero, 14 above 0.1. Our demo market (Fed rate hike, TLT) scores +0.257 in-sample and was picked because it is near the top; on its own walk-forward test the picked preset scored -0.245 on unseen data.

**What the product does with it.** Closed-market mode defaults to staged equity orders (hedge B). The prediction-market contract hedge (hedge A) is opt-in and labelled an estimate. Options-at-open is research-only. The AI fit is configuration, not edge: it picks a compiled preset, and nothing trades until you approve. The value is the live read plus execution and risk control (approval gate, coverage cap, fee gate, a tested catalog), not proven alpha.

## What's next
Test the staged hedge and the expected gap on a fresh sample of US macro markets, with a futures benchmark. Rework the fit so it is judged out of sample from the start, since today's walk-forward failed. Real fills on Webull paper, and options legs beyond simulation.

## Built with
C++20, pybind11, CMake, GoogleTest, Python 3.12, FastAPI, Next.js, TypeScript, Polymarket API, Kalshi API, Massive (market data), Gemini, ElevenLabs, Webull OpenAPI (paper), uv, pnpm
