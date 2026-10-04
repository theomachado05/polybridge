from __future__ import annotations

import time
from typing import Any, Awaitable, Callable


class TTLCache:

    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic):
        self.ttl_s = ttl_s
        self._clock = clock
        self._data: dict[Any, tuple[float, Any]] = {}

    async def get_or_set(self, key: Any, coro_fn: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
        hit = self._data.get(key)
        now = self._clock()
        if hit is not None and now - hit[0] < self.ttl_s:
            return hit[1], False
        try:
            value = await coro_fn()
        except Exception:
            if hit is not None:
                return hit[1], True
            raise
        self._data[key] = (now, value)
        return value, False
