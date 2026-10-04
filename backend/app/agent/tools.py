"""Tool catalogue for the voice agent: JSON schemas plus thin handlers over the existing route functions.

Every handler looks the route function up on its module at call time (so tests can monkeypatch it), and returns
(speakable summary, raw JSON). Approve and start_bridge refuse to run without confirm=true."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ValidationError

CONFIRM_TOOLS = {"approve", "start_bridge"}
# Screens the browser-only `navigate` tool can open (web routes: / /build /pipeline /bridge /portfolio ...).
SCREENS = ["landing", "build", "pipeline", "bridge", "portfolio", "library", "profile", "connect",
           "ladders", "tickets", "tested"]
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
    # The micro-markets product (read-only: nothing is drafted, approved or sent by these).
    {"name": "show_ladders", "method": "GET", "path": "/ladders",
     "description": "Open the date-ladder board and summarise its pairs, violations and the C++ engine's decisions. "
                    "Read-only.",
     "parameters": _obj({})},
    {"name": "show_tickets", "method": "GET", "path": "/tickets",
     "description": "Open the ticket board; filter above_reference lists tickets priced above the options reference. "
                    "Read-only.",
     "parameters": _obj({"filter": {"type": "string", "enum": ["all", "above_reference"],
                                    "description": "above_reference: only tickets priced above the options reference."}})},
    {"name": "explain_ticket", "method": "GET", "path": "/tickets",
     "description": "Explain one ticket: prices, options reference band, gap, C++ decision and evidence status. "
                    "Read-only.",
     "parameters": _obj({"ticket_id": {"type": "string", "description": "Ticket id from show_tickets."}}, ["ticket_id"])},
    {"name": "explain_mechanism", "method": "GET", "path": "/evidence/mechanisms",
     "description": "Explain one tested mechanism: status, claim, numbers with ranges and samples, caveat. Read-only.",
     "parameters": _obj({"mechanism_id": {"type": "string", "description": "Mechanism id from what_we_tested, for "
                                          "example foundation, ladders, touch, ticket_option_hedge."}}, ["mechanism_id"])},
    {"name": "what_we_tested", "method": "GET", "path": "/evidence/mechanisms",
     "description": "List every mechanism we tested and its status. Read-only.",
     "parameters": _obj({})},
    # Browser-only: the web page moves to that screen itself and never calls the backend for it (no route). The
    # dispatcher echoes it so POST /agent/tool/navigate answers like every other tool.
    {"name": "navigate", "method": None, "path": None, "client_only": True,
     "description": "Open a screen when the user asks to see something.",
     "parameters": _obj({
         "screen": {"type": "string", "enum": SCREENS, "description": "The screen to open."},
         "bridge_id": {"type": "string", "description": "A bridge id, only with screen bridge, to open that bridge."}},
         ["screen"])},
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
    llm_by = str(out.get("llm") or "")
    how = ("Gemini suggested" if llm_by.startswith("gemini") else "OpenAI suggested" if llm_by.startswith("openai")
           else "A rules-based pick:")
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


async def _navigate(request: Request, a: dict):
    screen = str(_need(a, "screen"))
    if screen not in SCREENS:
        raise ToolError(f"I cannot open {screen}. I can open: {', '.join(SCREENS)}.")
    bid = a.get("bridge_id") if screen == "bridge" and isinstance(a.get("bridge_id"), str) and a["bridge_id"] else None
    return f"Opening {screen}.", {"screen": screen, "bridge_id": bid}


# ---------------------------------------------------------------- micro-markets product (read-only)

def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _cents(x: Any) -> str:
    v = _f(x)
    return "unknown" if v is None else f"{v * 100:.1f} cents"


def ticket_band(t: dict) -> dict | None:
    """The reference band a ticket is compared with (touch for a touch ticket, finish-beyond otherwise), as the web's
    ticketReference: None when the reference is unavailable."""
    r = t.get("reference")
    if not isinstance(r, dict) or r.get("available") is False or r.get("ok") is False:
        return None
    b = r.get("touch") if t.get("type") == "touch_ticket" else r.get("finish_beyond")
    return b if isinstance(b, dict) and _f(b.get("mid")) is not None else None


def ticket_gap(t: dict) -> float | None:
    """Polymarket mid minus the reference mid, in points (web ticketGap's mid). Positive = priced above."""
    b, bid, ask = ticket_band(t), _f(t.get("best_bid")), _f(t.get("best_ask"))
    if b is None or bid is None or ask is None:
        return None
    return 100 * ((bid + ask) / 2 - _f(b["mid"]))


async def _board(kind: str) -> dict:
    from ..contracts import router as cr
    out = await (cr.tickets() if kind == "tickets" else cr.ladders())
    if not isinstance(out, dict) or not out.get("ok"):
        raise ToolError(f"The {kind} board is not available right now"
                        + (f": {out.get('error')}." if isinstance(out, dict) and out.get("error") else "."))
    return out


def _status(ev: Any) -> str:
    return str(ev.get("status_label")) if isinstance(ev, dict) and ev.get("status_label") else "unknown status"


async def _show_ladders(request: Request, a: dict):
    d = await _board("ladders")
    c = d.get("counts") or {}
    ladders = d.get("ladders") or []
    decided = "the C++ engine" if c.get("decided_by") == "engine" else "the Python fallback rule"
    names = "; ".join(str(x.get("event_title") or x.get("template") or "")[:60] for x in ladders[:3])
    summary = (f"{c.get('ladders', len(ladders))} date ladders with {c.get('pairs', 0)} adjacent pairs; "
               f"{c.get('nested_pairs', 0)} pairs pass the nesting checks, {c.get('violations', 0)} violate their "
               f"order after fees, {c.get('actionable', 0)} are actionable. Decisions by {decided}. "
               f"Status: {_status(d.get('evidence'))}." + (f" Ladders include: {names}." if names else ""))
    return summary, {"counts": c, "evidence": d.get("evidence"), "as_of": d.get("as_of")}


def _ticket_row(t: dict) -> dict:
    b = ticket_band(t) or {}
    e = t.get("engine") if isinstance(t.get("engine"), dict) else {}
    g = ticket_gap(t)
    return {"id": t.get("id"), "question": t.get("question"), "type": t.get("type"),
            "gap_points": None if g is None else round(g, 1), "engine_action": e.get("action"),
            "reference_mid": b.get("mid"), "best_bid": t.get("best_bid"), "best_ask": t.get("best_ask")}


async def _show_tickets(request: Request, a: dict):
    d = await _board("tickets")
    ts = [t for t in d.get("tickets") or [] if isinstance(t, dict)]
    c = d.get("counts") or {}
    priced = [t for t in ts if ticket_gap(t) is not None]
    above = sorted((t for t in priced if ticket_gap(t) > 0), key=lambda t: -ticket_gap(t))
    proposals = [t for t in ts if isinstance(t.get("engine"), dict) and t["engine"].get("action") == "propose"]
    touch = _status((d.get("evidence") or {}).get("touch_ticket"))
    head = (f"{len(ts)} open tickets, {c.get('linked', 0)} linked to option contracts, {len(priced)} priced against "
            f"the options reference, {len(above)} above it. The engine drafts {len(proposals)} sell-YES "
            f"proposal{'s' if len(proposals) != 1 else ''} inside the tested rule. Touch tickets are an {touch}; "
            "no hedge is offered.")
    if a.get("filter") == "above_reference":
        top = "; ".join(f"{str(t.get('question'))[:70]} at {ticket_gap(t):+.1f} points" for t in above[:3])
        head += f" Highest above the reference: {top}." if top else " None is above the reference right now."
    rows = [_ticket_row(t) for t in (above if a.get("filter") == "above_reference" else priced)[:8]]
    return head, {"filter": a.get("filter") or "all", "counts": c, "above": len(above), "tickets": rows}


async def _explain_ticket(request: Request, a: dict):
    tid = str(_need(a, "ticket_id")).strip()
    d = await _board("tickets")
    t = next((x for x in d.get("tickets") or [] if isinstance(x, dict) and str(x.get("id")) == tid), None)
    if t is None:
        raise ToolError(f"I cannot find ticket {tid} on the board. Ask me to show the tickets first.")
    b, g = ticket_band(t), ticket_gap(t)
    ev = (d.get("evidence") or {}).get(t.get("type")) if isinstance(d.get("evidence"), dict) else None
    parts = [f"{t.get('question')}. Polymarket bid {_cents(t.get('best_bid'))}, ask {_cents(t.get('best_ask'))}."]
    if b:
        parts.append(f"The options {'touch' if t.get('type') == 'touch_ticket' else 'finish-beyond'} reference is "
                     f"{_cents(b.get('mid'))}, range {_cents(b.get('lo'))} to {_cents(b.get('hi'))}"
                     + (f", {g:+.1f} points from the Polymarket mid." if g is not None else "."))
        sess = (t.get("reference") or {}).get("session_label")
        if sess:
            parts.append(f"Reference: {sess}.")
    else:
        why = (t.get("reference") or {}).get("reason") if isinstance(t.get("reference"), dict) else None
        parts.append(f"No options reference{': ' + str(why) if why else ''}.")
    e = t.get("engine") if isinstance(t.get("engine"), dict) else None
    if e:
        who = "the C++ engine" if e.get("source") == "engine" else "the Python fallback rule"
        lat = f" in {int(e['latency_ns'])} nanoseconds" if isinstance(e.get("latency_ns"), (int, float)) else ""
        parts.append(f"Decision by {who} ({e.get('family')}){lat}: {e.get('action')}, {e.get('reason')}.")
    else:
        parts.append("No engine decision for this ticket.")
    parts.append(f"Status: {_status(ev)}. A proposal still needs your acknowledgement and approval on screen; "
                 "nothing is sent.")
    return " ".join(parts), {"ticket": _ticket_row(t), "evidence": ev}


def _registry() -> dict:
    from ..closed import router as clr
    return clr.get_mechanisms()


def _number_text(n: dict) -> str:
    v, lo, hi = n.get("value"), n.get("ci_low"), n.get("ci_high")
    rng = f", range {lo} to {hi} ({n.get('range_kind')})" if lo is not None and hi is not None and n.get("range_kind") != "census" else ""
    s = n.get("sample") or {}
    sample = f", sample {s.get('n')} {s.get('units')}" if isinstance(s, dict) and s.get("n") else ""
    return f"{n.get('label')}: {v} {n.get('unit') or ''}".rstrip() + rng + sample


async def _explain_mechanism(request: Request, a: dict):
    mid = str(_need(a, "mechanism_id")).strip().lower()
    mechs = [m for m in _registry().get("mechanisms") or [] if isinstance(m, dict)]
    m = next((x for x in mechs if str(x.get("id")).lower() == mid), None) or next(
        (x for x in mechs if mid in str(x.get("name", "")).lower()), None)
    if m is None:
        raise ToolError(f"I do not know a mechanism called {mid}. I know: {', '.join(str(x.get('id')) for x in mechs)}.")
    nums = [n for n in m.get("numbers") or [] if isinstance(n, dict)][:2]
    caveat = (m.get("caveats") or [None])[0]
    summary = (f"{m.get('name')}. Status: {m.get('status_label') or m.get('status')}. {m.get('claim')}"
               + (" Numbers: " + "; ".join(_number_text(n) for n in nums) + "." if nums else "")
               + (f" Caveat: {caveat}" if caveat else ""))
    return summary, {"id": m.get("id"), "status": m.get("status")}


async def _what_we_tested(request: Request, a: dict):
    mechs = [m for m in _registry().get("mechanisms") or [] if isinstance(m, dict)]
    lines = "; ".join(f"{m.get('name')}: {m.get('status_label') or m.get('status')}" for m in mechs)
    return (f"We tested {len(mechs)} mechanisms. {lines}. None of them is a validated trading edge.",
            {"mechanisms": [{"id": m.get("id"), "status": m.get("status")} for m in mechs]})


HANDLERS: dict[str, Handler] = {
    "search_markets": _search_markets, "fit": _fit, "propose": _propose, "approve": _approve,
    "start_bridge": _start_bridge, "bridge_status": _bridge_status, "account": _account, "positions": _positions,
    "navigate": _navigate, "show_ladders": _show_ladders, "show_tickets": _show_tickets,
    "explain_ticket": _explain_ticket, "explain_mechanism": _explain_mechanism, "what_we_tested": _what_we_tested,
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
