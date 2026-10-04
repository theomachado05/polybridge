"""S11 live: what tonight's books show. Reads `.cache/live/checks.jsonl`, writes `results/s11_bundles/live_*.csv`.

Run from `research/`:  python -m s11_bundles.live_report
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .live import OUT

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "s11_bundles"
ET = ZoneInfo("America/New_York")
MIN_ORDER = 5.0


def load() -> pd.DataFrame:
    rows = [json.loads(x) for x in open(OUT / "checks.jsonl")]
    df = pd.DataFrame(rows)
    df["key"] = df.apply(lambda r: f"{r.event}|{r.side}" if r.kind == "negrisk" else f"{r.event}|{r.rich}>{r.cheap}", axis=1)
    return df


def summarise(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    snaps = sorted(df.t.unique())
    arb = df[df["size"] > 0].copy()
    # runs of consecutive snapshots per pair or set
    pos = {t: i for i, t in enumerate(snaps)}
    runs = []
    for k, g in arb.sort_values("t").groupby("key"):
        idx = [pos[t] for t in g.t]
        start = prev = idx[0]
        best = g.iloc[0]
        rows = [g.iloc[0]]
        for j, (_, r) in zip(idx[1:], g.iloc[1:].iterrows()):
            if j == prev + 1:
                rows.append(r)
            else:
                runs.append((k, start, prev, rows))
                start, rows = j, [r]
            prev = j
        runs.append((k, start, prev, rows))
    rr = []
    for k, a, b, rows in runs:
        x = pd.DataFrame(rows)
        rr.append({"bundle": k, "kind": x.kind.iloc[0], "first_seen_et": datetime.fromtimestamp(snaps[a], ET).strftime("%a %H:%M"),
                   "snapshots": b - a + 1, "minutes_at_least": round((snaps[b] - snaps[a]) / 60, 1),
                   "best_edge_cents": round(100 * x.edge.max(), 3), "max_size": round(x["size"].max(), 2),
                   "max_locked_usd": round(x.locked.max(), 2), "size_at_least_min_order": bool(x["size"].max() >= MIN_ORDER)})
    R = pd.DataFrame(rr).sort_values("max_locked_usd", ascending=False) if rr else pd.DataFrame()
    tested = df.groupby("kind").key.nunique().to_dict()
    tot = {"snapshots": len(snaps), "first_et": datetime.fromtimestamp(snaps[0], ET).isoformat(), "last_et": datetime.fromtimestamp(snaps[-1], ET).isoformat(),
           "checks": len(df), "pairs_or_sets_tested": tested,
           "negrisk_testable_share": float((df[df.kind == "negrisk"].missing == 0).mean()) if (df.kind == "negrisk").any() else float("nan"),
           "checks_with_money_locked": int(len(arb)), "distinct_arbitrages": int(len(R)),
           "arbitrages_at_least_min_order": int(R.size_at_least_min_order.sum()) if len(R) else 0,
           "sum_of_max_locked_usd": float(R.max_locked_usd.sum()) if len(R) else 0.0}
    # how close the books come: the best edge per check, distribution by kind
    near = df[df.edge.notna()].groupby("kind").edge.describe(percentiles=[0.5, 0.9, 0.99])
    return R, near, tot


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    df = load()
    R, near, tot = summarise(df)
    R.to_csv(RESULTS / "live_arbitrages.csv", index=False)
    near.to_csv(RESULTS / "live_best_edge_by_kind.csv")
    (RESULTS / "live_totals.json").write_text(json.dumps(tot, indent=1))
    print(json.dumps(tot, indent=1))
    print(R.head(20).to_string(index=False))
    print(near.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
