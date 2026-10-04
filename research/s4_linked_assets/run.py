"""S4 run: the link agent's verdicts, the closure trade on trusted links, every variant at 1x and 2x costs, and the
descriptive lead-lag tables (METHOD.md). Reads the cached pull; writes research/results/s4_linked_assets/.

Run from `research/`:  python -m s4_linked_assets.run
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg
from . import data as dt
from . import engine as en

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "s4_linked_assets"


def load_critic() -> dict[str, dict]:
    """Blind critic answers by market id: family and the set of (ticker, direction) it named."""
    out = {}
    for f in sorted(HERE.glob("critic_*.json")):
        for a in json.loads(f.read_text())["answers"]:
            out[a["id"]] = {"family": a.get("family", "none"),
                            "links": {(l["ticker"], 1 if l["direction"] == "up_on_yes" else -1) for l in a.get("links", [])},
                            "tickers": {l["ticker"] for l in a.get("links", [])}}
    return out


def verdict(link: dict, critic: dict) -> str:
    c = critic.get(link["market"])
    if c is None:
        return "not reviewed"
    if (link["ticker"], link["direction"]) in c["links"]:
        return "agreed"
    return "opposite direction" if link["ticker"] in c["tickers"] else "not named"


def eligible(df: pd.DataFrame, v: cfg.Variant) -> pd.Series:
    ok = ~df.motivating
    if v.links == "trusted":
        ok &= df.agreed & df.confirmed
    elif v.links == "agreed":
        ok &= df.agreed
    if not v.spot_proxy:
        ok &= df.family == "event"
    return ok


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    pull = json.loads((dt.CACHE / "pull_meta.json").read_text())
    critic = load_critic()
    links = dt.proposer_links()
    log: list[str] = []

    def npz(name):
        f = dt.CACHE / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    spy_px = en.session_prices(spy_bars, sess)
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(days)))
    seg_of = {d: ("OOS" if i >= len(days) - n_oos else "IS") for i, d in enumerate(days)}
    log.append(f"sessions {len(days)} ({days[0]} to {days[-1]}); OOS from {days[len(days) - n_oos]} ({n_oos} sessions)")

    tickers = sorted({l["ticker"] for l in links})
    tk = {}
    for t in tickers:
        b, d = npz(f"eq_{t}.npz"), npz(f"day_{t}.npz")
        if b is None or len(b["t"]) == 0 or d is None or len(d["day"]) == 0:
            log.append(f"no equity data for {t}")
            continue
        tk[t] = {"px": en.session_prices(b, sess), "beta": en.betas(d, spy_day, days)}

    rows, link_rows = [], []
    for l in links:
        mid = l["market"].split(":")[1]
        pm = npz(f"pm_{mid}.npz")
        v = verdict(l, critic)
        fam = critic.get(l["market"], {}).get("family", "not reviewed")
        base = {"market": l["market"], "question": l["question"], "ticker": l["ticker"],
                "direction": "up_on_yes" if l["direction"] > 0 else "down_on_yes", "critic": v, "family": fam,
                "motivating": dt.is_motivating(l["market"], l["question"])}
        if pm is None or len(pm["t"]) == 0 or l["ticker"] not in tk:
            link_rows.append({**base, "sessions_with_odds": 0, "status": "no data"})
            continue
        a = tk[l["ticker"]]
        ld = en.link_days(pm["t"], pm["p"].astype(float), l["direction"], sess, a["px"], spy_px, a["beta"])
        g = en.gate(ld.sxx, ld.sxy, ld.nbin)
        df = pd.DataFrame({"day": days, "x_night": ld.x_night, "e_gap": ld.e_gap, "e_day": ld.e_day, "e_10": ld.e_10,
                           "x_next_night": ld.x_next_night, "x_next_24h": ld.x_next_24h, "beta": a["beta"],
                           "confirmed": g["confirmed"], "gate_slope": g["slope"], "gate_t": g["t"], "gate_bins": g["bins"],
                           "vol5": a["px"]["vol5"], "vol30": a["px"]["vol30"]})
        df = df.assign(market=l["market"], ticker=l["ticker"], agreed=v == "agreed", family=fam, motivating=base["motivating"])
        rows.append(df)
        has = np.isfinite(ld.x_night)
        conf_days = [d for d, c in zip(days, g["confirmed"]) if c]
        end_sxx, end_sxy = float(ld.sxx.sum()), float(ld.sxy.sum())
        full = en.gate(np.append(ld.sxx, 0.0), np.append(ld.sxy, 0.0), np.append(ld.nbin, 0))
        link_rows.append({**base, "sessions_with_odds": int(has.sum()), "gate_bins": int(ld.nbin.sum()),
                          "gate_sessions": int((ld.nbin > 0).sum()), "sensitivity_bp_per_pp": end_sxy / end_sxx if end_sxx > 0 else float("nan"),
                          "gate_t": float(full["t"][-1]), "confirmed_at_end": bool(full["confirmed"][-1]),
                          "first_confirmed": conf_days[0] if conf_days else "", "sessions_confirmed": len(conf_days),
                          "status": "trusted" if v == "agreed" and conf_days else "agreed, not confirmed" if v == "agreed" else
                          "confirmed, not agreed" if conf_days else "neither"})
    ld_all = pd.concat(rows, ignore_index=True)
    ld_all["segment"] = ld_all.day.map(seg_of)

    # ---- trades
    trades, eq_rows, metric_rows = [], [], []
    for v in cfg.VARIANTS:
        el = ld_all[eligible(ld_all, v) & np.isfinite(ld_all.x_night)]
        move = "e_day" if v.exit == "close" else "e_10"
        sig = el.groupby(["day", "ticker"]).agg(x=("x_night", "mean"), n_links=("x_night", "size"), e=(move, "first"),
                                                beta=("beta", "first"), vol5=("vol5", "first"), vol30=("vol30", "first")).reset_index()
        sig = sig[np.isfinite(sig.e)]
        picked = pd.concat([en.pick(g) for _, g in sig.groupby("day")], ignore_index=True) if len(sig) else sig
        for c in cfg.COST_MULTIPLIERS:
            tt = []
            for r in picked.itertuples():
                gross, net = en.trade_bp(r.x, r.e, r.ticker, r.beta, c)
                tt.append({"variant": v.id, "cost_mult": c, "segment": seg_of[r.day], "day": r.day, "ticker": r.ticker,
                           "side": "long" if r.x > 0 else "short", "x_night_pp": r.x, "links": int(r.n_links), "beta": r.beta,
                           "gross_bp": gross, "cost_bp": gross - net, "net_bp": net, "pnl": cfg.NOTIONAL * net / 1e4,
                           "traded": 2 * cfg.NOTIONAL * (1 + abs(r.beta)), "vol5": r.vol5, "vol30": r.vol30})
            trades.extend(tt)
            for seg in ("IS", "OOS"):
                dl = [d for d in days if seg_of[d] == seg]
                st = [t for t in tt if t["segment"] == seg]
                by_day = np.array([sum(t["pnl"] for t in st if t["day"] == d) for d in dl])
                m = en.day_metrics(by_day, dl, sum(t["traded"] for t in st))
                b = en.date_bootstrap({d: [t["net_bp"] for t in st if t["day"] == d] for d in dl})
                bg = en.date_bootstrap({d: [t["gross_bp"] for t in st if t["day"] == d] for d in dl})
                metric_rows.append({"segment": seg, "variant": v.id, "links": v.links, "spot_proxy": v.spot_proxy, "exit": v.exit,
                                    "cost_mult": c, "sessions": len(dl), "trades": len(st), "tickers": len({t["ticker"] for t in st}),
                                    "trade_dates": len({t["day"] for t in st}), "pnl": float(by_day.sum()),
                                    "mean_net_bp": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_bp": bg[0], "gross_ci_lo": bg[1],
                                    "gross_ci_hi": bg[2], "hit_rate": float(np.mean([t["net_bp"] > 0 for t in st])) if st else float("nan"),
                                    "mean_cost_bp": float(np.mean([t["cost_bp"] for t in st])) if st else float("nan"), **m})
                cum = np.cumsum(by_day)
                eq_rows += [{"variant": v.id, "cost_mult": c, "segment": seg, "day": d, "pnl": float(x)} for d, x in zip(dl, cum)]

    from polybridge_research.stats import deflated_sharpe
    for row in metric_rows:
        peers = [x["daily_sharpe"] for x in metric_rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"])
                 and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["sessions"], len(cfg.VARIANTS), float(np.var(peers)),
                                                      row["skew"], row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")

    # ---- regressions (described, not traded)
    regs = []
    for label, mask in (("trusted, event (V0 set)", eligible(ld_all, cfg.VARIANTS[0])),
                        ("agreed, event, no data gate", eligible(ld_all, cfg.VARIANTS[2])),
                        ("every proposer link", eligible(ld_all, cfg.VARIANTS[4])),
                        ("motivating example (Brazil)", ld_all.motivating)):
        sub = ld_all[mask]
        for seg in ("IS", "OOS", "ALL"):
            s = sub if seg == "ALL" else sub[sub.segment == seg]
            g = s.day.to_numpy()
            for name, x, y, unit in (("gap on overnight odds move", s.x_night.to_numpy(), s.e_gap.to_numpy(), "bp per pp"),
                                     ("move after the open on overnight odds move", s.x_night.to_numpy(), s.e_day.to_numpy(), "bp per pp"),
                                     ("next overnight odds move on the equity's session move", s.e_day.to_numpy() / 100.0,
                                      s.x_next_night.to_numpy(), "pp per 100 bp"),
                                     ("next 24h odds move on the equity's session move", s.e_day.to_numpy() / 100.0,
                                      s.x_next_24h.to_numpy(), "pp per 100 bp")):
                regs.append({"set": label, "segment": seg, "relation": name, "unit": unit, "links": int(s[["market", "ticker"]].drop_duplicates().shape[0]),
                             **en.clustered_slope(x, y, g)})

    # ---- write
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

    write_csv("links.csv", link_rows)
    write_csv("trades.csv", trades)
    write_csv("metrics.csv", metric_rows)
    write_csv("equity.csv", eq_rows)
    write_csv("regressions.csv", regs)
    ld_all[ld_all.motivating & np.isfinite(ld_all.x_night)][["day", "market", "ticker", "x_night", "e_gap", "e_day", "x_next_night", "x_next_24h",
                                                             "confirmed", "gate_slope", "gate_t"]].to_csv(RESULTS / "motivating.csv", index=False)
    lk = pd.DataFrame(link_rows)
    test = lk[~lk.motivating]
    counts = {"proposer_links": int(len(test)), "markets": int(test.market.nunique()), "critic": test.critic.value_counts().to_dict(),
              "family_of_markets": test.drop_duplicates("market").family.value_counts().to_dict(),
              "status": test.status.value_counts().to_dict()}
    (RESULTS / "run_meta.json").write_text(json.dumps({
        "sessions": len(days), "first": days[0], "last": days[-1], "oos_start": days[len(days) - n_oos], "oos_sessions": n_oos,
        "pull_t1": pull["t1"], "pull_failures": pull.get("failures", []), "counts": counts, "log": log,
        "run_seconds": round(time.time() - t_run, 1)}, indent=1))
    print(json.dumps(counts, indent=1))
    print("seg  var cost trades tickers dates      pnl  net_bp  [ci]            gross_bp  hit  sharpe   maxDD")
    for x in metric_rows:
        print(f"{x['segment']:4} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['tickers']:7d} {x['trade_dates']:5d} {x['pnl']:8.0f} "
              f"{x['mean_net_bp']:7.1f} [{x['ci_lo']:6.1f},{x['ci_hi']:6.1f}] {x['mean_gross_bp']:8.1f} {x['hit_rate']:5.2f} {x['sharpe']:6.2f} {x['max_drawdown']:7.4f}")
    for r in regs:
        if r["segment"] == "ALL":
            print(f"{r['set'][:30]:30} | {r['relation'][:52]:52} | n {r['n']:5d} slope {r['slope']:7.2f} t {r['t']:6.2f} sign {r['sign_agree']:.2f} ({r['unit']})")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(HERE.parent))
    sys.exit(main())
