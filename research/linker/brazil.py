from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s5_big_moves import config as c5
from s5_big_moves import run as r5

from .benchmark import OUT, link_stats

MARKETS = (("Flávio Bolsonaro wins", "601826", 1), ("Lula wins", "601819", -1))
TICKERS = ("EWZ", "PBR", "VALE", "ITUB")
HORIZONS = (1, 2, 5, 10)


def ensure_data() -> None:
    C = r5.CACHE
    s, base = d4._massive_session()
    for tk in TICKERS:
        if not (C / f"eq_{tk}.npz").exists():
            np.savez_compressed(C / f"eq_{tk}.npz", **d4.equity_bars(s, base, tk, c5.WINDOW_START, c5.WINDOW_END))
            np.savez_compressed(C / f"day_{tk}.npz", **d4.daily_bars(s, base, tk, r5.DAILY_START, c5.WINDOW_END))
    pt = ds.Throttle(5.0)
    for _, mid, _ in MARKETS:
        if not (C / f"pm_{mid}.npz").exists():
            g = ds.get_json(f"{ds.GAMMA}/markets/{mid}", throttle=pt)
            tok = g["clobTokenIds"]
            tok = json.loads(tok)[0] if isinstance(tok, str) else tok[0]
            h = ds.pm_history({"token": tok}, ds._iso(g["startDate"]).replace(second=0, microsecond=0), datetime.now(timezone.utc), pt)
            np.savez_compressed(C / f"pm_{mid}.npz", **h)


def main() -> int:
    ensure_data()
    C = r5.CACHE
    spy_bars, spy_day = dict(np.load(C / "eq_SPY.npz")), dict(np.load(C / "day_SPY.npz"))
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    spy_px = en.session_prices(spy_bars, sess)
    cl = sess.close.to_numpy()
    spy_c = spy_px["close"]
    rows, lead = [], []
    for name, mid, dr in MARKETS:
        pm = dict(np.load(C / f"pm_{mid}.npz"))
        p_close = asof(cl.astype(np.int64), pm["t"], pm["p"].astype(float), 1800)
        for tk in TICKERS:
            a = {"px": en.session_prices(dict(np.load(C / f"eq_{tk}.npz")), sess), "beta": en.betas(dict(np.load(C / f"day_{tk}.npz")), spy_day, days)}
            rows.append({"question": name, "ticker": tk, "direction": "up_on_yes" if dr > 0 else "down_on_yes", **link_stats(pm, dr, sess, days, a, spy_px)})
            c = a["px"]["close"]
            dx = dr * 100 * np.diff(p_close)
            e = 1e4 * ((c[1:] / c[:-1] - 1) - a["beta"][1:] * (spy_c[1:] / spy_c[:-1] - 1))
            d = np.array(days[1:])
            ok = np.isfinite(dx) & np.isfinite(e)
            dx, e, d = dx[ok], e[ok], d[ok]
            for h in HORIZONS:
                fe = np.array([e[i + 1: i + 1 + h].sum() if i + 1 + h <= len(e) else np.nan for i in range(len(e))])
                fx = np.array([dx[i + 1: i + 1 + h].sum() if i + 1 + h <= len(dx) else np.nan for i in range(len(dx))])
                k1, k2 = np.isfinite(fe), np.isfinite(fx)
                r1 = en.clustered_slope(dx[k1], fe[k1], d[k1])
                r2 = en.clustered_slope(e[k2] / 100.0, fx[k2], d[k2])
                lead.append({"question": name, "ticker": tk, "next_days": h, "days": int(len(dx)),
                             "odds_first_bp_per_point": r1["slope"], "odds_first_t": r1["t"],
                             "equity_first_points_per_100bp": r2["slope"], "equity_first_t": r2["t"]})
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "brazil_links.csv", index=False)
    pd.DataFrame(lead).to_csv(OUT / "brazil_lead_lag.csv", index=False)
    pd.set_option("display.width", 220)
    print(pd.DataFrame(rows)[["question", "ticker", "days", "gap_bp_per_point", "gap_t", "intraday_t", "odds_mean_abs_move"]].round(2).to_string(index=False))
    print(pd.DataFrame(lead).round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
