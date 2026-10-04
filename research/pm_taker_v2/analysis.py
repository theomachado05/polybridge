"""Scoring of the frozen trade list (METHOD.md sections 4-5). Pure given data frames."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import core


def _fee_fn(row):
    return lambda p: core.fee_per_share(p, bool(row["fee_enabled"]), float(row["fee_rate"]), float(row["fee_exp"]))


def add_pnl(trades: pd.DataFrame, tick: float, col: str = "net") -> pd.DataFrame:
    t = trades.copy()
    t[col] = [core.net_pnl(r["side"], float(r["px"]), int(r["y"]), tick, _fee_fn(r)) for _, r in t.iterrows()]
    return t


def summarize(values, clusters, seed: int = C.SEED) -> dict:
    v = np.asarray(values, float)
    cl = np.asarray(clusters)
    if len(v) == 0:
        return {"n": 0, "clusters": 0, "mean": None, "ci_lo": None, "ci_hi": None}
    lo, hi = core.cluster_boot(v, cl, seed=seed)
    return {"n": int(len(v)), "clusters": int(len(np.unique(cl))), "mean": float(v.mean()), "ci_lo": lo, "ci_hi": hi}


def day_mean_summary(values, days, seed: int = C.SEED) -> dict:
    s = pd.Series(np.asarray(values, float)).groupby(np.asarray(days)).mean()
    if s.empty:
        return {"n_days": 0, "mean": None, "ci_lo": None, "ci_hi": None}
    lo, hi = core.cluster_boot(s.values, s.index.values, seed=seed)
    return {"n_days": int(len(s)), "mean": float(s.mean()), "ci_lo": lo, "ci_hi": hi}


def score(trades: pd.DataFrame, evals: pd.DataFrame, mid_trades: pd.DataFrame | None = None) -> dict:
    """trades: frozen rows with y, fee_enabled, fee_rate, fee_exp. evals: evaluated prints with y."""
    out: dict = {}
    prim = trades[trades["tau"].round(4) == round(C.TAU, 4)]
    prim = add_pnl(prim, C.TICK)
    p = summarize(prim["net"], prim["res_date"])
    p["days"] = p.pop("clusters")
    p["verdict"] = core.verdict(p["n"], p["days"], p["ci_lo"] if p["n"] else float("nan"), p["ci_hi"] if p["n"] else float("nan"))
    if p["n"]:
        se = (p["ci_hi"] - p["ci_lo"]) / 3.92
        p["se_approx"] = se
        p["mde_80"] = 2.80 * se
    out["primary"] = p
    sec: dict = {}
    for tk in C.TICK_SECONDARY:
        x = add_pnl(prim, tk)
        sec[f"tick_{tk:.2f}"] = summarize(x["net"], x["res_date"])
    for tau in C.TAUS_SECONDARY:
        x = add_pnl(trades[trades["tau"].round(4) == round(tau, 4)], C.TICK)
        sec[f"tau_{tau:.2f}"] = summarize(x["net"], x["res_date"])
    g = add_pnl(prim.assign(fee_enabled=False), 0.0, "gross")
    sec["gross_no_fee_no_tick"] = summarize(g["gross"], g["res_date"])
    sec["equal_weight_per_day"] = day_mean_summary(prim["net"], prim["res_date"])
    sec["ticker_day_cluster"] = summarize(prim["net"], prim["tk"] + "|" + prim["res_date"])
    splits = {}
    for col in ("tk", "side", "fee_enabled"):
        splits[col] = {str(k): summarize(v["net"], v["res_date"]) for k, v in prim.groupby(col)}
    sec["splits"] = splits
    if mid_trades is not None and len(mid_trades):
        m = mid_trades.copy()
        m["net"] = [(r["y"] - (r["mid"] + C.MID_HALF_SPREAD) - _fee_fn(r)(r["mid"])) if r["side"] == "BUY"
                    else ((1 - r["y"]) - (1 - r["mid"] + C.MID_HALF_SPREAD) - _fee_fn(r)(1 - r["mid"]))
                    for _, r in m.iterrows()]
        sec["mid_variant"] = summarize(m["net"], m["res_date"])
    else:
        sec["mid_variant"] = {"n": 0}
    ok = evals[(evals["status"] == "ok") & evals["y"].notna()]
    if len(ok):
        yv = ok["y"].astype(float).values
        sec["calibration"] = {"n_prints": int(len(ok)), "n_markets": int(ok["market_id"].nunique()),
                              "brier_option_p_mid": core.brier(ok["p_mid"].values, yv),
                              "brier_print_price": core.brier(ok["px"].values, yv),
                              "reliability_option": core.reliability(ok["p_mid"].values, yv),
                              "reliability_print": core.reliability(ok["px"].values, yv)}
    entry = np.where(prim["side"] == "BUY", prim["px"], 1 - prim["px"]) + C.TICK
    half = C.CAPACITY_SHARE * prim["size"].astype(float)
    sec["capacity"] = {"shares": float(half.sum()), "dollars_deployed": float((half * entry).sum()),
                       "dollars_pnl": float((half * prim["net"]).sum()),
                       "median_print_size": float(prim["size"].median()) if len(prim) else None}
    out["secondary"] = sec
    out["primary_trades"] = prim
    return out
