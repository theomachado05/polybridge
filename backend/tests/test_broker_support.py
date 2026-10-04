from __future__ import annotations

import asyncio

from app.broker.quotes import Quote


class FakeQuotes:

    def __init__(self, equity: dict[str, Quote] | None = None, option: dict[str, Quote] | None = None) -> None:
        self.eq, self.opt, self.calls = equity or {}, option or {}, []

    async def equity(self, symbol):
        self.calls.append(("equity", symbol))
        return self.eq.get(symbol)

    async def option(self, symbol):
        self.calls.append(("option", symbol))
        return self.opt.get(symbol)


def run(coro):
    return asyncio.run(coro)
