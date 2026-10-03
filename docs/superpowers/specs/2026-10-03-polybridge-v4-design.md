# PolyBridge v4: prediction-market signal → C++ algo library → AI fit → live account

**Status:** approved by Theo (owner) on 2026-10-03, about 03:30 ET. This replaces the product parts of spec v3.
The 8-K research in v3 stays as it is and becomes an input to the Opportunity division.
**Deadline:** Devpost Sun 2026-10-04 10:00 ET; pitch 13:00–15:00. Theo's partner writes the quant note.

## 1. Thesis (owner's words, made precise)

In stress, prediction markets (Polymarket, Kalshi) reprice faster than equities. A prediction-market price is therefore an early signal, and we hedge or trade on it before the stock moves.

- It is a new thesis, so there is no long time series that proves causation.
- The evidence is 10–20 single-event case studies in which the prediction market moved first, measured in minutes of lead.

Two divisions run on one signal stack. The signal stack is:

- prediction-market price;
- delta;
- implied probability;
- bids and asks;
- the Polymarket and Kalshi order books;
- the cross-venue gap;
- the 8-K signal.

| Division | What it does | Instruments | Main signal |
|---|---|---|---|
| **Hedge** | Systematic, low-latency hedging of equity positions when the prediction market moves first | equities / ETFs; prediction-market YES/NO legs | PM price and order book, delta, Poly–Kalshi gap |
| **Opportunity** | Trade the gap between the PM probability and the options-implied probability; 8-K-driven option trades | options (via Massive data), PM legs | PM price vs option-implied probability, 8-K tags |

## 2. Priorities (owner's order) for the ~30 hours

1. C++ algo library + AI pipeline (core)
2. Simulated account (Webull paper replaces it when the key arrives; same interface)
3. Options (Opportunity division; Massive option data; simulated fills if Webull paper lacks options)
4. Lead–lag case studies (10–20 events)
5. Options-arbitrage scan (PM vs options-implied probability)
6. Front end with the owner's UI/UX designs (dropped in by Theo); ElevenLabs voice agent; Gemini on stage
7. Quant note: Theo's partner, Sunday.

Method freeze for the 8-K study is still Sat 13:00 ET (about 10 min; only on Theo's word "freeze").

## 3. The C++20 library (`engine/hedgecore`)

**Principle:** blocks compose into named algos; every algo has a parameter grid; a preset is one grid point. The library can count its presets honestly, measure each one's latency, and export a manifest. The AI only ever sees what is compiled.

### 3.1 Blocks (`include/hedgecore/blocks/*.hpp`, header-only, no allocation on the hot path, `std::variant` dispatch)

- **signals:**
  - `PMid` (YES mid);
  - `ImpliedProb` (from bid/ask, de-vigged with NO);
  - `BookImbalance` (top-N depth);
  - `Microprice`;
  - `CrossVenueGap` (Poly − Kalshi);
  - `DeltaDp` (Δp over a window);
  - `EwmaVol`;
  - `Momentum`, `MeanRevertZ`;
  - `OptionImpliedProb` (from a call spread or `opt_delta`);
  - `PMvsOptionGap`;
  - `EightKScore`.
- **gates:** `Staleness`, `Sigma`, `Spread` (skip if too wide), `Depth` (min liquidity), `Session` (equity market hours), `Cooldown`, `EventWindow`.
- **sizers:** `DeltaBridge` (h* = round(c·N·p_adverse)), `LinearExposure`, `ConvexExposure`, `KellyCapped`, `VolTarget`, `FixedNotional`.
- **execution:** `NoTradeBand`, `FeeGate` (benefit vs fee + half-spread), `Slicer` (child qty cap), `PassiveAggressive` (join bid vs cross by urgency), `IcebergCap`.
- **risk:** `PositionCap`, `NotionalCap`, `DrawdownKill`, `GapFlipKill` (stops when the parity gap flips sign), `DailyLossCap`.

### 3.2 Named algo families (`include/hedgecore/algos/*.hpp`)

Each family is a fixed composition of blocks plus a parameter grid (2–5 params, 3–6 values each). Minimum set, one per situation the owner named. More may be added if a situation needs them.

| Family id | Division | Event classes | Instruments | Idea |
|---|---|---|---|---|
| `equity_delta_bridge` | hedge | all | equity | DeltaBridge on the adverse probability, fee-gated (today's engine, generalized) |
| `stress_lead_hedge` | hedge | macro_fed, geopolitics_energy, fig | equity/ETF | Hedge faster when Δp is large vs EwmaVol (stress regime); passive otherwise |
| `book_imbalance_hedge` | hedge | all | equity | Pre-hedge when the PM book imbalance leads the mid |
| `poly_kalshi_spread` | hedge/opp | all with both venues | PM legs | Trade the cross-venue gap net of fees |
| `no_bid_seller` | opportunity | all | PM NO leg | Sell into rich NO bids when the implied prob is overstated vs fair |
| `housing_rates` | hedge | housing | homebuilders/REIT ETFs (ITB, XHB, VNQ) | Mortgage-rate / home-price questions → rate-sensitive equities |
| `fig_stress` | hedge | fig | banks/insurers (KRE, XLF, KBE) | Bank-stress, Fed and regulation questions → FIG names |
| `macro_fed_hedge` | hedge | macro_fed | SPY, IWM, TLT proxies | Fed/CPI/recession odds → index hedge |
| `election_hedge` | hedge | elections | sector ETFs | Election odds → sector tilts |
| `tariff_trade_hedge` | hedge | tariffs_trade | importers/exporters ETFs | Tariff odds → trade-exposed equities |
| `energy_geo_hedge` | hedge | geopolitics_energy | XLE, USO proxies | Conflict/OPEC odds → energy |
| `crypto_reg_hedge` | hedge | crypto | COIN, MSTR | Crypto regulation/ETF odds → crypto equities |
| `tech_reg_hedge` | hedge | tech_regulation | mega-cap tech | Antitrust/AI regulation odds → names |
| `binary_vs_spread_arb` | opportunity | any with listed options | options (call/put spread) | PM prob vs option-implied prob of the same threshold |
| `vol_vs_pm_move` | opportunity | any with options | straddle/strangle | PM repricing without an IV move → buy/sell vol |
| `eightk_opportunity` | opportunity | corporate_8k | options (CSP, put spread) | 8-K tag + PM signal → option trade (uses the v3 research) |

### 3.3 Hot-path types (`include/hedgecore/market.hpp`); the contract every task builds against

```cpp
namespace hedgecore {
enum class Venue : std::uint8_t { Poly = 0, Kalshi = 1 };
enum class Instrument : std::uint8_t { Equity = 0, PredYes = 1, PredNo = 2, Option = 3 };
struct BookLevel { double px; double qty; };
constexpr int kDepth = 5;
struct MarketTick {                       // NaN = field not available
  std::int64_t ts_ns;
  Venue venue;
  double yes_bid, yes_ask, no_bid, no_ask;
  BookLevel bids[kDepth], asks[kDepth];   // YES book, best first
  double p_other_venue;                   // other venue's YES mid
  double under_px, under_bid, under_ask;  // equity/ETF
  double opt_mid, opt_delta, opt_iv, opt_implied_prob;
  double eightk_score;                    // [-1, 1], 0 = none
};
struct Intent {
  Action action;          // Hold | Order (existing enum)
  Instrument instrument;
  int side;               // +1 buy, -1 sell
  double qty;             // > 0
  double limit_px;        // NaN = marketable
  std::uint16_t reason;   // block-level reason code, see reasons.hpp
  double signal;          // the value that triggered it (for the UI log)
  std::int64_t latency_ns;
};
struct Position { double equity = 0, pred_yes = 0, pred_no = 0, option = 0; double shares_held = 0; };
constexpr int kMaxParams = 8;
struct Params { std::array<double, kMaxParams> v{}; };
}
```

- **Algo interface:** each family is a class with `static constexpr const char* id`, `static ParamSpec spec()` (names, min, max, grid), `explicit Family(const Params&, const Position&)`, `Intent on_tick(const MarketTick&, std::int64_t now_ns) noexcept`, `void on_fill(Instrument, double signed_qty, double px) noexcept`.
- **Dispatch:** `using AnyAlgo = std::variant<...all families...>`, with `make_algo(std::string_view id, const Params&, const Position&) -> AnyAlgo`.
- **Catalog:** `catalog()` returns the families with division, event_classes, instruments, blocks, params and grid, plus `preset_count` per family and the total.
- **Replay** (in C++, for tuning): `replay(id, params, position, span<const MarketTick>, FeeModel) -> ReplayStats{n_ticks, n_orders, pnl, fees, max_dd, hedge_var_reduction, turnover, p50_ns, p99_ns}`.
  - Fills at bid/ask plus the fee.
  - `hedge_var_reduction` = 1 − var(hedged P&L) / var(unhedged P&L) of the underlying exposure, defined when `shares_held > 0` and `under_px` is present.
- **Grid search:** `replay_grid(id, position, ticks, FeeModel) -> vector<ReplayStats>` over every preset.
- **Backward compatibility:** the existing `Engine`/`HedgeSpec`/`Tick` API and its 22 GoogleTests stay working; the backend's bridges use them today.

### 3.4 Python binding (`hedgecore` module)

| Function | Returns / notes |
|---|---|
| `hedgecore.catalog()` | dict (the manifest) |
| `hedgecore.Algo(family: str, params: dict[str, float], position: dict)` | `.on_tick(tick: dict) -> dict`, `.on_fill(instrument: str, qty: float, px: float)` |
| `hedgecore.replay(family, params, position, ticks)` | dict. `ticks` is a dict of equal-length numpy arrays named like the MarketTick fields, with book fields `bid_px_0..4`, `bid_qty_0..4`, `ask_px_0..4`, `ask_qty_0..4` |
| `hedgecore.replay_grid(family, position, ticks)` | list[dict], each with `preset_index` and `params` |
| `hedgecore.Engine` | unchanged |

`engine/hedgecore/manifest.json` is generated from `catalog()` by `scripts/gen_manifest.py` and committed. The backend falls back to it when the module is not built.

## 4. AI pipeline (`backend/app/pipeline/`)

`POST /pipeline/fit` takes `{market?: {source, id}, question?: str, ticker: str, direction?: "down_on_yes"|"up_on_yes", shares_held?: float}`. It runs five steps:

1. **classify** → `event_class`, one of `macro_fed | elections | tariffs_trade | geopolitics_energy | housing | fig | tech_regulation | crypto | corporate_8k | company_specific | unsupported`.
   - Uses Gemini (LLM provider) with the manifest's event classes as the allowed set.
   - Falls back to keyword rules.
2. **shortlist** families from the manifest whose event_classes include the class, split by division.
3. **build ticks** from that market's real price history (Polymarket CLOB `prices-history` and Kalshi history where available) aligned to Massive equity minute or daily bars for the ticker.
   - Recorded replay files are used when offline.
   - Missing book depth is set to NaN, never invented.
4. **tune**: `replay_grid` per shortlisted family; score = hedge_var_reduction (hedge) or pnl net of fees per unit risk (opportunity); pick the best preset; keep the top 3 alternatives.
5. **explain**: Gemini writes a 2–3 sentence rationale from the structured result only. If Gemini is unavailable, a template is used.

- **Response:** `{event_class, division, family, preset_index, params, score, alternatives[], rationale, llm: "gemini"|"rules", ticks_source: "live_history"|"replay"|"none", n_ticks}`.
- **LLM provider:** `LLMProvider` protocol with `GeminiProvider` and `RulesProvider`.
  - `GeminiProvider` uses env `GEMINI_API_KEY` and `GEMINI_MODEL` (default `gemini-2.5-flash`), over REST via httpx (`generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, JSON mode).
  - Timeout 8 s, then `RulesProvider`.
  - Never a 500.
  - Tests mock HTTP.
- **Batch precompute:** `scripts/precompute_fits.py` fits the market universe (`app/data/market_universe.json`) to `app/data/fits.json`. The stage demo is instant, and Gemini refines it live when a key is present.

## 5. Accounts (`backend/app/broker/`)

- **Interface (`Broker` protocol):**
  - `account() -> {cash, equity, buying_power, currency}`
  - `positions() -> list`
  - `place_order(OrderRequest) -> Order`
  - `orders(status?) -> list`
  - `cancel(id)`
- **`OrderRequest`:** `{symbol, asset: "equity"|"option"|"prediction", side: "buy"|"sell", qty, type: "market"|"limit", limit_px?, client_order_id, tag?: bridge id}`.
- **`SimBroker`** (default):
  - Starting cash $1,000,000.
  - Equity fills at the Massive last quote (or bridge-supplied price) ± half-spread, with a per-share fee.
  - Option fills at the Massive option quote mid ± half-spread, with a per-contract fee.
  - Prediction legs fill at the PM book.
  - Deterministic.
  - State persisted to `backend/.sim_account.json` (gitignored).
- **`WebullBroker`:** the same interface against the Webull OpenAPI paper-trading endpoints.
  - Enabled when `BROKER=webull` and `WEBULL_APP_KEY` / `WEBULL_APP_SECRET` are set.
  - Built from Webull's public docs, with HTTP mocked in tests.
  - Options route to SimBroker if Webull paper lacks them, labelled as such.
- **Routes:** `GET /account`, `GET /positions`, `GET /orders`, `POST /orders`, `DELETE /orders/{id}`.
- **Bridges** send every engine Order intent to the active broker and record the fill. The UI shows the broker name (`sim` | `webull-paper`).

## 6. Evidence (research lane, parallel; never blocks the core)

- **Lead–lag case studies** (`research/leadlag/`):
  - A curated list of 10–20 stress events, chosen for PM liquidity (2024 election night, FOMC days, the Apr 2025 tariff announcement, shutdown deadlines, TikTok, recession odds, regional-bank stress, geopolitical strikes, etc.).
  - For each event: Polymarket minute prices (CLOB `prices-history`, fidelity 1) and Massive minute bars for the mapped ETFs/stocks.
  - Measured:
    - time of first significant move, where significant = |Δ| > k·rolling σ;
    - lead in minutes;
    - cross-correlation peak lag;
    - a chart per event and a summary table.
  - Honest framing: case studies, not causal proof. Events where equities moved first are reported too.
- **Options-arbitrage scan** (`research/arb/`): PM threshold markets ("SPX above X on date", "NVDA above $Y") vs the call-spread-implied probability from Massive chains; the gap net of costs, as a table.
- **8-K study:** unchanged and frozen at 13:00; its tags feed `eightk_score` for `eightk_opportunity`.

## 7. Front end and voice

- Theo drops the UI/UX designs into the repo; the front end is built against them once the backend endpoints exist.
- Until then the existing Next.js app gets:
  - a **Library** screen (manifest browser: families → presets, latency);
  - an **AI fit** card on Build (event class, chosen algo, replay score, rationale, alternatives);
  - an **Account** panel (broker name, cash, positions, fills).
- **ElevenLabs voice agent:** an agent whose tools call our API (search markets, fit, propose, approve, start bridge, account).
  - The backend exposes `GET /agent/tools` (JSON tool schemas) and the routes those tools hit.
  - The web app embeds the ElevenLabs widget when `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` is set.

## 8. Global constraints

- Keys only in `.env` (gitignored): `MASSIVE_API_KEY`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `WEBULL_APP_KEY`, `WEBULL_APP_SECRET`. A missing key means a graceful fallback, never a crash or a 500.
- Real-money execution is out of scope: paper or simulated accounts only.
- Labels stay honest: replay vs live; AI estimate vs measured; simulated vs Webull paper; case study vs proof.
- Never touch the 8-K OOS window (2026-01-01 → 2026-08-31) before the freeze. `research/HYPOTHESIS.md` is append-only.
- C++20, header-only blocks, no heap allocation and no virtual calls in `on_tick`. GoogleTest per block and per family. A latency benchmark per family.
- Tests are offline: HTTP is mocked, and the engine-dependent tests sit behind the `engine` dependency group as today.
- Work on branches. PRs to `main`; never push to `main` directly. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## 9. Addendum after the design handoff (`design/design_handoff_polybridge/`)

- The UI is the high-fidelity design in `design/design_handoff_polybridge/README.md` + `PolyBridge.dc.html`: the liquid-glass style and 8 screens (Landing, Build chat wizard, Connect brokerage, AI pipeline, Bridge live, Portfolio, Library, Profile). Recreate it in `web/` (Next.js), replacing the prototype's simulated data with our API wherever an endpoint exists. Where no endpoint exists, keep the prototype's behavior, clearly labelled.
- The library UI groups algos as Gate, Reader, Impact, Execution, Tax, Routing, and the design quotes **~1,284 algorithms**. The C++ library therefore adds two block kinds:
  - **tax**: `TaxLotSelector` (HIFO / long-term first), `WashSaleGuard` (blocks re-buys within 30 days of a loss sale);
  - **routing**: `VenueRouter` (prediction-market leg to Poly vs Kalshi by best price).
- UI families map from block kinds:
  - signals → Reader;
  - impact sizers → Impact;
  - gates → Gate;
  - execution → Execution;
  - tax → Tax;
  - routing → Routing.
- The real preset count is whatever `catalog()` reports. Aim the grids so it lands near 1,284, and never pad with duplicate presets.
