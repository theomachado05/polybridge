from __future__ import annotations

import numpy as np
import pandas as pd

from leadlag_closed.closures import Closure, build_closures, equity_measures, pm_at  # noqa: F401  (re-exported)
from polybridge_research.calendar import TradingCalendar

from .config import OPEN_DAY_MAX, ORIGINAL_PANELS, TZ, WINDOW_END, WINDOW_START

EARLY_CLOSES = {"2024-07-03", "2024-11-29", "2024-12-24", "2025-07-03", "2025-11-28", "2025-12-24"}


def market_closures(start: str | pd.Timestamp, end: str | pd.Timestamp, cal: TradingCalendar | None = None) -> list[Closure]:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    s = s.tz_localize("UTC") if s.tzinfo is None else s.tz_convert("UTC")
    e = e.tz_localize("UTC") if e.tzinfo is None else e.tz_convert("UTC")
    out = []
    for c in build_closures(WINDOW_START, WINDOW_END, cal):
        if c.open_day > pd.Timestamp(OPEN_DAY_MAX):
            continue
        if c.nominal_close >= s and c.nominal_open <= e:
            out.append(c)
    return out


def calendar_close(c: Closure) -> pd.Timestamp:
    hrs = 13 if c.key in EARLY_CLOSES else 16
    return (c.close_day.tz_localize(TZ) + pd.Timedelta(hours=hrs)).tz_convert("UTC")


def pm_covered(points: list[tuple[int, float]], c: Closure) -> bool:
    return bool(np.isfinite(pm_at(points, calendar_close(c))) and np.isfinite(pm_at(points, c.nominal_open)))


def in_original_panels(close_day: str) -> bool:
    d = pd.Timestamp(close_day)
    return any(pd.Timestamp(a) <= d <= pd.Timestamp(b) for a, b in ORIGINAL_PANELS)


def replication_row(c: Closure, market: dict, points: list[tuple[int, float]], bars: dict[str, pd.DataFrame],
                    primary: str = "SPY") -> dict:
    eq = {t: equity_measures(b, c) for t, b in bars.items()}
    p = eq[primary]
    t_close = p["t_close"] if pd.notna(p["t_close"]) else calendar_close(c)
    pm_c, pm_o = pm_at(points, t_close), pm_at(points, c.nominal_open)
    dpm = round(pm_o - pm_c, 9) if np.isfinite(pm_c) and np.isfinite(pm_o) else float("nan")
    sign = int(market["sign"])
    row = {"market": market["market_slug"], "rank": int(market["rank"]), "sign": sign, "cls": market_class(market),
           "closure": c.key, "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind,
           "fresh_date": not in_original_panels(c.key),
           "pm_close": pm_c, "pm_open": pm_o, "dpm_pp": dpm, "x_pp": sign * dpm if np.isfinite(dpm) else float("nan")}
    for t, m in eq.items():
        row[f"gap_{t.lower()}_bp"] = m["gap_bp"]
    reasons = []
    if not (np.isfinite(pm_c) and np.isfinite(pm_o)):
        reasons.append("no PM quote")
    if not np.isfinite(p["gap_bp"]):
        reasons.append("no equity bar")
    row["reason"] = "; ".join(reasons)
    return row


MACRO_TERMS = ("recession", "shutdown", "default", "tariff")


def market_class(market: dict) -> str:
    why = str(market.get("sign_reason", "")).split(": ", 1)[-1]
    return "US macro/policy" if any(why.startswith(t) for t in MACRO_TERMS) else "geopolitics"
