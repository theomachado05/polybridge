"""S18 amendment 1: the calibration question at prices that traded (METHOD.md, Amendments).

Run from `research/`:  python -m s18_price_market_calibration.prints [--pull]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s6_monday_fade.run import write_csv
from s7_weekend_straddle.run import boot_mean

from . import config as cfg
from .run import RESEARCH, RESULTS, SOURCES, bucket

CACHE = Path(__file__).resolve().parent / ".cache"
WINDOW_S = 48 * 3600
PAGES = 2


def yes_terms(t: dict) -> tuple[float, str, float] | None:
    """(YES price, taker side in YES terms, size) of a print, or None if it cannot be read."""
    out, side = str(t.get("outcome", "")).lower(), str(t.get("side", "")).upper()
    if out not in ("yes", "no") or side not in ("BUY", "SELL"):
        return None
    px, size = float(t["price"]), float(t.get("size", 0))
    return (px, side, size) if out == "yes" else (1.0 - px, "BUY" if side == "SELL" else "SELL", size)


def weighted(prints: list[tuple[float, str, float]], side: str) -> tuple[float, float, int]:
    """Size-weighted mean YES price, total size and count of the prints on one taker side."""
    s = [(p, z) for p, sd, z in prints if sd == side and z > 0]
    tot = sum(z for _, z in s)
    return (sum(p * z for p, z in s) / tot if tot > 0 else float("nan")), tot, len(s)


def pull(entries: pd.DataFrame) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    cond = {str(m["id"]): m["condition"] for _, root in SOURCES for m in json.loads((root / "universe.json").read_text())["markets"]}
    pt, t0, n = ds.Throttle(3.0), time.time(), 0
    for r in entries.itertuples():
        f = CACHE / f"prints_{r.market}.json"
        if f.exists():
            continue
        rec = {"reach_oldest": None, "served": 0, "prints": []}
        try:
            raw = ds.pm_trades(cond[str(r.market)], r.entry_epoch, pt, max_pages=PAGES)
            ts = [float(t.get("timestamp", 0)) for t in raw]
            keep = [t for t, s in zip(raw, ts) if r.entry_epoch <= s <= r.entry_epoch + WINDOW_S]
            rec = {"reach_oldest": min(ts) if ts else None, "served": len(raw),
                   "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]}
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        f.write_text(json.dumps(rec))
        n += 1
    print(f"{time.time() - t0:.0f}s: prints pulled for {n} markets")


def main() -> int:
    entries = pd.read_csv(RESULTS / "entries.csv")
    if "--pull" in sys.argv:
        pull(entries)
        return 0
    rows, missing, why = [], 0, {"no print served at all (or the request failed)": 0, "never traded during its first weekend (every print was served)": 0,
                                 "first-weekend prints beyond the 20,000 the API keeps": 0}
    for r in entries.itertuples():
        f = CACHE / f"prints_{r.market}.json"
        if not f.exists():
            missing += 1
            continue
        rec = json.loads(f.read_text())
        truncated = rec["served"] >= PAGES * 10000
        if rec.get("reach_oldest") is None:
            why["no print served at all (or the request failed)"] += 1
            continue
        if truncated and rec["reach_oldest"] > r.entry_epoch:
            why["first-weekend prints beyond the 20,000 the API keeps"] += 1
            continue
        if rec["reach_oldest"] > r.entry_epoch + WINDOW_S:
            why["never traded during its first weekend (every print was served)"] += 1
            continue
        pr = [y for y in (yes_terms(t) for t in rec["prints"]) if y]
        ps, size_s, n_s = weighted(pr, "SELL")
        pb, size_b, n_b = weighted(pr, "BUY")

        def fee(p, c=1.0):
            return c * r.fee_rate * (p * (1.0 - p)) ** r.fee_exponent if 0 < p < 1 else 0.0

        rows.append({"market": r.market, "event": r.event, "segment": r.segment, "universe": r.universe, "asset_class": r.asset_class, "sign": r.sign,
                     "question": r.question, "outcome": r.outcome, "mid_at_entry": r.p, "prints_in_window": len(pr),
                     "sell_prints": n_s, "sell_size": size_s, "sell_price": ps, "sell_pnl_points": 100 * (ps - fee(ps) - r.outcome) if n_s else float("nan"),
                     "sell_pnl_points_2x_fee": 100 * (ps - fee(ps, 2.0) - r.outcome) if n_s else float("nan"),
                     "buy_prints": n_b, "buy_size": size_b, "buy_price": pb, "buy_pnl_points": 100 * (r.outcome - pb - fee(pb)) if n_b else float("nan"),
                     "buy_pnl_points_2x_fee": 100 * (r.outcome - pb - fee(pb, 2.0)) if n_b else float("nan")})
    d = pd.DataFrame(rows)
    out = []

    def stat(s: pd.DataFrame, col: str, label: str, scope: str, price_col: str):
        s = s[s[col].notna()]
        b = boot_mean({e: list(v) for e, v in s.groupby("event")[col]})
        out.append({"test": label, "scope": scope, "markets": len(s), "events": int(s.event.nunique()),
                    "mean_traded_price": float(100 * s[price_col].mean()) if len(s) else float("nan"),
                    "share_yes": float(100 * s.outcome.mean()) if len(s) else float("nan"), "mean_pnl_points": b[0], "ci_lo": b[1], "ci_hi": b[2],
                    "median_size": float(s[price_col.replace("price", "size")].median()) if len(s) else float("nan")})

    for side, pcol in (("sell", "sell_price"), ("buy", "buy_price")):
        name = "sellers: sold YES into a bid, held to the result" if side == "sell" else "buyers: bought YES at the ask, held to the result"
        for scope, s in (("all markets", d), ("in-sample events", d[d.segment == "IS"]), ("out-of-sample events", d[d.segment == "OOS"]),
                         ("S9's markets", d[d.universe == "S9"]), ("S15's markets", d[d.universe == "S15"]),
                         ("\"hit high\" markets", d[d.sign == 1]), ("\"hit low\" markets", d[d.sign == -1])):
            stat(s, f"{side}_pnl_points", name, scope, pcol)
        stat(d, f"{side}_pnl_points_2x_fee", name + ", fee doubled", "all markets", pcol)
        for lo, hi in cfg.BUCKETS:
            stat(d[(d[pcol] >= lo) & (d[pcol] < hi)], f"{side}_pnl_points", name, f"traded price {100 * lo:.0f} to {100 * hi:.0f}%", pcol)
    write_csv(RESULTS / "prints_markets.csv", rows)
    write_csv(RESULTS / "prints_tests.csv", out)
    meta = {"entries": int(len(entries)), "no_print_file": missing, "left_out": why, "markets_checked": int(len(d)),
            "checked_with_no_print_in_the_window": int((d.prints_in_window == 0).sum()),
            "with_a_taker_sell": int(d.sell_prints.gt(0).sum()), "with_a_taker_buy": int(d.buy_prints.gt(0).sum()),
            "mid_at_entry_45_55_among_checked": int(d.mid_at_entry.between(0.45, 0.55).sum())}
    (RESULTS / "prints_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for r in out:
        print(f"{r['test'][:44]:44} | {r['scope'][:26]:26} | mkts {r['markets']:4d} ev {r['events']:3d} | traded {r['mean_traded_price']:5.1f} yes {r['share_yes']:5.1f} | "
              f"pnl {r['mean_pnl_points']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}] | median size {r['median_size']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
