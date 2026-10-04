"""S4c, exploratory (METHOD.md amendment 2): does the linked equity already reflect the overnight move in odds in
the pre-market, where it can be traded? Entry 08:00 New York, exit at the 09:30 open.

Run from `research/`:  python -m s4_linked_assets.premarket [--pull]
"""
from __future__ import annotations

import csv
import json
import math
import sys

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof

from . import config as cfg
from . import data as dt
from . import engine as en
from .run import RESULTS, eligible, load_critic, verdict

ENTRY_FROM_MIN, ENTRY_TO_MIN = 8 * 60, 8 * 60 + 30       # first bar starting in [08:00, 08:30)
PRE_COST = {"liquid": 5.0, "other": 15.0, "spy": 2.0}     # per side, bp, pre-market entry


def pull_premarket() -> None:
    """5-minute bars starting 08:00 to 09:25 New York for every linked ticker and SPY (not committed)."""
    s, base = dt._massive_session()
    tickers = sorted({l["ticker"] for l in dt.proposer_links()} | {"SPY"})
    for tk in tickers:
        rows = []
        for a, b in dt.month_chunks(cfg.WINDOW_START, cfg.WINDOW_END):
            rows += dt.massive_rows(s, f"{base}/v2/aggs/ticker/{tk}/range/{dt.BAR_MIN}/minute/{a}/{b}",
                                    {"adjusted": "true", "sort": "asc", "limit": 50000})
        df = pd.DataFrame(rows).drop_duplicates("t").sort_values("t") if rows else pd.DataFrame(columns=["t", "o", "c", "v"])
        if len(df):
            local = pd.to_datetime(df.t, unit="ms", utc=True).dt.tz_convert(dt.ET)
            mins = local.dt.hour * 60 + local.dt.minute
            df = df[(mins >= ENTRY_FROM_MIN) & (mins < 570)]
        np.savez_compressed(dt.CACHE / f"pre_{tk}.npz", t=(df.t.to_numpy() // 1000).astype(np.int64), o=df.o.to_numpy(float),
                            c=df.c.to_numpy(float), v=df.v.to_numpy(float))
    print(f"pre-market bars saved for {len(tickers)} tickers", flush=True)


def entry_prices(pre: dict, sess: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Per session: the open of the first pre-market bar starting in [08:00, 08:30) and that bar's start time."""
    px, at = np.full(len(sess), np.nan), np.full(len(sess), np.nan)
    t, o = pre["t"], pre["o"]
    for i, op in enumerate(sess.open.to_numpy()):
        lo, hi = op - 90 * 60, op - 60 * 60                       # 08:00 and 08:30 on a 09:30 open
        j = np.searchsorted(t, lo)
        if j < len(t) and t[j] < hi:
            px[i], at[i] = o[j], t[j]
    return px, at


def pre_cost_bp(ticker: str, beta: float, mult: float) -> float:
    """Round trip, bp: pre-market entry and regular-open exit, on the equity and on the SPY hedge."""
    liquid = ticker in cfg.LIQUID
    entry = PRE_COST["liquid"] if liquid else PRE_COST["other"]
    exit_ = cfg.COST_LIQUID if liquid else cfg.COST_OTHER
    return mult * (entry + exit_ + abs(beta) * (PRE_COST["spy"] + cfg.COST_SPY))


def main() -> int:
    if "--pull" in sys.argv:
        pull_premarket()
    critic, links = load_critic(), dt.proposer_links()

    def npz(name):
        f = dt.CACHE / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    prev_cl = np.concatenate([[np.nan], cl[:-1]])
    weekend = np.concatenate([[False], (op[1:] - cl[:-1]) > 40 * 3600])       # more than one night between sessions
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(days)))
    seg = np.array(["OOS" if i >= len(days) - n_oos else "IS" for i in range(len(days))])
    spy_px = en.session_prices(spy_bars, sess)
    spy_pre, _ = entry_prices(npz("pre_SPY.npz"), sess)
    spy_prev = np.concatenate([[np.nan], spy_px["close"][:-1]])

    tk = {}
    for t in sorted({l["ticker"] for l in links}):
        b, d, p = npz(f"eq_{t}.npz"), npz(f"day_{t}.npz"), npz(f"pre_{t}.npz")
        if b is None or d is None or p is None or len(b["t"]) == 0:
            continue
        px = en.session_prices(b, sess)
        pre, at = entry_prices(p, sess)
        beta = en.betas(d, spy_day, days)
        prev = np.concatenate([[np.nan], px["close"][:-1]])
        tk[t] = {"beta": beta, "at": at,
                 "e_close_to_pre": 1e4 * ((pre / prev - 1) - beta * (spy_pre / spy_prev - 1)),
                 "e_pre_to_open": 1e4 * ((px["px"][:, 0] / pre - 1) - beta * (spy_px["px"][:, 0] / spy_pre - 1)),
                 "e_gap": 1e4 * ((px["px"][:, 0] / prev - 1) - beta * (spy_px["px"][:, 0] / spy_prev - 1))}

    rows = []
    for l in links:
        pm = npz(f"pm_{l['market'].split(':')[1]}.npz")
        if pm is None or len(pm["t"]) == 0 or l["ticker"] not in tk:
            continue
        a = tk[l["ticker"]]
        p_prev = asof(np.nan_to_num(prev_cl, nan=0).astype(np.int64), pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
        p_pre = asof((op - 91 * 60).astype(np.int64), pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)       # 07:59
        p_sig = asof((op - 60).astype(np.int64), pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)            # 09:29
        v = verdict(l, critic)
        rows.append(pd.DataFrame({
            "day": days, "segment": seg, "weekend": weekend, "market": l["market"], "ticker": l["ticker"],
            "x_pre": l["direction"] * 100.0 * (p_pre - p_prev), "x_night": l["direction"] * 100.0 * (p_sig - p_prev),
            "e_close_to_pre": a["e_close_to_pre"], "e_pre_to_open": a["e_pre_to_open"], "e_gap": a["e_gap"], "beta": a["beta"],
            "agreed": v == "agreed", "family": critic.get(l["market"], {}).get("family", "not reviewed"),
            "motivating": dt.is_motivating(l["market"], l["question"])}))
    df = pd.concat(rows, ignore_index=True)
    # the walk-forward gate of the main run, by link and day
    gate = pd.read_csv(RESULTS / "gate_days.csv") if (RESULTS / "gate_days.csv").exists() else None
    df["confirmed"] = False
    if gate is not None:
        df = df.drop(columns="confirmed").merge(gate, on=["day", "market", "ticker"], how="left")
        df["confirmed"] = df.confirmed.fillna(False).astype(bool)

    regs = []
    sets = (("agreed, event", eligible(df, cfg.VARIANTS[2])), ("trusted, event", eligible(df, cfg.VARIANTS[0])),
            ("every proposer link", eligible(df, cfg.VARIANTS[4])))
    for label, mask in sets:
        for scope, sm in (("all closures", np.ones(len(df), bool)), ("weekends only", df.weekend.to_numpy())):
            s = df[mask & sm]
            for name, x, y in (("previous close to 08:00, on the odds move to 07:59", s.x_pre, s.e_close_to_pre),
                               ("08:00 to the open, on the odds move to 07:59", s.x_pre, s.e_pre_to_open),
                               ("whole gap, on the odds move to 09:29", s.x_night, s.e_gap)):
                regs.append({"set": label, "scope": scope, "relation": name,
                             **en.clustered_slope(x.to_numpy(), y.to_numpy(), s.day.to_numpy())})

    trades, metrics = [], []
    for label, mask in sets[:2]:
        el = df[mask & np.isfinite(df.x_pre) & np.isfinite(df.e_pre_to_open)]
        sig = el.groupby(["day", "ticker"]).agg(x=("x_pre", "mean"), e=("e_pre_to_open", "first"), beta=("beta", "first"),
                                                segment=("segment", "first"), weekend=("weekend", "first")).reset_index()
        picked = pd.concat([en.pick(g) for _, g in sig.groupby("day")], ignore_index=True) if len(sig) else sig
        for c in cfg.COST_MULTIPLIERS:
            tt = []
            for r in picked.itertuples():
                gross = math.copysign(1.0, r.x) * r.e
                cost = pre_cost_bp(r.ticker, r.beta, c)
                tt.append({"set": label, "cost_mult": c, "segment": r.segment, "weekend": bool(r.weekend), "day": r.day, "ticker": r.ticker,
                           "x_pre_pp": r.x, "gross_bp": gross, "cost_bp": cost, "net_bp": gross - cost})
            trades += tt
            for sg in ("IS", "OOS"):
                st = [t for t in tt if t["segment"] == sg]
                dl = sorted({t["day"] for t in st})
                b = en.date_bootstrap({d: [t["net_bp"] for t in st if t["day"] == d] for d in dl})
                g = en.date_bootstrap({d: [t["gross_bp"] for t in st if t["day"] == d] for d in dl})
                metrics.append({"set": label, "segment": sg, "cost_mult": c, "trades": len(st), "tickers": len({t["ticker"] for t in st}),
                                "dates": len(dl), "mean_net_bp": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_bp": g[0],
                                "gross_ci_lo": g[1], "gross_ci_hi": g[2],
                                "hit_rate": float(np.mean([t["net_bp"] > 0 for t in st])) if st else float("nan"),
                                "mean_cost_bp": float(np.mean([t["cost_bp"] for t in st])) if st else float("nan")})

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

    write_csv("premarket_regressions.csv", regs)
    write_csv("premarket_trades.csv", trades)
    write_csv("premarket_metrics.csv", metrics)
    entry_ok = float(np.mean(np.isfinite(df[eligible(df, cfg.VARIANTS[2])].e_pre_to_open)))
    (RESULTS / "premarket_meta.json").write_text(json.dumps({"weekend_closures": int(weekend.sum()), "sessions": len(days),
                                                             "share_of_agreed_event_link_days_with_a_premarket_bar": entry_ok}, indent=1))
    for r in regs:
        print(f"{r['set'][:20]:20} | {r['scope']:13} | {r['relation'][:50]:50} | n {r['n']:5d} slope {r['slope']:7.2f} t {r['t']:6.2f} sign {r['sign_agree']:.2f}")
    print("set                  seg  cost trades tickers dates net_bp [ci]              gross_bp hit")
    for m in metrics:
        print(f"{m['set'][:20]:20} {m['segment']:4} {m['cost_mult']:.0f}x {m['trades']:6d} {m['tickers']:7d} {m['dates']:5d} {m['mean_net_bp']:6.1f} "
              f"[{m['ci_lo']:6.1f},{m['ci_hi']:6.1f}] {m['mean_gross_bp']:8.1f} {m['hit_rate']:.2f}")
    print(f"weekend closures {int(weekend.sum())} of {len(days)} sessions; agreed-event link-days with a pre-market bar {entry_ok:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
