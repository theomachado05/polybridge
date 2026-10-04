# PolyBridge

PolyBridge compares Polymarket's stock contracts with the probability implied by listed options, and trades only on signals that passed a test committed before the data was fetched. On 4,561 Polymarket stock contracts that no earlier test had used, the options price had 11 percent smaller squared forecast errors than the Polymarket price. None of the trading strategies built on the gap passed its registered test, and the product labels every signal accordingly. A person approves every order, and a compiled C++ library runs it on a simulated or Webull paper account.

- **Paper:** [paper/PolyBridge.pdf](paper/PolyBridge.pdf) (source `paper/main.tex`, figures `paper/figures.py`)
- **Demo:** `make dev`, then open http://localhost:3000 ([docs/demo.md](docs/demo.md))
- **8-K notebook (Massive challenge):** [research/polybridge_8k.ipynb](research/polybridge_8k.ipynb), report [note/WRITEUP.md](note/WRITEUP.md), organizers' starter in [research/starter/](research/starter/gqh-massive-8k-starter)
- **Every result with its source:** [research/EVIDENCE.md](research/EVIDENCE.md)

| Folder | Role |
|---|---|
| `paper/` | The paper, its LaTeX source and the script that draws its figures from committed result files |
| `research/` | One folder per pre-registered study (`METHOD.md` committed before data, `run.py`, tests) and its output in `research/results/<study>/` (`SUMMARY.md`, `RUN_LOG.md`, scored rows) |
| `engine/` | hedgecore, the C++20 algo library and order-book engine with pybind11 bindings (`third_party/simdjson` is vendored unchanged) |
| `backend/` | FastAPI control plane: markets, proposals with the evidence gate, bridges, risk and capital limits, broker (simulated or Webull paper), recorded replays |
| `web/` | Next.js interface |
| `note/` | The 8-K report and the earlier quant note |
| `scripts/` | End-to-end demo driver and forward-test wrappers |

## Run the demo

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 24 with pnpm, GNU make, a C++20 compiler, `cmake` and `ninja`.

```bash
cp .env.example .env                                     # every key is optional; missing keys fall back gracefully
cd backend && uv sync --locked --group engine && cd ..   # builds hedgecore
make setup-web
make dev                                                 # backend :8000 (offline replay) + web :3000
```

`make dev` replays the recorded April 2025 tariff weekend on "US recession in 2025?" and hedges SPY in closed-market mode at 3600x speed (about 67 seconds; approve the staged plan before Monday 04:00 on the recording). `make dev-tlt`, `dev-ita`, `dev-iwm` and `dev-nvda` play the other recordings in `backend/replays/`, and `make dev-live` uses the live Polymarket book. Open http://localhost:3000, not 127.0.0.1, because the backend allows CORS from localhost only.

| Variable | Used for | Without it |
|---|---|---|
| `MASSIVE_API_KEY` | equity and option quotes, the research notebooks | recorded bars and committed data only |
| `GEMINI_API_KEY` | event classification and the fit rationale | keyword rules and a template rationale |
| `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` | voice widget (`web/.env.local`) | no voice button |
| `BROKER` (`sim` or `webull`), `WEBULL_APP_KEY`, `WEBULL_APP_SECRET` | Webull paper trading (sandbox host only) | the simulated $1,000,000 account |
| `AGENT_TOOL_SECRET` | required before tunnelling the backend for the voice agent ([docs/voice-agent.md](docs/voice-agent.md)) | tunnelled writes are refused |
| `POLYBRIDGE_REPLAY_PATH`, `POLYBRIDGE_REPLAY_SPEED`, `POLYBRIDGE_REPLAY_PRICES` | replay file, speed and fill prices | set by `make dev` |

Keys live only in `.env` (gitignored) or the shell. Real-money execution is out of scope.

## Reproduce the paper

Every number, table and figure in the paper is computed from files committed under `research/results/`. Rebuilding them needs no API key.

```bash
cd research
uv venv .venv --python 3.10 && uv pip install --python .venv -e ".[dev]"
.venv/bin/python fresh_accuracy/checks.py         # Table 1 subsets and Appendix A -> results/fresh_accuracy/checks.json
.venv/bin/python -m fresh_accuracy.checks2        # post-hoc checks in Appendix A -> results/fresh_accuracy/checks2.json
.venv/bin/python weekend_scorecard.py             # the 14 weekend and cross-venue studies -> results/WEEKEND_SCORECARD.md
.venv/bin/python ../paper/figures.py              # paper/fig/*.pdf
cd ../paper && tectonic main.tex                  # paper/main.pdf
```

| Paper | Result files (`research/results/`) | Code (`research/`) |
|---|---|---|
| Table 1, Figure 1, Appendix A, Kalshi comparison | `fresh_accuracy/` (`rows.csv`, `kalshi_rows.csv`, `stats.json`, `checks.json`, `checks2.json`) | `fresh_accuracy/` |
| Discovery data (Section 2) | `arb/`, `open_options/`, `overshoot/` | `arb/`, `open_options/`, `overshoot/` |
| Table 2, Figure 2, Appendix B | `ladder_replay/` (registered rule), `ladder_replay/order_check/` (dates corrected), `ladder_replay/v0_void/` (voided first run), `s11_bundles/` (earlier pairs) | `ladder_replay/`, `s11_bundles/` |
| Section 5, Figure 3, Appendix C | `touch_fresh/`, `s21_options_anchor/` | `touch_fresh/`, `s21_options_anchor/` |
| Latency and Table 3 | `live_books/LATENCY.md`, `live_books_depth/depth.json` | `live_books/`, `live_books_depth/`, `engine/hedgecore/` |
| Appendix D | `in_sample/`, `oos/` (8-K), `leadlag_replication/`, `macro_panel/`, `pm_vs_premarket/`, `reopen_taker/`, `strategy_backtest/`, `WEEKEND_SCORECARD.md` | same names |
| Appendix F | the above plus `closed_hedge/`, `pm_taker_v2/`, `s1_twin_spread/` to `s23_monday_fade_real/` | same names |

Each study folder's `METHOD.md` and `RUN_LOG.md`, together with the git history, show that the method was committed before any price or outcome was fetched. Rerunning a study from scratch (`python -m <study>.run`) fetches data and needs `MASSIVE_API_KEY`; the committed rows are what the paper scores. `depth.json` comes from the live recorder's raw order-book files, which are not committed.

## Tests

```bash
make test        # research, backend, C++ (ctest), engine bindings, web lint, unit tests and build
```

One suite at a time: `make test-research`, `test-backend`, `test-engine`, `test-engine-py`, `test-web`. The live book tests that compare the Python and C++ engines skip until the bindings are built with `engine/hedgecore/scripts/build_stale.sh`, which needs `pybind11` in the research venv.
