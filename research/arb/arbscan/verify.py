from __future__ import annotations

from . import implied
from .costs import commission_per_share
from .datasrc import Http

DATA_API = "https://data-api.polymarket.com/trades"
WINDOW_SEC = 600
PAGE = 500
MAX_PAGES = 12


def fetch_trades(http: Http, condition_id: str) -> list[dict]:
    out: list[dict] = []
    for i in range(MAX_PAGES):
        d = http.get_json(DATA_API, {"market": condition_id, "limit": PAGE, "offset": i * PAGE}, allow_status=(400, 404))
        if not isinstance(d, list) or not d:
            break
        out.extend(d)
        if len(d) < PAGE:
            break
    return out


def needed_price(trade: str, p_lo: float, p_hi: float, width: float, fee, min_edge: float = implied.MIN_EDGE) -> float | None:
    comm = commission_per_share(width)
    grid = [i / 1000.0 for i in range(1, 1000)]
    if trade.startswith("A"):
        for b in grid:
            if b - fee.per_share(b) - p_hi - comm >= min_edge:
                return b
        return None
    for a in reversed(grid):
        if p_lo - a - fee.per_share(a) - comm >= min_edge:
            return a
    return None


def verify_row(trades: list[dict], snap_ts: float, trade: str, price_needed: float | None, window: float = WINDOW_SEC) -> dict:
    if price_needed is None:
        return {"verified": False, "verify_n": 0, "verify_size": 0.0}
    n, size = 0, 0.0
    for t in trades:
        ts = t.get("timestamp")
        if ts is None or abs(float(ts) - snap_ts) > window:
            continue
        px, side, out = float(t["price"]), str(t.get("side", "")).upper(), str(t.get("outcome", "")).lower()
        if out == "yes":
            yes_px, yes_side = px, side
        elif out == "no":
            yes_px, yes_side = 1.0 - px, ("BUY" if side == "SELL" else "SELL")
        else:
            continue
        if trade.startswith("A") and yes_side == "SELL" and yes_px >= price_needed - 1e-9:
            n, size = n + 1, size + float(t.get("size", 0))
        elif trade.startswith("B") and yes_side == "BUY" and yes_px <= price_needed + 1e-9:
            n, size = n + 1, size + float(t.get("size", 0))
    return {"verified": n > 0, "verify_n": n, "verify_size": size}
