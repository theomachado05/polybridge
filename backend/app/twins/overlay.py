from __future__ import annotations

import bisect
import math

import httpx
import numpy as np

from .store import Twin, twin_of

MAX_STALE_S = 4 * 3600


def asof_join(tick_ts_s: list[int], other: list[tuple[int, float]], max_stale_s: int = MAX_STALE_S) -> np.ndarray:
    pts = sorted((t, p) for t, p in other if math.isfinite(p))
    ts = [t for t, _ in pts]
    out = np.full(len(tick_ts_s), np.nan)
    for i, t in enumerate(tick_ts_s):
        j = bisect.bisect_right(ts, t) - 1
        if j >= 0 and t - ts[j] <= max_stale_s:
            out[i] = pts[j][1]
    return out


async def twin_history(http: httpx.AsyncClient, twin: Twin) -> list[tuple[int, float]]:
    from ..pipeline import ticks as pt

    if twin.source == "kalshi":
        series, _ = await pt.kalshi_series(http, twin.id)
        return [(t, mid) for t, mid, _, _ in await pt.kalshi_quotes(http, twin.id, series)]
    if not twin.token_id:
        return []
    return await pt.polymarket_points(http, twin.token_id)


async def overlay_other_venue(ticks: dict[str, np.ndarray], points: list[tuple[int, float]], *, source: str | None,
                              market_id: str | None, token_id: str | None, http: httpx.AsyncClient) -> str | None:
    if not source:
        return None
    twin = twin_of(source, market_id, token_id)
    if twin is None:
        return None
    label = f"{twin.source} twin {twin.id}"
    try:
        other = await twin_history(http, twin)
    except Exception as e:
        return f"{label}: history unavailable ({type(e).__name__}), p_other_venue stays NaN"
    joined = asof_join([t for t, _ in points], other)
    if not np.isfinite(joined).any():
        return f"{label}: no history overlapping these ticks, p_other_venue stays NaN"
    ticks["p_other_venue"] = joined
    return f"p_other_venue from {label} ({int(np.isfinite(joined).sum())}/{len(joined)} ticks)"
