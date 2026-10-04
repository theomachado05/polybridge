from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.broker import BrokerError, OrderRequest, SimBroker, build_broker  # noqa: E402
from app.broker.webull import SIM_NOTE, WebullBroker  # noqa: E402
from app.closed.session import now_utc, session_at  # noqa: E402

SMOKE_SYMBOL = "SPY"
SMOKE_LIMIT = 1.00
SHORT_CHECK = ("SPY", "TLT", "IWM")


def mask(v: Any) -> str:
    s = str(v or "")
    return "***" + s[-3:] if len(s) > 3 else "***"


def smoke_enabled(env: dict | None = None) -> bool:
    return (env if env is not None else os.environ).get("WEBULL_SMOKE_ORDER", "").strip().lower() in ("1", "true", "yes")


async def check(broker: WebullBroker, now: dt.datetime, smoke: bool, out: Callable[[str], None] = print) -> dict:
    res: dict[str, Any] = {"broker": broker.name, "host": broker.client.base_url, "order_test": "skipped"}
    sess = session_at(now)
    res.update(market_open=sess.equities_open, session=sess.label, extended_hours=bool(broker.extended_hours))
    out("Webull paper check (read-only unless WEBULL_SMOKE_ORDER=1 during the regular session)")
    out(f"  broker          {broker.name}  host {broker.client.base_url} (paper sandbox only)")

    acct = await broker.account()
    aid = await broker._aid()
    res.update(account=mask(aid), account_type=acct.account_type, account_class=acct.account_class,
               account_label=acct.account_label, cash=acct.cash, equity=acct.equity, buying_power=acct.buying_power)
    out(f"  account         {mask(aid)}  {acct.account_class or '?'} ({acct.account_type or '?'}"
        f"{', ' + repr(acct.account_label) if acct.account_label else ''})")
    out(f"  balance         cash ${acct.cash:,.2f}  equity ${acct.equity:,.2f}  buying power ${acct.buying_power:,.2f}"
        f"  {acct.currency}")

    if acct.overnight_buying_power is not None or acct.day_buying_power is not None:
        out(f"  margin          overnight BP ${acct.overnight_buying_power or 0:,.2f}  day BP "
            f"${acct.day_buying_power or 0:,.2f}  option BP ${acct.option_buying_power or 0:,.2f}  maintenance "
            f"${acct.maintenance_margin or 0:,.2f}  margin calls {len(acct.open_margin_calls or [])}  day trades left "
            f"{acct.day_trades_left or '?'}")
    res.update(overnight_buying_power=acct.overnight_buying_power, day_buying_power=acct.day_buying_power,
               option_buying_power=acct.option_buying_power, maintenance_margin=acct.maintenance_margin)

    held = await broker.broker_positions()
    res["positions"] = [{"symbol": p.symbol, "asset": p.asset, "qty": p.qty} for p in held]
    res["positions_count"] = len(held)
    out(f"  positions       {len(held)}" + (": " + ", ".join(f"{p.symbol} {p.qty:g}" for p in held) if held else ""))

    opn = await broker.open_orders()
    res["open_orders"] = len(opn)
    out(f"  open orders     {len(opn)}" + (": " + ", ".join(f"{mask(o.id)} {o.side} {o.qty:g} {o.symbol}"
                                                              for o in opn) if opn else ""))
    hist = await broker.order_history(7)
    by: dict[str, int] = {}
    for o in hist:
        by[o.status] = by.get(o.status, 0) + 1
    res["history_count"], res["history_by_status"] = len(hist), by
    out(f"  order history   {len(hist)} in the last 7 days"
        + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(by.items())) + ")" if by else "")
        + ("  [truncated: more pages than read]" if broker.history_truncated else ""))
    rec = await broker.reconcile()
    res["reconcile"] = {k: v for k, v in rec.items() if k != "transitions"}
    out(f"  reconcile       read-only pass: {rec['checked']} tracked, {rec['open_at_webull']} open at Webull, "
        f"{rec['updated']} updated (runs every 15 s in the regular session while the backend is up)")

    res["options_supported"] = bool(broker.options_supported)
    out(f"  options         options_supported={broker.options_supported}"
        + ("  (option orders go to Webull paper)" if broker.options_supported else
           "  (documented by the Webull OpenAPI, unverified on the paper sandbox: options stay simulated; "
           "WEBULL_OPTIONS=1 sends them to Webull)"))
    shorts = await broker.short_status(list(SHORT_CHECK))
    res["can_short"] = {s: v.get("can_short") for s, v in shorts.items()}
    out("  can_short       " + ", ".join(f"{s} {v.get('can_short')}"
                                       + ("" if v.get("easy_to_borrow") is not False else " (hard to borrow)")
                                       for s, v in shorts.items())
        + f"  (account type {next(iter(shorts.values()), {}).get('account_type') or '?'})")
    out(f"  session         {sess.label}  market_open={sess.equities_open}")
    out(f"  extended_hours  {broker.extended_hours}"
        + ("" if broker.extended_hours else "  (Webull paper takes orders 09:30-16:00 ET only; WEBULL_EXTENDED_HOURS=1 "
                                            "turns extended-hours limits on)"))

    if not sess.equities_open:
        res["order_test"] = "skipped: market closed"
        out("  order test      skipped: market closed (Webull paper refuses orders outside 09:30-16:00 ET); "
            f"next regular open {sess.next_open.isoformat().replace('+00:00', 'Z')}")
    elif not smoke:
        res["order_test"] = "skipped: WEBULL_SMOKE_ORDER not set"
        out("  order test      skipped (set WEBULL_SMOKE_ORDER=1 to place and cancel a 1-share $1.00 SPY limit)")
    else:
        req = OrderRequest(symbol=SMOKE_SYMBOL, asset="equity", side="buy", qty=1, type="limit", limit_px=SMOKE_LIMIT,
                           client_order_id=f"smoke-{uuid.uuid4().hex[:12]}", note="webull-check smoke order")
        placed = await broker.place_order(req)
        res["placed"] = {"id": mask(placed.id), "status": placed.status, "reject_reason": placed.reject_reason}
        out(f"  order test      placed {mask(placed.id)}: buy 1 {SMOKE_SYMBOL} limit ${SMOKE_LIMIT:.2f} -> {placed.status}"
            + (f" ({placed.reject_reason})" if placed.reject_reason else ""))
        if placed.status == "open":
            cancelled = await broker.cancel(placed.id)
            res["cancelled"] = {"id": mask(cancelled.id), "status": cancelled.status}
            out(f"                  cancelled {mask(cancelled.id)} -> {cancelled.status}")
            res["order_test"] = "placed and cancelled" if cancelled.status == "cancelled" else "cancel " + cancelled.status
        else:
            res["order_test"] = f"place {placed.status}"
    out(f"  RESULT          OK ({'read-only' if 'placed' not in res else res['order_test']})")
    return res


async def main() -> int:
    broker = build_broker(None)
    if not isinstance(broker, WebullBroker):
        print("Webull paper is not configured: set BROKER=webull, WEBULL_APP_KEY (or WEBULL_API_KEY) and "
              "WEBULL_APP_SECRET (and WEBULL_ACCOUNT_ID) in .env. Nothing was checked.")
        return 2
    broker.sim = SimBroker(None, order_note=SIM_NOTE)
    try:
        await check(broker, now_utc(), smoke_enabled())
    except BrokerError as e:
        print(f"  ERROR           Webull answered: {e.message} (HTTP {e.status_code})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
