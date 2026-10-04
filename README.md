# PolyBridge

Evidence-gated 24/7 hedging. PolyBridge hedges equity positions using live prediction-market prices (Polymarket + Kalshi) as the signal, including while the stock market is closed: stocks close, prediction markets don't. Each market's signal is labelled validated (it passed a pre-registered out-of-sample test) or unvalidated estimate, and the label is enforced: closed-hours staged equity orders are planned only on validated markets unless explicitly overridden (the prediction-market leg runs only on its own opt-in and is always labelled an estimate), and an unvalidated market needs an explicit acknowledgement before a hedge runs in regular hours. A human approves every hedge; a compiled C++ algo library runs it on a paper or simulated account.

**Massive "Trade the 8-K" judges:** the write-up is [note/massive/PolyBridge_Massive_8K_report.pdf](note/massive/PolyBridge_Massive_8K_report.pdf) (LaTeX source in `note/massive/tex/`) and the notebook is [research/massive_8k.ipynb](research/massive_8k.ipynb), built on the Massive starter. To run it: `cd research && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, put `MASSIVE_API_KEY` in `research/.env`, set `HOLDOUT_START`, `HOLDOUT_END` and `RUN_HOLDOUT = True` in the configuration cell, then run all cells (set `RUN_OOS = RUN_FRESH_2022 = False` to skip the re-runs of our own windows). Opened outside the repo, its first cell installs the package from GitHub. Pre-registration: [HYPOTHESIS.md](research/HYPOTHESIS.md), [HYPOTHESIS_TAGS.md](research/HYPOTHESIS_TAGS.md), [FORECAST.md](research/FORECAST.md).

**Start here:** [research/EVIDENCE.md](research/EVIDENCE.md) (every result, with its source) · [research/README.md](research/README.md) (the scored research) · [design](docs/design.md) (architecture, closed-market mode, evidence gating) · [demo script](docs/demo.md) (the tariff weekend first) · [HTTP contracts](docs/contracts.md) · [voice agent](docs/voice-agent.md)

| Folder | Stack | Role |
|---|---|---|
| `engine/` | C++20 · pybind11 | hedgecore: header-only blocks composed into 17 algo families (1,386 presets), run on approved hedges |
| `backend/` | Python 3.12 · FastAPI | Control plane: markets, AI mapping and fit, proposals with the evidence gate, bridges (SSE), liquidity caps and capacity, capital budget and margin, options chain and hedge quotes, broker (sim / Webull paper with reconciliation), portfolio |
| `web/` | Next.js · TypeScript | UI: Build chat, AI pipeline, Bridge live, Library, Portfolio, Connect, Profile |
| `research/` | Python | Evidence (9 studies): pre-registered 8-K study, lead-lag case studies, closed-market study, options-arbitrage scan, closed-hours replication, AI fit walk-forward, closed-market hedge (R1), expected-gap model (R2), options at the open (R3) |
| `scripts/`, `replays/`, `web/e2e/` | Python, Node | End-to-end demo driver, recorded Polymarket replays, headless-Chrome UI walk and screenshots |

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12 for the projects), any `python3` 3.10+ on PATH for the stdlib-only e2e driver, Node 24+ with pnpm, GNU make, a C++20 compiler (Xcode Command Line Tools / clang 16+ or gcc 12+), `cmake` and `ninja` (`uv tool install cmake ninja`) to build the C++ library, Chrome for the screenshot pass.

```bash
cp .env.example .env            # then fill in the keys you have (table below); every key is optional except for live data
cd backend && uv sync --locked --group engine && cd ..   # builds hedgecore (the C++ algo library)
make setup-web                  # pnpm install
make setup-research             # research venv (needed by make test)

make dev                        # backend :8000 (offline replay) + web :3000, Ctrl-C stops both
# open http://localhost:3000  (not 127.0.0.1: the backend's CORS allows localhost only)
```

`make dev` replays the recorded April 2025 tariff weekend on "US recession in 2025?" (the one market whose expected gap is validated out of sample), hedging SPY, in closed-market mode at 3600x (about 67 seconds; approve the staged plan before Monday 04:00 on the recording, about 61 s in). Every replay fill is at the recorded price (`REPLAY_PRICES=recorded`), and `.env` stays loaded, so the Gemini, ElevenLabs and Webull keys work. The click path does not depend on Polymarket being reachable; see the fallbacks in [docs/demo.md](docs/demo.md#4-fallbacks-what-each-failure-looks-like-and-what-to-say). Other recordings play from the same session at their own pace when a bridge picks their market (no restart); `make dev-tlt`, `make dev-ita`, `make dev-iwm` and `make dev-nvda` make one of them the configured file, with today's-quote fills ("Another Fed rate hike in 2026?" -> TLT, Russia/EU -> ITA, Fed October -> IWM, NVDA > $230 options). `make dev-live` starts bridges on the live Polymarket book instead. Recordings: [replays/README.md](replays/README.md), [backend/replays/README.md](backend/replays/README.md).

| Command | What it does |
|---|---|
| `make dev` | Backend (engine group, replay of the recorded tariff weekend) + web dev server |
| `make dev-tlt` / `dev-ita` / `dev-iwm` / `dev-nvda` | The same with another recording as the configured file |
| `make webull-check` | Read-only Webull paper check: account, balance, positions, open orders, market hours; never places an order outside 09:30-16:00 ET |
| `make test` | Every lane: research, backend, C++ (ctest), engine bindings, web lint + build |
| `make e2e` | The regression run on the TLT replay: starts both servers, drives the full flow over HTTP with assertions, clicks the real UI in headless Chrome, saves 8 screenshots to `web/e2e/screens/`, stops everything |
| `make e2e-weekend` (or `make e2e-demo`) | Closed-market mode over HTTP on the recorded tariff weekend: validated expected gap, staged order approved, filled at the first tradable moment, hand-off at the open, P&L vs no hedge (API only, about 70 s) |
| `make e2e-api` | The HTTP half of `make e2e` only (no web server, no Chrome). Default ports :8000/:3000; pass others with `make e2e-api E2E_ARGS="--backend-port 8766"` |
| `make test-backend` / `test-engine` / `test-engine-py` / `test-web` / `test-research` | One lane |

### Environment variables

Keys live only in `.env` (gitignored) or your shell. A missing key means a graceful fallback, never a crash or a 500.

| Variable | Used by | Without it |
|---|---|---|
| `MASSIVE_API_KEY` | backend: equity quotes and bars, options chains, research notebooks | no live equity quote or options data; recorded bars and the bundled data still work |
| `GEMINI_API_KEY` (optional `GEMINI_MODEL`, default `gemini-2.5-flash`) | backend: event classification and the fit rationale | a keyword-rules classifier and a template rationale; the UI labels it "rules-based fit" |
| `ELEVENLABS_API_KEY` | only to create or edit the voice agent through the ElevenLabs API/CLI | nothing: the app does not read it |
| `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` | web (`web/.env.local`): embeds the voice widget | no voice button renders |
| `BROKER` (`sim` default, or `webull`) | backend: which account takes orders | the simulated account ($1,000,000, deterministic) |
| `WEBULL_APP_KEY` (or its alias `WEBULL_API_KEY`), `WEBULL_APP_SECRET` (optional `WEBULL_ACCOUNT_ID`, `WEBULL_BASE_URL`, `WEBULL_EXTENDED_HOURS`, `WEBULL_RECONCILE`, `WEBULL_OPTIONS`) | backend: Webull OpenAPI paper trading when `BROKER=webull`. The paper sandbox accepts orders only from 09:30 to 16:00 ET (HTTP 417 outside), so extended hours are off unless `WEBULL_EXTENDED_HOURS=1`, and staged orders execute at the 09:30 open. `WEBULL_BASE_URL` is **sandbox only**: leave it unset or set it to `https://api.sandbox.webull.com`. Any other host (for example production `api.webull.com`) is refused, an error is logged, and the simulator is used. | the simulated account, labelled "Simulated account" |
| `CAPITAL_MAX_GROSS_PCT`, `CAPITAL_MAX_EVENT_PCT`, `CAPITAL_SHORT_PUT_MODE` | backend: the capital budget (gross hedge notional and per-event exposure as fractions of account equity) and how a short put is margined (`margin` = Reg T naked-put rule) | 0.50, 0.20, cash-secured puts |
| `AGENT_TOOL_SECRET` | backend: shared secret for the voice-agent tunnel. Every write from outside localhost (anything but GET/HEAD/OPTIONS) must send it as `X-Agent-Secret`, else 401. Required before you tunnel the backend; see [docs/voice-agent.md](docs/voice-agent.md#required-shared-secret) | writes from localhost work; tunnelled writes are refused |
| `POLYBRIDGE_REPLAY_PATH`, `POLYBRIDGE_REPLAY_SPEED`, `POLYBRIDGE_REPLAY_PRICES` | backend: replay file and speed for `source: "replay"` bridges and the offline fallback; `POLYBRIDGE_REPLAY_PRICES=recorded` (the `make dev` default) fills every replay order at the recorded price. A recording found through the replay index plays at its sidecar's `replay_speed`. The file is used only for the market it records, named in its `<file>.meta.json` sidecar (see [replays/README.md](replays/README.md)); another market gets a 422 | `replays/<market id>.jsonl` at real time |
| `NEXT_PUBLIC_API_URL` | web: backend URL | `http://localhost:8000` |
| `SIM_ACCOUNT_PATH`, `SIM_START_CASH` | backend: where the simulated account is saved and its starting cash | `backend/.sim_account.json` (gitignored), $1,000,000 |

Real-money execution is out of scope: accounts are simulated or Webull paper only, and the Webull client talks only to `api.sandbox.webull.com` (`backend/app/broker/webull.py` refuses any other host).

## Risk, liquidity and capital

Four checks stand between a signal and the account, and each refusal or cut names its reason. The liquidity caps sit on every order path (the bridges, staged plans, hedge A's prediction-market leg, the options-at-the-open trade and the manual `POST /orders`), and the capital budget on all of them except hedge A's simulated prediction-market leg. Details: [docs/design.md](docs/design.md) sections 6, 10 and 11.

| Check | Rule | On failure |
|---|---|---|
| Evidence gate | Approving a proposal on an unvalidated market needs `ack_unvalidated: true`; in closed hours a staged plan on an unvalidated market also needs `act_on_unvalidated` on a proposal approved with that acknowledgement; hedge A needs its own opt-in; the options-at-the-open trade (R3 NULL) needs `ack_unvalidated: true` | 409 `EVIDENCE_UNVALIDATED` / `EVIDENCE_GATE` / `evidence_unvalidated`; every decision and fill is labelled `validated` or `unvalidated (acknowledged)` |
| Approval and coverage | A bridge runs only the approved algorithm, capped at the approved coverage | 409; sells clipped to the cap |
| Liquidity caps | Equity: at most 10% of the opening 5-minute volume per order and 1% of ADV per day; options: at most 10% of volume and 5% of open interest per leg; PM legs: at most 50% of the depth within 2 cents | the order is cut to the cap (`liquidity_capped`, naming the cap); the manual `POST /orders` refuses it instead (409 `LIQUIDITY_CAPPED`, naming the size allowed); no liquidity numbers: not capped, labelled `unknown` |
| Capital budget | Gross hedge notional at most 50% of equity, per event at most 20%; Reg T margin; the broker's buying power | refused (`capital_budget`; 409 `CAPITAL_BUDGET` on staged approval and on `POST /orders`); an unreadable account refuses (fail closed); an exposure-increasing order with no price at all is refused at the account too (its notional is unknown) |

Cost model: half spread + 1.0 x daily sigma x sqrt(order / ADV), in bp. `POST /proposals` returns the hedge's capacity, cost and capital fit before approval; `GET /liquidity/{ticker}`, `/liquidity/option`, `/liquidity/pm` and `GET /capital` show the numbers live. A Saturday snapshot of Friday's data (`docs/liquidity-snapshot-2026-10-03.json`): one order at the open can hedge about $191M of SPY, $12.5M of TLT or $1.3M of ITA at 50% coverage; on the $1,000,000 paper account the 20% per-event budget binds long before that (about 259 SPY shares).

**Webull paper.** The Individual Margin paper account: orders only 09:30-16:00 ET, buying power read as Webull's overnight figure, shortability checked before a short is sent, and a reconciler that settles asynchronous fills every 15 s in the session. Option orders go to the simulator by default because the paper sandbox's option support could not be verified (`backend/app/broker/WEBULL_NOTES.md`); with `WEBULL_OPTIONS=1` a bridge's option combos go to Webull paper in the regular session, labelled so, and are budget-checked against the Webull account.

**Options.** `GET /options/chain/{underlying}` shows one expiry with quotes, volume, open interest, IV and greeks; `GET /options/hedge-quote` compares short stock, a protective put, a collar and a put spread at executable prices.

## Honest labels

Replay vs live, AI estimate vs measured, simulated vs Webull paper, case study vs proof: the UI says which one you are looking at. The AI fit score is an in-sample replay number: how much variance the hedge removed beyond a static hedge of the same average size on the history it was tuned on (the raw variance reduction is reported but never ranked, because any static short earns it). It is not a forecast, and in a pre-registered walk-forward test the picked preset did not beat a static hedge out of sample; see [docs/library.md](docs/library.md#how-the-ai-picks-and-tunes). A replay bridge trades in a replay sandbox (not your account) unless started with `replay_to_account`. See [docs/demo.md](docs/demo.md#5-claims-we-make-and-do-not-make).

> **Results** (full numbers, sources and method commits: [research/EVIDENCE.md](research/EVIDENCE.md))
> - **Principle (enforced):** Every signal is labelled validated (its market passed a pre-registered out-of-sample test) or unvalidated estimate, and the label is enforced: while the stock market is closed, PolyBridge plans staged equity orders only on a validated market unless the holder sets an explicit, acknowledged override, and the prediction-market leg (hedge A) runs only on its own opt-in, always labelled an estimate; in regular hours, a hedge on an unvalidated market runs only after an explicit acknowledgement at approval. Every decision, fill and staged order carries its label. Most markets fail, and the product says so.
> - **Closed-market mode:** while the stock market is closed the bridge tracks the prediction-market move since the close, shows the expected open gap with its band, and stages an equity hedge for the first tradable moment, sent only after approval. Demo on the recorded April 2025 tariff weekend ("US recession in 2025?" -> 1,000 SPY shares, Friday close to Monday 10:00): no hedge -$10,870, hedged -$8,276, +$2,594 vs no hedge; the staged order alone -$1,607, because SPY rallied after the open ([backend/replays/README.md](backend/replays/README.md)). One weekend shows the mechanism, not evidence.
> - **Expected gap, US-recession market (R2):** walk-forward in time, sign right in 64.2% of 151 closures, slope +1.28; pooled 141 of 235 (60.0%, p = 0.003), slope +1.25, permutation p < 0.001. Scope: one market; election market 52.4% (p = 0.744); fails on the 10-market replication panel (50.2% of 878, slope -0.23); already-seen panel. It is the only market whose expected gap the app labels validated.
> - **Staged equity hedge at 09:30 (R1 hedge B):** post-open variance cut +11.42% [+5.10, +18.14] vs no hedge, +6.82% [+0.50, +13.54] vs a same-size static hedge. Scope: fragile (partial under block bootstrap; -0.78% vs static after dropping 5 closures), timing not direction, does not touch the gap, already-seen 380-closure panel.
> - **Options at the open (fresh data, pre-registered R3):** at the Monday open options had repriced by only 0.44 of the prediction market's closure move (95% CI 0.33 to 0.57; 1,535 events, 44 closures). Scope: net of option costs the residual gap is +0.79 pt [-1.21, +2.78], so R3 is NULL: information, not a tradable arbitrage.
> - **380-closure relation (exploratory):** the PM move during US equity closures lined up with the next SPY gap (+7.52 bp per pp, permutation p = 0.001) and did not replicate on 10 rule-selected new markets (+0.63, p = 0.126). Same-window co-movement; not compared with futures.
> - **Six pre-registered tests run today:** replication: does not replicate (method `7a780b5`); AI fit walk-forward: fails, median -0.0040, 19 above 0 / 72 below, Wilcoxon p = 1.000 (`e2f1600`); 8-K out of sample: H1 INSUFFICIENT (3 events; the INSUFFICIENT label rule, see HYPOTHESIS.md change log), H2 NULL with sign opposite to in-sample (`344de99`); R1: hedge A no evidence and increases variance on the replication panel, hedge B passes but fragile (`c9fc174`); R2: passes on the panel via the recession market only, fails on the replication panel (`fe7c181`); R3: NULL after costs (`297727a`).
> - **What didn't work:** the most rigorous study is a null: the 8-K parity study, pre-registered, frozen and run once out of sample, is null in-sample; out of sample H1 INSUFFICIENT, H2 NULL; market-hours lead-lag PM first 9, equity first 9, simultaneous 2 (sign test p = 1.0); options arbitrage 5 verified, 0 executable; AI fit scores are in-sample replays only.
> - **Product implications:** closed-market mode defaults to staged equity orders (hedge B); the PM-contract hedge (A) is opt-in and labelled an estimate; options at the open is an unvalidated estimate (its simulated trade needs an explicit acknowledgement); the AI fit is configuration, not edge. Accounts are simulated or Webull paper; the Webull paper sandbox takes orders only from 09:30 to 16:00 ET, so on a weekend the demo fills in the simulator and a staged order for Webull executes at Monday's open.

## Workflow

Read [CONTRIBUTING.md](CONTRIBUTING.md): two lanes (Research, Product), shared files change only by PR, and `make test` runs every lane's tests.

Pre-registration: [research/HYPOTHESIS.md](research/HYPOTHESIS.md) and [research/HYPOTHESIS_TAGS.md](research/HYPOTHESIS_TAGS.md).
