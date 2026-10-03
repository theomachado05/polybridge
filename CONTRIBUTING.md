# Working on PolyBridge in parallel

## Lanes (one owner each; never edit another lane's folder without asking)

| Lane | Folders | Scored? |
|---|---|---|
| **R · Research** | `research/`, `overlay/`, `note/` | Yes: notebook, overlay backtest, quant note |
| **P · Product** | `backend/`, `engine/`, `web/` | No: the pitch demo |

## Shared files (PR + the other lane's review required)

- `docs/contracts.md`: every type and endpoint that crosses a folder boundary
- `research/polybridge_research/schema.py`: families, tags, `Event`
- `research/HYPOTHESIS.md`, `research/HYPOTHESIS_TAGS.md`: pre-registration. `HYPOTHESIS.md` changes are logged in its change log; `HYPOTHESIS_TAGS.md` changes go in a separate commit that states the reason (its rule 4)

## Branches

- Never push to `main`. Branch as `r/<thing>` (lane R) or `p/<thing>` (lane P), open a PR, merge when CI is green.
- Rebase on `main` before opening the PR. Keep PRs inside your lane's folders.

## Setup

1. `cp .env.example .env` and add `MASSIVE_API_KEY` (from the #massive Discord channel). Never commit `.env`.
2. Lane R: `make setup-research && make test-research`
3. Lane P: `make setup-backend test-backend`, `make test-engine` (needs `cmake` and `ninja`: `uv tool install cmake ninja`), `make setup-web test-web`

## Dependencies

- Backend installs are locked (`uv sync --locked`) and `backend/uv.lock` records research's dependencies too. Any change to `research/pyproject.toml` dependencies must run `cd backend && uv lock` in the same PR.

## Hard rules (they protect rubric points)

- Nothing in `research/` or `overlay/` imports `hedgecore` or calls an LLM.
- The out-of-sample window runs once, after the method freeze. Every peek is logged in the note.
- Every variant tried is counted.
