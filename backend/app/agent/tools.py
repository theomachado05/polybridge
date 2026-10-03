"""Tool catalogue for the voice agent: JSON schemas plus thin handlers over the existing route functions.

Every handler looks the route function up on its module at call time (so tests can monkeypatch it), and returns
(speakable summary, raw JSON). Approve and start_bridge refuse to run without confirm=true."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ValidationError

CONFIRM_TOOLS = {"approve", "start_bridge"}
Handler = Callable[[Request, dict], Awaitable[tuple[str, Any]]]


class ToolError(Exception):
    """A problem the agent should say out loud (bad arguments, missing confirmation)."""

    def __init__(self, message: str, *, needs_confirmation: bool = False):
        super().__init__(message)
        self.message, self.needs_confirmation = message, needs_confirmation


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_CONFIRM = {"type": "boolean", "description": "Must be true, and only after the user has clearly said yes out loud."}
_DIRECTION = {"type": "string", "enum": ["down_on_yes", "up_on_yes"],
              "description": "Which answer hurts the user's stock: down_on_yes means the stock falls if the market resolves yes."}

TOOLS: list[dict] = [
    {"name": "search_markets", "method": "GET", "path": "/markets/search",
     "description": "Find prediction markets about a topic, with their current yes price.",
     "parameters": _obj({"q": {"type": "string", "description": "Topic words, for example 'fed rate cut'."}}, ["q"])},
    {"name": "fit", "method": "POST", "path": "/pipeline/fit",
     "description": "Pick and tune a hedge for a stock against a market. Read-only, safe to run.",
     "parameters": _obj({
         "ticker": {"type": "string", "description": "Stock ticker, for example ABNB."},
         "question": {"type": "string", "description": "The market question in plain words, if no market id is known."},
         "market_source": {"type": "string", "description": "polymarket or kalshi."},
         "market_id": {"type": "string", "description": "Market id from search_markets."},
         "token_id": {"type": "string", "description": "Polymarket yes token id from search_markets."},
         "direction": _DIRECTION,
         "shares_held": {"type": "number", "description": "How many shares the user holds."}}, ["ticker"])},
    {"name": "propose", "method": "POST", "path": "/proposals",
     "description": "Draft a hedge proposal for the user to review. It does nothing until approved.",
     "parameters": _obj({
         "ticker": {"type": "string"},
         "shares_held": {"type": "number", "description": "Shares the user holds."},
         "market_source": {"type": "string", "description": "polymarket or kalshi."},
         "market_id": {"type": "string"},
         "token_id": {"type": "string"},
         "direction": _DIRECTION,
         "target_coverage": {"type": "number", "description": "Fraction to hedge, 0 to 1. Default 0.5."},
         "tags": {"type": "array", "items": {"type": "string"}, "description": "Filing tags, only if no market is given."}},
         ["ticker", "shares_held"])},
    {"name": "approve", "method": "POST", "path": "/proposals/{pid}/approve",
     "description": "Approve a proposal. Ask the user first and only call with confirm true after they say yes.",
     "parameters": _obj({"proposal_id": {"type": "string"}, "confirm": _CONFIRM}, ["proposal_id", "confirm"])},
    {"name": "start_bridge", "method": "POST", "path": "/bridges",
     "description": "Start the live hedge for an approved proposal. Ask the user first; confirm true only after yes.",
     "parameters": _obj({
         "proposal_id": {"type": "string"},
         "source": {"type": "string", "enum": ["live", "replay"], "description": "replay for the demo, live for real prices."},
         "gap_per_share": {"type": "number"},
         "confirm": _CONFIRM}, ["proposal_id", "confirm"])},
    {"name": "bridge_status", "method": "GET", "path": "/bridges/{bridge_id}",
     "description": "Check how a running hedge is doing.",
     "parameters": _obj({"bridge_id": {"type": "string"}}, ["bridge_id"])},
    {"name": "account", "method": "GET", "path": "/account",
     "description": "Read the paper trading account: cash and total value.",
     "parameters": _obj({})},
    {"name": "positions", "method": "GET", "path": "/positions",
     "description": "List what the account currently holds.",
     "parameters": _obj({})},
]
NAMES = {t["name"] for t in TOOLS}


def catalogue() -> list[dict]:
    """Schemas as served by GET /agent/tools; `webhook` is what the ElevenLabs server tool should call."""
    return [{**t, "webhook": {"method": "POST", "path": f"/agent/tool/{t['name']}"}} for t in TOOLS]


def _dump(x: Any) -> Any:
    if isinstance(x, BaseModel):
        return x.model_dump(mode="json")
    if isinstance(x, list):
        return [_dump(i) for i in x]
    return x


def _need(args: dict, key: str) -> Any:
    v = args.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ToolError(f"I need the {key.replace('_', ' ')} for that.")
    return v


def _market(args: dict) -> dict | None:
    if args.get("market_id"):
        return {"source": args.get("market_source") or "polymarket", "id": str(args["market_id"]),
                "token_id": args.get("token_id") or None}
    return None


def _money(x: Any) -> str:
    try:
        return f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return "an unknown amount"


async def _search_markets(request: Request, a: dict):
    from .. import markets
    out = _dump(await markets.markets_search(str(_need(a, "q")), request))
    ms = out["markets"]
    if not ms:
        return "I found no markets on that topic.", out
    parts = []
    for m in ms[:3]:
        p = m.get("yes_price") if m.get("yes_price") is not None else m.get("price")
        title = m.get("question") or m.get("title") or m.get("id")
        parts.append(f"{title}" + (f" at {round(float(p) * 100)} percent" if isinstance(p, (int, float)) else ""))
    return f"I found {len(ms)} markets. Top ones: " + "; ".join(parts) + ".", out


async def _fit(request: Request, a: dict):
    from ..pipeline import router as pr
    from ..pipeline.service import FitRequest
    body: dict = {"ticker": _need(a, "ticker")}
    for k in ("question", "direction", "shares_held"):
        if a.get(k) is not None:
            body[k] = a[k]
    if (m := _market(a)):
        body["market"] = m
    out = _dump(await pr.pipeline_fit(FitRequest(**body), request))
    score = out.get("score")
    s = (f"For {str(body['ticker']).upper()} I picked a {out.get('family') or 'default'} hedge for a {out.get('event_class')} event"
         + (f", score {score:.2f}" if isinstance(score, (int, float)) else ", unscored") + f". {out.get('rationale', '')}")
    return s.strip(), out


async def _propose(request: Request, a: dict):
    from .. import routes
    from ..models import ProposalIn
    body: dict = {"ticker": _need(a, "ticker"), "shares_held": _need(a, "shares_held")}
    for k in ("direction", "target_coverage", "tags"):
        if a.get(k) is not None:
            body[k] = a[k]
    if (m := _market(a)):
        body["market"] = m
    out = _dump(routes.create_proposal(ProposalIn(**body), request))
    return (f"I drafted proposal {out['id']}: a {out['strategy'].replace('_', ' ')} on {out['ticker']} covering "
            f"{round(out['target_coverage'] * 100)} percent of {out['shares_held']:g} shares. It is waiting for your approval. "
            "Shall I approve it?"), out


def _require_confirm(a: dict, what: str) -> None:
    if a.get("confirm") is not True:  # strictly the boolean true: the string "true" or 1 does not count
        raise ToolError(f"I need your explicit yes before I {what}. Ask the user, then call again with confirm true.",
                        needs_confirmation=True)


async def _approve(request: Request, a: dict):
    from .. import routes
    pid = str(_need(a, "proposal_id"))
    _require_confirm(a, f"approve proposal {pid}")
    out = _dump(routes.approve(pid, request))
    return f"Proposal {pid} is approved.", out


async def _start_bridge(request: Request, a: dict):
    from .. import bridges
    pid = str(_need(a, "proposal_id"))
    _require_confirm(a, f"start the hedge for proposal {pid}")
    body = bridges.BridgeIn(proposal_id=pid, source=a.get("source") or "replay",
                            gap_per_share=a.get("gap_per_share") or 0.0)
    out = _dump(await bridges.start_bridge(body, request, Response()))
    return f"The hedge is running as bridge {out.get('bridge_id')}.", out


async def _bridge_status(request: Request, a: dict):
    from .. import bridges
    out = _dump(bridges.bridge_summary(str(_need(a, "bridge_id")), request))
    bits = [f"{k.replace('_', ' ')} {v}" for k, v in out.items()
            if k in ("status", "ticks", "orders", "hedge", "coverage") and not isinstance(v, (dict, list))]
    return "Bridge status: " + (", ".join(bits) if bits else "running") + ".", out


async def _account(request: Request, a: dict):
    from ..broker import routes as br
    out = _dump(await br.get_account(request))
    return (f"The {out['broker']} account has {_money(out['cash'])} cash and {_money(out['equity'])} total value"
            + (", simulated." if out.get("simulated") else ".")), out


async def _positions(request: Request, a: dict):
    from ..broker import routes as br
    out = _dump(await br.get_positions(request))
    if not out:
        return "The account holds no positions.", out
    names = ", ".join(f"{p['qty']:g} {p['symbol']}" for p in out[:5])
    return f"The account holds {len(out)} positions: {names}" + (", and more." if len(out) > 5 else "."), out


HANDLERS: dict[str, Handler] = {
    "search_markets": _search_markets, "fit": _fit, "propose": _propose, "approve": _approve,
    "start_bridge": _start_bridge, "bridge_status": _bridge_status, "account": _account, "positions": _positions,
}


async def run_tool(name: str, request: Request, args: dict) -> dict:
    """Never raises: every failure becomes {ok: false, summary} so the agent can say it out loud."""
    try:
        summary, raw = await HANDLERS[name](request, args)
        return {"ok": True, "tool": name, "summary": summary, "data": raw}
    except ToolError as e:
        return {"ok": False, "tool": name, "summary": e.message, "needs_confirmation": e.needs_confirmation, "data": None}
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "the request was not accepted"
        return {"ok": False, "tool": name, "status": e.status_code, "summary": f"That did not work: {detail}", "data": None}
    except (ValidationError, ValueError, TypeError) as e:
        msg = "; ".join(str(x.get("msg", "")) for x in e.errors()) if isinstance(e, ValidationError) else "bad arguments"
        return {"ok": False, "tool": name, "summary": f"Those details were not valid: {msg}", "data": None}
    except Exception:
        return {"ok": False, "tool": name, "summary": "Something went wrong on my side. Please try again.", "data": None}
