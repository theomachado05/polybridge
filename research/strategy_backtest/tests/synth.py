"""Synthetic world for the strategy backtest tests: sessions, SPY bars and measures, two PM markets."""
from __future__ import annotations

import numpy as np
import pandas as pd

from polybridge_research.calendar import TradingCalendar
from strategy_backtest.engine import et_instant

A, B = "mkt-a", "mkt-b"


def sessions(n: int) -> list[pd.Timestamp]:
    s = TradingCalendar().sessions
    return list(s[s >= pd.Timestamp("2024-01-02")][: n + 1])


def world(n: int = 80, seed: int = 0, rate: float = 8.0) -> dict:
    """Market A (sign +1) drives the gap at `rate` bp per pp; market B (sign -1) is noise."""
    rng = np.random.default_rng(seed)
    days = sessions(n)
    rows, pm, xa = [], {}, {}
    px = 470.0
    for i, d in enumerate(days):
        if i == 0:
            rows.append({"day": d, "open_px": px, "px_1000": px, "px_0800": px, "rth_close": px})
            continue
        prev = days[i - 1]
        x = float(rng.choice([-1, 1]) * rng.uniform(0.5, 3.0))
        xb = float(rng.normal(0, 1.0))
        gap = rate * x + rng.normal(0, 3.0)
        open_px = px * (1 + gap / 1e4)
        p1000 = open_px * (1 + rng.normal(0, 20) / 1e4)
        close = p1000 * (1 + rng.normal(0, 40) / 1e4)
        rows.append({"day": d, "open_px": open_px, "px_1000": p1000, "px_0800": px * (1 + 0.5 * gap / 1e4), "rth_close": close})
        tc = int(et_instant(prev, (16, 0)).timestamp())
        tp = int(et_instant(d, (7, 59)).timestamp())
        ts = int(et_instant(d, (9, 29)).timestamp())
        pa, pb = 0.5, 0.4
        pm[(A, prev.strftime("%Y-%m-%d"))] = [(tc - 60, pa), (tp - 60, pa + x / 200), (ts - 60, pa + x / 100), (ts + 300, 0.99)]
        pm[(B, prev.strftime("%Y-%m-%d"))] = [(tc - 60, pb), (tp - 60, pb), (ts - 60, pb + xb / 100), (ts + 300, 0.01)]
        xa[d] = x
        px = close
    meas = pd.DataFrame(rows).set_index("day")
    meas["t_close"] = [et_instant(d, (16, 0)) for d in meas.index]
    meas["vol5_usd"] = 2e8
    meas["vol5_pre_usd"] = 5e6
    markets = [{"market_slug": A, "label": "a", "sign": 1, "token_id": "1", "source": "panel_A",
                "start": "2023-12-01T00:00:00+00:00", "end": "2030-01-01T00:00:00+00:00"},
               {"market_slug": B, "label": "b", "sign": -1, "token_id": "2", "source": "panel_B", "rank": 1,
                "start": "2023-12-01T00:00:00+00:00", "end": "2030-01-01T00:00:00+00:00"}]
    part = {d: [A, B] for d in days[1:]}
    return {"days": days, "meas": meas, "pm": pm, "markets": markets, "part": part, "xa": xa}


def bars_from(meas: pd.DataFrame) -> pd.DataFrame:
    """Minute bars 07:30-15:59 ET that reproduce the measures exactly."""
    idx, op, cl = [], [], []
    for d, r in meas.iterrows():
        base = pd.Timestamp(d).tz_localize("America/New_York")
        for m in range(450, 960):
            if m < 570:
                o = c = r["px_0800"]
            elif m < 600:
                o = r["open_px"] if m == 570 else r["open_px"] + (r["px_1000"] - r["open_px"]) * (m - 570) / 29
                c = r["open_px"] + (r["px_1000"] - r["open_px"]) * (m - 570) / 29
            else:
                o = c = r["px_1000"] + (r["rth_close"] - r["px_1000"]) * (m - 599) / 360
            idx.append(base + pd.Timedelta(minutes=m))
            op.append(o)
            cl.append(c)
    out = pd.DataFrame({"open": op, "close": cl, "volume": 1000.0}, index=pd.DatetimeIndex(idx).tz_convert("UTC"))
    return out
