"""Tick sources for the bridge loop. Each is an async iterator of (ts_ns, p)."""
from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import AsyncIterator

import httpx

from .markets import polymarket_midpoint

Tick = tuple[int, float]


class SourceError(RuntimeError):
    """The tick source failed and cannot continue."""


class LiveSource:
    """Polls the Polymarket CLOB midpoint every `interval_s`. Raises SourceError after
    `max_failures` consecutive failed polls (one blip does not end the bridge)."""

    def __init__(self, token_id: str, interval_s: float = 1.0, max_failures: int = 3,
                 http: httpx.AsyncClient | None = None) -> None:
        self.token_id, self.interval_s, self.max_failures, self._http = token_id, interval_s, max_failures, http

    async def __aiter__(self) -> AsyncIterator[Tick]:
        http = self._http or httpx.AsyncClient()
        failures = 0
        try:
            while True:
                try:
                    p = await polymarket_midpoint(http, self.token_id)
                    if p is None:
                        raise ValueError("no midpoint")
                except Exception as e:
                    failures += 1
                    if failures >= self.max_failures:
                        raise SourceError(f"live source failed {failures}x: {type(e).__name__}") from e
                else:
                    failures = 0
                    yield time.time_ns(), p
                await asyncio.sleep(self.interval_s)
        finally:
            if self._http is None:
                await http.aclose()


class ReplaySource:
    """Reads JSONL `{ts_ns, p}` and re-emits it on the wall clock: the first tick is stamped "now" and recorded
    gaps are preserved divided by `speed` (speed 3600 plays hourly history at one tick per second).
    speed <= 0 means no sleeping and each tick is stamped with the current time (used by tests).
    Rows with a non-finite p are skipped."""

    def __init__(self, path: str | Path, speed: float = 1.0) -> None:
        self.path, self.speed = Path(path), speed

    async def __aiter__(self) -> AsyncIterator[Tick]:
        start = time.time_ns()
        first: int | None = None
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            ts, p = int(row["ts_ns"]), float(row["p"])
            if not math.isfinite(p):
                continue
            if first is None:
                first = ts
            if self.speed > 0:
                target = start + int((ts - first) / self.speed)
                delay = (target - time.time_ns()) / 1e9
                if delay > 0:
                    await asyncio.sleep(delay)
                yield min(target, time.time_ns()), p  # never future-dated vs. the engine's now_ns
            else:
                yield time.time_ns(), p
