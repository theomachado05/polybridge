"""S24 audit: the bug hunt that METHOD.md section 9 requires before a Sharpe above 3 is reported.

Reads trades.csv and the cached prints; writes audit.json and pairs_read.csv (one line per pair that traded, for reading).
Everything here was looked at after the run. Run from `research/`:  python -m s24_ladder_fresh.audit
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from . import config as cfg
from . import run as rn


def side_check(ids: list[str]) -> dict:
    """Are the prints' sides the taker's? A taker buys at the ask and sells at the bid, so within one market a taker
    purchase of YES should print above a taker sale of YES seconds away. Over every pair of consecutive prints of one
    market on opposite YES sides at most 60 seconds apart: the purchase price minus the sale price."""
    diffs = []
    for i in ids:
        p = rn.prints(i)
        if p is None or len(p["t"]) < 2:
            continue
        ok = p["ok"]
        t, yp, ys = p["t"][ok], p["yp"][ok], p["ys"][ok]
        opp = (ys[1:] != ys[:-1]) & ((t[1:] - t[:-1]) <= 60)
        d = np.where(ys[1:] == 1, yp[1:] - yp[:-1], yp[:-1] - yp[1:])[opp]
        diffs.append(d)
    d = np.concatenate(diffs) if diffs else np.array([])
    return {"pairs_of_prints": int(len(d)), "mean_points": float(d.mean() * 100) if len(d) else None,
            "median_points": float(np.median(d) * 100) if len(d) else None, "share_positive": float((d > 0).mean()) if len(d) else None,
            "share_negative": float((d < 0).mean()) if len(d) else None}


def recheck_prints(P: pd.DataFrame) -> dict:
    """Each trade's two prints, found again in the cached arrays: right market, right side, right price, before the close."""
    bad = []
    for r in P.itertuples():
        a, b = rn.prints(r.rich), rn.prints(r.cheap)
        ia = np.flatnonzero((a["t"] == r.t_sale) & (a["ys"] == -1) & np.isclose(a["yp"], r.sale_print) & np.isclose(a["size"], r.size_sale))
        ib = np.flatnonzero((b["t"] == r.t_buy) & (b["ys"] == 1) & np.isclose(b["yp"], r.buy_print) & np.isclose(b["size"], r.size_buy))
        fees = float(rn.en.fee(r.sale_print, r.fee_rate_rich, r.fee_exp_rich)) + float(rn.en.fee(r.buy_print, r.fee_rate_cheap, r.fee_exp_cheap))
        ok = (len(ia) > 0 and len(ib) > 0 and abs(r.t_sale - r.t_buy) <= cfg.WINDOW_S and r.sale_print - r.buy_print > fees
              and r.t_entry == max(r.t_sale, r.t_buy) and not r.print_after_close)
        if not ok:
            bad.append({"rich": r.rich, "cheap": r.cheap, "date": r.date})
    return {"trades": int(len(P)), "failed": len(bad), "cases": bad[:20]}


def confirmation(P: pd.DataFrame) -> list[str]:
    """Was the earlier print's price still there when the later print completed the match? 'same second': both prints in
    one second. 'confirmed after': the earlier rung printed again, on the same side, at our fill price or better, between
    the entry and 10 minutes later. 'moved away': not confirmed, and the earlier rung printed at a worse price than our
    fill between its print and the entry. 'not confirmed': neither."""
    out = []
    for r in P.itertuples():
        if r.t_sale == r.t_buy:
            out.append("same second")
            continue
        T = r.t_entry
        if r.t_sale < r.t_buy:
            a = rn.prints(r.rich)
            again = a["ok"] & (a["t"] >= T) & (a["t"] <= T + cfg.WINDOW_S) & (a["ys"] == -1) & (a["yp"] >= r.sell_at_1x - 1e-9)
            away = a["ok"] & (a["t"] > r.t_sale) & (a["t"] <= T) & (a["yp"] < r.sell_at_1x - 1e-9)
        else:
            b = rn.prints(r.cheap)
            again = b["ok"] & (b["t"] >= T) & (b["t"] <= T + cfg.WINDOW_S) & (b["ys"] == 1) & (b["yp"] <= r.buy_at_1x + 1e-9)
            away = b["ok"] & (b["t"] > r.t_buy) & (b["t"] <= T) & (b["yp"] > r.buy_at_1x + 1e-9)
        out.append("confirmed after" if again.any() else ("moved away" if away.any() else "not confirmed"))
    return out


def main() -> int:
    T = pd.read_csv(rn.RESULTS / "trades.csv", dtype={"rich": str, "cheap": str})
    P = T[T.variant == "W600"].copy()
    gap = ((P.sale_print - P.buy_print) * 100).round(4)
    P["gap_points"] = gap
    ids = sorted(set(P.rich) | set(P.cheap))
    out = {"side_check": side_check(ids), "recheck": recheck_prints(P),
           "gap_points": {"1 or less": int((gap <= 1.0001).sum()), "over 1 to 2": int(((gap > 1.0001) & (gap <= 2.0001)).sum()),
                          "over 2 to 5": int(((gap > 2.0001) & (gap <= 5.0001)).sum()), "over 5 to 20": int(((gap > 5.0001) & (gap <= 20.0001)).sum()),
                          "over 20": int((gap > 20.0001).sum()), "median": float(gap.median()), "mean": float(gap.mean())},
           "seconds_apart": {"same second": int((P.seconds_apart == 0).sum()), "1 to 10": int(((P.seconds_apart > 0) & (P.seconds_apart <= 10)).sum()),
                             "11 to 60": int(((P.seconds_apart > 10) & (P.seconds_apart <= 60)).sum()),
                             "61 to 120": int(((P.seconds_apart > 60) & (P.seconds_apart <= 120)).sum()),
                             "121 to 600": int((P.seconds_apart > 120).sum()), "median": float(P.seconds_apart.median())},
           "result": {"both NO": int(((P.outcome_rich == 0) & (P.outcome_cheap == 0)).sum()), "both YES": int(((P.outcome_rich == 1) & (P.outcome_cheap == 1)).sum()),
                      "rich NO, cheap YES (pays $1)": int(((P.outcome_rich == 0) & (P.outcome_cheap == 1)).sum()),
                      "rich YES, cheap NO (order violated)": int(P.broken.sum()), "open": int((P.settled_by != "result").sum())},
           "pnl_points": {"entry_edge_mean": float(P.edge_1x.mean() * 100), "result_part_mean": float((P.pnl_1x - P.edge_1x).mean() * 100),
                          "total_mean": float(P.pnl_1x.mean() * 100), "mean_without_one_dollar_payouts": float(P.loc[(P.pnl_1x - P.edge_1x).abs() < 1e-9, "pnl_1x"].mean() * 100),
                          "negative_entry_edge": int((P.edge_1x < 0).sum()), "zero_entry_edge": int((P.edge_1x.abs() < 1e-9).sum()),
                          "positive_entry_edge": int((P.edge_1x > 1e-9).sum())},
           "print_after_close": int(P.print_after_close.sum()),
           "by_event_top": P.groupby("event_title").agg(trades=("pnl_1x", "size"), points=("pnl_1x", lambda x: float(x.sum() * 100)),
                                                         usd_cap=("usd_capped_1x", "sum")).sort_values("trades", ascending=False).head(15).reset_index().to_dict("records"),
           "by_month": P.assign(month=P.date.str[:7]).groupby("month").size().to_dict()}
    def cut_by(col, edges, labels, D=None):
        D = P if D is None else D
        res = {}
        for (lo, hi), lab in zip(edges, labels):
            t = D[(D[col] > lo) & (D[col] <= hi)]
            m, a, b, n, nd = rn.en.boot(t.assign(_p=t.pnl_1x * 100), "_p")
            m2 = float(t.pnl_2x.mean() * 100) if len(t) else None
            res[lab] = {"trades": n, "dates": nd, "points_1x": m if n else None, "lo": a if n else None, "hi": b if n else None, "points_2x": m2,
                        "entry_edge_points": float(t.edge_1x.mean() * 100) if n else None, "usd_capped_1x": float(t.usd_capped_1x.sum())}
        return res
    out["pnl_by_seconds_apart"] = cut_by("seconds_apart", [(-1, 0), (0, 10), (10, 60), (60, 120), (120, 600)],
                                         ["same second", "1 to 10 s", "11 to 60 s", "61 to 120 s", "121 to 600 s"])
    P["confirmation"] = confirmation(P)
    out["pnl_by_confirmation"] = {}
    for lab in ("same second", "confirmed after", "not confirmed", "moved away"):
        for seg in ("ALL", "IS", "OOS"):
            t = P[(P.confirmation == lab) & ((P.segment == seg) | (seg == "ALL"))]
            m, a, b, n, nd = rn.en.boot(t.assign(_p=t.pnl_1x * 100), "_p")
            out["pnl_by_confirmation"][f"{lab} | {seg}"] = {"trades": n, "dates": nd, "points_1x": m if n else None, "lo": a if n else None, "hi": b if n else None,
                                                            "points_2x": float(t.pnl_2x.mean() * 100) if n else None,
                                                            "entry_edge_points": float(t.edge_1x.mean() * 100) if n else None,
                                                            "usd_capped_1x": float(t.usd_capped_1x.sum()), "usd_uncapped_1x": float(t.usd_uncapped_1x.sum())}
    if "direction_ok" in P and "corrected_ok" in P:        # the cleaned sample of amendments 1 and 2 (real ladders, unseen markets)
        Q = P[P.corrected_ok.astype(bool) & ~P.partner_used.astype(bool) & P.direction_ok.astype(bool)]
        out["clean"] = {"trades": int(len(Q)),
                        "pnl_by_seconds_apart": cut_by("seconds_apart", [(-1, 0), (0, 10), (10, 60), (60, 120), (120, 600)],
                                                       ["same second", "1 to 10 s", "11 to 60 s", "61 to 120 s", "121 to 600 s"], Q),
                        "pnl_by_gap": cut_by("gap_points", [(0, 1.0001), (1.0001, 2.0001), (2.0001, 5.0001), (5.0001, 20.0001), (20.0001, 1000)],
                                             ["1 point or less", "over 1 to 2", "over 2 to 5", "over 5 to 20", "over 20"], Q),
                        "pnl_by_confirmation": {}, "event_bootstrap": {},
                        "paid_one_dollar": int(((Q.outcome_cheap == 1) & (Q.outcome_rich == 0)).sum()),
                        "mean_without_one_dollar_payouts": float(Q.loc[~((Q.outcome_cheap == 1) & (Q.outcome_rich == 0)), "pnl_1x"].mean() * 100),
                        "mean_2x_without_one_dollar_payouts": float(Q.loc[~((Q.outcome_cheap == 1) & (Q.outcome_rich == 0)), "pnl_2x"].mean() * 100),
                        "top5_share_of_uncapped_usd": float(Q.usd_uncapped_1x.sort_values(ascending=False).head(5).sum() / Q.usd_uncapped_1x.sum()),
                        "largest_trade_uncapped_usd": float(Q.usd_uncapped_1x.max()), "median_size": float(Q.size_uncapped.median()),
                        "under_5_contracts": int((Q.size_uncapped < 5).sum()),
                        "by_month": Q.assign(month=Q.date.str[:7]).groupby("month").size().to_dict(),
                        "by_event_top": Q.groupby("event_title").agg(trades=("pnl_1x", "size"), points=("pnl_1x", lambda x: float(x.sum() * 100)),
                                                                     usd_cap=("usd_capped_1x", "sum")).sort_values("trades", ascending=False).head(10).reset_index().to_dict("records")}
        for lab in ("same second", "confirmed after", "not confirmed", "moved away"):
            t = Q[Q.confirmation == lab]
            m, a, b, n, nd = rn.en.boot(t.assign(_p=t.pnl_1x * 100), "_p")
            out["clean"]["pnl_by_confirmation"][lab] = {"trades": n, "dates": nd, "points_1x": m if n else None, "lo": a if n else None, "hi": b if n else None,
                                                        "points_2x": float(t.pnl_2x.mean() * 100) if n else None,
                                                        "entry_edge_points": float(t.edge_1x.mean() * 100) if n else None,
                                                        "usd_capped_1x": float(t.usd_capped_1x.sum()), "usd_uncapped_1x": float(t.usd_uncapped_1x.sum())}
        for seg in ("ALL", "IS", "OOS"):
            t = Q if seg == "ALL" else Q[Q.segment == seg]
            m, a, b, n, nd = rn.en.boot(t.assign(_p=t.pnl_1x * 100, date=t.event), "_p")
            out["clean"]["event_bootstrap"][seg] = {"trades": n, "events": nd, "points_1x": m if n else None, "lo": a if n else None, "hi": b if n else None}
    out["event_bootstrap"] = {}
    for seg in ("ALL", "IS", "OOS"):
        t = P if seg == "ALL" else P[P.segment == seg]
        m, a, b, n, nd = rn.en.boot(t.assign(_p=t.pnl_1x * 100, date=t.event), "_p")
        out["event_bootstrap"][seg] = {"trades": n, "events": nd, "points_1x": m if n else None, "lo": a if n else None, "hi": b if n else None}
    P[["variant", "set", "rich", "cheap", "date", "t_entry", "confirmation"]].to_csv(rn.RESULTS / "confirmation.csv", index=False)
    out["pnl_by_gap"] = cut_by("gap_points", [(0, 1.0001), (1.0001, 2.0001), (2.0001, 5.0001), (5.0001, 20.0001), (20.0001, 1000)],
                               ["1 point or less", "over 1 to 2", "over 2 to 5", "over 5 to 20", "over 20"])
    (rn.RESULTS / "audit.json").write_text(json.dumps(out, indent=1, default=lambda x: None if x != x else x))
    g = P.groupby(["set", "kind", "event_title", "rich_q", "cheap_q"]).agg(trades=("pnl_1x", "size"), first=("date", "min"), last=("date", "max"),
                                                                           mean_gap_points=("gap_points", "mean"), mean_points=("pnl_1x", lambda x: float(x.mean() * 100)),
                                                                           broken=("broken", "sum")).reset_index().sort_values("trades", ascending=False)
    g.to_csv(rn.RESULTS / "pairs_read.csv", index=False)
    print(json.dumps({k: v for k, v in out.items() if k not in ("by_event_top",)}, indent=1))
    print(len(g), "pairs traded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
