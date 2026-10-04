"""S19: S18's test at traded prices, on crypto price markets (METHOD.md).

Run from `research/`:
    python -m s19_crypto_price_markets.run --pull     # prints of at least $50 in each market's first 48 hours (not committed)
    python -m s19_crypto_price_markets.run            # the sellers' and buyers' tests and the two books
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s6_monday_fade.run import closure_metrics, write_csv
from s7_weekend_straddle.run import boot_mean
from s9_weekend_price_markets.run import _ts
from s18_price_market_calibration.prints import weighted, yes_terms
from s18_price_market_calibration.run import max_locked

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s19_crypto_price_markets"
CACHE = HERE / ".cache"
PAGE = 10000
SELL, BUY = "sellers: sold YES into a bid, held to the result", "buyers: bought YES at the ask, held to the result"


def universe() -> list[dict]:
    return json.loads((HERE / "universe.json").read_text())["markets"]


def pull() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    pt, t0, n = ds.Throttle(2.0), time.time(), 0
    for m in universe():
        f = CACHE / f"prints_{m['id']}.json"
        if f.exists():
            continue
        start = _ts(m["start"])
        rec = {"served": 0, "reach_oldest": None, "complete": False, "prints": []}
        try:
            raw: list[dict] = []
            for page in range(2):
                d = ds.get_json(ds.DATA_API, {"market": m["condition"], "limit": PAGE, "offset": page * PAGE, "filterType": "CASH",
                                              "filterAmount": cfg.MIN_PRINT_CASH}, throttle=pt, allow=(400, 404, 422))
                if not isinstance(d, list) or not d:
                    rec["complete"] = True
                    break
                raw.extend(d)
                if len(d) < PAGE:
                    rec["complete"] = True
                    break
                if min(float(t.get("timestamp", 0)) for t in d) < start:
                    break
            ts = [float(t.get("timestamp", 0)) for t in raw]
            keep = [t for t, s in zip(raw, ts) if start <= s <= start + cfg.WINDOW_S]
            rec.update({"served": len(raw), "reach_oldest": min(ts) if ts else None,
                        "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]})
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        f.write_text(json.dumps(rec))
        n += 1
    print(f"{time.time() - t0:.0f}s: prints pulled for {n} markets")


def build() -> tuple[pd.DataFrame, dict]:
    ms = universe()
    first = {}
    for m in ms:
        first[m["event"]] = min(first.get(m["event"], float("inf")), _ts(m["start"]))
    order = sorted(first, key=lambda e: (first[e], e))
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(order)))
    oos = set(order[len(order) - n_oos:])
    rows, why = [], {"the request failed": 0, "its first 48 hours are beyond what the API serves": 0}
    for m in ms:
        f = CACHE / f"prints_{m['id']}.json"
        if not f.exists():
            why["the request failed"] += 1
            continue
        rec, start = json.loads(f.read_text()), _ts(m["start"])
        if "error" in rec:
            why["the request failed"] += 1
            continue
        if not rec.get("complete") and (rec.get("reach_oldest") is None or rec["reach_oldest"] > start):
            why["its first 48 hours are beyond what the API serves"] += 1
            continue
        pr = [y for y in (yes_terms(t) for t in rec["prints"]) if y]
        ps, size_s, n_s = weighted(pr, "SELL")
        pb, size_b, n_b = weighted(pr, "BUY")

        def fee(p, c=1.0):
            return c * m["fee_rate"] * (p * (1.0 - p)) ** m["fee_exponent"] if 0 < p < 1 else 0.0

        rows.append({"market": m["id"], "event": m["event"], "segment": "OOS" if m["event"] in oos else "IS", "asset": m["asset"], "horizon": m["horizon"],
                     "question": m["question"], "outcome": m["outcome"], "start_epoch": start, "result_epoch": _ts(m["closed_time"]),
                     "listed": datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d"), "fee_rate": m["fee_rate"], "prints_in_window": len(pr),
                     "sell_prints": n_s, "sell_size": size_s, "sell_price": ps, "sell_pnl_points": 100 * (ps - fee(ps) - m["outcome"]) if n_s else float("nan"),
                     "sell_pnl_points_2x_fee": 100 * (ps - fee(ps, 2.0) - m["outcome"]) if n_s else float("nan"),
                     "buy_prints": n_b, "buy_size": size_b, "buy_price": pb, "buy_pnl_points": 100 * (m["outcome"] - pb - fee(pb)) if n_b else float("nan"),
                     "buy_pnl_points_2x_fee": 100 * (m["outcome"] - pb - fee(pb, 2.0)) if n_b else float("nan")})
    d = pd.DataFrame(rows)
    meta = {"markets_in_sample": len(ms), "events_in_sample": len(order), "left_out": why, "markets_checked": int(len(d)),
            "checked_with_no_print_in_the_window": int((d.prints_in_window == 0).sum()), "with_a_taker_sell": int(d.sell_prints.gt(0).sum()),
            "with_a_taker_buy": int(d.buy_prints.gt(0).sum()), "oos_events": n_oos,
            "oos_from": datetime.fromtimestamp(first[order[len(order) - n_oos]], timezone.utc).strftime("%Y-%m-%d"),
            "first_listing": datetime.fromtimestamp(min(first.values()), timezone.utc).strftime("%Y-%m-%d"),
            "last_listing": datetime.fromtimestamp(max(first.values()), timezone.utc).strftime("%Y-%m-%d")}
    return d, meta


def tests(d: pd.DataFrame) -> list[dict]:
    out = []

    def stat(s: pd.DataFrame, col: str, label: str, scope: str, pcol: str):
        s = s[s[col].notna()]
        b = boot_mean({e: list(v) for e, v in s.groupby("event")[col]})
        out.append({"test": label, "scope": scope, "markets": len(s), "events": int(s.event.nunique()),
                    "mean_traded_price": float(100 * s[pcol].mean()) if len(s) else float("nan"),
                    "share_yes": float(100 * s.outcome.mean()) if len(s) else float("nan"), "mean_pnl_points": b[0], "ci_lo": b[1], "ci_hi": b[2],
                    "median_size": float(s[pcol.replace("price", "size")].median()) if len(s) else float("nan")})

    for side, name in (("sell", SELL), ("buy", BUY)):
        pcol, col = f"{side}_price", f"{side}_pnl_points"
        scopes = [("all markets", d), ("in-sample events", d[d.segment == "IS"]), ("out-of-sample events", d[d.segment == "OOS"]),
                  ("listed up to 2025-12-31", d[d.listed <= "2025-12-31"]), ("listed in 2026", d[d.listed >= "2026-01-01"])] \
            + [(f"asset: {a}", d[d.asset == a]) for a in ("bitcoin", "ethereum", "solana", "xrp")] \
            + [(f"horizon: {h}", d[d.horizon == h]) for h in ("monthly or longer", "weekly", "other range")]
        for scope, s in scopes:
            stat(s, col, name, scope, pcol)
        stat(d, f"{side}_pnl_points_2x_fee", name + ", fee doubled", "all markets", pcol)
        for lo, hi in cfg.BUCKETS:
            stat(d[(d[pcol] >= lo) & (d[pcol] < hi)], col, name, f"traded price {100 * lo:.0f} to {100 * hi:.0f}%", pcol)
    return out


def book(d: pd.DataFrame, side: str) -> tuple[pd.DataFrame, list[dict]]:
    col, pcol, zcol = f"{side}_pnl_points", f"{side}_price", f"{side}_size"
    s = d[d[col].notna()].copy()
    s["size"] = np.minimum(s[zcol], cfg.CONTRACTS)
    s["pnl"] = s["size"] * s[col] / 100.0
    s["capital"] = s["size"] * ((1.0 - s[pcol]) if side == "sell" else s[pcol])
    s["result_month"] = s.result_epoch.map(lambda x: datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m"))
    months = list(pd.period_range(s.result_month.min(), s.result_month.max(), freq="M").strftime("%Y-%m"))
    rows = []
    for seg in ("IS", "OOS", "ALL"):
        t = s if seg == "ALL" else s[s.segment == seg]
        ml = [m for m in months if t.result_month.min() <= m <= t.result_month.max()] if len(t) else []
        pc = np.array([t[t.result_month == m].pnl.sum() for m in ml])
        K = max_locked([{"entry_epoch": a, "result_epoch": b, "capital": c} for a, b, c in zip(t.start_epoch, t.result_epoch, t.capital)])
        ev = t.groupby("event").pnl.sum()
        rows.append({"book": "sellers" if side == "sell" else "buyers", "segment": seg, "markets": len(t), "events": int(t.event.nunique()),
                     "pnl": float(t.pnl.sum()), "capital_base": K, "months": len(ml), **closure_metrics(pc, ml, K, float(t.capital.sum()), cfg.MONTHS_PER_YEAR),
                     "winners": float((t.pnl > 0).mean()) if len(t) else float("nan"), "worst_event": float(ev.min()) if len(ev) else float("nan"),
                     "best_event": float(ev.max()) if len(ev) else float("nan"), "mean_capital": float(t.capital.mean()) if len(t) else float("nan"),
                     "median_days_locked": float(((t.result_epoch - t.start_epoch) / 86400).median()) if len(t) else float("nan"),
                     "fee_bp_of_capital": float((1e4 * t.fee_rate * t[pcol] * (1 - t[pcol]) * t["size"] / t.capital).mean()) if len(t) else float("nan")})
    monthly = s.groupby("result_month").pnl.sum().reindex(months).fillna(0.0).rename_axis("result_month").reset_index()
    return monthly, rows


def main() -> int:
    if "--pull" in sys.argv:
        pull()
        return 0
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    d, meta = build()
    tt = tests(d)
    sell_m, sb = book(d, "sell")
    buy_m, bb = book(d, "buy")
    write_csv(RESULTS / "markets.csv", d.to_dict("records"))
    write_csv(RESULTS / "tests.csv", tt)
    write_csv(RESULTS / "book.csv", sb + bb)
    sell_m.assign(book="sellers").to_csv(RESULTS / "book_monthly_sellers.csv", index=False)
    buy_m.assign(book="buyers").to_csv(RESULTS / "book_monthly_buyers.csv", index=False)
    meta["run_seconds"] = round(time.time() - t_run, 1)
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for r in tt:
        print(f"{r['test'][:36]:36} | {r['scope'][:26]:26} | mkts {r['markets']:4d} ev {r['events']:3d} | traded {r['mean_traded_price']:5.1f} yes {r['share_yes']:5.1f} | "
              f"pnl {r['mean_pnl_points']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}] | median size {r['median_size']:.0f}")
    for r in sb + bb:
        print(f"{r['book']:8} {r['segment']:3} markets {r['markets']:4d} pnl {r['pnl']:9.0f} capital base {r['capital_base']:8.0f} sharpe {r['sharpe']:6.2f} "
              f"maxDD {r['max_drawdown']:.3f} worst month {r['worst_month']:.3f} worst event {r['worst_event']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
