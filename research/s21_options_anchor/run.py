"""S21: the three tests of METHOD.md from the cached option quotes and S18's traded prices. No network.

Run from `research/`:  python -m s21_options_anchor.run
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from s18_price_market_calibration.report import book as s18_book
from s7_weekend_straddle.run import boot_diff, boot_mean, write_csv

from . import config as cfg
from . import engine as eg
from .pull import CACHE, RESEARCH, S18, Src, build, plan

RESULTS = RESEARCH / "results" / "s21_options_anchor"
BUCKETS = [eg.bucket_label(lo, hi) for lo, hi in cfg.GAP_BUCKETS]


def by_event(s: pd.DataFrame, col: str) -> dict[str, list[float]]:
    return {str(e): list(v) for e, v in s.groupby("event")[col]}


def boot_slope(x: np.ndarray, y: np.ndarray, events: np.ndarray) -> tuple[float, float, float]:
    """Least-squares slope of y on x and its event-bootstrap 95% interval (events resampled with replacement)."""
    keys = sorted(set(events))
    b = float(np.polyfit(x, y, 1)[0]) if len(x) > 2 and np.ptp(x) > 0 else float("nan")
    if len(keys) < 5:
        return b, float("nan"), float("nan")
    S = np.array([[np.sum(events == k), x[events == k].sum(), y[events == k].sum(), (x[events == k] ** 2).sum(), (x[events == k] * y[events == k]).sum()]
                  for k in keys])
    pick = np.random.default_rng(cfg.BOOT_SEED).integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    n, sx, sy, sxx, sxy = (S[pick][:, :, i].sum(axis=1) for i in range(5))
    with np.errstate(divide="ignore", invalid="ignore"):
        sl = (n * sxy - sx * sy) / (n * sxx - sx ** 2)
    sl = sl[np.isfinite(sl)]
    lo, hi = np.percentile(sl, [2.5, 97.5])
    return b, float(lo), float(hi)


def t1(d: pd.DataFrame, anchor: str) -> tuple[list[dict], dict]:
    s = d[d.buy_pnl_points.notna()].copy()
    s["gap"] = 100.0 * (s.buy_price - s[f"anchor_{anchor}"])
    s["bucket"] = s.gap.map(eg.gap_bucket)
    rows = []
    for name, t in [(b, s[s.bucket == b]) for b in BUCKETS] + [("every gap", s)]:
        m = boot_mean(by_event(t, "buy_pnl_points"))
        rows.append({"anchor": anchor, "gap_bucket": name, "markets": len(t), "events": int(t.event.nunique()),
                     "mean_gap_points": float(t.gap.mean()) if len(t) else float("nan"),
                     "mean_traded_price": float(100 * t.buy_price.mean()) if len(t) else float("nan"),
                     "mean_anchor": float(100 * t[f"anchor_{anchor}"].mean()) if len(t) else float("nan"),
                     "share_yes": float(100 * t.outcome.mean()) if len(t) else float("nan"),
                     "buyers_pnl_points": m[0], "ci_lo": m[1], "ci_hi": m[2]})
    if len(s) > 3:
        b, se = eg.ols_cluster(s.buy_pnl_points.to_numpy(), s[["gap"]].to_numpy(), s.event.to_numpy())
        bs = boot_slope(s.gap.to_numpy(), s.buy_pnl_points.to_numpy(), s.event.astype(str).to_numpy())
        slope = {"anchor": anchor, "markets": len(s), "events": int(s.event.nunique()), "slope_points_per_point": float(b[1]), "clustered_se": float(se[1]),
                 "t": float(b[1] / se[1]), "boot_lo": bs[1], "boot_hi": bs[2], "intercept": float(b[0])}
    else:
        slope = {"anchor": anchor, "markets": len(s), "events": int(s.event.nunique()), "slope_points_per_point": float("nan"), "clustered_se": float("nan"),
                 "t": float("nan"), "boot_lo": float("nan"), "boot_hi": float("nan"), "intercept": float("nan")}
    return rows, slope


def t2(d: pd.DataFrame) -> list[dict]:
    s = d[(d.buy_prints > 0) | (d.sell_prints > 0)].copy()
    bz, sz = s.buy_size.fillna(0.0), s.sell_size.fillna(0.0)
    s["price"] = (s.buy_price.fillna(0.0) * bz + s.sell_price.fillna(0.0) * sz) / (bz + sz)
    s = s[s.price.notna()]
    y, ev = s.outcome.to_numpy(), s.event.to_numpy()
    rows = []
    for name, cols in (("result on central anchor and traded price", ["anchor_central", "price"]),
                       ("result on lower-bound anchor and traded price", ["anchor_lower", "price"]),
                       ("result on traded price alone", ["price"]), ("result on central anchor alone", ["anchor_central"]),
                       ("result on lower-bound anchor alone", ["anchor_lower"])):
        if len(s) <= len(cols) + 2:
            continue
        b, se = eg.ols_cluster(y, s[cols].to_numpy(), ev)
        for term, bi, si in zip(["intercept"] + cols, b, se):
            rows.append({"kind": "regression", "model": name, "term": term, "value": float(bi), "clustered_se": float(si), "t": float(bi / si),
                         "ci_lo": float(bi - 1.96 * si), "ci_hi": float(bi + 1.96 * si), "markets": len(s), "events": int(s.event.nunique())})
    for name, col in (("traded price", "price"), ("central anchor", "anchor_central"), ("lower-bound anchor", "anchor_lower")):
        rows.append({"kind": "brier", "model": name, "term": "Brier score", "value": eg.brier(s[col], y) if len(s) else float("nan"),
                     "markets": len(s), "events": int(s.event.nunique())})
    for name, col in (("traded price minus central anchor", "anchor_central"), ("traded price minus lower-bound anchor", "anchor_lower")):
        s["_d"] = (s.price - s.outcome) ** 2 - (s[col] - s.outcome) ** 2
        m = boot_mean(by_event(s, "_d"))
        rows.append({"kind": "brier difference", "model": name, "term": "positive = the anchor is the better forecast", "value": m[0], "ci_lo": m[1],
                     "ci_hi": m[2], "markets": len(s), "events": int(s.event.nunique())})
    rows.append({"kind": "means", "model": "traded price / central anchor / lower-bound anchor / resolved YES", "term": "percent",
                 "value": float(100 * s.price.mean()) if len(s) else float("nan"), "ci_lo": float(100 * s.anchor_central.mean()) if len(s) else float("nan"),
                 "ci_hi": float(100 * s.anchor_lower.mean()) if len(s) else float("nan"), "t": float(100 * s.outcome.mean()) if len(s) else float("nan"),
                 "markets": len(s), "events": int(s.event.nunique())})
    return rows


def book_sets(d_all: pd.DataFrame) -> dict[str, tuple[str, pd.DataFrame, str]]:
    """{book id: (side, the markets the book takes, the anchor column or "")}. `d_all`: every stock and S&P market."""
    ok = d_all[d_all.status == "ok"]
    out = {}
    for b in cfg.BOOKS:
        col, price = f"anchor_{b.anchor}", f"{b.side}_price"
        s = ok[ok[f"{b.side}_pnl_points"].notna()]
        out[b.id] = (b.side, s[[eg.selected(b, p, a) for p, a in zip(s[price], s[col])]], col)
    prim = next(b for b in cfg.BOOKS if b.id == cfg.PRIMARY)
    out["R1"] = ("sell", out[cfg.PRIMARY][1][~out[cfg.PRIMARY][1].zero_bid_leg.astype(bool)], f"anchor_{prim.anchor}")
    out["U"] = ("sell", ok[ok.sell_pnl_points.notna()], "anchor_central")
    out["U-all"] = ("sell", d_all[d_all.sell_pnl_points.notna()], "")
    left = ok[ok.sell_pnl_points.notna() & ~ok.market.isin(out[cfg.PRIMARY][1].market)]
    out["U-left"] = ("sell", left, "anchor_central")
    return out


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    markets, dropped = plan()
    src = Src(offline=True)
    anchors = build(src, markets)
    write_csv(RESULTS / "anchors.csv", sorted(anchors, key=lambda r: (r["anchor_day"], r["ticker"], r["market"])))
    a = pd.DataFrame(anchors)
    pm = pd.read_csv(S18 / "prints_markets.csv")
    pm = pm[pm.asset_class.isin(cfg.ASSET_CLASSES)].copy()
    pm["market"] = pm.market.astype(str)
    keep = ["market", "status", "ticker", "level", "direction", "end_session", "anchor_day", "expiry", "days_expiry_after_end", "k_lo", "k_hi",
            "zero_bid_leg", "stepped", "p_lo", "p_mid", "p_hi", "anchor_lower", "anchor_central", "central_lo", "central_hi"]
    for k in keep:
        if k not in a.columns:
            a[k] = np.nan
    d_all = pm.merge(a[keep], on="market", how="left")
    d_all["status"] = d_all.status.fillna("dropped in parsing")
    d_all["zero_bid_leg"] = d_all.zero_bid_leg.fillna(False).astype(bool)
    d = d_all[d_all.status == "ok"].copy()

    # ---- T1
    b_c, s_c = t1(d, "central")
    b_l, s_l = t1(d, "lower")
    write_csv(RESULTS / "t1_buckets.csv", b_c + b_l)
    write_csv(RESULTS / "t1_slope.csv", [s_c, s_l])
    # ---- T2
    write_csv(RESULTS / "t2_regression.csv", t2(d))

    # ---- T3
    entries = pd.read_csv(S18 / "entries.csv")
    sets = book_sets(d_all)
    metrics, trades, monthly = [], [], []
    for bid, (side, s, col) in sets.items():
        pcol, prc, zcol = f"{side}_pnl_points", f"{side}_price", f"{side}_size"
        for c in cfg.FEE_MULTIPLES:
            x = s.copy()
            x["market"] = x.market.astype(int)
            if c == 2.0:
                x[pcol] = x[f"{pcol}_2x_fee"]
            mon, bk = s18_book(x, entries, side) if len(x) else (pd.DataFrame(columns=["result_month", "pnl"]), {})
            if c == 1.0:
                monthly += [{"book": bid, "result_month": r.result_month, "pnl": float(r.pnl), "capital_base": bk["ALL"]["capital_base"]} for r in mon.itertuples()]
            for seg in ("IS", "OOS", "ALL"):
                t = x if seg == "ALL" else x[x.segment == seg]
                m = boot_mean(by_event(t, pcol))
                v = bk.get(seg, {})
                metrics.append({"book": bid, "side": "sell YES" if side == "sell" else "buy YES", "segment": seg, "fee_mult": c, "markets": len(t),
                                "events": int(t.event.nunique()), "mean_pnl_points": m[0], "ci_lo": m[1], "ci_hi": m[2],
                                "mean_traded_price": float(100 * t[prc].mean()) if len(t) else float("nan"),
                                "mean_anchor": float(100 * t[col].mean()) if len(t) and col else float("nan"),
                                "share_yes": float(100 * t.outcome.mean()) if len(t) else float("nan"),
                                **{k: v.get(k, float("nan")) for k in ("pnl", "capital_base", "sharpe", "max_drawdown", "worst_month", "total_return", "months",
                                                                      "winners", "worst_event", "best_event", "turnover_ann", "mean_capital",
                                                                      "median_days_locked")}})
        for r in s.itertuples():
            size = min(getattr(r, zcol), cfg.CONTRACTS)
            price = getattr(r, prc)
            anchor = getattr(r, col) if col and r.status == "ok" else float("nan")
            trades.append({"book": bid, "market": r.market, "event": r.event, "segment": r.segment, "ticker": r.ticker, "question": r.question,
                           "side": "sell YES" if side == "sell" else "buy YES", "traded_price": price, "anchor": anchor,
                           "gap_points": 100.0 * (price - anchor), "p_lo": r.p_lo, "p_mid": r.p_mid, "p_hi": r.p_hi, "expiry": r.expiry,
                           "zero_bid_leg": r.zero_bid_leg, "outcome": r.outcome, "pnl_points": getattr(r, pcol), "pnl_points_2x_fee": getattr(r, f"{pcol}_2x_fee"),
                           "printed_size": getattr(r, zcol), "contracts": size, "pnl_dollars": size * getattr(r, pcol) / 100.0,
                           "capital_dollars": size * ((1.0 - price) if side == "sell" else price)})
    write_csv(RESULTS / "metrics.csv", metrics)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "equity.csv", monthly)

    # ---- does the anchor improve S18's book?
    taken, left = sets[cfg.PRIMARY][1], sets["U-left"][1]
    imp = []
    for seg in ("ALL", "IS", "OOS"):
        ta = taken if seg == "ALL" else taken[taken.segment == seg]
        le = left if seg == "ALL" else left[left.segment == seg]
        df = boot_diff(by_event(ta, "sell_pnl_points"), by_event(le, "sell_pnl_points")) if len(ta) and len(le) else (float("nan"),) * 3
        imp.append({"segment": seg, "taken_markets": len(ta), "left_markets": len(le), "taken_mean_points": float(ta.sell_pnl_points.mean()) if len(ta) else float("nan"),
                    "left_mean_points": float(le.sell_pnl_points.mean()) if len(le) else float("nan"), "difference_points": df[0], "ci_lo": df[1], "ci_hi": df[2]})
    write_csv(RESULTS / "improvement.csv", imp)

    ok = a[a.status == "ok"] if "status" in a else a
    st = a.status.value_counts().to_dict() if len(a) else {}
    log = (CACHE / "pull.log").read_text().splitlines() if (CACHE / "pull.log").exists() else []
    meta = {"markets_in_s18_file": int(len(pm)), "parsed": len(markets), "dropped_in_parsing": dropped, "anchored": int(len(ok)), "status": st,
            "anchored_with_a_taker_purchase": int(d.buy_pnl_points.notna().sum()), "anchored_with_a_taker_sale": int(d.sell_pnl_points.notna().sum()),
            "anchored_events": int(d.event.nunique()), "anchored_by_segment": {k: int(v) for k, v in d.segment.value_counts().items()},
            "zero_bid_leg": int(ok.zero_bid_leg.astype(bool).sum()) if len(ok) else 0, "stepped": int((ok.stepped > 0).sum()) if len(ok) else 0,
            "noarb_violation": int(ok.noarb_violation.astype(bool).sum()) if len(ok) else 0,
            "expiry_rank_counts": {str(int(k)): int(v) for k, v in ok.expiry_rank.value_counts().items()} if len(ok) else {},
            "median_days_expiry_after_end": float(ok.days_expiry_after_end.median()) if len(ok) else float("nan"),
            "max_days_expiry_after_end": float(ok.days_expiry_after_end.max()) if len(ok) else float("nan"),
            "median_band_width_points": float(100 * (ok.p_hi - ok.p_lo).median()) if len(ok) else float("nan"),
            "median_anchor_lower": float(100 * ok.anchor_lower.median()) if len(ok) else float("nan"),
            "by_ticker": {k: {"markets": int(len(v)), "anchored": int((v.status == "ok").sum())} for k, v in a.groupby("ticker")},
            "cache_lines": len(src.cache), "pull_log": log, "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_seconds": round(time.time() - t_run, 1)}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k not in ("pull_log", "by_ticker")}, indent=1))
    for r in b_c:
        print(f"T1 {r['gap_bucket']:12} mkts {r['markets']:4d} ev {r['events']:3d} price {r['mean_traded_price']:5.1f} anchor {r['mean_anchor']:5.1f} "
              f"yes {r['share_yes']:5.1f} pnl {r['buyers_pnl_points']:7.2f} [{r['ci_lo']:7.2f},{r['ci_hi']:7.2f}]")
    print("T1 slope", s_c)
    for r in metrics:
        print(f"{r['book']:6} {r['segment']:3} {r['fee_mult']:.0f}x mkts {r['markets']:4d} ev {r['events']:3d} pnl {r['mean_pnl_points']:7.2f} "
              f"[{r['ci_lo']:7.2f},{r['ci_hi']:7.2f}] ${r['pnl']:9.0f} sharpe {r['sharpe']:6.2f} dd {r['max_drawdown']:6.3f} worst month {r['worst_month']:6.3f}")
    for r in imp:
        print("improvement", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
