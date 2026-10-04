"""S21 bug hunt (METHOD.md, amendment 2): checks added AFTER the result was seen, because books showed a Sharpe above 3.
None of them is a pre-registered test and none changes a rule. Cached data only.

Run from `research/`:  python -m s21_options_anchor.checks
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from s7_weekend_straddle.run import boot_diff, boot_mean, write_csv

from . import config as cfg
from . import engine as eg
from .pull import S18
from .run import RESULTS, boot_slope

PLACEBO_DRAWS, PLACEBO_SEED = 5000, 0
PRICE_BUCKETS = (0.0, 0.10, 0.25, 0.50, 0.75, 1.0)           # S18's traded-price buckets, with the two ends closed


def placebo(price: np.ndarray, anchor: np.ndarray, pnl: np.ndarray, threshold: float, draws: int = PLACEBO_DRAWS, seed: int = PLACEBO_SEED) -> dict:
    """The taken-minus-left difference when the anchors are shuffled across markets (prices and results kept)."""
    taken = 100.0 * (price - anchor) >= threshold - 1e-9
    obs = float(pnl[taken].mean() - pnl[~taken].mean())
    rng = np.random.default_rng(seed)
    out, n = [], []
    for _ in range(draws):
        t = 100.0 * (price - rng.permutation(anchor)) >= threshold - 1e-9
        if t.any() and (~t).any():
            out.append(pnl[t].mean() - pnl[~t].mean())
            n.append(int(t.sum()))
    out = np.array(out)
    return {"observed": obs, "placebo_mean": float(out.mean()), "lo": float(np.percentile(out, 2.5)), "hi": float(np.percentile(out, 97.5)),
            "share_at_least_observed": float(np.mean(out >= obs)), "draws": len(out), "mean_markets_taken": float(np.mean(n))}


def groups(s: pd.DataFrame, by: str, col: str) -> dict[str, list[float]]:
    return {str(k): list(v) for k, v in s.groupby(by)[col]}


def main() -> int:
    a = pd.read_csv(RESULTS / "anchors.csv", dtype={"market": str})
    ok = a[a.status == "ok"]
    pm = pd.read_csv(S18 / "prints_markets.csv", dtype={"market": str})
    d = pm.merge(ok.drop(columns=["event", "segment", "asset_class", "question"]), on="market")
    s = d[d.sell_pnl_points.notna()].copy()
    s["gap"] = 100.0 * (s.sell_price - s.anchor_central)
    prim = next(b for b in cfg.BOOKS if b.id == cfg.PRIMARY)
    taken = np.array([eg.selected(prim, p, x) for p, x in zip(s.sell_price, s.anchor_central)])
    b0, left = s[taken], s[~taken]
    bb = d[d.buy_pnl_points.notna()].copy()
    bb["gap"] = 100.0 * (bb.buy_price - bb.anchor_central)
    rows = []

    def add(check, item, value, lo=float("nan"), hi=float("nan"), n=float("nan"), note=""):
        rows.append({"check": check, "item": item, "value": value, "lo": lo, "hi": hi, "n": n, "note": note})

    # 1. no look-ahead
    lead = d.entry_epoch - d.anchor_epoch
    add("no look-ahead", "seconds from the anchor instant to the start of the traded-price window, minimum", float(lead.min()), n=len(d))
    add("no look-ahead", "oldest leg quote, seconds before the anchor instant", float(max(ok.leg_lo_age_s.max(), ok.leg_hi_age_s.max())), n=len(ok))
    add("no look-ahead", "youngest leg quote, seconds before the anchor instant", float(min(ok.leg_lo_age_s.min(), ok.leg_hi_age_s.min())), n=len(ok))

    # 2. is it the anchor, or only the price level?
    p = placebo(s.sell_price.to_numpy(), s.anchor_central.to_numpy(), s.sell_pnl_points.to_numpy(), prim.threshold)
    add("placebo: anchors shuffled across markets", "taken minus left, observed", p["observed"], n=len(s))
    add("placebo: anchors shuffled across markets", "taken minus left, placebo mean and 95% range", p["placebo_mean"], p["lo"], p["hi"], p["draws"],
        f"mean markets taken {p['mean_markets_taken']:.0f}")
    add("placebo: anchors shuffled across markets", "share of placebo draws at or above the observed difference", p["share_at_least_observed"], n=p["draws"])
    for name, x, y in (("sellers' P&L on traded price (points) and gap", s, "sell"), ("buyers' P&L on traded price (points) and gap", bb, "buy")):
        b, se = eg.ols_cluster(x[f"{y}_pnl_points"].to_numpy(), np.column_stack([100.0 * x[f"{y}_price"], x.gap]), x.event.to_numpy())
        for term, bi, si in zip(("intercept", "traded price", "gap"), b, se):
            add("regression with the price level held fixed", f"{name}: {term}", float(bi), float(bi - 1.96 * si), float(bi + 1.96 * si), len(x), f"t = {bi / si:+.2f}")
    s["price_bucket"] = pd.cut(s.sell_price, PRICE_BUCKETS)
    for k, g in s.groupby("price_bucket", observed=True):
        for label, t in (("taken by B0", g[taken[s.index.get_indexer(g.index)]]), ("left by B0", g[~taken[s.index.get_indexer(g.index)]])):
            add("within S18's traded-price buckets", f"sold at {100 * k.left:.0f} to {100 * k.right:.0f}%: {label}",
                float(t.sell_pnl_points.mean()) if len(t) else float("nan"), n=len(t),
                note=f"resolved YES {100 * t.outcome.mean():.0f}%, mean anchor {100 * t.anchor_central.mean():.0f}%" if len(t) else "")

    # 3. the anchor's own fragilities
    for label, t in (("B0 on anchors with no leg moved outward", b0[b0.stepped == 0]), ("the markets it leaves, same anchors", left[left.stepped == 0]),
                     ("sell only when the traded bid is 5+ points above the TOP of the anchor's band", s[100.0 * (s.sell_price - s.central_hi) >= 5.0]),
                     ("B0, printed size of 100 contracts or more", b0[b0.sell_size >= 100]), ("B0, printed size under 100 contracts", b0[b0.sell_size < 100]),
                     ("B0, stock markets", b0[b0.asset_class == "stock"]), ("B0, S&P 500 markets", b0[b0.asset_class == "sp500"])):
        m = boot_mean(groups(t, "event", "sell_pnl_points"))
        add("subsets of the primary", label, m[0], m[1], m[2], len(t), f"{t.event.nunique()} events")
    size = np.minimum(b0.sell_size, cfg.CONTRACTS)
    add("subsets of the primary", "B0 weighted by contracts in the book (up to 100 per market)", float((size * b0.sell_pnl_points).sum() / size.sum()), n=float(size.sum()))
    add("subsets of the primary", "B0 worst single market, points", float(b0.sell_pnl_points.min()), n=len(b0))
    add("subsets of the primary", "B0 share of markets that made money", float((b0.sell_pnl_points > 0).mean()), n=len(b0))

    # 4. one bet per Friday instead of one per event
    m = boot_mean(groups(b0, "anchor_day", "sell_pnl_points"))
    add("resampling Fridays instead of events", "B0 mean P&L per contract", m[0], m[1], m[2], b0.anchor_day.nunique(), "Fridays")
    m = boot_diff(groups(b0, "anchor_day", "sell_pnl_points"), groups(left, "anchor_day", "sell_pnl_points"))
    add("resampling Fridays instead of events", "taken minus left", m[0], m[1], m[2], s.anchor_day.nunique(), "Fridays")
    m = boot_slope(bb.gap.to_numpy(), bb.buy_pnl_points.to_numpy(), bb.anchor_day.to_numpy())
    add("resampling Fridays instead of events", "T1 slope of buyers' P&L on the gap", m[0], m[1], m[2], bb.anchor_day.nunique(), "Fridays")

    # 5. how much a Sharpe on ten or eleven months can say
    eq = pd.read_csv(RESULTS / "equity.csv")
    for bk, e in eq.groupby("book"):
        r = (e.pnl / e.capital_base.iloc[0]).to_numpy()
        if len(r) < 3 or not np.std(r, ddof=1) > 0:
            continue
        sr = float(np.mean(r) / np.std(r, ddof=1))
        se = float(np.sqrt((1.0 + 0.5 * sr * sr) / len(r)) * np.sqrt(12))
        add("Sharpe on monthly P&L", f"{bk}: annualised Sharpe and a rough 95% range (plus or minus two standard errors)", sr * np.sqrt(12), sr * np.sqrt(12) - 2 * se,
            sr * np.sqrt(12) + 2 * se, len(r), f"{int((r < 0).sum())} losing months of {len(r)}; capital base ${e.capital_base.iloc[0]:,.0f}")
    write_csv(RESULTS / "checks.csv", rows)
    for r in rows:
        print(f"{r['check'][:44]:44} | {r['item'][:84]:84} | {r['value']:9.3f} [{r['lo']:8.3f},{r['hi']:8.3f}] n {r['n']:7.0f} {r['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
