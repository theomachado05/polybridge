from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol

from polybridge_research.massive import BASE_URL

from .. import chain


@dataclass(frozen=True)
class Quote:
    mid: float
    half_spread: float | None
    source: str


class QuoteProvider(Protocol):
    async def equity(self, symbol: str) -> Quote | None: ...
    async def option(self, symbol: str) -> Quote | None: ...


class NullQuotes:

    async def equity(self, symbol: str) -> Quote | None:
        return None

    async def option(self, symbol: str) -> Quote | None:
        return None


def _pos(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _get(client, path: str, params: dict | None = None) -> dict:
    r = client.session.get(BASE_URL + path, params=params)
    r.raise_for_status()
    return r.json()


def _equity_sync(client, symbol: str) -> Quote | None:
    try:
        p = _pos((_get(client, f"/v2/last/trade/{symbol}").get("results") or {}).get("p"))
        if p is not None:
            return Quote(mid=p, half_spread=None, source="massive_last_trade")
    except Exception:
        pass
    rows = _get(client, f"/v2/aggs/ticker/{symbol}/prev", {"adjusted": "false"}).get("results") or []
    p = _pos(rows[0].get("c")) if rows else None
    return Quote(mid=p, half_spread=None, source="massive_prev_close") if p is not None else None


def _option_sync(client, symbol: str) -> Quote | None:
    rows = _get(client, f"/v3/quotes/{symbol}", {"order": "desc", "sort": "timestamp", "limit": 1}).get("results") or []
    if rows:
        bid, ask = _pos(rows[0].get("bid_price")), _pos(rows[0].get("ask_price"))
        if bid is not None and ask is not None and ask >= bid:
            return Quote(mid=(bid + ask) / 2, half_spread=(ask - bid) / 2, source="massive_option_quote")
    bars = _get(client, f"/v2/aggs/ticker/{symbol}/prev", {"adjusted": "false"}).get("results") or []
    p = _pos(bars[0].get("c")) if bars else None
    return Quote(mid=p, half_spread=None, source="massive_option_prev_close") if p is not None else None


class MassiveQuotes:
    def __init__(self, client_factory: Callable[[], object | None] = chain.make_client) -> None:
        self._factory = client_factory
        self._client: object | None = None
        self._resolved = False

    def _get_client(self):
        if not self._resolved:
            self._client, self._resolved = self._factory(), True
        return self._client

    async def _run(self, fn, symbol: str) -> Quote | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            return await chain.bounded(fn, client, symbol)
        except Exception:
            return None

    async def equity(self, symbol: str) -> Quote | None:
        return await self._run(_equity_sync, symbol)

    async def option(self, symbol: str) -> Quote | None:
        return await self._run(_option_sync, symbol)
