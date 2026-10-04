from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

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
    "S10 weekend lag": {"dir": "s10_weekend_lag", "value": "net_points", "metric": "mean_net_points", "unit": "points per trade",
                        "segments": {"IS": "IS", "OOS": "OOS", "ALL": None}},
    "S15 weekend scare": {"dir": "s15_weekend_scare", "value": "net_points", "metric": "mean_net_points", "unit": "points per trade",
                          "segments": {"IS": "IS", "OOS": "OOS", "ALL": None}},
    "S16 Kalshi quotes": {"dir": "s16_kalshi_quotes", "value": "net_points", "metric": "mean_net_points", "unit": "points per trade",
                          "segments": {"IS": "IS", "OOS": "OOS", "ALL": None}},
    "S18 calibration, at history mids": {"dir": "s18_price_market_calibration", "value": "net_points", "metric": "mean_net_points",
                                         "unit": "points per trade", "segments": {"IS": "IS", "OOS": "OOS", "ALL": None}},
}
PRIMARY = "V0"


def recompute(results: Path | str = RESULTS) -> pd.DataFrame:
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
    f = R / "s10_weekend_lag" / "leadlag.csv"
    if f.exists():
        l = pd.read_csv(f)
        e, pr = _row(l, **{"class": "crude", "direction": "event first", "horizon_min": 30}), _row(l, **{"class": "crude", "direction": "price first", "horizon_min": 30})
        m = _row(pd.read_csv(R / "s10_weekend_lag" / "metrics.csv"), variant="V0", segment="IS", cost_mult=1.0)
        add("S10", "Inside the weekend: oil price markets' move over the next 30 minutes per point of event odds, and the reverse",
            f"{e.slope:+.3f} (t = {e.t:.2f}) against {pr.slope:+.3f} (t = {pr.t:.2f}); the trade nets {m.mean_net_points:+.2f} points in-sample "
            f"[{m.ci_lo:+.2f}, {m.ci_hi:+.2f}]", "event questions lead by minutes; not a pass")
    f = R / "s12_resting_orders" / "metrics.csv"
    if f.exists():
        m = pd.read_csv(f)
        a, o = (_row(m, sample="S9", variant="R0", cost_mult=1, segment="ALL"), _row(m, sample="S9", variant="R0", cost_mult=1, segment="OOS"))
        add("S12", "Resting orders on S9's fades: net per filled order, and filled against unfilled at mid out-of-sample",
            f"{a.net_per_filled:+.2f} points [{a.net_lo:+.2f}, {a.net_hi:+.2f}] on {int(a.filled)} of {int(a.reachable)} orders; "
            f"out-of-sample difference {o.adverse_diff:+.2f} [{o.adverse_lo:+.2f}, {o.adverse_hi:+.2f}]", "adverse selection; not a pass")
    f = R / "s15_weekend_scare" / "tests.csv"
    if f.exists():
        r = _row(pd.read_csv(f), threshold=5.0, scope="all fresh markets", side="risers")
        m = _row(pd.read_csv(R / "s15_weekend_scare" / "metrics.csv"), variant="V0", segment="ALL", cost_mult=1.0)
        add("S15", "871 fresh price markets: change by Monday after a weekend rise of 5+ points, and against quiet markets",
            f"{r.mean_y:+.2f} points [{r.ci_lo:+.2f}, {r.ci_hi:+.2f}]; {r.diff_vs_quiet:+.2f} [{r.diff_ci_lo:+.2f}, {r.diff_ci_hi:+.2f}]; selling it nets "
            f"{m.mean_net_points:+.2f} [{m.ci_lo:+.2f}, {m.ci_hi:+.2f}]; {int(m.verified_trades)} of {int(m.checkable_trades)} entries print-verified",
            "replicates in quoted prices only; not a pass")
    f = R / "s16_kalshi_quotes" / "tests.csv"
    if f.exists():
        t = pd.read_csv(f)
        t = t[(t.quote_age == "6h") & (t.threshold == 10.0)]
        k, p_, kk = (t[t.test.str.startswith(x)].iloc[0] for x in ("K2 the same nights, Kalshi", "K2 the same nights, Polymarket", "K3 nights picked on Polymarket's move: Kalshi"))
        pp = t[t.test.str.startswith("K3 nights picked on Polymarket's move: Polymarket")].iloc[0]
        m = _row(pd.read_csv(R / "s16_kalshi_quotes" / "metrics.csv"), variant="V0", segment="ALL", cost_mult=1.0)
        add("S16", "After a 10+ point overnight move on one venue: that venue's price by the close, and the twin's on the same nights",
            f"picked on Kalshi: Kalshi {k['mean']:+.2f} [{k.ci_lo:+.2f}, {k.ci_hi:+.2f}], Polymarket {p_['mean']:+.2f}; picked on Polymarket: "
            f"Polymarket {pp['mean']:+.2f} [{pp.ci_lo:+.2f}, {pp.ci_hi:+.2f}], Kalshi {kk['mean']:+.2f}; the fade at Kalshi's real quotes nets "
            f"{m.mean_net_points:+.2f} points [{m.ci_lo:+.2f}, {m.ci_hi:+.2f}]", "the give-back is one venue's noise; not a pass")
    f = R / "s18_price_market_calibration" / "prints_tests.csv"
    if f.exists():
        t = pd.read_csv(f)
        sell, buy = "sellers: sold YES into a bid, held to the result", "buyers: bought YES at the ask, held to the result"
        b, sa, so = _row(t, test=buy, scope="all markets"), _row(t, test=sell, scope="all markets"), _row(t, test=sell, scope="out-of-sample events")
        add("S18", "Price markets at traded prices, held to the result: buyers of YES, and sellers at the bid",
            f"buyers {b.mean_pnl_points:+.2f} points per contract [{b.ci_lo:+.2f}, {b.ci_hi:+.2f}]; sellers {sa.mean_pnl_points:+.2f} "
            f"[{sa.ci_lo:+.2f}, {sa.ci_hi:+.2f}], out-of-sample {so.mean_pnl_points:+.2f} [{so.ci_lo:+.2f}, {so.ci_hi:+.2f}]",
            "buyers overpaid; selling fails out-of-sample; not a pass")
    f = R / "s19_crypto_price_markets" / "tests.csv"
    if f.exists():
        t = pd.read_csv(f)
        sell, buy = "sellers: sold YES into a bid, held to the result", "buyers: bought YES at the ask, held to the result"
        b, sa = _row(t, test=buy, scope="all markets"), _row(t, test=sell, scope="all markets")
        add("S19", "The same test on 1,265 crypto price markets, two years: sellers at the bid, and buyers",
            f"sellers {sa.mean_pnl_points:+.2f} points per contract [{sa.ci_lo:+.2f}, {sa.ci_hi:+.2f}]; buyers {b.mean_pnl_points:+.2f} "
            f"[{b.ci_lo:+.2f}, {b.ci_hi:+.2f}]", "S18's premium does not replicate")
    f = R / "s14_link_ceiling" / "tests.csv"
    if f.exists():
        t = pd.read_csv(f)
        ctrl = _row(t, test="C2 count of strong links", outcome="opening gap")
        o = _row(t, test="C1 oracle link", group="both groups, reversal links flipped", sample="out-of-sample")
        add("S14", "Links with the gap relation on their own, against shuffled; hindsight-picked links out-of-sample",
            f"{100 * ctrl.observed:.0f}% against {100 * ctrl.shuffle_mean:.0f}%; {o.slope:+.2f} bp per point (t = {o.t:.2f})",
            "neither a link nor a signal-definition problem")
    return pd.DataFrame(out)
