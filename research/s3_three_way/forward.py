"""S3 Part F: Kalshi S&P 500 against Polymarket SPY on Monday's close, on this weekend's recorded books (METHOD.md
section 3). Fills come only from recorded levels. Run from `research/`:
    python -m s3_three_way.forward --rate 0.0417 [--final]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread import forward as fw
from s1_twin_spread.recording import load_rows

from . import config as cfg
from .run import ARB, CACHE, PM_FEE_EXP, PM_FEE_RATE, RESEARCH, RESULTS, closes, kalshi_event, kalshi_settlement, map_strike

RAW = RESEARCH / "forward" / "raw" / "thresholds"
CADENCE_GAP_S = 45.0       # consecutive snapshots of the 30 s cadence
MAX_SKEW_S = 10.0          # the two venues' books of one cycle


def build_sets(ratio: float) -> list[dict]:
    """Monday's Polymarket SPY strikes mapped to Kalshi strikes, from the recorder's universe files (names only)."""
    uni = json.loads(sorted(RAW.glob("universe_*.json"))[-1].read_text())
    day = cfg.FORWARD_RESOLUTION.strftime("%Y-%m-%d")
    pm = [m for m in uni["pm"] if m["underlying"] == cfg.PM_UNDERLYING and (m.get("end_date") or "").startswith(day)]
    kal = {round(m["strike"], 2): m for m in uni["kalshi"] if m["underlying"] == "SPX" and m["close_time"].startswith(day)}
    sets = []
    for m in sorted(pm, key=lambda x: x["strike"]):
        mp = map_strike(float(m["strike"]), ratio, sorted(kal))
        if mp is None:
            continue
        k = kal[mp[0]]
        sets.append({"ticker": k["ticker"], "token": m["token"], "question": m["question"], "pm_strike": float(m["strike"]),
                     "kalshi_strike": mp[0], "strike_gap_pts": mp[1], "deadline_ts": cfg.FORWARD_RESOLUTION.timestamp(),
                     "k_mult": 1.0, "pm_rate": PM_FEE_RATE, "pm_exp": PM_FEE_EXP})
    return sets


def referee() -> dict[float, tuple[float, float]]:
    """Friday-close options band per SPY strike, from the arb scan's live rows. Stale all weekend: reported only."""
    arb = pd.read_csv(ARB, low_memory=False)
    day = cfg.FORWARD_RESOLUTION.strftime("%Y-%m-%d")
    r = arb[(arb.venue == "polymarket") & (arb.underlying == cfg.PM_UNDERLYING) & (arb.live == True) & (arb.res_date == day)  # noqa: E712
            & arb.p_lo.notna()]
    return {float(x.strike): (float(x.p_lo), float(x.p_hi)) for x in r.itertuples()}


def describe(snaps: list, band: tuple[float, float] | None) -> dict:
    """What the two books looked like over the window: mids, spreads, and where each sat against the stale band."""
    def mid(b):
        return (b["b"][0][0] + b["a"][0][0]) / 2 if b["b"] and b["a"] else np.nan

    def spread(b):
        return b["a"][0][0] - b["b"][0][0] if b["b"] and b["a"] else np.nan

    pm_mid = np.array([mid(s[1]) for s in snaps])
    k_mid = np.array([mid(s[2]) for s in snaps])
    out = {"snapshots": len(snaps), "pm_two_sided_share": float(np.mean(~np.isnan(pm_mid))) if len(snaps) else np.nan,
           "kalshi_two_sided_share": float(np.mean(~np.isnan(k_mid))) if len(snaps) else np.nan,
           "pm_mid_median": float(np.nanmedian(pm_mid)) if np.isfinite(pm_mid).any() else np.nan,
           "kalshi_mid_median": float(np.nanmedian(k_mid)) if np.isfinite(k_mid).any() else np.nan,
           "pm_spread_median": float(np.nanmedian([spread(s[1]) for s in snaps])) if np.isfinite(pm_mid).any() else np.nan,
           "kalshi_spread_median": float(np.nanmedian([spread(s[2]) for s in snaps])) if np.isfinite(k_mid).any() else np.nan}
    both = ~np.isnan(pm_mid) & ~np.isnan(k_mid)
    out["mid_gap_median"] = float(np.median(pm_mid[both] - k_mid[both])) if both.any() else np.nan
    out["mid_gap_abs_mean"] = float(np.mean(np.abs(pm_mid[both] - k_mid[both]))) if both.any() else np.nan
    if band:
        out["options_lo_friday"], out["options_hi_friday"] = band
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.massive import MassiveClient, load_api_key

    end = cfg.FORWARD_END_FINAL if a.final else cfg.FORWARD_END
    tag = "forward_final" if a.final else "forward"
    RESULTS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    client = MassiveClient(load_api_key(search_from=RESEARCH), cache_dir=RESEARCH / ".massive_cache")
    spy = closes(client, "SPY", "2026-09-25", cfg.FORWARD_RATIO_DATE)[cfg.FORWARD_RATIO_DATE]
    spx = kalshi_settlement(kalshi_event(cfg.FORWARD_RATIO_DATE, ds.Throttle(3.0)))
    ratio = spx / spy
    sets = build_sets(ratio)
    bands = referee()
    rows = load_rows(cfg.FORWARD_START, end, RAW)
    want = {s["token"] for s in sets} | {s["ticker"] for s in sets}
    snaps = fw.snapshots([r for r in rows if r["id"] in want], sets, MAX_SKEW_S)

    out_rows, trades, cap_rows, desc = [], [], [], []
    for s in sets:
        desc.append({"pm_strike": s["pm_strike"], "kalshi_strike": s["kalshi_strike"], "kalshi_ticker": s["ticker"],
                     "strike_gap_pts": s["strike_gap_pts"], **describe(snaps.get(s["ticker"], []), bands.get(s["pm_strike"]))})
    for v in (x for x in cfg.VARIANTS if x.trade == "lock" and x.id != "V2"):       # in Part F, V0 and V2 coincide
        for c in cfg.COST_MULTIPLIERS:
            tt = []
            for s in sets:
                sn = snaps.get(s["ticker"], [])
                if not sn:
                    continue
                tr, cap = fw.paper_test(sn, s, v.theta, False, c, a.rate, cfg.FORWARD_MAX_SIZE, CADENCE_GAP_S)
                for x in tr:
                    fw.mark_end(x, sn, s, c, a.rate)
                    x.update(variant=v.id, cost_mult=c, segment=tag, pm_strike=s["pm_strike"], kalshi_strike=s["kalshi_strike"])
                tt.extend(tr)
                cap_rows.append({"variant": v.id, "cost_mult": c, "pm_strike": s["pm_strike"], "pair": s["ticker"], **cap})
            trades.extend(tt)
            cost = sum(x["cost"] for x in tt)
            out_rows.append({"segment": tag, "variant": v.id, "theta": v.theta, "cost_mult": c, "sets": len(sets),
                             "entries": len(tt), "strikes_traded": len({x["pair"] for x in tt}),
                             "contracts": sum(x["qty"] for x in tt), "capital": cost,
                             "pnl_locked_if_resolved_alike": sum(x["pnl_locked"] for x in tt),
                             "pnl_mid": float(np.nansum([x["pnl_mid"] for x in tt])),
                             "pnl_liq": float(np.nansum([x["pnl_liq"] for x in tt])),
                             "locked_edge_bp": sum(x["pnl_locked"] for x in tt) / cost * 1e4 if cost else float("nan"),
                             "fees_bp": sum(x["fees"] for x in tt) / cost * 1e4 if cost else float("nan")})

    def write_csv(name, recs):
        keys = []
        for rec in recs:
            for k in rec:
                if k not in keys:
                    keys.append(k)
        with open(RESULTS / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(recs)

    write_csv(f"metrics_{tag}.csv", out_rows)
    write_csv(f"trades_{tag}.csv", trades)
    write_csv(f"capacity_{tag}.csv", cap_rows)
    write_csv(f"sets_{tag}.csv", desc)
    last = max((s[-1][0] for s in snaps.values() if s), default=float("nan"))
    (RESULTS / f"run_meta_{tag}.json").write_text(json.dumps({
        "window_start": cfg.FORWARD_START.isoformat(), "window_end": end.isoformat(),
        "last_snapshot": fw.iso(last) if last == last else None, "ratio": ratio, "spx_close": spx, "spy_close": spy,
        "ratio_date": cfg.FORWARD_RATIO_DATE, "sets": len(sets), "rate": a.rate, "book_rows": len(rows)}, indent=1))
    print(f"{tag}: ratio {ratio:.5f} ({spx} / {spy}); {len(sets)} matched strikes; last snapshot {fw.iso(last) if last == last else 'none'}")
    for d in desc:
        print(f"  SPY {d['pm_strike']:.0f} <-> SPX {d['kalshi_strike']:.0f}: snapshots {d['snapshots']}, PM mid {d['pm_mid_median']:.3f} "
              f"(spread {d['pm_spread_median']:.3f}), Kalshi mid {d['kalshi_mid_median']:.3f} (spread {d['kalshi_spread_median']:.3f}), "
              f"two-sided PM {d['pm_two_sided_share']:.2f} K {d['kalshi_two_sided_share']:.2f}")
    print("var cost entries strikes contracts  capital  locked     mid     liq")
    for x in out_rows:
        print(f"{x['variant']} {x['cost_mult']:.0f}x {x['entries']:7d} {x['strikes_traded']:7d} {x['contracts']:9.0f} {x['capital']:8.2f} "
              f"{x['pnl_locked_if_resolved_alike']:7.2f} {x['pnl_mid']:7.2f} {x['pnl_liq']:7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
