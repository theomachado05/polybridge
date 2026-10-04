"""Per-market closures and rows (METHOD.md sections 4-5). Pure functions, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd

from leadlag_closed.closures import Closure, build_closures, equity_measures, pm_at  # noqa: F401
from polybridge_research.calendar import TradingCalendar

from .config import EARLIER_PANELS, OPEN_DAY_MAX, TZ, WINDOW_END, WINDOW_START

EARLY_CLOSES = {"2023-07-03", "2023-11-24", "2024-07-03", "2024-11-29", "2024-12-24", "2025-07-03", "2025-11-28",
                "2025-12-24"}


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def window_closures(cal: TradingCalendar | None = None) -> list[Closure]:
    return [c for c in build_closures(WINDOW_START, WINDOW_END, cal) if c.open_day <= pd.Timestamp(OPEN_DAY_MAX)]


def market_closures(start, end, all_closures: list[Closure] | None = None) -> list[Closure]:
    s, e = _utc(start), _utc(end)
    return [c for c in (all_closures if all_closures is not None else window_closures())
            if c.nominal_close >= s and c.nominal_open <= e]


def calendar_close(c: Closure) -> pd.Timestamp:
    hrs = 13 if c.key in EARLY_CLOSES else 16
    return (c.close_day.tz_localize(TZ) + pd.Timedelta(hours=hrs)).tz_convert("UTC")


def pm_covered(points: list[tuple[int, float]], c: Closure) -> bool:
    return bool(np.isfinite(pm_at(points, calendar_close(c))) and np.isfinite(pm_at(points, c.nominal_open)))


def fresh_date(close_day: str) -> bool:
    d = pd.Timestamp(close_day)
    return not any(pd.Timestamp(a) <= d <= pd.Timestamp(b) for a, b in EARLIER_PANELS)


def panel_row(c: Closure, market: dict, points: list[tuple[int, float]], bars: pd.DataFrame | None) -> dict:
    eq = equity_measures(bars, c) if bars is not None else {"t_close": pd.NaT, "gap_bp": float("nan")}
    t_close = eq["t_close"] if pd.notna(eq["t_close"]) else calendar_close(c)
    pm_c, pm_o = pm_at(points, t_close), pm_at(points, c.nominal_open)
    ok = bool(np.isfinite(pm_c) and np.isfinite(pm_o))
    dpm = round(pm_o - pm_c, 9) if ok else float("nan")
    sign = int(market["sign"])
    reasons = [r for r, bad in (("no PM quote", not ok), ("no equity bar", not np.isfinite(eq["gap_bp"]))) if bad]
    return {"market": market["market_slug"], "rank": int(market["rank"]), "sign": sign, "cls": market["cls"],
            "closure": c.key, "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind,
            "fresh_date": fresh_date(c.key), "pm_close": pm_c, "pm_open": pm_o, "dpm_pp": dpm,
            "x_pp": sign * dpm if ok else float("nan"), "gap_spy_bp": eq["gap_bp"], "reason": "; ".join(reasons)}
