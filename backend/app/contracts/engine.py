from __future__ import annotations

import time
from typing import Any

LADDER = "ladder_pair"
TICKET = "touch_ticket_reference"
ACTIONABLE = {"order"}
PROPOSE = {"propose"}


def _module() -> Any | None:
    try:
        import hedgecore  # noqa: PLC0415
    except Exception:
        return None
    return hedgecore if hasattr(hedgecore, "LadderPair") and hasattr(hedgecore, "TouchTicketReference") else None


def available() -> bool:
    return _module() is not None


def preset(mechanism_id: str) -> dict | None:
    try:
        from ..closed import evidence as ev  # noqa: PLC0415
        m = ev.mechanism(mechanism_id)
    except Exception:
        return None
    p = (m or {}).get("engine_preset")
    return dict(p) if isinstance(p, dict) else None


def _now_ns() -> int:
    return time.time_ns()


def effective_rate(p: float | None, rate: float, exponent: float) -> float:
    if p is None or not 0 < p < 1 or rate == 0:
        return 0.0
    return rate * (p * (1.0 - p)) ** exponent / (p * (1.0 - p))


def ladder_tick(pair: dict, rich: dict, cheap: dict, nested: bool | None, now_ns: int) -> dict:
    b, a = rich.get("best_bid"), cheap.get("best_ask")
    return {
        "ts_ns": now_ns,
        "bid_rich": b, "bid_rich_qty": rich.get("bid_size"),
        "ask_cheap": a, "ask_cheap_qty": cheap.get("ask_size"),
        "fee_rate_rich": effective_rate(b, rich.get("fee_rate", 0.0), rich.get("fee_exponent", 1.0)),
        "fee_rate_cheap": effective_rate(a, cheap.get("fee_rate", 0.0), cheap.get("fee_exponent", 1.0)),
        "tick": max(float(rich.get("tick") or 0.01), float(cheap.get("tick") or 0.01)),
        "ts_rich_ns": rich.get("book_ts_ns") or now_ns, "ts_cheap_ns": cheap.get("book_ts_ns") or now_ns,
        "nested": nested, "event_held": 0.0,
    }


def decide_ladder(tick: dict, now_ns: int) -> dict | None:
    hc = _module()
    pr = preset("ladders")
    if hc is None or pr is None:
        return None
    out = hc.LadderPair(dict(pr["params"])).on_tick(tick, now_ns)
    return {"family": LADDER, "source": "engine", "preset": pr["index"], "params": dict(pr["params"]),
            "action": out["action"], "reason": out["reason"], "reason_block": out.get("reason_block"),
            "signal_points": out.get("signal"),
            "sizes": {"rich": out["rich"]["qty"], "cheap": out["cheap"]["qty"]},
            "limit_prices": {"rich": out["rich"]["limit_px"], "cheap": out["cheap"]["limit_px"]},
            "sides": {"rich": out["rich"]["side"], "cheap": out["cheap"]["side"]},
            "latency_ns": out["latency_ns"], "actionable": out["action"] in ACTIONABLE}


def ticket_tick(row: dict, ref: dict, now_ns: int) -> dict:
    central = (ref.get("central") or ref.get("touch") or {}).get("mid")
    return {"ts_ns": row.get("book_ts_ns") or now_ns, "bid": row.get("best_bid"), "bid_qty": row.get("bid_size"),
            "ask": row.get("best_ask"), "ref_lower": ref.get("lower_bound"), "ref_central": central,
            "underlying_short": 0.0, "event_short": 0.0, "validated": False}


def decide_ticket(tick: dict, now_ns: int) -> dict | None:
    hc = _module()
    pr = preset("touch")
    if hc is None or pr is None:
        return None
    out = hc.TouchTicketReference(dict(pr["params"])).on_tick(tick, now_ns)
    return {"family": TICKET, "source": "engine", "preset": pr["index"], "params": dict(pr["params"]),
            "action": out["action"], "reason": out["reason"], "reason_block": out.get("reason_block"),
            "signal_points": out.get("signal"), "qty": out["qty"], "limit_px": out["limit_px"],
            "latency_ns": out["latency_ns"], "propose": out["action"] in PROPOSE}
