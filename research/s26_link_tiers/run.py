from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from s4_linked_assets import engine as en
from s14_link_ceiling.run import build

from .tiers import tier

RESULTS = Path(__file__).resolve().parent.parent / "results" / "s26_link_tiers"
MIN_MOVE, COST = 5.0, 5.0


def trade_book(panel, idx, mask, days, cost):
    rows = []
    for i in idx:
        l = panel[i]
        x, y = l["x"], l["after"]
        ok = mask & np.isfinite(x) & np.isfinite(y) & (np.abs(np.nan_to_num(x)) >= MIN_MOVE)
        for j in np.flatnonzero(ok):
            rows.append({"day": days[j], "link": i, "net_bp": float(np.sign(x[j]) * y[j] - cost)})
    t = pd.DataFrame(rows, columns=["day", "link", "net_bp"])
    n_sessions = int(mask.sum())
    if t.empty:
        return {"trades": 0, "days": 0, "mean_bp": np.nan, "ci_lo": np.nan, "ci_hi": np.nan, "sharpe": np.nan}
    daily = t.groupby("day")["net_bp"].mean()
    full = np.zeros(n_sessions); full[: len(daily)] = daily.to_numpy()
    rng = np.random.default_rng(7)
    by_day = [g.to_numpy() for _, g in t.groupby("day")["net_bp"]]
    boot = [np.concatenate([by_day[k] for k in rng.integers(0, len(by_day), len(by_day))]).mean() for _ in range(4000)]
    sd = full.std(ddof=1)
    return {"trades": len(t), "days": int(t.day.nunique()), "mean_bp": float(t.net_bp.mean()),
            "ci_lo": float(np.percentile(boot, 2.5)), "ci_hi": float(np.percentile(boot, 97.5)),
            "sharpe": float(full.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan}


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    panel, cal = build()
    days, oos = np.asarray(cal["days"]), cal["oos"]
    tiers = np.array([tier(l["question"], l["ticker"]) for l in panel])
    pd.DataFrame({"market": [l["market"] for l in panel], "ticker": [l["ticker"] for l in panel],
                  "question": [l["question"] for l in panel], "tier": tiers}).to_csv(RESULTS / "tiers.csv", index=False)
    rows = []
    for tname in ("A", "B", "C", "all"):
        idx = np.arange(len(panel)) if tname == "all" else np.flatnonzero(tiers == tname)
        for seg, m in (("in-sample", ~oos), ("out-of-sample", oos)):
            for y in ("after", "gap"):
                xs = [panel[i]["x"][m] for i in idx]; ys = [panel[i][y][m] for i in idx]; ds = [days[m] for _ in idx]
                s = en.clustered_slope(np.concatenate(xs), np.concatenate(ys), np.concatenate(ds)) if len(idx) else {}
                rows.append({"tier": tname, "links": len(idx), "segment": seg, "kind": f"slope on {y}", **s})
            for c, cn in ((COST, "1x"), (2 * COST, "2x")):
                rows.append({"tier": tname, "links": len(idx), "segment": seg, "kind": f"trade {cn}", **trade_book(panel, idx, m, days, c)})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "metrics.csv", index=False)
    a = out[(out.tier == "A") & (out.segment == "out-of-sample")].set_index("kind")
    l1 = a.loc["slope on after", "slope"] > 0 and a.loc["slope on after", "t"] >= 2
    l2 = a.loc["trade 1x", "trades"] >= 30 and a.loc["trade 1x", "ci_lo"] > 0
    l3 = a.loc["trade 2x", "mean_bp"] > 0
    verdict = {"line1_slope": bool(l1), "line2_trade": bool(l2), "line3_2x": bool(l3), "PASS": bool(l1 and l2 and l3),
               "oos_from": cal["oos_from"], "tier_counts": pd.Series(tiers).value_counts().to_dict()}
    (RESULTS / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str))
    pd.set_option("display.width", 250)
    print(out.round(3).to_string(index=False))
    print(json.dumps(verdict, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
