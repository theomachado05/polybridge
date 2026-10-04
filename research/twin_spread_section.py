from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results" / "s1_twin_spread"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from s1_twin_spread import config as cfg  # noqa: E402
from s1_twin_spread.engine import metrics, pair_bootstrap  # noqa: E402

FILES = ("trades.csv", "equity_history.csv", "metrics.csv", "run_meta.json")
RULE, PRIMARY = "registered", cfg.PRIMARY
RUNS = [("IS", 1.0), ("IS", 2.0), ("OOS", 1.0), ("OOS", 2.0)]


def load(results_dir: Path | str = RESULTS) -> dict:
    root = Path(results_dir)
    missing = [f for f in FILES if not (root / f).exists()]
    if missing:
        raise FileNotFoundError(f"committed result files missing under {root}: {missing}")
    out = {"trades": pd.read_csv(root / "trades.csv"), "equity": pd.read_csv(root / "equity_history.csv"),
           "metrics": pd.read_csv(root / "metrics.csv"), "meta": json.loads((root / "run_meta.json").read_text())}
    for name in ("trades_forward.csv", "capacity_forward.csv"):
        out[name[:-4]] = pd.read_csv(root / name) if (root / name).exists() else None
    return out


def _epoch(iso: str) -> int:
    return int(pd.Timestamp(iso).timestamp())


def recompute(data: dict) -> dict:
    tr, eq, meta = data["trades"], data["equity"], data["meta"]
    starts = {"IS": _epoch(meta["t0"]), "OOS": _epoch(meta["split"])}
    out: dict = {}
    for seg, cost in RUNS:
        t = tr[(tr.quote_rule == RULE) & (tr.variant == PRIMARY) & (tr.segment == seg) & (tr.cost_mult == cost)]
        e = eq[(eq.quote_rule == RULE) & (eq.variant == PRIMARY) & (eq.segment == seg) & (eq.cost_mult == cost)]
        mid = e[e["mark"] == "mid"].sort_values("t")
        m = metrics(mid.pnl.to_numpy(), mid.t.to_numpy(), cfg.CAPITAL_HISTORY, float(t.traded.sum()), starts[seg])
        ver = t[t.verified]
        boot = pair_bootstrap({k: g.pnl_mid.tolist() for k, g in t.groupby("pair")}, cfg.N_BOOT, cfg.BOOT_SEED)
        out[(seg, cost)] = {
            "entries": int(len(t)), "pairs_traded": int(t.pair.nunique()), "pnl_mid": float(mid.pnl.iloc[-1]),
            "pnl_locked": float(e[e["mark"] == "locked"].sort_values("t").pnl.iloc[-1]),
            "sharpe_mid": m["sharpe"], "max_drawdown": m["max_drawdown"], "worst_month": m["worst_month"],
            "turnover_ann": m["turnover_ann"], "verified_entries": int(len(ver)),
            "verified_share": len(ver) / len(t) if len(t) else float("nan"),
            "pnl_mid_verified": float(t.pnl_mid_verified.sum()), "edge_at_entry_verified": float((t.edge_in * t.verified_qty).sum()),
            "mean_pnl_per_trade_mid": boot[0], "ci_lo_mid": boot[1], "ci_hi_mid": boot[2],
        }
    o1, o2 = out[("OOS", 1.0)], out[("OOS", 2.0)]
    out["criteria"] = {
        "1 enough out-of-sample entries": o1["entries"] >= cfg.MIN_OOS_ENTRIES and o1["pairs_traded"] >= cfg.MIN_OOS_PAIRS,
        "2 positive with an interval above zero": o1["pnl_mid"] > 0 and o1["pnl_locked"] > 0 and o1["ci_lo_mid"] > 0,
        "3 positive at 2x costs": o2["pnl_mid"] > 0 and o2["pnl_locked"] > 0,
        "4 at least half print-verified and verified subset positive": o1["verified_share"] >= cfg.MIN_VERIFIED_SHARE and o1["pnl_mid_verified"] > 0,
    }
    out["verdict"] = "pass" if all(out["criteria"].values()) else "not a pass"
    return out


def comparison(rec: dict, data: dict) -> pd.DataFrame:
    m = data["metrics"]
    rows = []
    for seg, cost in RUNS:
        c = m[(m.quote_rule == RULE) & (m.variant == PRIMARY) & (m.segment == seg) & (m.cost_mult == cost)].iloc[0]
        for k, v in rec[(seg, cost)].items():
            a, b = float(v), float(c[k])
            rows.append({"segment": seg, "costs": f"{cost:.0f}x", "statistic": k, "recomputed": a, "committed": b,
                         "match": bool(np.isclose(a, b, rtol=1e-6, atol=1e-6, equal_nan=True))})
    return pd.DataFrame(rows)


def summary(rec: dict) -> pd.DataFrame:
    o1, o2, i1 = rec[("OOS", 1.0)], rec[("OOS", 2.0)], rec[("IS", 1.0)]
    rows = [
        {"finding": "Print-verified out-of-sample entries (1x costs)",
         "numbers": f"{o1['verified_entries']} of {o1['entries']} entries; edge locked at entry ${o1['edge_at_entry_verified']:.2f}; "
                    f"P&L at mid ${o1['pnl_mid_verified']:.2f}",
         "verdict": "real, small and rare"},
        {"finding": "Same at 2x costs",
         "numbers": f"{o2['verified_entries']} of {o2['entries']} entries; edge locked at entry ${o2['edge_at_entry_verified']:.2f}",
         "verdict": "still positive" if o2["edge_at_entry_verified"] > 0 else "not positive"},
        {"finding": "Modelled backtest, all entries, out-of-sample (1x costs)",
         "numbers": f"P&L at mid ${o1['pnl_mid']:.2f}, Sharpe {o1['sharpe_mid']:.2f}, max drawdown {100 * o1['max_drawdown']:.2f}%",
         "verdict": "an artifact of the modelled Polymarket spread: not evidence"},
        {"finding": "Modelled backtest, in-sample (1x costs)",
         "numbers": f"{i1['verified_entries']} of {i1['entries']} entries print-verified; P&L at mid ${i1['pnl_mid']:.2f}",
         "verdict": "not evidence"},
        {"finding": "Pre-registered success criterion",
         "numbers": "; ".join(f"{k}: {'pass' if v else 'fail'}" for k, v in rec["criteria"].items()),
         "verdict": rec["verdict"]},
    ]
    return pd.DataFrame(rows)


def chart(data: dict, ax=None):
    import matplotlib.pyplot as plt

    from s1_twin_spread.report import BLUE, GRID, INK, INK2, ORANGE, SURFACE, curve

    eq, split = data["equity"], pd.Timestamp(data["meta"]["split"]).tz_localize(None)
    if ax is None:
        _, ax = plt.subplots(figsize=(8.5, 4.2), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for mark, label, color in (("mid", "All modelled entries", BLUE), ("mid_verified", "Print-verified entries only", ORANGE)):
        c = curve(eq, 1.0, mark)
        ax.plot(c.t, c.y, color=color, linewidth=2, label=label)
        ax.annotate(f"{c.y.iloc[-1]:+.1f}%", (c.t.iloc[-1], c.y.iloc[-1]), xytext=(7, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)
    ax.axvline(split, color=INK2, linewidth=1)
    ax.annotate("out-of-sample starts ▸", (split, 1.0), xycoords=("data", "axes fraction"), xytext=(-5, -4),
                textcoords="offset points", va="top", ha="right", fontsize=8.5, color=INK2)
    ax.grid(True, axis="y", color=GRID, linewidth=1)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.margins(x=0.08)
    ax.set_ylabel("Cumulative net P&L, % of $3,300 capital", fontsize=9, color=INK2)
    ax.set_title("S1 twin spread, primary variant, 1x costs (mid mark)", loc="left", fontsize=11, color=INK)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    return ax


def forward_table(data: dict) -> pd.DataFrame | None:
    m = data["metrics"]
    f = m[m.segment.astype(str).str.startswith("forward") & (m.variant == PRIMARY)]
    if f.empty:
        return None
    return f[["segment", "cost_mult", "entries", "pairs_traded", "contracts", "capital", "pnl_locked", "pnl_mid", "pnl_liq"]]
