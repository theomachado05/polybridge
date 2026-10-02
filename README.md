# PolyBridge

Hedge equity positions using live prediction-market prices (Polymarket + Kalshi) as the signal, with a low-latency C++ algo stack.

**Start here:** [design spec](docs/superpowers/specs/2026-10-02-polybridge-design.md)

| Folder | Stack | Role |
|---|---|---|
| `engine/` | C++20 | Hot path: feeds → algos → paper fills (ZeroMQ out) |
| `api/` | Python 3.12 · FastAPI | Control plane: markets, AI impact, hedge ranking, portfolio |
| `web/` | Next.js · TypeScript | UI: Build · Bridge · Library · Portfolio |

## Workflow
- Branch from `main` as `feat/<area>-<thing>`; open a PR to merge.
- Copy `.env.example` → `.env` and fill your keys. Never commit `.env`.
- The engine ↔ api ZeroMQ contract (spec §6) is frozen at v1; change it only via a PR that edits the spec.
