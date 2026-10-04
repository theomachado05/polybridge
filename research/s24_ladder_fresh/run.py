"""S24 run: detect out-of-order ladders from prints, fix the out-of-sample cut from the dates, then settle the trades.

Run from `research/`:
    python -m s24_ladder_fresh.run detect     # prints only: matches.csv, coverage.csv, oos_cut.json. No result is read.
    python -m s24_ladder_fresh.run settle     # results and P&L: trades.csv
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config as cfg
from . import engine as en

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
PRINTS = CACHE / "prints"
RESULTS = HERE.parent / "results" / "s24_ladder_fresh"
ET = ZoneInfo("America/New_York")
VARIANTS = {"W600": cfg.WINDOW_S, "W120": cfg.WINDOW_VARIANT_S}      # W600 is the primary
LAST_DAY = "2026-10-04"                                               # a pair without both results is carried to this day


def ts(s) -> float | None:
    """A catalogue time as epoch seconds."""
    if not s:
        return None
    s = str(s).replace("Z", "+00:00")
    if "T" not in s:
        s = s.replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    d = datetime.fromisoformat(s)
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


_mem: dict[str, dict | None] = {}


def prints(mid: str) -> dict | None:
    if mid not in _mem:
        f = PRINTS / f"{mid}.npz"
        if f.exists():
            z = np.load(f)
            yp, ys = en.yes_terms(z["price"], z["side"], z["out"])
            ok = (z["out"] >= 0) & (z["side"] != 0)
            _mem[mid] = {"t": z["t"], "price": z["price"], "side": z["side"], "out": z["out"], "size": z["size"], "yp": yp, "ys": ys,
                         "ok": ok, "served": int(z["served"][0]), "capped": bool(int(z["served"][0]) >= cfg.PRINT_PAGE * cfg.PRINT_PAGES)}
        else:
            _mem[mid] = None
    return _mem[mid]


def raw(p: dict, k: int) -> str:
    return f"{'BUY' if p['side'][k] > 0 else 'SELL'} {'Yes' if p['out'][k] == 1 else 'No'} @{p['price'][k]:.4f}"


def pair_matches(a: dict, b: dict, fa, fb, t_close: float | None, window: int) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """Matches of one pair. a: the rich rung's prints, b: the cheap rung's. Prints at or after the first close are dropped;
    so are prints whose fills would not exist at 1x and 2x costs."""
    h = max(c["haircut"] for c in cfg.COSTS.values())
    sa = a["ok"] & (a["ys"] == -1) & (a["yp"] - h >= cfg.PRICE_CLIP[0] - 1e-12)
    sb = b["ok"] & (b["ys"] == 1) & (b["yp"] + h <= cfg.PRICE_CLIP[1] + 1e-12)
    if t_close is not None:
        sa &= a["t"] < t_close
        sb &= b["t"] < t_close
    ia, ib = np.flatnonzero(sa), np.flatnonzero(sb)
    ms = en.first_matches(a["t"][ia], a["yp"][ia], a["size"][ia], b["t"][ib], b["yp"][ib], b["size"][ib], fa, fb, window)
    return ms, ia, ib


def detect() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    L = json.loads((HERE / "ladders.json").read_text())
    st = json.loads((CACHE / "pull_state.json").read_text())
    M = L["markets"]
    rows, cov = [], []
    for k in st["done"]:
        b = L["ladders"][k]
        for a_id, b_id in b["pairs"]:
            pa, pb = prints(a_id), prints(b_id)
            ca, cb = ts(M[a_id].get("closedTime")), ts(M[b_id].get("closedTime"))
            closes = [x for x in (ca, cb) if x is not None]
            t_close = min(closes) if closes else None
            c = {"set": b["set"], "kind": b["kind"], "event": b["event"], "ladder": k, "rich": a_id, "cheap": b_id,
                 "prints_rich": pa["served"] if pa else None, "prints_cheap": pb["served"] if pb else None,
                 "capped_rich": pa["capped"] if pa else None, "capped_cheap": pb["capped"] if pb else None,
                 "first_print_rich": int(pa["t"][0]) if pa and len(pa["t"]) else None,
                 "first_print_cheap": int(pb["t"][0]) if pb and len(pb["t"]) else None,
                 "listed_rich": str(M[a_id].get("startDate") or M[a_id].get("createdAt"))[:10],
                 "listed_cheap": str(M[b_id].get("startDate") or M[b_id].get("createdAt"))[:10]}
            if pa is None or pb is None or not len(pa["t"]) or not len(pb["t"]):
                c["state"] = "no prints served"
                cov.append(c)
                continue
            c["state"] = "latest 20,000 prints only" if (pa["capped"] or pb["capped"]) else "every print checked"
            fa, fb = (M[a_id]["fee_rate"], M[a_id]["fee_exponent"]), (M[b_id]["fee_rate"], M[b_id]["fee_exponent"])
            for name, w in VARIANTS.items():
                ms, ia, ib = pair_matches(pa, pb, fa, fb, t_close, w)
                c[f"matches_{name}"] = len(ms)
                for m in ms:
                    i, j = int(ia[m["i_sale"]]), int(ib[m["i_buy"]])
                    rows.append({"variant": name, "set": b["set"], "kind": b["kind"], "event": b["event"], "event_title": b.get("event_title"),
                                 "ladder": k, "rich": a_id, "cheap": b_id, "rich_q": M[a_id]["question"], "cheap_q": M[b_id]["question"],
                                 "date": m["date"], "t_entry": m["t_entry"], "t_sale": m["t_sale"], "t_buy": m["t_buy"],
                                 "seconds_apart": abs(m["t_sale"] - m["t_buy"]), "sale_print": m["sale_print"], "buy_print": m["buy_print"],
                                 "sale_raw": raw(pa, i), "buy_raw": raw(pb, j), "size_sale": m["size_sale"], "size_buy": m["size_buy"],
                                 "fee_rate_rich": fa[0], "fee_exp_rich": fa[1], "fee_rate_cheap": fb[0], "fee_exp_cheap": fb[1],
                                 "close_rich_catalogue": M[a_id].get("closedTime"), "close_cheap_catalogue": M[b_id].get("closedTime")})
            cov.append(c)
    X = pd.DataFrame(rows)
    C = pd.DataFrame(cov)
    C.to_csv(RESULTS / "coverage.csv", index=False)
    X.to_csv(RESULTS / "matches.csv", index=False)
    cut = {}
    for s in ("a", "b"):
        d = X[(X.variant == "W600") & (X.set == s)]["date"] if len(X) else []
        dates = sorted(set(d))
        cut[s] = {"oos_start": en.oos_cut(dates), "trade_dates": len(dates), "trades": int(len(d)),
                  "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None}
    cut["written_utc"] = datetime.now(timezone.utc).isoformat()
    cut["rule"] = "within each set, the most recent 20% (rounded up) of the New York dates with a primary (10-minute) trade"
    (RESULTS / "oos_cut.json").write_text(json.dumps(cut, indent=1))
    print(json.dumps(cut, indent=1))
    print(C.groupby(["set", "state"]).size())
    print(X.groupby(["variant", "set", "kind"]).size() if len(X) else "no matches")
    return 0


def settle() -> int:
    X = pd.read_csv(RESULTS / "matches.csv", dtype={"rich": str, "cheap": str})
    cut = json.loads((RESULTS / "oos_cut.json").read_text())
    res = json.loads((CACHE / "outcomes.json").read_text())
    out = []
    for r in X.itertuples():
        ra, rb = res.get(r.rich, {}), res.get(r.cheap, {})
        oa, ob = ra.get("outcome"), rb.get("outcome")
        ca, cb = ts(ra.get("closedTime")) or ts(r.close_rich_catalogue if isinstance(r.close_rich_catalogue, str) else None), \
            ts(rb.get("closedTime")) or ts(r.close_cheap_catalogue if isinstance(r.close_cheap_catalogue, str) else None)
        fa, fb = (r.fee_rate_rich, r.fee_exp_rich), (r.fee_rate_cheap, r.fee_exp_cheap)
        rec = r._asdict()
        rec.pop("Index")
        size = min(r.size_sale, r.size_buy)
        rec["size_uncapped"], rec["size_capped"] = size, min(size, cfg.SIZE_CAP)
        for mult in cfg.COSTS:
            t = en.trade(r.sale_print, r.buy_print, fa, fb, mult, oa, ob)
            tag = f"{mult:g}x"
            for kk in ("sell_at", "buy_at", "edge", "capital", "pnl"):
                rec[f"{kk}_{tag}"] = t[kk]
            rec["settled_by"] = t["settled_by"]
        rec["outcome_rich"], rec["outcome_cheap"] = oa, ob
        rec["broken"] = bool(oa is not None and ob is not None and oa > ob)        # the ladder's order violated at the result
        both = oa is not None and ob is not None and ca is not None and cb is not None
        t_settle = max(ca, cb) if both else None
        rec["settle_date"] = datetime.fromtimestamp(t_settle, ET).strftime("%Y-%m-%d") if t_settle else LAST_DAY
        if rec["settle_date"] < r.date:
            rec["settle_date"] = r.date
        rec["days_locked"] = (pd.Timestamp(rec["settle_date"]) - pd.Timestamp(r.date)).days
        closes = [x for x in (ca, cb) if x is not None]
        rec["print_after_close"] = bool(closes and max(r.t_sale, r.t_buy) >= min(closes))
        rec["segment"] = "OOS" if r.date >= cut[r.set]["oos_start"] else "IS"
        rec["calendar_segment"] = "OOS" if r.date >= cfg.CALENDAR_OOS_START[r.set] else "IS"
        rec["locked_at_entry"] = bool(rec["edge_1x"] > 0)
        for tag in ("1x", "2x"):
            rec[f"usd_capped_{tag}"] = rec[f"pnl_{tag}"] * rec["size_capped"]
            rec[f"usd_uncapped_{tag}"] = rec[f"pnl_{tag}"] * rec["size_uncapped"]
        out.append(rec)
    T = pd.DataFrame(out)
    pc = RESULTS / "pair_checks.csv"
    if pc.exists():                      # amendment 1: the secondary analysis' verdict on each pair (text only), carried along
        C = pd.read_csv(pc, dtype={"rich": str, "cheap": str})[["rich", "cheap", "year_ok", "corrected_ok", "corrected_reason", "partner_used"]]
        T = T.merge(C, on=["rich", "cheap"], how="left")
    dc = RESULTS / "direction_checks.csv"
    if dc.exists():                      # amendment 2 (post hoc): does a rung's description contradict the ladder's direction?
        D = pd.read_csv(dc, dtype={"rich": str, "cheap": str})[["rich", "cheap", "direction_ok"]]
        T = T.merge(D, on=["rich", "cheap"], how="left")
    T.to_csv(RESULTS / "trades.csv", index=False)
    p = T[T.variant == "W600"]
    print(f"{len(T)} rows; primary {len(p)} trades on {p.date.nunique()} dates; broken {int(p.broken.sum())}; "
          f"after close {int(p.print_after_close.sum())}; open {int((p.settled_by != 'result').sum())}")
    return 0


if __name__ == "__main__":
    sys.exit({"detect": detect, "settle": settle}[sys.argv[1]]())
