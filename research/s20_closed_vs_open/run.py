"""S20: the first weekend (shut) against the open week and the second weekend, at traded prices (METHOD.md). Cached prints only.

Run from `research/`:  python -m s20_closed_vs_open.run
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from s6_monday_fade.run import write_csv
from s7_weekend_straddle.run import boot_diff, boot_mean
from s18_price_market_calibration.prints import weighted, yes_terms
from s18_price_market_calibration.report import book as s18_book

from . import config as cfg
from . import windows as wn
from .pull import CACHE, RESEARCH, S18_CACHE, S18_RESULTS, plan

RESULTS = RESEARCH / "results" / "s20_closed_vs_open"
NAN = float("nan")
OK = "ok"
NO_FILE, NOT_SERVED, BEYOND = "no print file", "no print served at all (or the request failed)", "beyond the 20,000 prints the API keeps"
SIDES = (("buy", "buyers"), ("sell", "sellers"))
ALL, RANGE = "all markets", "traded price 2 to 98%"
BUCKET_NAMES = [f"traded price {100 * lo:.0f} to {100 * hi:.0f}%" for lo, hi in cfg.BUCKETS]
SCOPES = [ALL, RANGE, *BUCKET_NAMES, *cfg.CLASS_GROUPS, "in-sample events", "out-of-sample events"]
DIFFS = (("T1", "W1", "D1"), ("T2", "W2", "D1"), ("T2", "W1", "W2"))
PATHS = (("W1", "D1"), ("W2", "D1"))


# ---------------------------------------------------------------- one observation per market, window and side

def fee(p: float, rate: float, exponent: float, c: float = 1.0) -> float:
    return c * rate * (p * (1.0 - p)) ** exponent if 0.0 < p < 1.0 else 0.0


def observe(raw: list[dict], rate: float, exponent: float, outcome: float) -> dict:
    """S18's formulas: size-weighted mean traded YES price per taker side, and the P&L of holding to the result after the fee."""
    pr = [y for y in (yes_terms(t) for t in raw) if y]
    ps, size_s, n_s = weighted(pr, "SELL")
    pb, size_b, n_b = weighted(pr, "BUY")
    return {"prints_in_window": len(pr),
            "sell_prints": n_s, "sell_size": size_s, "sell_price": ps,
            "sell_pnl_points": 100 * (ps - fee(ps, rate, exponent) - outcome) if n_s else NAN,
            "sell_pnl_points_2x_fee": 100 * (ps - fee(ps, rate, exponent, 2.0) - outcome) if n_s else NAN,
            "buy_prints": n_b, "buy_size": size_b, "buy_price": pb,
            "buy_pnl_points": 100 * (outcome - pb - fee(pb, rate, exponent)) if n_b else NAN,
            "buy_pnl_points_2x_fee": 100 * (outcome - pb - fee(pb, rate, exponent, 2.0)) if n_b else NAN}


def reach_w1(rec: dict | None, entry: float) -> str:
    """S18's rule for its own cache: the first weekend is out of reach if 20,000 prints were served and none is older than the entry."""
    if rec is None:
        return NO_FILE
    if rec.get("reach_oldest") is None:
        return NOT_SERVED
    return BEYOND if rec["served"] >= cfg.PAGES * cfg.PAGE and rec["reach_oldest"] > entry else OK


def reach_later(rec: dict | None, start: float) -> str:
    """D1 and W2: the window is covered if the last page served was short (every print of the market came) or a print older than its start came."""
    if rec is None:
        return NO_FILE
    if rec.get("reach_oldest") is None:
        return NOT_SERVED
    return BEYOND if rec["served"] % cfg.PAGE == 0 and rec["reach_oldest"] > start else OK


def _load(f: Path) -> dict | None:
    return json.loads(f.read_text()) if f.exists() else None


def group_of(asset_class: str) -> str:
    return next((g for g, cs in cfg.CLASS_GROUPS.items() if asset_class in cs), "other")


def build(now: float) -> pd.DataFrame:
    """One row per market, window and rule."""
    rows = []
    for m in plan():
        s18, mine = _load(S18_CACHE / f"prints_{m['market']}.json"), _load(CACHE / f"prints_{m['market']}.json")
        for w in cfg.WINDOWS:
            spans = m["windows"][w]
            b = wn.bounds(spans)
            if w == "W1":
                raw, reach = (s18 or {}).get("prints", []), reach_w1(s18, m["entry_epoch"])
            else:
                raw, reach = (mine or {}).get(w.lower(), []), (reach_later(mine, b[0]) if b else NO_FILE)
            for rule in cfg.RULES:
                st = wn.status(rule, spans, m["result_epoch"], now)
                st = st if st != "in" else ("in" if reach == OK else reach)
                rows.append({"rule": rule, "window": w, "status": st, "market": m["market"], "event": m["event"], "segment": m["segment"],
                             "universe": m["universe"], "asset_class": m["asset_class"], "group": group_of(m["asset_class"]), "kind": m["kind"],
                             "sign": m["sign"], "question": m["question"], "outcome": m["outcome"], "fee_rate": m["fee_rate"],
                             "window_start": b[0] if b else NAN, "window_end": b[1] if b else NAN, "sessions": len(spans) if w == "D1" else NAN,
                             "result_epoch": m["result_epoch"], **observe(raw if st == "in" else [], m["fee_rate"], m["fee_exponent"], m["outcome"])})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- scopes and tests

def in_scope(d: pd.DataFrame, scope: str, price: pd.Series) -> pd.Series:
    if scope == ALL:
        return pd.Series(True, index=d.index)
    if scope == RANGE:
        return (price >= cfg.BUCKETS[0][0]) & (price < cfg.BUCKETS[-1][1])
    if scope in BUCKET_NAMES:
        lo, hi = cfg.BUCKETS[BUCKET_NAMES.index(scope)]
        return (price >= lo) & (price < hi)
    if scope in cfg.CLASS_GROUPS:
        return d.group == scope
    return d.segment == ("IS" if scope.startswith("in-sample") else "OOS")


def by_event(d: pd.DataFrame, col: str) -> dict[str, list[float]]:
    return {e: list(v) for e, v in d.groupby("event")[col]}


def side_frame(d: pd.DataFrame, window: str, side: str, col: str, scope: str) -> pd.DataFrame:
    s = d[(d.window == window) & (d.status == "in") & d[col].notna()]
    return s[in_scope(s, scope, s[f"{side}_price"])]


def tests(d: pd.DataFrame, rule: str) -> list[dict]:
    """Levels per window, differences between windows (T1, T2) and the price path on the same markets (T3)."""
    d, out = d[d.rule == rule], []
    for scope in SCOPES:
        for side, who in SIDES:
            for c in cfg.FEE_MULTIPLIERS:
                col = f"{side}_pnl_points" + ("" if c == 1.0 else "_2x_fee")
                frames = {w: side_frame(d, w, side, col, scope) for w in cfg.WINDOWS}
                for w, s in frames.items():
                    b = boot_mean(by_event(s, col))
                    out.append({"rule": rule, "kind": "level", "test": f"{who}: mean P&L held to the result", "windows": w, "side": side, "scope": scope,
                                "fee_mult": c, "markets": len(s), "events": int(s.event.nunique()),
                                "mean_traded_price": float(100 * s[f"{side}_price"].mean()) if len(s) else NAN,
                                "share_yes": float(100 * s.outcome.mean()) if len(s) else NAN, "estimate": b[0], "ci_lo": b[1], "ci_hi": b[2],
                                "median_size": float(s[f"{side}_size"].median()) if len(s) else NAN})
                for label, a, b_ in DIFFS:
                    sa, sb = frames[a], frames[b_]
                    x = boot_diff(by_event(sa, col), by_event(sb, col))
                    out.append({"rule": rule, "kind": "difference", "test": f"{label} {who}: mean P&L, {a} minus {b_}", "windows": f"{a}-{b_}", "side": side,
                                "scope": scope, "fee_mult": c, "markets": len(sa), "events": int(sa.event.nunique()), "markets_b": len(sb),
                                "events_b": int(sb.event.nunique()), "estimate": x[0], "ci_lo": x[1], "ci_hi": x[2]})
            pcol = f"{side}_price"
            for a, b_ in PATHS:
                wa = d[(d.window == a) & (d.status == "in") & d[pcol].notna()].set_index("market")
                wb = d[(d.window == b_) & (d.status == "in") & d[pcol].notna()].set_index("market")
                j = wa.join(wb[[pcol]].rename(columns={pcol: "other"}), how="inner")
                j = j.assign(diff=100 * (j[pcol] - j.other), mid=(j[pcol] + j.other) / 2)
                j = j[in_scope(j, scope, j.mid)]
                x = boot_mean(by_event(j, "diff"))
                out.append({"rule": rule, "kind": "path", "test": f"T3 {who}: traded price on the same markets, {a} minus {b_}", "windows": f"{a}-{b_}",
                            "side": side, "scope": scope, "fee_mult": NAN, "markets": len(j), "events": int(j.event.nunique()),
                            "mean_traded_price": float(100 * j[pcol].mean()) if len(j) else NAN, "mean_traded_price_b": float(100 * j.other.mean()) if len(j) else NAN,
                            "share_yes": float(100 * j.outcome.mean()) if len(j) else NAN, "estimate": x[0], "ci_lo": x[1], "ci_hi": x[2]})
    return out


def books(d: pd.DataFrame, rule: str) -> tuple[list[dict], list[dict]]:
    """T4: the sellers' book per window with S18's book function."""
    d, rows, eq = d[(d.rule == rule) & (d.status == "in")], [], []
    for w in cfg.WINDOWS:
        dw = d[(d.window == w) & d.sell_pnl_points.notna()]
        for scope in SCOPES[:-2]:
            s = dw[in_scope(dw, scope, dw.sell_price)]
            if not len(s):
                continue
            entries = s[["market", "result_epoch"]].assign(entry_epoch=s.window_start)
            for c in cfg.FEE_MULTIPLIERS:
                pm = s if c == 1.0 else s.assign(sell_pnl_points=s.sell_pnl_points_2x_fee)
                monthly, out = s18_book(pm, entries, "sell")
                for seg, v in out.items():
                    rows.append({"rule": rule, "window": w, "scope": scope, "fee_mult": c, "segment": seg, **v})
                if scope == ALL:
                    eq += [{"rule": rule, "window": w, "fee_mult": c, "month": r.result_month, "pnl": float(r.pnl)} for r in monthly.itertuples()]
    return rows, eq


def counts(d: pd.DataFrame) -> list[dict]:
    out = []
    for rule in cfg.RULES:
        for w in cfg.WINDOWS:
            s = d[(d.rule == rule) & (d.window == w)]
            k = s[s.status == "in"]
            out.append({"rule": rule, "window": w, "markets": len(s), "counted": len(k), "events_counted": int(k.event.nunique()),
                        "share_yes_counted": float(100 * k.outcome.mean()) if len(k) else NAN,
                        "with_a_print": int(k.prints_in_window.gt(0).sum()), "with_a_taker_buy": int(k.buy_prints.gt(0).sum()),
                        "events_with_a_taker_buy": int(k[k.buy_prints > 0].event.nunique()), "with_a_taker_sell": int(k.sell_prints.gt(0).sum()),
                        "events_with_a_taker_sell": int(k[k.sell_prints > 0].event.nunique()), "prints": int(k.prints_in_window.sum()),
                        **{f"left out: {reason}": int(n) for reason, n in s[s.status != "in"].status.value_counts().items()}})
    return out


def reproduces_s18(t: list[dict], b: list[dict]) -> dict:
    """W1 under rule B is S18's own test: it must return S18's committed numbers."""
    ref = pd.read_csv(S18_RESULTS / "prints_tests.csv")
    ref = ref[ref.scope == "all markets"]
    rb = pd.read_csv(S18_RESULTS / "prints_book.csv")
    out, ok = {}, True
    for side, who, name in (("buy", "buyers", "buyers: bought YES at the ask, held to the result"), ("sell", "sellers", "sellers: sold YES into a bid, held to the result")):
        mine = next(r for r in t if r["rule"] == "B" and r["kind"] == "level" and r["windows"] == "W1" and r["side"] == side and r["scope"] == ALL and r["fee_mult"] == 1.0)
        theirs = ref[ref.test == name].iloc[0]
        same = int(theirs.markets) == mine["markets"] and all(abs(float(theirs[k]) - mine[q]) < 1e-9 for k, q in (("mean_pnl_points", "estimate"), ("ci_lo", "ci_lo"), ("ci_hi", "ci_hi")))
        out[who] = {"s18": [int(theirs.markets), float(theirs.mean_pnl_points), float(theirs.ci_lo), float(theirs.ci_hi)],
                    "s20_w1_rule_b": [mine["markets"], mine["estimate"], mine["ci_lo"], mine["ci_hi"]], "same": bool(same)}
        ok &= same
    mine = next(r for r in b if r["rule"] == "B" and r["window"] == "W1" and r["scope"] == ALL and r["fee_mult"] == 1.0 and r["segment"] == "ALL")
    theirs = rb[(rb.book == "sellers") & (rb.segment == "ALL")].iloc[0]
    same = abs(float(theirs.pnl) - mine["pnl"]) < 1e-6 and abs(float(theirs.sharpe) - mine["sharpe"]) < 1e-9
    out["sellers_book"] = {"s18": [float(theirs.pnl), float(theirs.sharpe)], "s20_w1_rule_b": [mine["pnl"], mine["sharpe"]], "same": bool(same)}
    return {"all_same": bool(ok and same), **out}


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    pull_meta = json.loads((CACHE / "pull_meta.json").read_text())
    d = build(float(pull_meta["started"]))
    t, b, eq = [], [], []
    for rule in cfg.RULES:
        t += tests(d, rule)
        rb, re_ = books(d, rule)
        b, eq = b + rb, eq + re_
    cn = counts(d)
    write_csv(RESULTS / "trades.csv", d.to_dict("records"))
    write_csv(RESULTS / "metrics.csv", t)
    write_csv(RESULTS / "books.csv", b)
    write_csv(RESULTS / "equity.csv", eq)
    write_csv(RESULTS / "counts.csv", cn)
    rep = reproduces_s18(t, b)
    meta = {"markets": int(d.market.nunique()), "events": int(d.event.nunique()), "pull": pull_meta, "reproduces_s18": rep,
            "max_sharpe_in_books": float(np.nanmax([r["sharpe"] for r in b])), "run_seconds": round(time.time() - t_run, 1)}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k != "pull"}))
    for r in cn:
        print({k: v for k, v in r.items()})
    for r in t:
        if r["scope"] in (ALL, RANGE, *cfg.CLASS_GROUPS) and r["fee_mult"] != 2.0:
            print(f"{r['rule']} | {r['test'][:58]:58} | {r['windows']:5} | {r['scope'][:22]:22} | n {r['markets']:4d} ev {r['events']:3d} | "
                  f"{r['estimate']:7.2f} [{r['ci_lo']:7.2f},{r['ci_hi']:7.2f}]")
    for r in b:
        if r["scope"] == ALL:
            print(f"{r['rule']} book {r['window']} {r['fee_mult']:.0f}x {r['segment']:3} | n {r['trades']:4d} | pnl {r['pnl']:9.0f} | K {r['capital_base']:8.0f} | "
                  f"sharpe {r['sharpe']:6.2f} | maxDD {r['max_drawdown']:.3f} | worst month {r['worst_month']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
