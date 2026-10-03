"""Fetch + cache, reusing the wave-1 CLOB fetcher and the closed-market study's Massive month-chunk fetcher."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from leadlag.data import CountingSession, fetch_pm_history  # noqa: F401
from leadlag_closed.data import fetch_equity_range  # noqa: F401

from .closures import Closure
from .config import CACHE_DIR, PARAMS


def closure_pm_window(c: Closure) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (c.nominal_close - pd.Timedelta(minutes=PARAMS.pm_pad_before_min),
            c.nominal_open + pd.Timedelta(minutes=PARAMS.pm_pad_after_min))


def fetch_market_pm(token_id: str, closures: list[Closure], session=None, cache_dir=None, workers: int = 6,
                    fetch=fetch_pm_history) -> dict[str, list | Exception]:
    cache_dir = cache_dir or (CACHE_DIR / "pm")

    def one(c: Closure):
        a, b = closure_pm_window(c)
        try:
            return c.key, fetch(token_id, a, b, cache_dir, session=session)
        except Exception as exc:  # noqa: BLE001
            return c.key, exc

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, closures))
