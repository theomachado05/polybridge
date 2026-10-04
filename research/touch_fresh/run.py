"""touch_fresh: the tests of METHOD.md section 3 from the cache. No network.

Run from `research/`:  python -m touch_fresh.run
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from s18_price_market_calibration.prints import weighted, yes_terms
from s21_options_anchor import engine as eg
from s21_options_anchor import pull as p21
from s7_weekend_straddle.run import boot_diff, boot_mean, write_csv

from . import config as cfg
from .pull import CACHE, HERE, anchor_epoch, build_anchor

RESULTS = HERE.parent / "results" / "touch_fresh"
N = NormalDist()


def matched_touch(p_t: float, T: float, tau: float) -> float:
    if not (p_t == p_t) or T <= 0 or tau <= 0:
        return float("nan")
    p = min(max(p_t, 1e-9), 1 - 1e-9)
    z = N.inv_cdf(1 - p)
    return min(1.0, 2.0 * N.cdf(-z * math.sqrt(T / tau)))


def window_start(m: dict) -> date | None:
    t = m["event_title"]
    end = date.fromisoformat(m["window_end"])
    if "Week of" in t:
        return date.fromordinal(end.toordinal() - 4)
    if "before" in t:
        return None
    return end.replace(day=1)


def market_rows() -> list[dict]:
    p21.CACHE = CACHE
    src = p21.Src(offline=True)
    rows = []
    for m in json.loads((HERE / "universe.json").read_text())["markets"]:
        r = {k: m[k] for k in ("id", "event", "event_title", "ticker", "asset_class", "strict", "question", "level", "direction", "window_end",
                               "end_session", "entry_day", "fee_rate", "fee_exponent", "volume")}
        r["weekly"] = "Week of" in m["event_title"]
        ws = window_start(m)
        r["forward_start"] = bool(ws and ws > date.fromisoformat(m["entry_day"]))
        f = CACHE / f"pm_{m['id']}.json"
        if not f.exists():
            rows.append({**r, "status": "prints not pulled"})
            continue
        pm = json.loads(f.read_text())
        r["outcome"] = pm.get("outcome")
        pr = [y for y in (yes_terms(t) for t in pm["prints"]) if y]
        ps, size_s, n_s = weighted(pr, "SELL")
        pb, size_b, n_b = weighted(pr, "BUY")
        pa, _, _ = (sum(p * z for p, _, z in pr) / sum(z for _, _, z in pr), 0, 0) if pr and sum(z for _, _, z in pr) > 0 else (float("nan"), 0, 0)
        r.update({"prints": len(pr), "sell_prints": n_s, "sell_size": size_s, "sell_price": ps, "buy_prints": n_b, "buy_price": pb, "print_price": pa,
                  "served": pm["served"], "reach_oldest": pm["reach_oldest"]})
        try:
            a = build_anchor(src, m)
        except p21.NotPulled:
            a = {"status": "anchor not pulled"}
        r.update(a)
        at = anchor_epoch(m["entry_day"])
        q = src.cache.get(f"sq|{m['ticker']}|{datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        closes = src.cache.get(f"d|{m['ticker']}") or {}
        r["s0"] = (q["bid"] + q["ask"]) / 2 if q and q["bid"] > 0 and q["ask"] >= q["bid"] else float("nan")
        r["s0_half_spread"] = (q["ask"] - q["bid"]) / 2 if q and q["bid"] > 0 and q["ask"] >= q["bid"] else float("nan")
        r["s0_age_s"] = at - q["ts"] if q else float("nan")
        r["close_end"] = closes.get(m["end_session"], float("nan"))
        rows.append(r)
    return rows


def enrich(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    ok = d.status.eq("ok")
    d["anchor_central"] = [matched_touch(p, T, t) if o else float("nan") for p, T, t, o in zip(d.p_mid, d.T_days, d.tau_days, ok)]
    d["central_lo"] = [matched_touch(p, T, t) if o else float("nan") for p, T, t, o in zip(d.p_lo, d.T_days, d.tau_days, ok)]
    d["central_hi"] = [matched_touch(p, T, t) if o else float("nan") for p, T, t, o in zip(d.p_hi, d.T_days, d.tau_days, ok)]
    d["anchor_s21"] = np.where(ok, np.minimum(1.0, 2.0 * d.p_mid), np.nan)

    def fee(p, rate, ex, c):
        return c * rate * (p * (1 - p)) ** ex if 0 < p < 1 else 0.0

    for c in cfg.FEE_MULTIPLES:
        sfx = "" if c == 1 else "_2x_fee"
        d[f"sell_pnl{sfx}"] = [100 * (p - fee(p, r, e, c) - o) if (n and o == o and o is not None) else float("nan")
                              for p, r, e, o, n in zip(d.sell_price, d.fee_rate, d.fee_exponent, d.outcome.astype(float), d.sell_prints.fillna(0))]
    d["in_band"] = d.print_price.between(*cfg.PRICE_BAND)
    d["gap"] = 100 * (d.sell_price - d.anchor_central)
    d["gap_s21"] = 100 * (d.sell_price - d.anchor_s21)
    d["B0"] = d.gap >= cfg.THRESHOLD - 1e-9
    d["B0_s21"] = d.gap_s21 >= cfg.THRESHOLD - 1e-9
    # hedge
    deltas, hp, hp2, mv = [], [], [], []
    for r in d.itertuples():
        delta = float("nan")
        if r.status == "ok" and r.s0 == r.s0 and r.anchor_central == r.anchor_central and 0 < r.anchor_central < 1:
            x = math.log(r.level / r.s0) * r.direction
            if x > 0:
                p = min(max(r.p_mid, 1e-9), 1 - 1e-9)
                zt = N.inv_cdf(1 - p) * math.sqrt(r.T_days / r.tau_days)
                if zt > 0:
                    sst = x / zt
                    delta = r.direction * 2 * N.pdf(zt) / (r.s0 * sst)
        deltas.append(delta)
        s_exit = r.level if r.outcome == 1.0 else r.close_end
        h = 100 * (delta * (s_exit - r.s0) - 2 * abs(delta) * r.s0_half_spread) if delta == delta and s_exit == s_exit else float("nan")
        hp.append(r.sell_pnl + h if h == h else float("nan"))
        hp2.append(r.sell_pnl_2x_fee + h if h == h else float("nan"))
        mv.append(r.direction * math.log(r.close_end / r.s0) if r.s0 == r.s0 and r.close_end == r.close_end else float("nan"))
    d["delta"], d["hedged_pnl"], d["hedged_pnl_2x_fee"], d["move_dir"] = deltas, hp, hp2, mv
    return d


def stat(s: pd.DataFrame, col: str, book: str, sample: str) -> dict:
    s = s[s[col].notna()]
    b = boot_mean({str(e): list(v) for e, v in s.groupby("event")[col]})
    return {"sample": sample, "book": book, "pnl": col, "markets": len(s), "events": int(s.event.nunique()),
            "mean_sell_price": 100 * s.sell_price.mean() if len(s) else float("nan"),
            "mean_anchor": 100 * s.anchor_central.mean() if len(s) else float("nan"),
            "share_yes": 100 * s.outcome.astype(float).mean() if len(s) else float("nan"), "mean_points": b[0], "ci_lo": b[1], "ci_hi": b[2]}


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    d = enrich(pd.DataFrame(market_rows()))
    write_csv(RESULTS / "markets.csv", d.to_dict("records"))
    base = d[d.status.eq("ok") & d.sell_prints.fillna(0).gt(0) & d.in_band & d.outcome.notna()]
    books = []
    for sample, s in (("R", base), ("S21-eligible (descriptive)", base[base.strict.astype(bool)])):
        for col in ("sell_pnl", "sell_pnl_2x_fee", "hedged_pnl", "hedged_pnl_2x_fee"):
            books.append(stat(s[s.B0], col, "B0 (matched anchor, gap >= 5)", sample))
        for col in ("sell_pnl", "sell_pnl_2x_fee", "hedged_pnl"):
            books.append(stat(s, col, "U (every anchored market with a taker sale)", sample))
        books.append(stat(s[s.B0_s21], "sell_pnl", "B0 with S21's unmatched anchor", sample))
        books.append(stat(s[s.B0 & ~s.forward_start.astype(bool)], "sell_pnl", "B0, window already started", sample))
        books.append(stat(s[s.B0 & s.forward_start.astype(bool)], "sell_pnl", "B0, forward-start window", sample))
        books.append(stat(s[s.B0 & s.weekly.astype(bool)], "sell_pnl", "B0, weekly events", sample))
        books.append(stat(s[s.B0 & ~s.weekly.astype(bool)], "sell_pnl", "B0, monthly events", sample))
        books.append(stat(s[~s.B0], "sell_pnl", "U-left (not taken by B0)", sample))
        df = boot_diff({str(e): list(v) for e, v in s[s.B0].groupby("event").sell_pnl}, {str(e): list(v) for e, v in s[~s.B0].groupby("event").sell_pnl})
        books.append({"sample": sample, "book": "B0 taken minus left", "pnl": "sell_pnl", "markets": len(s), "events": int(s.event.nunique()),
                      "mean_points": df[0], "ci_lo": df[1], "ci_hi": df[2]})
    write_csv(RESULTS / "books.csv", books)
    ex = []
    for book, s in (("B0", base[base.B0]), ("U", base)):
        s = s[s.move_dir.notna() & s.sell_pnl.notna()]
        if len(s) > 5 and s.event.nunique() > 2:
            b, se = eg.ols_cluster(s.sell_pnl.to_numpy(), s.move_dir.to_numpy()[:, None] * 100, s.event.to_numpy())
            for i, term in enumerate(("intercept", "slope per 1% directional move")):
                ex.append({"sample": "R", "book": book, "term": term, "coef": b[i], "se": se[i], "ci_lo": b[i] - 1.96 * se[i], "ci_hi": b[i] + 1.96 * se[i],
                           "markets": len(s), "events": int(s.event.nunique())})
    write_csv(RESULTS / "exposure.csv", ex)
    counts = {"universe": len(d), "status": d.status.value_counts().to_dict(), "anchored": int(d.status.eq("ok").sum()),
              "with_taker_sale": int(d.sell_prints.fillna(0).gt(0).sum()), "in_band": int(d.in_band.sum()),
              "with_result": int(d.outcome.notna().sum()), "base": len(base), "base_events": int(base.event.nunique()),
              "B0": int(base.B0.sum()), "B0_events": int(base[base.B0].event.nunique()), "forward_start_in_base": int(base.forward_start.sum()),
              "hedge_available_in_B0": int(base[base.B0].hedged_pnl.notna().sum()), "zero_bid_leg_in_base": int(base.zero_bid_leg.fillna(False).sum()),
              "max_leg_age_s": float(np.nanmax(base[["leg_lo_age_s", "leg_hi_age_s"]].to_numpy())) if len(base) else float("nan"),
              "median_days_expiry_minus_end": float(base.days_expiry_minus_end.median()) if len(base) else float("nan")}
    (RESULTS / "counts.json").write_text(json.dumps(counts, indent=1, default=str))
    print(json.dumps(counts, indent=1, default=str))
    for b in books:
        print(f"{b['sample'][:10]:10} | {b['book'][:44]:44} | {b['pnl']:18} | n {b['markets']:3d} ev {b['events']:3d} | {b['mean_points']:7.2f} [{b['ci_lo']:7.2f}, {b['ci_hi']:7.2f}]")
    for e in ex:
        print(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
