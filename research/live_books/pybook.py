from __future__ import annotations

import json
import time

from . import detector


class PyBookEngine:
    def __init__(self, tau: float, fee_rate: float = 0.04, fee_exp: float = 1.0):
        self.tau, self.fee_rate, self.fee_exp = tau, fee_rate, fee_exp
        self.slots: dict[str, int] = {}
        self.info: list[tuple[int, bool]] = []
        self.active: set[str] = set()
        self.books: dict[str, tuple[dict, dict]] = {}
        self.p: dict[int, float] = {}
        self.fees: dict[int, bool] = {}
        self.out: list[tuple] = []
        self.bad_frames = self.other_events = 0

    def add_asset(self, a: str, market: int, is_yes: bool) -> int:
        if a not in self.slots:
            self.slots[a] = len(self.info)
            self.info.append((market, is_yes))
        self.info[self.slots[a]] = (market, is_yes)
        self.active.add(a)
        return self.slots[a]

    def remove_asset(self, a: str) -> bool:
        self.active.discard(a)
        return self.books.pop(a, None) is not None or a in self.slots

    def set_market(self, market: int, p_ref: float, fees_enabled: bool):
        self.p[market], self.fees[market] = p_ref, fees_enabled

    def set_p(self, market: int, p_ref: float):
        self.p[market] = p_ref

    def process(self, raw: str | bytes, t0: int, t0_mono: int = 0) -> int:
        self.out = []
        try:
            msg = json.loads(raw)
        except ValueError:
            self.bad_frames += 1
            return -1
        t1 = time.time_ns()
        for ev in (msg if isinstance(msg, list) else [msg]):
            if not isinstance(ev, dict):
                continue
            et = ev.get("event_type")
            if et == "book":
                a = ev.get("asset_id")
                if a not in self.active:
                    continue
                self.books[a] = ({float(x["price"]): float(x["size"]) for x in ev.get("bids") or []},
                                 {float(x["price"]): float(x["size"]) for x in ev.get("asks") or []})
                self.decide(a, t1, 0)
            elif et == "price_change":
                changes = ev.get("price_changes") or [dict(c, asset_id=ev.get("asset_id")) for c in ev.get("changes") or []]
                touched = []
                for c in changes:
                    a = c.get("asset_id")
                    if a not in self.active:
                        continue
                    bids, asks = self.books.setdefault(a, ({}, {}))
                    side = bids if c.get("side") == "BUY" else asks
                    px, sz = float(c["price"]), float(c["size"])
                    if sz > 0:
                        side[px] = sz
                    else:
                        side.pop(px, None)
                    if a not in touched:
                        touched.append(a)
                for a in touched:
                    self.decide(a, t1, 1)
        return len(self.out)

    def decide(self, a: str, t1: int, kind: int):
        market, is_yes = self.info[self.slots[a]]
        bids, asks = self.books[a]
        bb = max(bids) if bids else 0.0
        ba = min(asks) if asks else 0.0
        bs, as_ = bids.get(bb, 0.0), asks.get(ba, 0.0)
        if is_yes:
            yb, ybs, ya, yas = bb, bs, ba, as_
        else:
            yb, ybs = (1.0 - ba, as_) if ba > 0 else (0.0, 0.0)
            ya, yas = (1.0 - bb, bs) if bb > 0 else (0.0, 0.0)
        p = self.p.get(market, float("nan"))
        side, edge, net, px, sz = detector.decide(yb, ybs, ya, yas, p, self.tau, self.fee_rate, self.fee_exp,
                                                  self.fees.get(market, True))
        self.out.append((self.slots[a], kind, side, yb, ybs, ya, yas, None, None, p, edge, net, px, sz, t1, time.time_ns()))

    def decisions(self) -> list[tuple]:
        return self.out
