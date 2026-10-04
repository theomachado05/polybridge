from __future__ import annotations

import json
import subprocess
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from s6_monday_fade.run import closure_metrics, write_csv  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS, cboot, cboot_diff  # noqa: E402

PER_YEAR = {"S9": cfg.S9_WEEKENDS_PER_YEAR, "S8": cfg.S8_DAYS_PER_YEAR}
UNIT = {"S9": "weekends", "S8": "dates"}


def segment_rows(t: pd.DataFrame, sample: str, v: str, c: float, K: float) -> list[dict]:
    rows = []
    for seg in ("IS", "OOS", "ALL"):
        s = t if seg == "ALL" else t[t.segment == seg]
        r = s[s.reachable]
        f = r[r.filled.astype(bool)]
        u = r[~r.filled.astype(bool)]
        groups = sorted(r.group.unique())
        w = f.fill_frac.to_numpy() if len(f) else np.zeros(0)
        net = cboot(list(f.group), f.net_points.to_numpy(), w)
        gross = cboot(list(f.group), f.gross_points.to_numpy(), w)
        posted = cboot(list(r.group), np.where(r.filled.astype(bool), r.net_points.fillna(0) * r.fill_frac.fillna(0), 0.0))
        adv = cboot_diff(list(f.group), f.mid_to_mid_points.to_numpy(), list(u.group), u.mid_to_mid_points.to_numpy())
        adv2 = cboot_diff(list(f.group), f.net_points.to_numpy(), list(u.group), u.mid_to_mid_points.to_numpy())
        pc = np.array([f[f.group == g].pnl.sum() for g in groups])
        m = closure_metrics(pc, groups, K, float(f.capital.sum()), PER_YEAR[sample])
        cap_pc = (f.capital / (cfg.CONTRACTS * f.fill_frac)).to_numpy() if len(f) else np.zeros(0)
        cost_bp = float(np.sum(w * f.cost_points.to_numpy() / 100.0) / np.sum(w * cap_pc) * 1e4) if len(f) else float("nan")
        rows.append({
            "sample": sample, "variant": v, "primary": v == cfg.PRIMARY, "cost_mult": c, "segment": seg,
            "orders": len(s), "reachable": len(r), UNIT[sample]: len(groups), "filled": len(f),
            "fill_rate": len(f) / len(r) if len(r) else np.nan, "full_fills": int((f.fill_frac >= 1 - 1e-9).sum()),
            "mean_fill_frac": float(f.fill_frac.mean()) if len(f) else np.nan,
            "median_fill_minutes": float(f.fill_minutes.median()) if len(f) else np.nan,
            "filled_" + UNIT[sample]: int(f.group.nunique()),
            "net_per_filled": net[0], "net_lo": net[1], "net_hi": net[2],
            "gross_per_filled": gross[0], "gross_lo": gross[1], "gross_hi": gross[2],
            "cost_points": gross[0] - net[0] if len(f) else np.nan, "cost_bp": cost_bp,
            "net_per_posted": posted[0], "posted_lo": posted[1], "posted_hi": posted[2],
            "mid_to_mid_filled": float(f.mid_to_mid_points.mean()) if len(f) else np.nan,
            "mid_to_mid_unfilled": float(u.mid_to_mid_points.mean()) if len(u) else np.nan,
            "adverse_diff": adv[0], "adverse_lo": adv[1], "adverse_hi": adv[2],
            "filled_net_minus_unfilled_mid": adv2[0], "fnum_lo": adv2[1], "fnum_hi": adv2[2],
            "exit_rest_share": float((f.exit_how == "rest").mean()) if len(f) else np.nan,
            "exit_cross_share": float(f.exit_how.isin(["cross at deadline", "rest + cross", "cross at exit"]).mean()) if len(f) else np.nan,
            "winners": float((f.net_points > 0).mean()) if len(f) else np.nan,
            "pnl": float(f.pnl.sum()), "capital_base": K, "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"],
            "worst_month": m["worst_month"], "turnover_ann": m["turnover_ann"], "total_return": m["total_return"],
            **{f"fills_at_{n}": float((r.qual_volume >= n).mean()) if len(r) else np.nan for n in cfg.CAPACITY_SIZES},
        })
    return rows


def criterion(met: pd.DataFrame) -> list[dict]:
    out = []
    for sample in cfg.SAMPLES:
        g = met[(met["sample"] == sample) & (met.variant == cfg.PRIMARY)]
        oos = g[(g.segment == "OOS") & (g.cost_mult == 1.0)].iloc[0]
        ins = g[(g.segment == "IS") & (g.cost_mult == 1.0)].iloc[0]
        all2 = g[(g.segment == "ALL") & (g.cost_mult == 2.0)].iloc[0]
        u = UNIT[sample]
        lines = [
            ("enough OOS fills", oos.filled >= cfg.MIN_OOS_FILLED and oos["filled_" + u] >= cfg.MIN_OOS_GROUPS,
             f"{int(oos.filled)} filled on {int(oos['filled_' + u])} {u}"),
            ("IS net per filled > 0, interval excludes 0", ins.net_lo > 0, f"{ins.net_per_filled:+.2f} [{ins.net_lo:+.2f}, {ins.net_hi:+.2f}]"),
            ("OOS net per filled > 0", oos.net_per_filled > 0, f"{oos.net_per_filled:+.2f}"),
            ("ALL net per filled > 0 at 2x", all2.net_per_filled > 0, f"{all2.net_per_filled:+.2f}"),
        ]
        for name, ok, ev in lines:
            out.append({"sample": sample, "criterion": name, "pass": bool(ok), "evidence": ev})
        out.append({"sample": sample, "criterion": "VERDICT", "pass": all(x[1] for x in lines), "evidence": ""})
    return out


def charts(tr: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    fig2, ax2 = plt.subplots(figsize=(9, 3.5))
    for sample, c, style in (("S9", 1.0, "-"), ("S9", 2.0, "--"), ("S8", 1.0, ":")):
        t = tr[(tr["sample"] == sample) & (tr.variant == cfg.PRIMARY) & (tr.cost_mult == c) & tr.reachable]
        groups = sorted(t.group.unique())
        pc = t[t.filled.astype(bool)].groupby("group").pnl.sum().reindex(groups, fill_value=0.0)
        x = pd.to_datetime(pd.Series(groups))
        eq = pc.cumsum().to_numpy()
        lab = f"{sample} R0 {c:g}x"
        ax.plot(x, eq, style, label=lab)
        ax2.plot(x, eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:], style, label=lab)
        if sample == "S9" and c == 1.0:
            oos = t[t.segment == "OOS"].group.min()
            if isinstance(oos, str):
                for a in (ax, ax2):
                    a.axvline(pd.Timestamp(oos), color="grey", lw=0.8)
                    a.text(pd.Timestamp(oos), a.get_ylim()[1], " OOS", va="top", fontsize=8, color="grey")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Resting fade, primary R0 (post at mid, 30 min): cumulative P&L, $ (100 contracts per order)")
    ax.set_ylabel("$")
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS / "equity_curve.png", dpi=130)
    ax2.set_title("Drawdown from the running peak, $")
    ax2.legend()
    fig2.tight_layout()
    fig2.savefig(RESULTS / "drawdown.png", dpi=130)
    plt.close("all")


def capacity(met: pd.DataFrame, tr: pd.DataFrame) -> str:
    lines = ["# S12 capacity", "",
             "Qualifying volume = the taker prints that would have reached a resting order (through its price in full, at its "
             "price beyond the 500-contract queue allowance) inside its window. The share of reachable orders that would have "
             "filled completely at each order size, primary posting at the mid (1x rule):", "",
             "| Sample | Variant | Window | Reachable | 100 | 500 | 2,000 | 10,000 | Median qualifying volume |", "|---|---|---|---|---|---|---|---|---|"]
    for sample in cfg.SAMPLES:
        for v in cfg.VARIANTS:
            g = met[(met["sample"] == sample) & (met.variant == v.id) & (met.cost_mult == 1.0) & (met.segment == "ALL")].iloc[0]
            t = tr[(tr["sample"] == sample) & (tr.variant == v.id) & (tr.cost_mult == 1.0) & tr.reachable]
            lines.append(f"| {sample} | {v.id} | {v.window_min} min, {'mid' if v.offset_ticks == 0 else 'one cent better'} | {int(g.reachable)} | "
                         + " | ".join(f"{100 * g[f'fills_at_{n}']:.0f}%" for n in cfg.CAPACITY_SIZES)
                         + f" | {t.qual_volume.median():,.0f} |")
    lines += ["", "Capacity is bounded by the taker flow that comes through the price inside the window. At 100 contracts most "
              "reachable S9 orders never fill at all (the median qualifying volume is shown in the last column); a book "
              "of 10,000 contracts would almost never have been filled in 30 minutes."]
    return "\n".join(lines) + "\n"


def report(od: pd.DataFrame, trades: list[dict], prints: dict, t_run: float) -> None:
    tr = pd.DataFrame(trades)
    rows = []
    for sample in cfg.SAMPLES:
        for v in cfg.VARIANTS:
            for c in cfg.COST_MULTIPLIERS:
                t = tr[(tr["sample"] == sample) & (tr.variant == v.id) & (tr.cost_mult == c)]
                f = t[t.reachable & t.filled.astype(bool)]
                K = float(f.groupby("group").capital.sum().max()) if len(f) else 0.0
                rows += segment_rows(t, sample, v.id, c, K)
    met = pd.DataFrame(rows)
    met.to_csv(RESULTS / "metrics.csv", index=False, float_format="%.6g")
    write_csv(RESULTS / "trades.csv", trades)
    crit = criterion(met)
    write_csv(RESULTS / "criterion.csv", crit)
    charts(tr)
    (RESULTS / "capacity.md").write_text(capacity(met, tr))
    reach = {s: {"markets": int(sum(1 for (smp, _), r in prints.items() if smp == s)),
                 "markets_with_prints_file": int(sum(1 for (smp, _), r in prints.items() if smp == s and r)),
                 "errors": [k[1] for k, r in prints.items() if k[0] == s and r and "error" in r]} for s in cfg.SAMPLES}
    head = subprocess.run(["git", "log", "-1", "--format=%h %cI", "--", "research/s12_resting_orders"], capture_output=True, text=True,
                          cwd=RESULTS.parents[2]).stdout.strip()
    missing = int(tr.get("deadline_mid_missing", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    meta = {"run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": round(time.time() - t_run, 1), "code_commit": head,
            "orders": {s: int((od["sample"] == s).sum()) for s in cfg.SAMPLES}, "prints": reach,
            "deadline_mid_missing_rows": missing}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))
    pd.set_option("display.width", 250)
    cols = ["sample", "variant", "cost_mult", "segment", "reachable", "filled", "fill_rate", "net_per_filled", "net_lo", "net_hi",
            "gross_per_filled", "net_per_posted", "mid_to_mid_filled", "mid_to_mid_unfilled", "adverse_diff", "adverse_lo", "adverse_hi", "sharpe"]
    print(met[cols].round(2).to_string(index=False))
    print(pd.DataFrame(crit).to_string(index=False))
    print(json.dumps(meta))
