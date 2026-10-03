# PolyBridge

**Tagline:** Hedge your stocks with live Polymarket and Kalshi prices, through a compiled C++ library of 1,278 presets, with a human approving every trade and an honest account of what the data did and did not show.

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
- **C++20 library (`hedgecore`):** 16 families, 1,278 presets, built from 37 reusable header-only blocks. A decision takes 27.1 to 34.6 ns per `on_tick` on a synthetic 1,000,000-tick tape (Apple M5), including its own timing stamp. Decision logic alone averages 4.2 to 22.9 ns. Scoring all 1,278 presets over 20,000 ticks takes 1.68 s on one thread. This is `on_tick` only, not end-to-end latency.
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
- Four pre-registered studies, reported including the ones that failed.
- A full approve-then-bridge flow, checked over HTTP and in headless Chrome.

## What we learned
We report the research as it came out. A well-argued null is a result.
- **8-K parity (H1, H2): NULL in-sample** (2024 to 2025; 36 hedge events, 24 opportunity events). No confidence interval excludes zero at any headline horizon. The out-of-sample window (2026-01 to 2026-08) is sealed and has not been run yet; [fill in after the single run, whatever it shows].
- **Market hours: no prediction-market lead.** Of 28 usable events, 20 had both series move: prediction market first 9, equity first 9, simultaneous 2; sign test p = 1.000. The pooled tests lean the other way.
- **Closed markets: mixed.** Across 17 news closures the prediction-market move and the SPY opening gap move together (slope +10.43 bp per pp, permutation p = 0.005). But 380 placebo closures show the same relation, and the timing test is null. That is co-movement, not a head start.
- **Options arbitrage: 5 resolved gaps, 0 executable.** Each rests on a single print of 5 to 100 shares. Nothing was traded.
- **AI fit scores are in-sample, best-of-many-presets replays.** Median score 0.0053; 36 of 122 are at or below zero and 14 of 122 are above 0.1. On our demo market (Fed rate hike, TLT) the score is +0.257 in-sample, and we picked it because it scores near the top. It is not a forecast.

So the product's value is execution and risk control (approval gate, coverage cap, fee gate, a tested catalog), not alpha.

## What's next
Run the sealed 8-K out-of-sample test once and report the result. Pre-register a closed-market test with intra-closure timing. Add an out-of-sample test of the fits, real fills on Webull paper, and options legs beyond simulation.

## Built with
C++20, pybind11, CMake, GoogleTest, Python 3.12, FastAPI, Next.js, TypeScript, Polymarket API, Kalshi API, Massive (market data), Gemini, ElevenLabs, Webull OpenAPI (paper), uv, pnpm
