"""Segments, metrics, verdict, capacity and the R1 reconciliation (METHOD.md sections 6, 8, 9). Pure: no network."""
from __future__ import annotations

from math import ceil, sqrt

import numpy as np
import pandas as pd

from .config import PARAMS
from .engine import et_instant, pm_at

ANN = 252


def oos_length(ret_days: list[pd.Timestamp], p=PARAMS) -> int:
    """L = min(ceil(oos_frac x N), return days in the last oos_max_days calendar days)."""
    n = len(ret_days)
    last = pd.Timestamp(ret_days[-1])
    recent = sum(1 for d in ret_days if pd.Timestamp(d) > last - pd.Timedelta(days=p.oos_max_days))
    return int(min(ceil(p.oos_frac * n), recent))


def segments(days: list[pd.Timestamp], p=PARAMS) -> dict[str, list[pd.Timestamp]]:
    """Return days per segment; days[0] is the purchase day and never a return day."""
    ret = list(days[1:])
    k = oos_length(ret, p)
    return {"IS": ret[:-k] if k else ret, "OOS": ret[-k:] if k else [], "full": ret}


def segment_metrics(equity: pd.Series, seg: list[pd.Timestamp], daily: pd.DataFrame | None = None) -> dict:
    """Metrics of one book over one segment, rebased at the equity of the session before the segment's first day."""
    if not seg:
        return {}
    idx = equity.index
    i0 = idx.get_loc(pd.Timestamp(seg[0]))
    e = equity.iloc[i0 - 1: idx.get_loc(pd.Timestamp(seg[-1])) + 1]
    r = e.pct_change().iloc[1:]
    n = len(r)
    sd = float(r.std(ddof=1)) if n > 1 else float("nan")
    m_end = e.iloc[1:].groupby(e.index[1:].to_period("M")).last()
    m_prev = np.concatenate([[e.iloc[0]], m_end.to_numpy()[:-1]])
    out = {
        "n_days": n, "start": seg[0].strftime("%Y-%m-%d"), "end": seg[-1].strftime("%Y-%m-%d"),
        "ann_return": float(np.prod(1 + r.to_numpy()) ** (ANN / n) - 1),
        "ann_vol": sd * sqrt(ANN),
        "sharpe": float(r.mean()) / sd * sqrt(ANN) if sd > 0 else float("nan"),
        "max_dd": float((e / e.cummax() - 1).min()),
        "worst_month": float((m_end.to_numpy() / m_prev - 1).min()),
        "mean_daily": float(r.mean()), "sd_daily": sd,
    }
    if daily is not None:
        d = daily.loc[seg]
        on = d["f"] > 0
        years = n / ANN
        out.update({
            "turnover": float(d["traded_usd"].sum() / e.iloc[1:].mean() / years),
            "hedge_days": int(on.sum()),
            "mean_hedge_fraction": float(d.loc[on, "f"].mean()) if on.any() else 0.0,
            "hit_rate": float((d.loc[on, "hedge_net"] > 0).mean()) if on.any() else float("nan"),
            "hedge_pnl": float(d["hedge_net"].sum()),
        })
    else:
        out.update({"turnover": 0.0, "hedge_days": 0, "mean_hedge_fraction": 0.0, "hit_rate": float("nan"),
                    "hedge_pnl": 0.0})
    return out


def verdict(strat: dict, bh: dict, p=PARAMS) -> dict:
    """Section 8 on the OOS segment at 1x costs."""
    if not strat or strat.get("hedge_days", 0) == 0:
        return {"verdict": "Fail", "reason": "the overlay never trades in OOS (books identical, no effect)",
                "dd_rel": 0.0, "vol_rel": 0.0, "a": False, "b": False}
    dd_rel = 1 - abs(strat["max_dd"]) / abs(bh["max_dd"]) if bh["max_dd"] != 0 else 0.0
    vol_rel = 1 - strat["ann_vol"] / bh["ann_vol"]
    a = dd_rel >= p.materiality or vol_rel >= p.materiality
    b = strat["sharpe"] >= bh["sharpe"]
    reasons = []
    if not a:
        reasons.append(f"risk not lower by 1% (max DD {100 * dd_rel:+.2f}%, vol {100 * vol_rel:+.2f}% relative)")
    if not b:
        reasons.append(f"Sharpe lower ({strat['sharpe']:.3f} vs {bh['sharpe']:.3f})")
    return {"verdict": "Pass" if a and b else "Fail", "reason": "; ".join(reasons) or "both conditions hold",
            "dd_rel": dd_rel, "vol_rel": vol_rel, "a": bool(a), "b": bool(b)}


# ---------------------------------------------------------------- capacity (section 9)


def capacity(meas: pd.DataFrame, daily_bars: pd.DataFrame, days: list[pd.Timestamp], hedges: pd.DataFrame,
             vol_col: str = "vol5_usd", p=PARAMS) -> dict:
    """hedges: rows indexed by day with `notional` at the study's book size and `book` (equity at that day)."""
    dv = (daily_bars["volume"] * daily_bars["vwap"]).reindex(days)
    adv = dv.shift(1).rolling(p.adv_window, min_periods=p.adv_window).mean()
    v5 = meas[vol_col].reindex(days[1:])
    v5 = v5[v5 > 0]
    max_book = p.cap_share * v5 / p.target_coverage
    out = {"sessions": int(len(v5)), "book_max_hedge_median": float(max_book.median()) if len(v5) else float("nan"),
           "book_max_hedge_p5": float(max_book.quantile(0.05)) if len(v5) else float("nan"),
           "n_hedges": int(len(hedges)), "median_vol5_usd": float(v5.median()) if len(v5) else float("nan")}
    if len(hedges):
        h = hedges.copy()
        h["adv_usd"] = adv.reindex(h.index)
        h["vol5_usd"] = meas[vol_col].reindex(h.index)
        h["share_adv"] = h["notional"] / h["adv_usd"]
        h["share_vol5"] = h["notional"] / h["vol5_usd"].where(h["vol5_usd"] > 0)
        scale = p.cap_share / h["share_vol5"]
        out.update({
            "median_share_adv": float(h["share_adv"].median()), "max_share_adv": float(h["share_adv"].max()),
            "median_share_vol5": float(h["share_vol5"].median()), "max_share_vol5": float(h["share_vol5"].max()),
            "book_95pct_hedges": float(p.book_usd * scale.quantile(0.05)),
            "rows": h,
        })
    return out


# ---------------------------------------------------------------- R1 reconciliation (section 9)


def reconcile_r1(r1: pd.DataFrame, meas: pd.DataFrame, pm: dict, markets: list[dict], days: list[pd.Timestamp],
                 p=PARAMS) -> tuple[pd.DataFrame, dict]:
    """Compare gap, open-to-10:00 return and oriented move with R1's columns on overlapping panel-A closures, and
    recompute R1's hedge-B P&L (-f_B x ret30 - 4 f_B) with this study's price legs."""
    by_label = {m["label"]: m for m in markets if m.get("source") == "panel_A"}
    nxt = {days[i - 1].strftime("%Y-%m-%d"): days[i] for i in range(1, len(days))}
    rows = []
    for _, r in r1.iterrows():
        m = by_label.get(r["market"])
        d = nxt.get(str(r["closure"]))
        if m is None or d is None:
            continue
        prev = pd.Timestamp(r["closure"])
        mp, md = meas.loc[prev], meas.loc[d]
        gap = 1e4 * (md["open_px"] / mp["rth_close"] - 1)
        ret30 = 1e4 * (md["px_1000"] / md["open_px"] - 1)
        pts = pm.get((m["market_slug"], r["closure"]))
        x = float("nan")
        if pts and not isinstance(pts, Exception):
            t_close = mp["t_close"] if pd.notna(mp["t_close"]) else et_instant(prev, (16, 0))
            x = m["sign"] * (pm_at(pts, et_instant(d, p.sig_hm)) - pm_at(pts, t_close))
        fb = r.get("f_B")
        pnl_r1 = r["Y_B"] - r["Y0_B"] if pd.notna(fb) else np.nan
        pnl_us = -fb * ret30 - 4 * fb if pd.notna(fb) else np.nan
        rows.append({"market": r["market"], "closure": r["closure"], "gap_r1": r["gap_bp"], "gap": gap,
                     "ret30_r1": r["ret30_bp"], "ret30": ret30, "x_r1": r["dpm_o_pp"], "x": x, "f_B": fb,
                     "pnl_B_r1": pnl_r1, "pnl_B": pnl_us})
    df = pd.DataFrame(rows)
    summ = {"n": int(len(df))}
    for a, b in (("gap", "gap_r1"), ("ret30", "ret30_r1"), ("x", "x_r1"), ("pnl_B", "pnl_B_r1")):
        if df.empty:
            break
        both = df[[a, b]].dropna()
        diff = (both[a] - both[b]).abs()
        summ[a] = {"n_both": int(len(both)), "n_match_0.01": int((diff <= 0.01).sum()),
                   "max_abs_diff": float(diff.max()) if len(diff) else float("nan"),
                   "corr": float(both[a].corr(both[b])) if len(both) > 2 else float("nan"),
                   "only_r1": int((df[b].notna() & df[a].isna()).sum()),
                   "only_here": int((df[a].notna() & df[b].isna()).sum())}
    return df, summ
