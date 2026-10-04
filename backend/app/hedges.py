from __future__ import annotations

from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from polybridge_research.costs import half_spread
from pydantic import BaseModel

from . import chain
from .equities import get_client, get_snapshot

FEE_PER_SHARE_LEG = 0.0035
NO_EDGE_NOTE = "no edge found for this event; hedge only if you want insurance"
ORDER = ["protective_put", "collar", "cash_secured_put", "covered_call", "long_call"]
PRIORITY = {"hedge": ["protective_put", "collar"], "opportunity": ["cash_secured_put", "covered_call"]}
COVERS = {"protective_put": "downside", "collar": "downside", "cash_secured_put": "cash for shares (buy-the-dip)",
          "covered_call": "income, no downside cover", "long_call": "upside exposure"}


class Leg(BaseModel):
    action: Literal["buy", "sell"]
    leg: str
    contract: str
    kind: str
    strike: float
    mark: float | None = None


class HedgeOption(BaseModel):
    strategy: str
    legs: list[Leg]
    premium_per_share: float | None
    premium_total: float | None
    max_loss_per_share: float | None
    breakeven_price: float | None
    fees: float
    half_spread_cost: float | None
    covers: str
    rank: int
    why: str


class HedgeMenu(BaseModel):
    ticker: str
    spot: float | None = None
    expiry: str | None = None
    options: list[HedgeOption]
    notes: list[str] = []


def _recipes(otm: float) -> dict[str, list[tuple[str, str]]]:
    c, p = f"C_U{otm}", f"P_L{otm}"
    return {"protective_put": [("buy", p)], "collar": [("buy", p), ("sell", c)], "cash_secured_put": [("sell", p)],
            "covered_call": [("sell", c)], "long_call": [("buy", "C_K")]}


def build_options(snap: dict, shares: float, client, label: str) -> list[HedgeOption]:
    spot, legs_ = snap["spot"], snap["legs"]
    opts: list[HedgeOption] = []
    for strat, recipe in _recipes(snap["otm"]).items():
        legs = [Leg(action=a, leg=n, contract=legs_[n]["ticker"], kind=legs_[n]["kind"], strike=legs_[n]["strike"],
                    mark=legs_[n]["mark"]) for a, n in recipe]
        fees = FEE_PER_SHARE_LEG * shares * len(legs)
        if any(l.mark is None for l in legs):
            prem = None
        else:
            prem = sum(l.mark if l.action == "buy" else -l.mark for l in legs)
        hs = []
        for l in legs:
            try:
                hs.append(half_spread(client, l.contract, pd.Timestamp(snap["as_of"])))
            except Exception:
                hs.append(None)
        spread = None if any(h is None for h in hs) else sum(hs) * shares
        put = next((l for l in legs if l.kind == "put"), None)
        call_k = next((l for l in legs if l.kind == "call"), None)
        if prem is None:
            max_loss = breakeven = None
        elif strat in ("protective_put", "collar"):
            max_loss, breakeven = (spot - put.strike) + prem, spot + prem
        elif strat == "covered_call":
            max_loss, breakeven = spot + prem, spot + prem
        elif strat == "cash_secured_put":
            max_loss, breakeven = put.strike + prem, put.strike + prem
        else:
            max_loss, breakeven = prem, call_k.strike + prem
        opts.append(HedgeOption(strategy=strat, legs=legs, premium_per_share=prem,
                                premium_total=None if prem is None else prem * shares,
                                max_loss_per_share=max_loss, breakeven_price=breakeven, fees=fees,
                                half_spread_cost=spread, covers=COVERS[strat], rank=0, why=""))
    return _rank(opts, label)


def _rank(opts: list[HedgeOption], label: str) -> list[HedgeOption]:
    if label == "no_edge":
        protect = {"protective_put", "collar"}
        key = lambda o: (o.strategy not in protect, o.premium_per_share if o.premium_per_share is not None else 1e18)
        ordered = sorted(opts, key=key)
        why = lambda o: NO_EDGE_NOTE
    else:
        pri = PRIORITY[label]
        ordered = sorted(opts, key=lambda o: (pri.index(o.strategy) if o.strategy in pri else len(pri) + ORDER.index(o.strategy)))
        why = lambda o: ("Ranked first: the filing type's verdict is " + label + "." if o.strategy in pri
                         else "Available, but not what this verdict favors.")
    for i, o in enumerate(ordered, 1):
        o.rank, o.why = i, why(o)
    return ordered


router = APIRouter()


@router.get("/hedges/{ticker}", response_model=HedgeMenu)
async def hedges(ticker: str, request: Request, shares: float = 100, label: Literal["hedge", "opportunity", "no_edge"] = "no_edge") -> HedgeMenu:
    if not (shares > 0) or shares == float("inf"):
        raise HTTPException(422, "shares must be a positive finite number.")
    ticker = ticker.strip().upper()
    client = get_client(request)
    if client is None:
        return HedgeMenu(ticker=ticker, options=[], notes=["Massive key not configured"])
    try:
        snap, note = await get_snapshot(request, client, ticker)
    except Exception:
        return HedgeMenu(ticker=ticker, options=[], notes=["options data unavailable"])
    if snap is None:
        return HedgeMenu(ticker=ticker, options=[], notes=[note or "no listed options"])
    try:
        opts = await chain.bounded(build_options, snap, shares, client, label)
    except TimeoutError:
        return HedgeMenu(ticker=ticker, options=[], notes=["options data unavailable"])
    except Exception as e:
        return HedgeMenu(ticker=ticker, options=[], notes=[f"pricing unavailable: {type(e).__name__}"])
    return HedgeMenu(ticker=ticker, spot=snap["spot"], expiry=snap["expiry"], options=opts, notes=list(snap.get("notes", [])))
