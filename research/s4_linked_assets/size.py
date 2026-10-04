from __future__ import annotations

import csv
import json
import math
import sys

import numpy as np
import pandas as pd

from . import config as cfg
from . import data as dt
from . import engine as en
from .run import RESULTS, load_critic, verdict

BUCKETS = ((0.0, 2.0, "under 2"), (2.0, 5.0, "2 to 5"), (5.0, 10.0, "5 to 10"), (10.0, 1e9, "10 or more"))


def build() -> pd.DataFrame:
    critic, links = load_critic(), dt.proposer_links()

    def npz(name):
        f = dt.CACHE / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    weekend = np.concatenate([[False], (op[1:] - cl[:-1]) > 40 * 3600])
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(days)))
    seg = np.array(["OOS" if i >= len(days) - n_oos else "IS" for i in range(len(days))])
    spy_px = en.session_prices(spy_bars, sess)
    rows = []
    cache: dict[str, dict] = {}
    for l in links:
        fam = critic.get(l["market"], {}).get("family", "none")
        if verdict(l, critic) != "agreed" or fam != "event" or dt.is_motivating(l["market"], l["question"]):
            continue
        pm = npz(f"pm_{l['market'].split(':')[1]}.npz")
        if l["ticker"] not in cache:
            b, d = npz(f"eq_{l['ticker']}.npz"), npz(f"day_{l['ticker']}.npz")
            cache[l["ticker"]] = None if b is None or d is None or len(b["t"]) == 0 else {
                "px": en.session_prices(b, sess), "beta": en.betas(d, spy_day, days)}
        a = cache[l["ticker"]]
        if pm is None or len(pm["t"]) == 0 or a is None:
            continue
        ld = en.link_days(pm["t"], pm["p"].astype(float), l["direction"], sess, a["px"], spy_px, a["beta"])
        rows.append(pd.DataFrame({"day": days, "segment": seg, "weekend": weekend, "market": l["market"], "question": l["question"],
                                  "ticker": l["ticker"], "x": ld.x_night, "gap": ld.e_gap, "after": ld.e_day}))
    df = pd.concat(rows, ignore_index=True)
    return df[np.isfinite(df.x) & np.isfinite(df.gap)]


def boot_mean(v: np.ndarray, g: np.ndarray) -> tuple[float, float, float]:
    return en.date_bootstrap({d: list(v[g == d]) for d in np.unique(g)})


def r2(x: np.ndarray, y: np.ndarray, b: float) -> float:
    return float(1.0 - np.sum((y - b * x) ** 2) / np.sum(y ** 2))


def main() -> int:
    df = build()
    out: dict = {"link_days": int(len(df)), "links": int(df[["market", "ticker"]].drop_duplicates().shape[0]),
                 "tickers": int(df.ticker.nunique()), "dates": int(df.day.nunique())}
    ax = df.x.abs()
    out["share_abs_move"] = {lab: float(np.mean((ax >= lo) & (ax < hi))) for lo, hi, lab in BUCKETS}
    out["gap_sd_bp"] = float(df.gap.std())
    out["abs_move_mean_pp"] = float(ax.mean())

    buckets = []
    for scope, sm in (("all closures", np.ones(len(df), bool)), ("weekends only", df.weekend.to_numpy())):
        for lo, hi, lab in BUCKETS[1:]:
            s = df[sm & (ax >= lo) & (ax < hi)]
            if not len(s):
                continue
            signed_gap, signed_after = (np.sign(s.x) * s.gap).to_numpy(), (np.sign(s.x) * s.after).to_numpy()
            ok = np.isfinite(signed_after)
            m, lo_, hi_ = boot_mean(signed_gap, s.day.to_numpy())
            am, alo, ahi = boot_mean(signed_after[ok], s.day.to_numpy()[ok])
            buckets.append({"scope": scope, "odds_move_pp": lab, "link_days": int(len(s)), "dates": int(s.day.nunique()),
                            "tickers": int(s.ticker.nunique()), "mean_abs_move_pp": float(s.x.abs().mean()),
                            "signed_gap_bp": m, "gap_ci_lo": lo_, "gap_ci_hi": hi_, "gap_same_sign": float(np.mean(signed_gap > 0)),
                            "signed_after_open_bp": am, "after_ci_lo": alo, "after_ci_hi": ahi})

    is_, oos = df[df.segment == "IS"], df[df.segment == "OOS"]
    b_all = float(np.sum(df.x * df.gap) / np.sum(df.x ** 2))
    b_is = float(np.sum(is_.x * is_.gap) / np.sum(is_.x ** 2))
    out["slope_all"], out["slope_is"] = b_all, b_is
    out["r2_all"] = r2(df.x.to_numpy(), df.gap.to_numpy(), b_all)
    out["r2_oos_with_is_slope"] = r2(oos.x.to_numpy(), oos.gap.to_numpy(), b_is)
    big = df[ax >= 5]
    out["r2_moves_5pp_plus"] = r2(big.x.to_numpy(), big.gap.to_numpy(), b_all) if len(big) else float("nan")

    td = df.groupby(["day", "ticker"]).agg(x=("x", "mean"), gap=("gap", "first")).reset_index()
    out["ticker_day"] = en.clustered_slope(td.x.to_numpy(), td.gap.to_numpy(), td.day.to_numpy())

    per = []
    for tk, s in df.groupby("ticker"):
        r = en.clustered_slope(s.x.to_numpy(), s.gap.to_numpy(), s.day.to_numpy())
        per.append({"ticker": tk, "links": int(s[["market"]].drop_duplicates().shape[0]), "link_days": int(len(s)),
                    "weight": float(np.sum(s.x ** 2) / np.sum(df.x ** 2)), "slope_bp_per_pp": r["slope"], "t": r["t"],
                    "example": s.question.iloc[0][:70]})
    per.sort(key=lambda r: -r["weight"])
    loo = []
    for r in per[:5]:
        s = df[df.ticker != r["ticker"]]
        c = en.clustered_slope(s.x.to_numpy(), s.gap.to_numpy(), s.day.to_numpy())
        loo.append({"without": r["ticker"], "slope": c["slope"], "t": c["t"], "n": c["n"]})
    out["leave_one_ticker_out"] = loo

    def fit(d):
        c = en.clustered_slope(d.x.to_numpy(), d.gap.to_numpy(), d.day.to_numpy())
        return {"slope": c["slope"], "t": c["t"], "n": c["n"]}

    w = df.groupby("question").apply(lambda d: float(np.sum(d.x ** 2) / np.sum(df.x ** 2)), include_groups=False).sort_values(ascending=False)
    out["heaviest_markets"] = [{"question": q, "weight": float(v)} for q, v in w.head(5).items()]
    out["without_heaviest_market"] = fit(df[df.question != w.index[0]])
    out["without_three_heaviest_markets"] = fit(df[~df.question.isin(w.index[:3])])
    crypto = {"COIN", "GLXY", "HOOD", "MSTR", "MARA", "IBIT", "ETHA", "BMNR", "CRCL"}
    nc = df[~df.ticker.isin(crypto)]
    out["without_crypto_equities"] = {"all": fit(nc), "IS": fit(nc[nc.segment == "IS"]), "OOS": fit(nc[nc.segment == "OOS"])}
    bnc = nc[nc.x.abs() >= 10]
    sg = (np.sign(bnc.x) * bnc.gap).to_numpy()
    m, lo_, hi_ = boot_mean(sg, bnc.day.to_numpy())
    out["moves_10pp_plus_without_crypto"] = {"link_days": int(len(bnc)), "dates": int(bnc.day.nunique()), "signed_gap_bp": m,
                                             "ci_lo": lo_, "ci_hi": hi_, "same_sign": float(np.mean(sg > 0))}

    def write_csv(name, recs):
        with open(RESULTS / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
            w.writeheader()
            w.writerows(recs)

    write_csv("size_buckets.csv", buckets)
    write_csv("size_tickers.csv", per)
    (RESULTS / "size.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "leave_one_ticker_out"}, indent=1))
    print(pd.DataFrame(buckets).round(2).to_string(index=False))
    print(pd.DataFrame(per).head(14).round(3).to_string(index=False))
    print(pd.DataFrame(loo).round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
