# Forward-test output

Written by `make forward-ladders` and `make forward-touch` (code: `backend/app/forward/`). The rules are frozen in
`research/ladder_replay/` (METHOD step 4, `live.py`) and `research/touch_fresh/` (`FORWARD.md`); this directory only
holds what they produced. Nothing is written under `research/results/`.

- `ladders/snapshots/<UTC stamp>.json`: committed summary of one live check (counts out of their samples, the gap range,
  each violation after fees, the sha256 and last commit of the frozen rule files). `ladders/raw/` (pair CSV) is ignored.
- `touch/snapshots/<UTC stamp>.json`: committed state of the listed markets; `stage_<stage>_<stamp>.json` for the frozen
  runner's timed stages. `touch/forward_log/` is the runner's own append-only log (kept). `touch/raw/` is ignored.
