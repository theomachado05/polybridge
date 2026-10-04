"""S5: links from two blind labellers, the data pull, P1 (replication of the opening-gap relation) and P2 (the
10-point continuation trade) on markets S4 never used (METHOD.md).

Run from `research/`:
    python -m s5_big_moves.run links     # merge the labels into links.csv (text only)
    python -m s5_big_moves.run pull      # odds and equity bars for the linked markets and tickers (not committed)
    python -m s5_big_moves.run           # the tests
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
RESULTS = RESEARCH / "results" / "s5_big_moves"
UTC = timezone.utc
DAILY_START = "2025-06-02"
BUCKETS = ((2.0, 5.0, "2 to 5"), (5.0, 10.0, "5 to 10"), (10.0, 1e9, "10 or more"))


def write_csv(path: Path, recs: list[dict]) -> None:
    keys: list[str] = []
    for rec in recs:
        for k in rec:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(recs)


# ---------------------------------------------------------------- links

def load_labels() -> dict[str, dict[str, dict]]:
    """labeller -> market id -> {family, links{(ticker, direction): confidence}}"""
    out: dict[str, dict[str, dict]] = {}
    for f in sorted(HERE.glob("labels_*.json")):
        d = json.loads(f.read_text())
        out[f.stem.split("_")[1]] = {a["id"]: {"family": a.get("family", "none"),
                                               "links": {(l["ticker"], 1 if l["direction"] == "up_on_yes" else -1): float(l.get("confidence", 0))
                                                         for l in a.get("links", []) if l.get("ticker") in cfg.MENU}}
                                     for a in d["answers"]}
    return out


def merge_links() -> tuple[list[dict], dict]:
    """A link is a (ticker, direction) both labellers of a chunk named, on a question both classed as an event."""
    uni = {m["id"]: m for m in json.loads((HERE / "universe.json").read_text())["markets"]}
    lab = load_labels()
    links, stats = [], {"questions": 0, "both_event": 0, "named_by_one": 0, "agreed": 0, "opposite_direction": 0, "markets_with_link": 0}
    for chunk in ("1", "2"):
        a, b = lab.get(chunk + "A", {}), lab.get(chunk + "B", {})
        for mid in a.keys() & b.keys():
            stats["questions"] += 1
            la, lb = a[mid], b[mid]
            both_event = la["family"] == "event" and lb["family"] == "event"
            stats["both_event"] += both_event
            ta, tb = {t for t, _ in la["links"]}, {t for t, _ in lb["links"]}
            agreed = set(la["links"]) & set(lb["links"]) if both_event else set()
            stats["opposite_direction"] += len({t for t in ta & tb if not any(k[0] == t for k in set(la["links"]) & set(lb["links"]))})
            stats["named_by_one"] += len(ta ^ tb)
            stats["agreed"] += len(agreed)
            stats["markets_with_link"] += bool(agreed)
            for tk, dr in sorted(agreed):
                links.append({"market": mid, "question": uni[mid]["question"], "ticker": tk, "direction": dr,
                              "direction_label": "up_on_yes" if dr > 0 else "down_on_yes", "confidence_a": la["links"][(tk, dr)],
                              "confidence_b": lb["links"][(tk, dr)], "volume": uni[mid]["volume"], "start": uni[mid]["start"],
                              "end": uni[mid]["end"], "token": uni[mid]["token"]})
    return links, stats


# ---------------------------------------------------------------- pull

def pull() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    links, _ = merge_links()
    markets = {l["market"]: l for l in links}
    t0 = time.time()
    pt = ds.Throttle(5.0)
    win_a = datetime.fromisoformat(cfg.WINDOW_START).replace(tzinfo=UTC) - timedelta(days=4)
    win_b = datetime.fromisoformat(cfg.WINDOW_END).replace(tzinfo=UTC) + timedelta(days=2)
    fails = []

    def job(m):
        try:
            a = max(ds._iso(m["start"]), win_a)
            b = min(ds._iso(str(m["end"]).replace(" ", "T").replace("+00", "+00:00") if "T" not in str(m["end"]) else m["end"]), win_b) + timedelta(days=1)
            h = ds.pm_history({"token": m["token"]}, a.replace(second=0, microsecond=0), min(b, datetime.now(UTC)), pt)
            np.savez_compressed(CACHE / f"pm_{m['market'].split(':')[1]}.npz", **h)
            return len(h["t"])
        except Exception as e:
            fails.append({"market": m["market"], "error": repr(e)[:200]})
            return 0

    with ThreadPoolExecutor(max_workers=6) as ex:
        pts = list(ex.map(job, markets.values()))
    print(f"{time.time() - t0:5.0f}s odds: {len(markets)} markets, {sum(1 for p in pts if p)} with data, {len(fails)} failures", flush=True)
    s, base = d4._massive_session()
    tickers = sorted({l["ticker"] for l in links} | {"SPY"})
    for tk in tickers:
        try:
            np.savez_compressed(CACHE / f"eq_{tk}.npz", **d4.equity_bars(s, base, tk, cfg.WINDOW_START, cfg.WINDOW_END))
            np.savez_compressed(CACHE / f"day_{tk}.npz", **d4.daily_bars(s, base, tk, DAILY_START, cfg.WINDOW_END))
        except Exception as e:
            fails.append({"ticker": tk, "error": repr(e)[:160].replace(s.headers["Authorization"], "<key>")})
    (CACHE / "pull_meta.json").write_text(json.dumps({"t1": datetime.now(UTC).isoformat(), "markets": len(markets), "tickers": len(tickers),
                                                      "failures": fails, "seconds": round(time.time() - t0, 1)}, indent=1))
    print(f"{time.time() - t0:5.0f}s equities: {len(tickers)} tickers; failures {len(fails)}", flush=True)
    for f in fails[:8]:
        print("  failure:", f, flush=True)


# ---------------------------------------------------------------- tests

def cost_bp(ticker: str, beta: float, mult: float) -> float:
    c = cfg.COST_LIQUID if ticker in cfg.LIQUID else cfg.COST_OTHER
    return mult * (2 * c + abs(beta) * 2 * cfg.COST_SPY)


def pick(sig: pd.DataFrame, threshold: float) -> pd.DataFrame:
    s = sig[np.abs(sig.x) >= threshold]
    return s.reindex(s.x.abs().sort_values(ascending=False).index).head(cfg.MAX_POSITIONS)


def run() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    links, stats = merge_links()
    uni = json.loads((HERE / "universe.json").read_text())

    def npz(name):
        f = CACHE / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    weekend = np.concatenate([[False], (op[1:] - cl[:-1]) > 40 * 3600])
    n_recent = int(math.ceil(cfg.OOS_FRACTION * len(days)))
    seg = np.array(["recent" if i >= len(days) - n_recent else "earlier" for i in range(len(days))])
    spy_px = en.session_prices(spy_bars, sess)
    tk: dict[str, dict | None] = {}
    rows, link_rows = [], []
    for l in links:
        if l["ticker"] not in tk:
            b, d = npz(f"eq_{l['ticker']}.npz"), npz(f"day_{l['ticker']}.npz")
            tk[l["ticker"]] = None if b is None or d is None or len(b["t"]) == 0 or len(d["day"]) == 0 else {
                "px": en.session_prices(b, sess), "beta": en.betas(d, spy_day, days)}
        a, pm = tk[l["ticker"]], npz(f"pm_{l['market'].split(':')[1]}.npz")
        base = {k: l[k] for k in ("market", "question", "ticker", "direction_label", "confidence_a", "confidence_b", "volume")}
        if a is None or pm is None or len(pm["t"]) == 0:
            link_rows.append({**base, "sessions_with_odds": 0, "status": "no data"})
            continue
        ld = en.link_days(pm["t"], pm["p"].astype(float), l["direction"], sess, a["px"], spy_px, a["beta"])
        g = en.gate(ld.sxx, ld.sxy, ld.nbin)
        ok = np.isfinite(ld.x_night)
        rows.append(pd.DataFrame({"day": days, "segment": seg, "weekend": weekend, "market": l["market"], "question": l["question"],
                                  "ticker": l["ticker"], "x": ld.x_night, "gap": ld.e_gap, "after": ld.e_day, "after10": ld.e_10,
                                  "beta": a["beta"], "confirmed": g["confirmed"], "vol30": a["px"]["vol30"]})[ok])
        link_rows.append({**base, "sessions_with_odds": int(ok.sum()), "max_abs_overnight_move_pp": float(np.nanmax(np.abs(ld.x_night))) if ok.any() else float("nan"),
                          "sessions_gate_confirmed": int(np.sum(g["confirmed"] & ok)), "status": "used" if ok.any() else "no overlap"})
    df = pd.concat(rows, ignore_index=True)
    df = df[np.isfinite(df.gap)]

    def fit(d, y="gap"):
        c = en.clustered_slope(d.x.to_numpy(), d[y].to_numpy(), d.day.to_numpy())
        return c

    # ---- P1
    regs = []
    td = df.groupby(["day", "ticker"]).agg(x=("x", "mean"), gap=("gap", "first"), after=("after", "first"), segment=("segment", "first"),
                                           weekend=("weekend", "first")).reset_index()
    nc = df[~df.ticker.isin(cfg.CRYPTO_EQUITIES)]
    for label, d in (("all link-days", df), ("one per ticker and day", td), ("weekends only", df[df.weekend]),
                     ("without crypto-linked equities", nc), ("earlier 80% of sessions", df[df.segment == "earlier"]),
                     ("most recent 20% of sessions", df[df.segment == "recent"]), ("links that pass the data gate", df[df.confirmed])):
        if len(d):
            regs.append({"sample": label, "relation": "opening gap on overnight odds move", **fit(d)})
            regs.append({"sample": label, "relation": "move after the open on overnight odds move", **fit(d[np.isfinite(d.after)], "after")})
    p1 = regs[0]

    # ---- size buckets (link-days)
    buckets = []
    for scope, d in (("all closures", df), ("weekends only", df[df.weekend])):
        for lo, hi, lab in BUCKETS:
            s = d[(d.x.abs() >= lo) & (d.x.abs() < hi)]
            if not len(s):
                continue
            sg, sa = (np.sign(s.x) * s.gap).to_numpy(), (np.sign(s.x) * s.after).to_numpy()
            okk = np.isfinite(sa)
            m1 = en.date_bootstrap({d_: list(sg[s.day.to_numpy() == d_]) for d_ in s.day.unique()})
            m2 = en.date_bootstrap({d_: list(sa[okk][s.day.to_numpy()[okk] == d_]) for d_ in s.day.unique()})
            buckets.append({"scope": scope, "odds_move_pp": lab, "link_days": int(len(s)), "dates": int(s.day.nunique()), "tickers": int(s.ticker.nunique()),
                            "signed_gap_bp": m1[0], "gap_ci_lo": m1[1], "gap_ci_hi": m1[2], "gap_same_sign": float(np.mean(sg > 0)),
                            "signed_after_open_bp": m2[0], "after_ci_lo": m2[1], "after_ci_hi": m2[2]})

    # ---- P2
    sig_all = df.groupby(["day", "ticker"]).agg(x=("x", "mean"), n_links=("x", "size"), after=("after", "first"), after10=("after10", "first"),
                                                beta=("beta", "first"), segment=("segment", "first"), weekend=("weekend", "first"),
                                                vol30=("vol30", "first"), question=("question", "first")).reset_index()
    trades, metric_rows, eq_rows = [], [], []
    for v in cfg.VARIANTS:
        move = "after" if v.exit == "close" else "after10"
        s = sig_all[np.isfinite(sig_all[move])]
        if v.weekends_only:
            s = s[s.weekend]
        picked = pd.concat([pick(g, v.threshold) for _, g in s.groupby("day")], ignore_index=True) if len(s) else s
        for c in cfg.COST_MULTIPLIERS:
            tt = []
            for r in picked.itertuples():
                gross = math.copysign(1.0, r.x) * getattr(r, move)
                cost = cost_bp(r.ticker, r.beta, c)
                tt.append({"variant": v.id, "cost_mult": c, "segment": r.segment, "weekend": bool(r.weekend), "day": r.day, "ticker": r.ticker,
                           "side": "long" if r.x > 0 else "short", "signal_pp": r.x, "links": int(r.n_links), "beta": r.beta, "gross_bp": gross,
                           "cost_bp": cost, "net_bp": gross - cost, "pnl": cfg.NOTIONAL * (gross - cost) / 1e4,
                           "traded": 2 * cfg.NOTIONAL * (1 + abs(r.beta)), "vol30": r.vol30, "question": r.question})
            trades += tt
            for sg_name in ("all", "earlier", "recent"):
                dl = [d for d, s_ in zip(days, seg) if sg_name == "all" or s_ == sg_name]
                st = [t for t in tt if t["day"] in set(dl)]
                by_day = np.array([sum(t["pnl"] for t in st if t["day"] == d) for d in dl])
                m = en.day_metrics(by_day, dl, sum(t["traded"] for t in st))
                b = en.date_bootstrap({d: [t["net_bp"] for t in st if t["day"] == d] for d in dl})
                g = en.date_bootstrap({d: [t["gross_bp"] for t in st if t["day"] == d] for d in dl})
                metric_rows.append({"segment": sg_name, "variant": v.id, "threshold_pp": v.threshold, "exit": v.exit, "weekends_only": v.weekends_only,
                                    "cost_mult": c, "sessions": len(dl), "trades": len(st), "tickers": len({t["ticker"] for t in st}),
                                    "trade_dates": len({t["day"] for t in st}), "pnl": float(by_day.sum()), "mean_net_bp": b[0], "ci_lo": b[1],
                                    "ci_hi": b[2], "mean_gross_bp": g[0], "gross_ci_lo": g[1], "gross_ci_hi": g[2],
                                    "hit_rate": float(np.mean([t["net_bp"] > 0 for t in st])) if st else float("nan"),
                                    "mean_cost_bp": float(np.mean([t["cost_bp"] for t in st])) if st else float("nan"), **m})
                if sg_name == "all":
                    eq_rows += [{"variant": v.id, "cost_mult": c, "day": d, "pnl": float(x)} for d, x in zip(dl, np.cumsum(by_day))]
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.stats import deflated_sharpe
    for row in metric_rows:
        peers = [x["daily_sharpe"] for x in metric_rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["sessions"], len(cfg.VARIANTS), float(np.var(peers)),
                                                      row["skew"], row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")

    write_csv(RESULTS / "links.csv", link_rows)
    write_csv(RESULTS / "universe.csv", [{k: m[k] for k in ("id", "question", "volume", "start", "end", "closed", "event")} for m in uni["markets"]])
    write_csv(RESULTS / "regressions.csv", regs)
    write_csv(RESULTS / "buckets.csv", buckets)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", metric_rows)
    write_csv(RESULTS / "equity.csv", eq_rows)
    pull_meta = json.loads((CACHE / "pull_meta.json").read_text())
    (RESULTS / "run_meta.json").write_text(json.dumps({
        "sessions": len(days), "first": days[0], "last": days[-1], "recent_from": days[len(days) - n_recent], "universe_counts": uni["counts"],
        "universe_candidates": uni["candidates"], "label_stats": stats, "links": len(links), "links_with_data": int(sum(1 for r in link_rows if r["status"] == "used")),
        "link_days": int(len(df)), "markets_in_test": int(df.market.nunique()), "tickers_in_test": int(df.ticker.nunique()),
        "dates_in_test": int(df.day.nunique()), "weekend_closures": int(weekend.sum()), "gap_sd_bp": float(df.gap.std()),
        "share_moves": {lab: float(np.mean((df.x.abs() >= lo) & (df.x.abs() < hi))) for lo, hi, lab in BUCKETS},
        "p1": p1, "pull_failures": pull_meta.get("failures", []), "run_seconds": round(time.time() - t_run, 1)}, indent=1))
    print(json.dumps(stats), "| links", len(links), "| link-days", len(df), "| markets", df.market.nunique(), "| tickers", df.ticker.nunique())
    for r in regs:
        print(f"{r['sample'][:32]:32} | {r['relation'][:44]:44} | n {r['n']:5d} slope {r['slope']:7.2f} t {r['t']:6.2f} sign {r['sign_agree']:.2f}")
    print(pd.DataFrame(buckets).round(1).to_string(index=False))
    print("seg     var cost trades tickers dates    pnl  net_bp [ci]              gross_bp  hit sharpe  maxDD")
    for x in metric_rows:
        print(f"{x['segment']:7} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['tickers']:7d} {x['trade_dates']:5d} {x['pnl']:7.0f} {x['mean_net_bp']:7.1f} "
              f"[{x['ci_lo']:6.1f},{x['ci_hi']:6.1f}] {x['mean_gross_bp']:8.1f} {x['hit_rate']:5.2f} {x['sharpe']:6.2f} {x['max_drawdown']:6.4f}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "links":
        ls, st = merge_links()
        print(json.dumps(st), "| links", len(ls), "| tickers", len({l["ticker"] for l in ls}))
    elif cmd == "pull":
        pull()
    else:
        sys.exit(run())
