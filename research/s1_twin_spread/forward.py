"""S1 forward paper test on the recorded order books (METHOD.md sections 5, 6 and 8).

Fills are taken from the recorded levels only: prices and sizes that were on the book. Run from `research/`:
    python -m s1_twin_spread.forward --rate 0.0417 [--final]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config as cfg
from . import data as ds
from .engine import YEAR_S
from .recording import load_rows

RESULTS = Path(__file__).resolve().parents[1] / "results" / "s1_twin_spread"
MAX_PAIR_SKEW_S = 5.0      # the two venues' books of one snapshot must be this close in time


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, cfg.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def widen(book: dict, c: float) -> dict:
    """Costs x c: every ask moves up and every bid down by (c - 1) half-spreads of the top of the book."""
    if c == 1.0 or not book["b"] or not book["a"]:
        return book
    shift = (c - 1.0) * (book["a"][0][0] - book["b"][0][0]) / 2.0
    return {"b": [[max(p - shift, 0.001), s] for p, s in book["b"]], "a": [[min(p + shift, 0.999), s] for p, s in book["a"]]}


def no_asks(book: dict) -> list[list[float]]:
    """Buying NO costs 1 - (YES bid), level by level."""
    return [[1.0 - p, s] for p, s in book["b"]]


def no_bids(book: dict) -> list[list[float]]:
    return [[1.0 - p, s] for p, s in book["a"]]


def walk(pm_levels: list, k_levels: list, pm_rate: float, pm_exp: float, k_mult: float, c: float, carry_rate: float,
         theta: float | None, max_size: float, buying: bool = True) -> dict:
    """Matches the two legs level by level. Buying: takes every increment whose marginal edge
    1 - (pm + fee) - (k + fee) - carry is still >= theta. Selling (theta None): sells up to max_size.
    The Kalshi fee is rounded up to a cent on the whole order."""
    i = j = 0
    ri = pm_levels[0][1] if pm_levels else 0.0
    rj = k_levels[0][1] if k_levels else 0.0
    q = pm_gross = k_gross = pm_fee = k_fee_raw = 0.0
    fills = []
    while i < len(pm_levels) and j < len(k_levels) and q < max_size - 1e-9:
        pp, kp = pm_levels[i][0], k_levels[j][0]
        fp = c * pm_rate * (pp * (1 - pp)) ** pm_exp if 0 < pp < 1 else 0.0
        fk = c * cfg.KALSHI_FEE_COEFF * k_mult * kp * (1 - kp) if 0 < kp < 1 else 0.0
        if buying and theta is not None:
            cost = pp + fp + kp + fk
            if 1.0 - cost * (1.0 + carry_rate) < theta:
                break
        inc = min(ri, rj, max_size - q)
        if inc > 0:
            q += inc
            pm_gross += inc * pp
            k_gross += inc * kp
            pm_fee += inc * fp
            k_fee_raw += inc * fk
            fills.append([pp, kp, inc])
        ri -= inc
        rj -= inc
        if ri <= 1e-9:
            i += 1
            ri = pm_levels[i][1] if i < len(pm_levels) else 0.0
        if rj <= 1e-9:
            j += 1
            rj = k_levels[j][1] if j < len(k_levels) else 0.0
    k_fee = math.ceil(k_fee_raw * 100 - 1e-9) / 100 if q > 0 else 0.0
    return {"qty": q, "pm_gross": pm_gross, "k_gross": k_gross, "pm_fee": pm_fee, "k_fee": k_fee, "fills": fills}


def entry_legs(pm: dict, k: dict, d: str):
    """Books to buy from. A = Polymarket YES + Kalshi NO; B = Polymarket NO + Kalshi YES."""
    return (pm["a"], no_asks(k)) if d == "A" else (no_asks(pm), k["a"])


def exit_legs(pm: dict, k: dict, d: str):
    """Books to sell into: the bids of what is held."""
    return (pm["b"], no_bids(k)) if d == "A" else (no_bids(pm), k["b"])


def top_edge(pm: dict, k: dict, d: str, m: dict, c: float, carry_rate: float) -> float:
    """Edge of the first contract at the top of both books."""
    pl, kl = entry_legs(pm, k, d)
    if not pl or not kl:
        return float("nan")
    pp, kp = pl[0][0], kl[0][0]
    cost = pp + c * m["pm_rate"] * (pp * (1 - pp)) ** m["pm_exp"] + kp + c * cfg.KALSHI_FEE_COEFF * m["k_mult"] * kp * (1 - kp)
    return 1.0 - cost * (1.0 + carry_rate)


def snapshots(rows: list[dict], metas: list[dict]) -> dict[str, list[tuple[float, dict, dict]]]:
    """Per pair, the time-ordered (t, Polymarket book, Kalshi book) snapshots whose two books are close in time."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r)
    out = {}
    for m in metas:
        pm = sorted(by.get(m["token"], []), key=lambda r: r["t"])
        kk = sorted(by.get(m["ticker"], []), key=lambda r: r["t"])
        kt = np.array([r["t"] for r in kk])
        snaps = []
        for r in pm:
            if not len(kt):
                break
            j = int(np.argmin(np.abs(kt - r["t"])))
            if abs(kt[j] - r["t"]) <= MAX_PAIR_SKEW_S:
                snaps.append((max(r["t"], kk[j]["t"]), r, kk[j]))
        out[m["ticker"]] = snaps
    return out


def adjacent(prev_t: float, t: float) -> bool:
    """Consecutive snapshots of the 15 s cadence (a missed cycle breaks the run of two)."""
    return 0 < t - prev_t <= 25.0


def paper_test(snaps: list, m: dict, theta: float, exit_on: bool, c: float, r: float, max_size: float) -> tuple[list[dict], dict]:
    """One pair: entries and exits on the recorded books, plus what was fillable with no size cap."""
    deadline = m["deadline_ts"]
    trades, pos = [], None
    prev = None
    cap = {"snapshots": len(snaps), "snapshots_with_edge": 0, "max_fillable_qty": 0.0, "max_fillable_dollars": 0.0,
           "max_fillable_edge_dollars": 0.0, "depth_share_at_max": float("nan")}
    for t, pm_raw, k_raw in snaps:
        pm, k = widen(pm_raw, c), widen(k_raw, c)
        carry = c * r * max(deadline - t, 0.0) / YEAR_S
        edges = {d: top_edge(pm, k, d, m, c, carry) for d in "AB"}
        # capacity, measured on every snapshot regardless of the position
        for d in "AB":
            if edges[d] == edges[d] and edges[d] >= theta:
                pl, kl = entry_legs(pm, k, d)
                w = walk(pl, kl, m["pm_rate"], m["pm_exp"], m["k_mult"], c, carry, theta, float("inf"))
                if w["qty"] > 0:
                    cap["snapshots_with_edge"] += 1
                    dollars = w["pm_gross"] + w["k_gross"]
                    if dollars > cap["max_fillable_dollars"]:
                        cost = dollars + w["pm_fee"] + w["k_fee"]
                        depth = min(sum(s for _, s in pl), sum(s for _, s in kl))
                        cap.update(max_fillable_qty=w["qty"], max_fillable_dollars=dollars,
                                   max_fillable_edge_dollars=w["qty"] - cost * (1 + carry),
                                   depth_share_at_max=w["qty"] / depth if depth else float("nan"))
        two = prev is not None and adjacent(prev["t"], t)
        exit_ok = False
        if pos is None:
            best = max("AB", key=lambda d: edges[d] if edges[d] == edges[d] else -9)
            if two and edges[best] == edges[best] and edges[best] >= theta and prev["edges"][best] == prev["edges"][best] \
                    and prev["edges"][best] >= theta:
                pl, kl = entry_legs(pm, k, best)
                w = walk(pl, kl, m["pm_rate"], m["pm_exp"], m["k_mult"], c, carry, theta, max_size)
                if w["qty"] >= cfg.FORWARD_MIN_SIZE:
                    cost = w["pm_gross"] + w["k_gross"] + w["pm_fee"] + w["k_fee"]
                    pos = {"pair": m["ticker"], "dir": best, "t_in": t, "entry_utc": iso(t), "qty": w["qty"],
                           "cost": cost, "cost_per_pair": cost / w["qty"], "pm_avg": w["pm_gross"] / w["qty"],
                           "k_avg": w["k_gross"] / w["qty"], "fees": w["pm_fee"] + w["k_fee"],
                           "carry": carry * cost, "locked_pnl": w["qty"] - cost * (1 + carry),
                           "top_edge": edges[best], "levels": len(w["fills"]), "pm_book_age_s": t - pm_raw["vts"] / 1000.0
                           if pm_raw.get("vts") else float("nan"), "t_out": None, "exit_utc": "", "proceeds": None}
                    trades.append(pos)
        elif exit_on:
            pl, kl = exit_legs(pm, k, pos["dir"])
            w = walk(pl, kl, m["pm_rate"], m["pm_exp"], m["k_mult"], c, 0.0, None, pos["qty"], buying=False)
            proceeds = w["pm_gross"] + w["k_gross"] - w["pm_fee"] - w["k_fee"]
            exit_ok = w["qty"] >= pos["qty"] - 1e-6 and proceeds / pos["qty"] >= 1.0 - carry
            if exit_ok and two and prev["exit_ok"]:
                pos.update(t_out=t, exit_utc=iso(t), proceeds=proceeds)
                pos, exit_ok = None, False
        prev = {"t": t, "edges": edges, "exit_ok": exit_ok}
    return trades, cap


def mark_end(tr: dict, snaps: list, m: dict, c: float, r: float) -> None:
    """Marks of a trade at the end of the window: realised if exited, else mid, liquidation and locked."""
    financing = c * r * tr["cost"] * ((tr["t_out"] or snaps[-1][0]) - tr["t_in"]) / YEAR_S
    if tr["t_out"] is not None:
        tr["pnl_mid"] = tr["pnl_liq"] = tr["pnl_locked"] = tr["proceeds"] - tr["cost"] - financing
        return
    t, pm_raw, k_raw = snaps[-1]
    pm, k = widen(pm_raw, c), widen(k_raw, c)

    def mid(b):
        return (b["b"][0][0] + b["a"][0][0]) / 2.0 if b["b"] and b["a"] else float("nan")

    pm_mid, k_mid = mid(pm_raw), mid(k_raw)
    value_mid = (pm_mid + 1 - k_mid) if tr["dir"] == "A" else (k_mid + 1 - pm_mid)
    tr["pnl_mid"] = tr["qty"] * value_mid - tr["cost"] - financing
    pl, kl = exit_legs(pm, k, tr["dir"])
    w = walk(pl, kl, m["pm_rate"], m["pm_exp"], m["k_mult"], c, 0.0, None, tr["qty"], buying=False)
    tr["liq_qty"] = w["qty"]
    tr["pnl_liq"] = (w["pm_gross"] + w["k_gross"] - w["pm_fee"] - w["k_fee"]) - tr["cost"] * w["qty"] / tr["qty"] - financing \
        if w["qty"] >= tr["qty"] - 1e-6 else float("nan")
    tr["pnl_locked"] = tr["locked_pnl"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--final", action="store_true", help="labelled update through Sun 09:30 ET instead of 07:00 ET")
    a = ap.parse_args()
    end = cfg.FORWARD_END_FINAL if a.final else cfg.FORWARD_END
    tag = "forward_final" if a.final else "forward"
    pull = json.loads((ds.CACHE / "pull_meta.json").read_text())
    metas = [{"ticker": p["ticker"], "token": p["token"], "question": p["question"], "deadline_ts": ds._iso(p["deadline"]).timestamp(),
              "k_mult": p["kalshi_fee_multiplier"], "pm_rate": p["pm_fee_rate"] if p["pm_fees_enabled"] else 0.0,
              "pm_exp": p["pm_fee_exponent"]} for p in pull["pairs"]]
    rows = load_rows(cfg.FORWARD_START, end)
    snaps = snapshots(rows, metas)
    last = max((s[-1][0] for s in snaps.values() if s), default=float("nan"))
    out_rows, all_trades, cap_rows = [], [], []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            trades = []
            for m in metas:
                sn = snaps.get(m["ticker"], [])
                if not sn:
                    continue
                tr, cap = paper_test(sn, m, v.theta, v.exit_on, c, a.rate, cfg.FORWARD_MAX_SIZE)
                for x in tr:
                    mark_end(x, sn, m, c, a.rate)
                    x.update(variant=v.id, cost_mult=c, segment=tag)
                trades.extend(tr)
                cap_rows.append({"variant": v.id, "cost_mult": c, "pair": m["ticker"], **cap})
            all_trades.extend(trades)
            cost = sum(x["cost"] for x in trades)
            out_rows.append({
                "segment": tag, "variant": v.id, "theta": v.theta, "exit_on": v.exit_on, "cost_mult": c,
                "start": iso(cfg.FORWARD_START.timestamp()), "end": iso(last) if last == last else "",
                "entries": len(trades), "pairs_traded": len({x["pair"] for x in trades}),
                "exits": sum(1 for x in trades if x["t_out"]), "contracts": sum(x["qty"] for x in trades),
                "capital": cost, "pnl_locked": sum(x["pnl_locked"] for x in trades),
                "pnl_mid": float(np.nansum([x["pnl_mid"] for x in trades])),
                "pnl_liq": float(np.nansum([x["pnl_liq"] for x in trades])),
                "locked_edge_bp": sum(x["pnl_locked"] for x in trades) / cost * 1e4 if cost else float("nan"),
                "fees_bp": sum(x["fees"] for x in trades) / cost * 1e4 if cost else float("nan"),
                "carry_bp": sum(x["carry"] for x in trades) / cost * 1e4 if cost else float("nan"),
                "capital_base": cfg.CAPITAL_FORWARD})
    RESULTS.mkdir(parents=True, exist_ok=True)

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
    write_csv(f"trades_{tag}.csv", all_trades)
    write_csv(f"capacity_{tag}.csv", cap_rows)
    n_snap = {k: len(v) for k, v in snaps.items()}
    (RESULTS / f"run_meta_{tag}.json").write_text(json.dumps({
        "window_start": cfg.FORWARD_START.isoformat(), "window_end": end.isoformat(), "last_snapshot": iso(last) if last == last else None,
        "rate": a.rate, "rows": len(rows), "pairs_with_snapshots": sum(1 for v in n_snap.values() if v),
        "snapshots_per_pair_median": float(np.median(list(n_snap.values()))) if n_snap else 0}, indent=1))
    print(f"{tag}: {len(rows)} book rows, last snapshot {iso(last) if last == last else 'none'}")
    print("var cost entries pairs exits contracts  capital  locked     mid     liq")
    for x in out_rows:
        print(f"{x['variant']} {x['cost_mult']:.0f}x {x['entries']:7d} {x['pairs_traded']:5d} {x['exits']:5d} {x['contracts']:9.0f} "
              f"{x['capital']:8.2f} {x['pnl_locked']:7.2f} {x['pnl_mid']:7.2f} {x['pnl_liq']:7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
