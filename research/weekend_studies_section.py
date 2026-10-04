"""The weekend and linked-asset studies (S3 to S9, S14, and the parallel studies when present) for the scored notebook,
rebuilt from the COMMITTED result files only.

No network, no API key. For every study with a trade list, the number of trades and the mean net result per trade of
the pre-registered primary variant are recomputed from the committed `trades.csv` and checked against the committed
`metrics.csv`. The test statistics shown are read from the committed result files.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

# study -> how to recompute its primary variant from trades.csv and where the same numbers sit in metrics.csv
STUDIES = {
    "S4 linked assets": {"dir": "s4_linked_assets", "value": "net_bp", "metric": "mean_net_bp", "unit": "bp per trade",
                         "segments": {"IS": "IS", "OOS": "OOS"}},
    "S5 big moves": {"dir": "s5_big_moves", "value": "net_bp", "metric": "mean_net_bp", "unit": "bp per trade",
                     "segments": {"earlier": "earlier", "recent": "recent", "all": None}},
    "S6 Monday fade": {"dir": "s6_monday_fade", "value": "pnl", "metric": "mean_pnl_per_trade", "unit": "$ per trade",
                       "segments": {"IS": "IS", "OOS": "OOS", "ALL": None}},
    "S8 open referee": {"dir": "s8_open_referee", "value": "net_points", "metric": "mean_net_points", "unit": "points per trade",
                        "segments": {"IS": "IS", "OOS": "OOS", "ALL": None}},
    "S9 weekend price markets": {"dir": "s9_weekend_price_markets", "value": "net_points", "metric": "mean_net_points",
                                 "unit": "points per trade", "segments": {"IS": "IS", "OOS": "OOS", "ALL": None}},
}
PRIMARY = "V0"


def recompute(results: Path | str = RESULTS) -> pd.DataFrame:
    """One row per study, segment and cost level: trades and mean net result of the primary variant, recomputed from
    the trade list, next to the committed figures."""
    rows = []
    for name, s in STUDIES.items():
        root = Path(results) / s["dir"]
        if not (root / "trades.csv").exists() or not (root / "metrics.csv").exists():
            continue
        tr, m = pd.read_csv(root / "trades.csv"), pd.read_csv(root / "metrics.csv")
        tr = tr[tr.variant == PRIMARY]
        for seg, trade_seg in s["segments"].items():
            for c in sorted(m.cost_mult.unique()):
                t = tr[(tr.cost_mult == c) & ((tr.segment == trade_seg) if trade_seg else True)]
                ref = m[(m.variant == PRIMARY) & (m.segment == seg) & (m.cost_mult == c)]
                if ref.empty:
                    continue
                ref = ref.iloc[0]
                mean = float(t[s["value"]].mean()) if len(t) else float("nan")
                same_mean = (np.isnan(mean) and np.isnan(ref[s["metric"]])) or bool(np.isclose(mean, ref[s["metric"]], rtol=1e-9, atol=1e-9))
                rows.append({"study": name, "segment": seg, "costs": f"{c:.0f}x", "trades": len(t), "trades committed": int(ref.trades),
                             f"mean net": mean, "mean net committed": float(ref[s["metric"]]), "unit": s["unit"],
                             "match": len(t) == int(ref.trades) and same_mean})
    s7 = Path(results) / "s7_weekend_straddle"
    if (s7 / "trades.csv").exists():
        tr, m = pd.read_csv(s7 / "trades.csv"), pd.read_csv(s7 / "metrics.csv")
        ok = tr[(tr.status == "ok") & (tr.group == "flagged") & tr.flag_V0]
        for seg in ("IS", "OOS", "ALL"):
            for c, col in ((1.0, "ret_1x"), (2.0, "ret_2x")):
                t = ok if seg == "ALL" else ok[ok.segment == seg]
                ref = m[(m.variant == PRIMARY) & (m.segment == seg) & (m.cost_mult == c)]
                if ref.empty:
                    continue
                ref = ref.iloc[0]
                mean = float(t[col].mean()) if len(t) else float("nan")
                rows.append({"study": "S7 weekend straddles", "segment": seg, "costs": f"{c:.0f}x", "trades": len(t),
                             "trades committed": int(ref.flagged_trades), "mean net": mean, "mean net committed": float(ref.mean_ret_flagged),
                             "unit": "share of the premium", "match": len(t) == int(ref.flagged_trades)
                             and bool(np.isclose(mean, ref.mean_ret_flagged, rtol=1e-9, atol=1e-9, equal_nan=True))})
    s3 = Path(results) / "s3_three_way"
    if (s3 / "trades.csv").exists():
        tr, m = pd.read_csv(s3 / "trades.csv"), pd.read_csv(s3 / "metrics.csv")
        for seg in sorted(m.segment.unique()):
            for c in sorted(m.cost_mult.unique()):
                ref = m[(m.variant == PRIMARY) & (m.segment == seg) & (m.cost_mult == c)].iloc[0]
                n = int(((tr.variant == PRIMARY) & (tr.cost_mult == c) & (tr.segment == seg)).sum())
                rows.append({"study": "S3 three-way", "segment": seg, "costs": f"{c:.0f}x", "trades": n, "trades committed": int(ref.entries),
                             "mean net": float("nan"), "mean net committed": float("nan"), "unit": "no trade fired", "match": n == int(ref.entries)})
    return pd.DataFrame(rows)


def _row(df: pd.DataFrame, **eq) -> pd.Series:
    m = np.ones(len(df), bool)
    for k, v in eq.items():
        m &= (df[k] == v).to_numpy()
    return df[m].iloc[0]


def findings(results: Path | str = RESULTS) -> pd.DataFrame:
    """The main statistic of each study, read from its committed result files."""
    R, out = Path(results), []

    def add(study, finding, value, verdict):
        out.append({"study": study, "finding": finding, "value": value, "verdict": verdict})

    f = R / "s4_linked_assets" / "regressions.csv"
    if f.exists():
        r = pd.read_csv(f)
        g = _row(r, **{"set": "agreed, event, no data gate", "segment": "ALL", "relation": "gap on overnight odds move"})
        a = _row(r, **{"set": "agreed, event, no data gate", "segment": "ALL", "relation": "move after the open on overnight odds move"})
        add("S4", "Opening gap of the linked asset per point of overnight odds move (links both models agreed on)",
            f"{g.slope:+.2f} bp (t = {g.t:.2f}, n = {int(g.n):,}); after the open {a.slope:+.2f} (t = {a.t:.2f})", "relation real; trade too few and negative")
    f = R / "s5_big_moves" / "regressions.csv"
    if f.exists():
        r = pd.read_csv(f)
        g, a = _row(r, sample="all link-days", relation="opening gap on overnight odds move"), _row(r, sample="all link-days", relation="move after the open on overnight odds move")
        add("S5", "The same on 93 fresh markets", f"{g.slope:+.2f} bp (t = {g.t:.2f}); after the open {a.slope:+.2f} (t = {a.t:.2f})", "replicates; nothing left after the open")
    f = R / "s7_weekend_straddle" / "metrics.csv"
    if f.exists():
        r = _row(pd.read_csv(f), variant="V0", segment="ALL", cost_mult=1.0)
        add("S7", "Friday straddles on flagged weekends, against ordinary weekends",
            f"{100 * r.mean_ret_flagged:+.1f}% of the premium [{100 * r.ci_lo:+.1f}, {100 * r.ci_hi:+.1f}] against {100 * r.mean_ret_control:+.1f}%; "
            f"at mid prices {100 * r.mean_mid_ret_flagged:+.1f}% against {100 * r.mean_mid_ret_control:+.1f}%", "options were not too cheap")
    f = R / "s8_open_referee" / "giveback.csv"
    if f.exists():
        g = pd.read_csv(f)
        d = _row(g, threshold=5.0, scope="all nights", window="09:40 to the close", group="not confirmed minus confirmed")
        m = _row(pd.read_csv(R / "s8_open_referee" / "metrics.csv"), variant="V0", segment="ALL", cost_mult=1.0)
        add("S8", "Give-back of an overnight odds move when the asset's open does not confirm it, against when it does",
            f"difference {d['mean']:+.2f} points [{d.ci_lo:+.2f}, {d.ci_hi:+.2f}]; the fade nets {m.mean_net_points:+.2f} points per trade "
            f"[{m.ci_lo:+.2f}, {m.ci_hi:+.2f}]", "null")
    f = R / "s9_weekend_price_markets" / "tests.csv"
    if f.exists():
        t = pd.read_csv(f)
        link = t[t.test == "T2 link"].iloc[0]
        g = _row(t[t.test == "T1 give-back"], threshold=5.0, markets="all", window="to the next session 09:40")
        m = pd.read_csv(R / "s9_weekend_price_markets" / "metrics.csv")
        a, o = _row(m, variant="V0", segment="ALL", cost_mult=1.0), _row(m, variant="V0", segment="OOS", cost_mult=1.0)
        add("S9", "Oil price markets' weekend move per point of oil-linked event odds", f"{link.slope:+.2f} points (t = {link.t:.2f})",
            "the link holds inside the weekend")
        add("S9", "Give-back by Monday of a weekend move of 5+ points, and the fade after costs",
            f"{g['mean']:+.2f} points [{g.ci_lo:+.2f}, {g.ci_hi:+.2f}]; fade {a.mean_net_points:+.2f} per trade [{a.ci_lo:+.2f}, {a.ci_hi:+.2f}], "
            f"out-of-sample {o.mean_net_points:+.2f}", "not a pass")
    f = R / "s14_link_ceiling" / "tests.csv"
    if f.exists():
        t = pd.read_csv(f)
        ctrl = _row(t, test="C2 count of strong links", outcome="opening gap")
        o = _row(t, test="C1 oracle link", group="both groups, reversal links flipped", sample="out-of-sample")
        add("S14", "Links with the gap relation on their own, against shuffled; hindsight-picked links out-of-sample",
            f"{100 * ctrl.observed:.0f}% against {100 * ctrl.shuffle_mean:.0f}%; {o.slope:+.2f} bp per point (t = {o.t:.2f})",
            "neither a link nor a signal-definition problem")
    return pd.DataFrame(out)
