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
     "description": "Approve a proposal. Ask the user first; confirm true only after yes. Unvalidated markets also need "
                    "ack_unvalidated.",
     "parameters": _obj({"proposal_id": {"type": "string"}, "confirm": _CONFIRM,
                         "ack_unvalidated": {"type": "boolean", "description": "True only after the user acknowledged "
                                             "that this market's signal has not passed its out-of-sample test."}},
                        ["proposal_id", "confirm"])},
    {"name": "start_bridge", "method": "POST", "path": "/bridges",
     "description": "Start the live hedge for an approved proposal. Ask the user first; confirm true only after yes.",
     "parameters": _obj({
         "proposal_id": {"type": "string"},
         "source": {"type": "string", "enum": ["live", "replay"], "description": "replay for the demo, live for real prices."},
         "gap_per_share": {"type": "number"},
         "market_source": {"type": "string", "description": "polymarket or kalshi. Only for proposals built from filing tags."},
         "market_id": {"type": "string", "description": "Market id. Only for proposals built from filing tags."},
         "token_id": {"type": "string", "description": "Polymarket yes token id, if known."},
         "direction": _DIRECTION,
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


def _recorded_matches(q: str, seen: set[tuple[str, str]]) -> list[dict]:
    """Recorded markets (replay index) whose question has every query word: a live search does not list resolved
    markets, but their recordings replay on demand (the default demo weekend is one). Labelled as recordings."""
    from .. import markets
    words = [w for w in q.lower().split() if len(w) > 2]
    if not words:
        return []
    try:
        recs = markets._recordings()
    except Exception:
        return []
    return [_dump(m) for m in recs
            if (m.source, m.id) not in seen and all(w in m.question.lower() for w in words)]


async def _search_markets(request: Request, a: dict):
    from .. import markets
    q = str(_need(a, "q"))
    try:
        out = _dump(await markets.markets_search(q, request))
    except HTTPException:
        out = {"markets": [], "stale": True, "note": "live market search unavailable"}
    rec = _recorded_matches(q, {(m.get("source"), m.get("id")) for m in out["markets"]})
    live = out["markets"]
    out["markets"] = live + rec  # live results first; recordings appended, each with its `recorded` file name
    if not out["markets"]:
        if out.get("note") == "live market search unavailable":
            raise ToolError("Live market search is unavailable right now, and no recorded market matches that topic.")
        return "I found no markets on that topic.", out
    parts = []
    for m in live[:3 if not rec else 2]:
        p = m.get("yes_price") if m.get("yes_price") is not None else m.get("price")
        title = m.get("question") or m.get("title") or m.get("id")
        parts.append(f"{title}" + (f" at {round(float(p) * 100)} percent" if isinstance(p, (int, float)) else ""))
    kind = "cached or offline" if out.get("stale") else "live"
    said = (f"I found {len(live)} {kind} markets. Top ones: " + "; ".join(parts) + ".") if live else (
        "Live search found nothing." if out.get("note") is None else "Live market search is unavailable.")
    if rec:
        said += " Recorded replays: " + "; ".join(f"{m['question']} (id {m['id']})" for m in rec[:2]) + "."
    return said, out


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
    how = "Gemini suggested" if str(out.get("llm") or "").startswith("gemini") else "A rules-based pick:"
    s = (f"For {str(body['ticker']).upper()} {how} a {out.get('family') or 'default'} hedge for a {out.get('event_class')} event"
         + (f", replay score {score:.2f} on {out.get('n_ticks') or 0} historical ticks" if isinstance(score, (int, float))
            else ", unscored") + f". {out.get('rationale', '')}")
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
    kind = "an opportunity, not a hedge" if out.get("family") == "opportunity" else "a draft"
    label = f" {out['label']}." if out.get("label") else ""
    ev = out.get("evidence") if isinstance(out.get("evidence"), dict) else None
    evidence = ("" if ev is None else " Its market's signal is validated out of sample." if ev.get("validated") else
                " Its market's signal is an unvalidated estimate: approving needs your acknowledgement of that.")
    return (f"I drafted proposal {out['id']} ({kind}): a {out['strategy'].replace('_', ' ')} on {out['ticker']} covering "
            f"{round(out['target_coverage'] * 100)} percent of {out['shares_held']:g} shares.{label}{evidence} It is waiting "
            "for your approval. Shall I approve it?"), out


def _require_confirm(a: dict, what: str) -> None:
    if a.get("confirm") is not True:  # strictly the boolean true: the string "true" or 1 does not count
        raise ToolError(f"I need your explicit yes before I {what}. Ask the user, then call again with confirm true.",
                        needs_confirmation=True)


async def _approve(request: Request, a: dict):
    from .. import routes
    pid = str(_need(a, "proposal_id"))
    _require_confirm(a, f"approve proposal {pid}")
    from ..models import ApproveIn
    out = _dump(routes.approve(pid, request, ApproveIn(ack_unvalidated=a.get("ack_unvalidated") is True)))
    return f"Proposal {pid} is approved.", out


async def _start_bridge(request: Request, a: dict):
    from .. import bridges
    pid = str(_need(a, "proposal_id"))
    _require_confirm(a, f"start the hedge for proposal {pid}")
    source = a.get("source") or "replay"
    kw: dict = {}
    if (m := _market(a)):
        kw["market"] = m
    if a.get("direction"):
        kw["direction"] = a["direction"]
    body = bridges.BridgeIn(proposal_id=pid, source=source, gap_per_share=a.get("gap_per_share") or 0.0, **kw)
    out = _dump(await bridges.start_bridge(body, request, Response()))
    where = ("on replayed historical data in a sandbox account, not live" if source == "replay"
             else "requesting live data")
    return (f"Started bridge {out.get('bridge_id')} {where}. Hedge figures are the engine's intent, not broker fills."), out


async def _bridge_status(request: Request, a: dict):
    from .. import bridges
    out = _dump(bridges.bridge_summary(str(_need(a, "bridge_id")), request))
    bits = [f"{k.replace('_', ' ')} {v}" for k, v in out.items()
            if k in ("status", "ticks", "orders", "hedge", "coverage") and not isinstance(v, (dict, list))]
    eff, req = out.get("source"), out.get("requested_source")
    src = ""
    if eff:
        src = f" Running on {eff} data" + (", in a sandbox account, not live" if out.get("account_scope") == "replay_sandbox" else "")
        if req and req != eff:
            src += f"; you asked for {req} but it is running on {eff}"
        src += "."
    return ("Bridge status: " + (", ".join(bits) if bits else "running") + "." + src
            + " Hedge and coverage are the engine's intent, not broker fills."), out


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
