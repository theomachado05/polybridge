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
from .pull import CACHE, RESEARCH, S18, NotPulled, Src, plan, recorder_failures

RESULTS = RESEARCH / "results" / "s25_ticket_option_hedge"
SETS = ("full", "rule", "left")
SEGMENTS = ("ALL", "IS", "OOS")
V = {v.id: v for v in cfg.VARIANTS}


def by_event(s: pd.DataFrame, col: str) -> dict[str, list[float]]:
    return {str(e): list(v) for e, v in s.groupby("event")[col]}


def close_status(src: Src, r) -> tuple[str, dict]:
    index = r.agg_ticker.startswith("I:")
    try:
        raw = src.daily(r.agg_ticker, cfg.CLOSE_FROM, cfg.CLOSE_TO, adjusted=False)
        adj = raw if index else src.daily(r.agg_ticker, cfg.CLOSE_FROM, cfg.CLOSE_TO, adjusted=True)
        splits = [] if index else src.splits(r.agg_ticker)
    except NotPulled:
        return "the underlying's closes or splits are not served", {}
    if not index and eg.split_between(splits, r.anchor_day, r.expiry):
        return "a split between the first weekend and the expiry", {}
    if r.expiry not in raw:
        return "no close on the expiry date", {}
    c_exp = raw[r.expiry][0]
    if not index and (r.expiry not in adj or not eg.reconciles(adj[r.expiry][0], c_exp, splits, r.expiry)):
        return "the close does not reconcile with the listed splits", {}
    c_anchor = raw.get(r.anchor_day, [float("nan")])[0]
    if not eg.level_ratio_ok(c_anchor, r.level):
        return "the level and the price are on different bases", {}
    return "ok", {"close_expiry": c_exp, "close_anchor_day": c_anchor}


def monday_status(src: Src, r) -> tuple[str, dict]:
    out, bad = {}, []
    for name, leg in (("lo", r.leg_lo), ("hi", r.leg_hi)):
        try:
            q = src.quote(leg, r.hedge_epoch)
        except NotPulled:
            return "not pulled", {}
        if q is None:
            bad.append("no quote at or before Monday 09:35")
        elif not eg.usable(q, r.hedge_epoch, r.open_epoch):
            bad.append("no usable quote at Monday 09:35 (from before the open, or no offer)")
        if q is not None:
            out.update({f"mon_{name}_bid": q["bid"], f"mon_{name}_ask": q["ask"], f"mon_{name}_bid_size": q["bsz"], f"mon_{name}_ask_size": q["asz"],
                        f"mon_{name}_age_s": r.hedge_epoch - q["ts"]})
    return (bad[0] if bad else "ok"), out


def leg_volume(src: Src, leg: str, day: str) -> float:
    try:
        v = src.daily(leg, day, day, adjusted=False)
    except NotPulled:
        return float("nan")
    return float(v[day][1]) if day in v else 0.0


def build_rows(src: Src, d: pd.DataFrame) -> list[dict]:
    rows = []
    for r in d.itertuples():
        up = r.direction > 0
        width = r.k_hi - r.k_lo
        size = float(min(r.sell_size, cfg.CONTRACTS))
        row = {"market": r.market, "event": r.event, "segment": r.segment, "ticker": r.ticker, "question": r.question, "direction": r.direction,
               "level": r.level, "rule": bool(r.rule), "anchor_day": r.anchor_day, "hedge_day": r.hedge_day, "expiry": r.expiry,
               "days_expiry_after_end": r.days_expiry_after_end, "option_type": r.option_type, "k_lo": r.k_lo, "k_hi": r.k_hi, "width": width,
               "long_leg": r.leg_lo if up else r.leg_hi, "short_leg": r.leg_hi if up else r.leg_lo, "s21_stepped": r.stepped,
               "anchor_central": r.anchor_central, "sell_price": r.sell_price, "outcome": r.outcome, "printed_size": r.sell_size, "contracts": size,
               "ticket_pnl_points": r.sell_pnl_points, "ticket_pnl_points_2x": r.sell_pnl_points_2x_fee,
               "ticket_capital_points": 100.0 * (1.0 - r.sell_price), "entry_epoch": r.entry_epoch, "result_epoch": r.result_epoch,
               "anchor_epoch": r.anchor_epoch, "hedge_epoch": r.hedge_epoch, "expiry_epoch": r.expiry_epoch,
               "fri_lo_bid": r.leg_lo_bid, "fri_lo_ask": r.leg_lo_ask, "fri_hi_bid": r.leg_hi_bid, "fri_hi_ask": r.leg_hi_ask}
        cs, cinfo = close_status(src, r)
        ms, minfo = monday_status(src, r)
        row.update(cinfo)
        row.update(minfo)
        row["close_status"], row["monday_status"] = cs, ms
        row["status"] = cs if cs != "ok" else ms
        if cs == "ok":
            row["payoff_unit"] = eg.unit_payoff(r.direction, row["close_expiry"], r.k_lo, r.k_hi)
            row["finished_beyond"] = eg.finished_beyond(r.direction, row["close_expiry"], r.level)
            row["cell"] = eg.cell(r.outcome, r.direction, row["close_expiry"], r.level)
            row["result_before_hedge"] = bool(r.result_epoch < r.hedge_epoch)
        for v in cfg.VARIANTS:
            if cs != "ok" or (v.quotes == "monday" and ms != "ok"):
                continue
            q = (minfo["mon_lo_bid"], minfo["mon_lo_ask"], minfo["mon_hi_bid"], minfo["mon_hi_ask"]) if v.quotes == "monday" else \
                (r.leg_lo_bid, r.leg_lo_ask, r.leg_hi_bid, r.leg_hi_ask)
            c = eg.unit_cost(r.direction, *q, width, v.cost_mult)
            ticket = r.sell_pnl_points if v.cost_mult == 1.0 else r.sell_pnl_points_2x_fee
            hp = eg.hedge_pnl_points(v.h, row["payoff_unit"], c["cost"])
            row.update({f"unit_cost_{v.id}": c["cost"], f"unit_mid_{v.id}": c["mid"], f"crossed_{v.id}": c["crossed"], f"above_one_{v.id}": c["above_one"],
                        f"hedge_cost_points_{v.id}": 100.0 * v.h * c["cost"], f"hedge_payoff_points_{v.id}": 100.0 * v.h * row["payoff_unit"],
                        f"hedge_pnl_points_{v.id}": hp, f"hedged_pnl_points_{v.id}": ticket + hp})
        row["long_leg_volume_hedge_day"] = leg_volume(src, row["long_leg"], r.hedge_day)
        row["short_leg_volume_hedge_day"] = leg_volume(src, row["short_leg"], r.hedge_day)
        rows.append(row)
    return rows


def legs_of(t: pd.DataFrame, strategy: str) -> pd.DataFrame:
    two = strategy.endswith("2x")
    tp = t.ticket_pnl_points_2x if two else t.ticket_pnl_points
    base = {"market": t.market, "event": t.event.astype(str), "segment": t.segment}
    ticket = pd.DataFrame({**base, "pnl": t.contracts * tp / 100.0, "capital": t.contracts * (1.0 - t.sell_price),
                           "entry_epoch": t.entry_epoch, "end_epoch": t.result_epoch, "leg": "ticket"})
    if strategy in ("U", "U2x"):
        return ticket
    v = V[strategy]
    hedge = pd.DataFrame({**base, "pnl": t.contracts * t[f"hedge_pnl_points_{v.id}"] / 100.0, "capital": t.contracts * v.h * t[f"unit_cost_{v.id}"],
                          "entry_epoch": t.hedge_epoch if v.quotes == "monday" else t.anchor_epoch, "end_epoch": t.expiry_epoch, "leg": "hedge"})
    return pd.concat([ticket, hedge], ignore_index=True)


def pnl_col(strategy: str) -> str:
    return {"U": "ticket_pnl_points", "U2x": "ticket_pnl_points_2x"}.get(strategy, f"hedged_pnl_points_{strategy}")


def subset(t: pd.DataFrame, name: str) -> pd.DataFrame:
    return t if name == "full" else t[t.rule] if name == "rule" else t[~t.rule]


def metric_rows(t_all: pd.DataFrame, scope: str, strategies: list[str]) -> tuple[list[dict], list[dict]]:
    out, monthly = [], []
    for sname in SETS:
        t = subset(t_all, sname)
        for st in strategies:
            col = pnl_col(st)
            mon, bk = eg.book(legs_of(t, st)) if len(t) else (pd.DataFrame(columns=["month", "pnl"]), {})
            lg = legs_of(t, st) if len(t) else pd.DataFrame(columns=["leg", "capital", "segment"])
            for r in mon.itertuples():
                monthly.append({"scope": scope, "set": sname, "strategy": st, "month": r.month, "pnl": float(r.pnl), "capital_base": bk["ALL"]["capital_base"]})
            for seg in SEGMENTS:
                x = t if seg == "ALL" else t[t.segment == seg]
                m = boot_mean(by_event(x, col))
                b = bk.get(seg, {})
                ls = lg if seg == "ALL" else lg[lg.segment == seg]
                row = {"scope": scope, "set": sname, "strategy": st, "segment": seg, "markets": len(x), "events": int(x.event.nunique()),
                       "mean_pnl_points": m[0], "ci_lo": m[1], "ci_hi": m[2], **eg.risk_stats(x[col]),
                       "share_yes": float(100 * x.outcome.mean()) if len(x) else float("nan"),
                       "mean_ticket_price": float(100 * x.sell_price.mean()) if len(x) else float("nan"),
                       "mean_ticket_pnl_points": float((x.ticket_pnl_points_2x if st.endswith("2x") else x.ticket_pnl_points).mean()) if len(x) else float("nan")}
                if st not in ("U", "U2x"):
                    row.update({"mean_hedge_cost_points": float(x[f"hedge_cost_points_{st}"].mean()) if len(x) else float("nan"),
                                "mean_hedge_payoff_points": float(x[f"hedge_payoff_points_{st}"].mean()) if len(x) else float("nan"),
                                "mean_hedge_pnl_points": float(x[f"hedge_pnl_points_{st}"].mean()) if len(x) else float("nan")})
                row.update({"book_pnl": b.get("pnl", float("nan")), "capital_base": b.get("capital_base", float("nan")),
                            "ticket_capital_deployed": float(ls[ls.leg == "ticket"].capital.sum()) if len(ls) else float("nan"),
                            "hedge_capital_deployed": float(ls[ls.leg == "hedge"].capital.sum()) if len(ls) else float("nan"),
                            **{k: b.get(k, float("nan")) for k in ("sharpe", "max_drawdown", "worst_month", "worst_month_dollars", "total_return", "months",
                                                                  "losing_months", "monthly_skew")}})
                out.append(row)
    return out, monthly


def hypothesis_rows(t_all: pd.DataFrame) -> list[dict]:
    out = []
    for vid in ("P", "A", "B", "P2x", "A2x", "B2x"):
        hcol, ucol, ust = pnl_col(vid), pnl_col("U2x" if vid.endswith("2x") else "U"), ("U2x" if vid.endswith("2x") else "U")
        for seg in SEGMENTS:
            x_all = t_all if seg == "ALL" else t_all[t_all.segment == seg]
            judged = vid == cfg.PRIMARY and seg == "ALL"
            for sname in ("rule", "full"):
                x = subset(x_all, sname)
                base = {"variant": vid, "segment": seg, "set": sname, "markets": len(x), "events": int(x.event.nunique())}
                m = boot_mean(by_event(x, hcol))
                if sname == "rule":
                    out.append({**base, "hypothesis": "H1", "what": "mean hedged P&L per ticket, points", "value": m[0], "ci_lo": m[1], "ci_hi": m[2],
                                "judged": judged, "passes": bool(m[0] > 0 and m[1] == m[1] and m[1] > 0)})
                if len(x) >= 2:
                    r = eg.boot_sd_ratio(x[hcol], x[ucol], x.event)
                    sd_h, sd_u = float(np.std(x[hcol], ddof=1)), float(np.std(x[ucol], ddof=1))
                else:
                    r, sd_h, sd_u = (float("nan"),) * 3, float("nan"), float("nan")
                out.append({**base, "hypothesis": "H2a", "what": "sd of hedged P&L per market / sd unhedged", "value": r[0], "ci_lo": r[1], "ci_hi": r[2],
                            "hedged": sd_h, "unhedged": sd_u, "judged": judged and sname == "rule",
                            "passes": bool(r[0] < 1 and r[2] == r[2] and r[2] < 1)})
                if len(x):
                    lh, lu = legs_of(x, vid), legs_of(x, ust)
                    _, bh = eg.book(lh)
                    _, bu = eg.book(lu)
                    months = sorted(pd.period_range(lh.end_epoch.map(eg.month_of).min(), lh.end_epoch.map(eg.month_of).max(), freq="M").strftime("%Y-%m"))
                    evs = sorted(set(lh.event))
                    wd = eg.boot_worst_month_diff(eg.event_month_matrix(lh, evs, months), eg.event_month_matrix(lu, evs, months))
                    wh, wu = bh["ALL"]["worst_month_dollars"], bu["ALL"]["worst_month_dollars"]
                    out.append({**base, "hypothesis": "H2b", "what": "worst month of the hedged book minus the unhedged book's, dollars", "value": wh - wu,
                                "ci_lo": wd[1], "ci_hi": wd[2], "hedged": wh, "unhedged": wu, "share_of_draws_not_worse": wd[3],
                                "hedged_pct_of_capital": bh["ALL"]["worst_month"], "unhedged_pct_of_capital": bu["ALL"]["worst_month"],
                                "judged": judged and sname == "rule", "passes": bool(wh >= wu - 1e-9)})
            ru, le = subset(x_all, "rule"), subset(x_all, "left")
            df = boot_diff(by_event(ru, hcol), by_event(le, hcol)) if len(ru) and len(le) else (float("nan"),) * 3
            out.append({"variant": vid, "segment": seg, "set": "rule minus left", "markets": len(ru), "events": int(x_all.event.nunique()),
                        "hypothesis": "H3", "what": "mean hedged P&L, rule subset minus left markets, points", "value": df[0], "ci_lo": df[1],
                        "ci_hi": df[2], "rule_mean": float(ru[hcol].mean()) if len(ru) else float("nan"),
                        "left_mean": float(le[hcol].mean()) if len(le) else float("nan"), "left_markets": len(le), "judged": judged,
                        "passes": bool(df[0] > 0 and df[1] == df[1] and df[1] > 0)})
    return out


def cell_rows(t_all: pd.DataFrame) -> list[dict]:
    out = []
    for sname in SETS:
        t = subset(t_all, sname)
        for c in eg.CELLS + ("every market",):
            x = t if c == "every market" else t[t.cell == c]
            row = {"set": sname, "cell": c, "markets": len(x), "events": int(x.event.nunique()), "share_of_markets": float(len(x) / len(t)) if len(t) else float("nan")}
            if len(x):
                row.update({"mean_ticket_price": float(100 * x.sell_price.mean()), "ticket_pnl_points": float(x.ticket_pnl_points.mean()),
                            "payoff_unit": float(x.payoff_unit.mean())})
                for vid in ("P", "A", "B"):
                    row.update({f"hedge_cost_points_{vid}": float(x[f"hedge_cost_points_{vid}"].mean()), f"hedge_pnl_points_{vid}": float(x[f"hedge_pnl_points_{vid}"].mean()),
                                f"hedged_pnl_points_{vid}": float(x[f"hedged_pnl_points_{vid}"].mean()),
                                f"hedged_sum_points_{vid}": float(x[f"hedged_pnl_points_{vid}"].sum())})
                row["ticket_sum_points"] = float(x.ticket_pnl_points.sum())
            out.append(row)
    return out


def recheck(src: Src, t: pd.DataFrame) -> dict:
    pm = pd.read_csv(S18 / "prints_markets.csv", dtype={"market": str}).set_index("market")
    bad = 0
    for r in t.itertuples():
        iso = datetime.fromtimestamp(r.hedge_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ql, qs = src.cache[f"q|{r.long_leg}|{iso}"], src.cache[f"q|{r.short_leg}|{iso}"]
        close = src.cache[f"d|{cfg.INDEX_AGG_TICKER.get(r.ticker, r.ticker)}|{cfg.CLOSE_FROM}|{cfg.CLOSE_TO}|raw"][r.expiry][0]
        w = r.k_hi - r.k_lo
        intrinsic_long = max(close - r.k_lo, 0.0) if r.direction > 0 else max(r.k_hi - close, 0.0)
        intrinsic_short = max(close - r.k_hi, 0.0) if r.direction > 0 else max(r.k_lo - close, 0.0)
        pay = (intrinsic_long - intrinsic_short) / w
        cost = max(0.0, ql["ask"] - qs["bid"]) / w + 2 * 0.65 / (100 * w)
        again = float(pm.loc[r.market, "sell_pnl_points"]) + 200.0 * (pay - cost)
        bad += int(abs(again - r.hedged_pnl_points_P) > 1e-6)
    return {"recomputed": int(len(t)), "mismatches": bad}


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    d = plan()
    src = Src(offline=True)
    rows = build_rows(src, d)
    drop = ["entry_epoch", "result_epoch", "anchor_epoch", "hedge_epoch", "expiry_epoch"]
    write_csv(RESULTS / "trades.csv", [{k: v for k, v in r.items() if k not in drop} for r in rows])
    t = pd.DataFrame(rows)
    for c in ("close_expiry", "mon_lo_bid", "hedged_pnl_points_P", "hedged_pnl_points_B", "cell", "payoff_unit"):
        if c not in t.columns:
            t[c] = np.nan
    prim = t[t.status == "ok"].copy()
    bset = t[t.close_status == "ok"].copy()
    status = t.status.value_counts().to_dict()
    monday_not_served = int((t.monday_status != "ok").sum())
    if len(prim) == 0:
        print("STOP: no market has usable Monday quotes and a verified close.", json.dumps(status, indent=1))
        (RESULTS / "run_meta.json").write_text(json.dumps({"status": status, "stopped": True}, indent=1))
        return 2

    m1, mon1 = metric_rows(prim, "primary", ["U", "P", "A", "B", "U2x", "P2x", "A2x", "B2x"])
    m2, mon2 = metric_rows(bset, "B", ["U", "B", "U2x", "B2x"])
    write_csv(RESULTS / "metrics.csv", m1 + m2)
    write_csv(RESULTS / "equity.csv", mon1 + mon2)
    write_csv(RESULTS / "hypotheses.csv", hypothesis_rows(prim))
    write_csv(RESULTS / "cells.csv", cell_rows(prim))

    x = prim.copy()
    x["market"] = x.market.astype(int)
    x = x.rename(columns={"ticket_pnl_points": "sell_pnl_points", "printed_size": "sell_size"})
    _, bk18 = s18_book(x, pd.read_csv(S18 / "entries.csv"), "sell")
    _, bk = eg.book(legs_of(prim, "U"))
    same = all(abs(bk18["ALL"][k] - bk["ALL"][k]) < 1e-9 for k in ("sharpe", "max_drawdown", "worst_month", "capital_base", "pnl"))

    ages = pd.concat([prim.mon_lo_age_s, prim.mon_hi_age_s])
    fb = prim[prim.cell == eg.CELLS[3]]
    log = (CACHE / "pull.log").read_text().splitlines() if (CACHE / "pull.log").exists() else []
    spread_pct = lambda b, a: 100.0 * (a - b) / ((a + b) / 2.0)
    meta = {"markets_in_plan": int(len(d)), "events_in_plan": int(d.event.nunique()), "rule_subset_in_plan": int(d.rule.sum()),
            "hedged_primary": int(len(prim)), "hedged_primary_events": int(prim.event.nunique()),
            "hedged_primary_by_segment": {k: int(v) for k, v in prim.segment.value_counts().items()},
            "hedged_primary_rule": int(prim.rule.sum()), "hedged_primary_rule_by_segment": {k: int(v) for k, v in prim[prim.rule].segment.value_counts().items()},
            "dropped": int(len(t) - len(prim)), "status": status, "status_rule_subset": t[t.rule].status.value_counts().to_dict(),
            "close_status": t.close_status.value_counts().to_dict(), "monday_status": t.monday_status.value_counts().to_dict(),
            "markets_without_a_usable_monday_pair": monday_not_served,
            "variant_B_own_set": int(len(bset)), "variant_B_own_rule": int(bset.rule.sum()),
            "dropped_by_ticker": {k: int(v) for k, v in t[t.status != "ok"].ticker.value_counts().items()},
            "hedged_by_ticker": {k: int(v) for k, v in prim.ticker.value_counts().items()},
            "monday_quote_age_s": {"min": float(ages.min()), "median": float(ages.median()), "max": float(ages.max())},
            "crossed_pairs_P": int(prim.crossed_P.sum()), "above_one_P": int(prim.above_one_P.sum()), "crossed_pairs_B": int(prim.crossed_B.sum()),
            "zero_bid_short_leg_P": int((np.where(prim.direction > 0, prim.mon_hi_bid, prim.mon_lo_bid) <= 0).sum()),
            "result_before_hedge": int(prim.result_before_hedge.sum()),
            "finished_beyond_without_touch": [{"market": r.market, "ticker": r.ticker, "question": r.question, "expiry": r.expiry,
                                               "days_expiry_after_end": float(r.days_expiry_after_end), "close_expiry": r.close_expiry, "level": r.level,
                                               "rule": bool(r.rule)} for r in fb.itertuples()],
            "copied_book_equals_s18_book_on_ticket_leg": bool(same), "recheck": recheck(src, prim),
            "median_unit_cost_P": float(prim.unit_cost_P.median()), "median_unit_mid_P": float(prim.unit_mid_P.median()),
            "median_unit_cost_B": float(prim.unit_cost_B.median()), "median_unit_mid_B": float(prim.unit_mid_B.median()),
            "median_width": float(prim.width.median()),
            "recorder_fetch_failed_now": recorder_failures(), "cache_lines": len(src.cache), "pull_log": log,
            "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "run_seconds": round(time.time() - t_run, 1)}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k != "pull_log"}, indent=1))
    for r in m1:
        if r["segment"] == "ALL":
            print(f"{r['set']:5} {r['strategy']:4} mkts {r['markets']:4d} mean {r['mean_pnl_points']:7.2f} [{r['ci_lo']:7.2f},{r['ci_hi']:7.2f}] sd {r['sd']:6.2f} "
                  f"worst {r['worst_market']:8.2f} skew {r['skew']:6.2f} ${r['book_pnl']:8.0f} K {r['capital_base']:7.0f} sharpe {r['sharpe']:6.2f} "
                  f"dd {r['max_drawdown']:6.3f} worst month {r['worst_month']:7.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
