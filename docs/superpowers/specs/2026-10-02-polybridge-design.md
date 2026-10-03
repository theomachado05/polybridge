# PolyBridge — Design Spec (v3, research-first)

**Date:** 2026-10-02 · **Event:** GatorQuant Hacks 2026 · Systematic Trading track + Massive bonus
**Deadline:** Devpost Sunday 2026-10-04 10:00 ET (quant note PDF + public repo) · pitch 13:00–15:00
**Supersedes:** v2 (live-demo-first). The pivot reason: the track scores research evidence, not live P&L.
**Companion docs:** `research/HYPOTHESIS.md`, `research/HYPOTHESIS_TAGS.md`, `docs/win-plan.html`, `docs/journey.html`

## 1. Thesis

Markets put a price on events before they resolve. A prediction market prices the probability; an
option chain prices the move. **Prediction–Price Parity** says the gap between the priced move and the
realized move, for a class of events, tells you which side to take:

- **Hedge side:** the event is underpriced, so buy protection.
- **Opportunity side:** the event is overpriced, so sell it.

The evidence is 8-K events × options (Massive). The product, PolyBridge, applies the same rule to any
event a market prices, including prediction markets, through a C++20 hedge algorithm the user approves.

## 2. What is scored, and by whom

| Deliverable | Judged on | Must hold |
|---|---|---|
| Notebook (built on the Massive starter) | Massive 100 pts; main-track evidence criterion | Runs from a clean kernel with only `MASSIVE_API_KEY`; takes start and end dates; judges rerun it on a sealed window |
| Quant note PDF, ≤ 5 pages | Main track (5 criteria × 10); pages 1–2 = Massive write-up | Hypothesis before results; IS and OOS net of costs; Sharpe, max DD, turnover, equity curve; risk; capacity; variants disclosed |
| Public GitHub repo | Backs the evidence score | README with one command; dependency file; no keys or licensed data |
| 5-minute pitch | Communication | 3 min findings, 90 s live demo |

Score caps we design out: anything beyond the Massive key needed to reproduce; lookahead; tuning on OOS.

## 3. Architecture

**Python everywhere except the hedge algorithm.**

```
 research/            Python · SCORED
   notebook.ipynb       Massive starter, sections 1–11 kept; H1/H2 event tables, parity decay, atlas
   polybridge_research/ events.py · pricing.py · strategies.py · parity.py · stats.py (bootstrap, BH, DSR)
   HYPOTHESIS*.md       pre-registration (committed before data)

 overlay/             Python · SCORED (main track)
   Webull backtrader kit + PolyBridgeOverlay strategy: top-100 book hedged by the H1/H2 rules
   (fallback: cited public daily source until the Webull key arrives)

 backend/             Python · FastAPI · DEMO
   events/   live 8-K (EDGAR) + Polymarket/Kalshi watchers → Event(ticker, t0, category, source, priced_move)
   signal/   parity classification using the research results (side: hedge | opportunity | none)
   approve/  hedge proposals queue; nothing executes until the user approves in the UI
   broker/   Webull paperTrade adapter (later, when the key arrives)
   bridge/   runs the approved hedge through hedgecore; streams telemetry to web

 engine/hedgecore/    C++20 · the systematic hedge algorithm · pybind11 module
   one job: given an approved hedge and live ticks, decide size and timing, tick by tick
   DeltaBridge sizing · parity-gap signal · band · slicer · tax-lot · risk limits
   no allocation in the loop, std::variant stages, latency measured per decision

 web/                 Next.js · DEMO
   Build: event → stock → ranked hedge (from research) → APPROVE → Bridge (live, hedgecore)
```

Rules:

- **The scored paths (`research/`, `overlay/`) never import `hedgecore` or call Claude.** Judges need
  only the Massive key, and a C++ build failure can't cap the evidence score.
- **hedgecore runs only after a user approval.** The backend proposes; the human approves; the C++
  algorithm executes the approved hedge. That keeps a person in the loop, which matters for any real
  deployment.
- **One `Event` schema** feeds both sources (8-K and prediction markets), so the demo shows the same
  rule the research tested.

## 4. Research design (pre-registered)

Fixed in `research/HYPOTHESIS.md` and `HYPOTHESIS_TAGS.md`:

- **H1, hedge side:** 7 tags (litigation, class action, regulatory investigation, cybersecurity incident,
  goodwill / asset / investment impairment) → protective put. The prediction is R above the placebo's.
- **H2, opportunity side:** 4 tags (restructuring plan, workforce reduction, facility closure, business-line
  exit) → cash-secured put. The prediction is R below the placebo's.
- **Spec:** top 100; 3–6m expiry; put 5% OTM; post-filing entry with the EDGAR after-hours fix; all
  8 horizons + expiry reported; headline 21 / 42 / expiry; costs 5% of premium per side, and 2×.
- **Pass rule:** a 97.5% bootstrap CI on event-minus-placebo excludes zero in the predicted direction at
  2 or more headline horizons, and R moves in the predicted direction. Otherwise we report a null.
- **Atlas (exploratory):** all 119 tags × 5 strategies × grid, with BH q-values and the deflated Sharpe.
  Never a headline.
- **OOS:** run once, after the method freeze.

## 5. Overlay backtest (main-track Results section)

An equal-weight top-100 book on daily bars. On an H1 event in a holding, buy the protective put; on an
H2 event, sell the cash-secured put from a cash sleeve. The option legs come from Massive bars and the
stock from Webull. It is compared with the unhedged book and with random-day hedging, using walk-forward
folds with a purge gap. The locked final period is the shorter of 20% or 2 years. Reported: annualized
return, volatility, Sharpe, max DD, worst month, skew, turnover and the equity curve, at 1× and 2× costs.
Capacity comes from % of ADV and option leg volume.

## 6. hedgecore (C++20)

- `HedgeSpec` (approved by the user): event, ticker, shares, lots, side, strategy, target coverage, limits.
- `Tick` in → `Decision` out (hold | order {qty, side, limit}) with a reason record.
- Stages are `std::variant`s: Gate (σ-gate, staleness) → Signal (parity gap) → Size (DeltaBridge,
  `dV/dp = −N·J`) → Band → Slice → TaxLot → Risk.
- pybind11 binding `hedgecore.Engine(spec).on_tick(tick) -> Decision`; GoogleTest unit tests; latency p50/p99.
- Optional and not in the scored path. If it fails to build, the demo replays a recorded session.

## 7. Repo layout and run commands

```
research/   requirements.txt · notebook.ipynb · polybridge_research/ · HYPOTHESIS*.md · starter/ (as shipped)
overlay/    Webull kit + strategies/polybridge_overlay.py
backend/    FastAPI app (pyproject)
engine/     hedgecore (CMake + pybind11)
web/        Next.js
note/       quant note source → note.pdf
docs/       spec, system map, win plan, journey
```

- Reproduce (judges): `cd research && pip install -r requirements.txt && jupyter nbconvert --execute notebook.ipynb`
- Secrets: `.env` holds `MASSIVE_API_KEY` (and later `WEBULL_APP_KEY` / `WEBULL_APP_SECRET`). It is
  gitignored, and so are `.massive_cache/` and raw API dumps.

## 8. Testing

- research: pytest on strategy P&L (hand-computed cases), the bootstrap, the parity ratio, the tag filter and
  the cross-family exclusion; a clean-kernel run before submission.
- overlay: deterministic run on a fixed window; numbers must match the note.
- hedgecore: GoogleTest per stage; replay test (fixed ticks → fixed decisions); latency benchmark.
- backend/web: smoke test of the approve → bridge flow.

## 9. Out of scope

Real-money execution, auth, options execution inside hedgecore, mobile apps, and any result not covered
by the pre-registration presented as confirmatory.
