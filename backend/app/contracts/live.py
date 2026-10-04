"""Live boards: Polymarket date ladders (GET /ladders) and stock / S&P 500 tickets (GET /tickets).

Every network call is bounded (per-request timeout, page cap, overall deadline) and cached; a failure returns an
``error`` with whatever was built, never an exception. Labels come from the evidence registry
(``app.closed.evidence.mechanism_for``) when it is present; no label is written here.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import time
from typing import Any

import httpx

from ..cache import TTLCache
from . import engine, research
from .classify import rules_classify

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
REQ_TIMEOUT_S = 6.0
DEADLINE_S = 20.0
LADDER_PAGES = 3                 # gamma keyset pages of 100 open events (volume >= $100k, as ladder_replay step 4)
TICKET_PAGES = 2
BOOKS_PER_CALL = 100
MAX_CHAINS = 40                  # option-contract listings per /tickets build
MAX_REFERENCES = 120              # options references per /tickets build (each one is its own Massive snapshot + NBBO)
REF_CONCURRENCY = 4              # references in flight at once
ROW_TIMEOUT_S = 8.0              # one ticket's listing + reference
TICKET_MARGIN_S = 2.0            # left of DEADLINE_S for serialising what was built
BUDGET = "budget"                # reason on a row whose reference was not built in this build's budget
MIN_RUNG_VOLUME = 50_000.0       # S11's rung volume rule (s11_bundles.config.MIN_MARKET_VOLUME)
TICKET_TAGS = ({"tag_slug": "hit-price"}, {"tag_id": 102676})   # touch_fresh's "hit-price" tag; fresh_accuracy's close-above tag
CACHE = TTLCache(60.0)


def contract_key(res: dict | None) -> str:
    """The registry key for a classifier result: "btc_15min" for the classifier's BTC watch mechanism, else its type."""
    res = res or {}
    return "btc_15min" if res.get("mechanism") == "btc_15m_watch" else str(res.get("type") or "other")


def evidence_for(contract_type: str) -> dict | None:
    """The registry entry's id, status and label for a contract type (or contract_key), or None when the registry is
    not present."""
    try:
        from ..closed import evidence as ev
        fn = getattr(ev, "mechanism_for", None)
        if fn is None:
            return None
        m = fn(contract_type)
    except Exception:
        return None
    if not isinstance(m, dict):
        return None
    return {k: m.get(k) for k in ("id", "status", "status_label", "trade_mechanism") if k in m}


async def _get(http: httpx.AsyncClient, url: str, params: dict) -> Any:
    r = await http.get(url, params=params, timeout=REQ_TIMEOUT_S)
    r.raise_for_status()
    return r.json()


async def open_events(http: httpx.AsyncClient, extra: dict, pages: int) -> list[dict]:
    out, cur = [], None
    for _ in range(pages):
        p = {"closed": "false", "active": "true", "limit": 100, **extra}
        if cur:
            p["after_cursor"] = cur
        d = await _get(http, f"{GAMMA}/events/keyset", p)
        if not isinstance(d, dict):
            break
        out += d.get("events") or []
        cur = d.get("next_cursor")
        if not cur or not d.get("events"):
            break
    return out


async def books(http: httpx.AsyncClient, tokens: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(tokens), BOOKS_PER_CALL):
        chunk = tokens[i:i + BOOKS_PER_CALL]
        r = await http.post(f"{CLOB}/books", json=[{"token_id": t} for t in chunk], timeout=REQ_TIMEOUT_S)
        if r.status_code == 200:
            for b in r.json() or []:
                out[str(b.get("asset_id"))] = b
    return out


def best(book: dict | None, side: str) -> float | None:
    lv = [float(x["price"]) for x in (book or {}).get(side) or [] if x.get("price") is not None]
    if not lv:
        return None
    return max(lv) if side == "bids" else min(lv)


def best_size(book: dict | None, side: str) -> float | None:
    """Size shown at the best level of one side (summed over entries at that price)."""
    px = best(book, side)
    if px is None:
        return None
    return sum(float(x.get("size") or 0) for x in (book or {}).get(side) or []
               if x.get("price") is not None and float(x["price"]) == px)


def book_ts_ns(book: dict | None) -> int | None:
    """The book's own timestamp (CLOB gives milliseconds), or None."""
    try:
        t = int(float((book or {}).get("timestamp")))
    except (TypeError, ValueError):
        return None
    return t * 1_000_000 if t > 0 else None


def token_and_fees(m: dict) -> dict:
    """YES token, taker fee rate and exponent, tick: the S11 catalogue fields (fees off unless enabled with a schedule)."""
    toks = m.get("clobTokenIds")
    try:
        toks = json.loads(toks) if isinstance(toks, str) else (toks or [])
    except ValueError:
        toks = []
    fs = m.get("feeSchedule") or {}
    on = bool(m.get("feesEnabled")) and bool(fs)
    try:
        tick = float(m.get("orderPriceMinTickSize") or 0.01)
    except (TypeError, ValueError):
        tick = 0.01
    return {"token": str(toks[0]) if toks else None, "fee_rate": float(fs.get("rate", 0.0)) if on else 0.0,
            "fee_exponent": float(fs.get("exponent", 1)) if on else 1.0, "tick": tick}


def fee(p: float, rate: float, exponent: float) -> float:
    """Polymarket taker fee per contract at price p (`s11_bundles.engine.fee`)."""
    return rate * (p * (1.0 - p)) ** exponent if 0 < p < 1 else 0.0


def pair_edge(bid_rich: float | None, ask_cheap: float | None, a: dict, b: dict) -> float | None:
    """Points locked in per contract by selling the earlier rung at its bid and buying the later rung at its ask, each
    one tick worse and after both taker fees (ladder_replay step 2's entry condition on live quotes). > 0 = violation."""
    if bid_rich is None or ask_cheap is None:
        return None
    pa, pb = bid_rich - a["tick"], ask_cheap + b["tick"]
    return 100.0 * ((pa - fee(pa, a["fee_rate"], a["fee_exponent"])) - (pb + fee(pb, b["fee_rate"], b["fee_exponent"])))


def _rung_market(m: dict) -> bool:
    try:
        vol = float(m.get("volume") or 0)
    except (TypeError, ValueError):
        vol = 0.0
    return not m.get("closed") and m.get("acceptingOrders") is not False and vol >= MIN_RUNG_VOLUME


def build_ladders(events: list[dict]) -> list[dict]:
    """Ladders of the given gamma events (rungs in re-derived date order with nesting checks), no prices yet."""
    lm = research.link_map()
    out = []
    for e in events:
        ms = [m for m in e.get("markets") or [] if _rung_market(m)]
        if len(ms) < 2:
            continue
        for lad in lm.link_ladders(ms, e):
            if len(lad["rungs"]) < 2:
                continue                 # a lone rung (its siblings below the volume rule) is not a ladder
            byid = {str(m.get("id")): m for m in ms}
            for r in lad["rungs"]:
                r.update(token_and_fees(byid[r["id"]]))
            lad["event_title"] = e.get("title")
            out.append(lad)
    return out


def price_ladders(ladders: list[dict], bk: dict[str, dict], now_ns: int | None = None) -> None:
    """Quotes on every rung, then the decision on every pair: the C++ ``ladder_pair`` family with the registry's
    preset when the compiled module has it, else the previous Python rule (``pair_edge`` > 0, nested, valid ladder),
    labelled ``source: "python_fallback"``. ``edge_points`` / ``violation`` stay as the descriptive Python measure of
    ladder_replay step 2 (each leg one tick worse); ``actionable`` is the deciding family's verdict."""
    now_ns = now_ns or engine._now_ns()
    for lad in ladders:
        rid = {r["id"]: r for r in lad["rungs"]}
        for r in lad["rungs"]:
            b = bk.get(r.get("token") or "")
            r["best_bid"], r["best_ask"] = best(b, "bids"), best(b, "asks")
            r["bid_size"], r["ask_size"] = best_size(b, "bids"), best_size(b, "asks")
            r["book_ts_ns"] = book_ts_ns(b)
        for p in lad["pairs"]:
            a, b = rid[p["rich"]], rid[p["cheap"]]
            e = pair_edge(a.get("best_bid"), b.get("best_ask"), a, b)
            p["bid_rich"], p["ask_cheap"] = a.get("best_bid"), b.get("best_ask")
            p["edge_points"] = None if e is None else round(e, 3)
            p["violation"] = bool(e is not None and e > 0)
            nested = None if p.get("nested") is None else bool(p["nested"] and lad.get("valid"))
            eng = engine.decide_ladder(engine.ladder_tick(p, a, b, nested, now_ns), now_ns)
            if eng is None:
                p["actionable"] = p["violation"] and bool(p["nested"]) and bool(lad["valid"])
                p["engine"] = {"family": engine.LADDER, "source": "python_fallback",
                               "action": "order" if p["actionable"] else "hold",
                               "reason": "python: edge after fees and a tick per leg > 0, nested" if p["actionable"]
                               else "python: no violation, or not nested"}
            else:
                p["actionable"] = eng.pop("actionable")
                p["engine"] = eng


async def ladders_board(http: httpx.AsyncClient | None = None) -> dict:
    async def build() -> dict:
        own = http is None
        client = http or httpx.AsyncClient()
        try:
            evs = await open_events(client, {"volume_min": 100000}, LADDER_PAGES)
            lads = build_ladders(evs)
            toks = sorted({r["token"] for lad in lads for r in lad["rungs"] if r.get("token")})
            price_ladders(lads, await books(client, toks))
            return {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(), "events_read": len(evs), "ladders": lads}
        finally:
            if own:
                await client.aclose()

    return await _served("ladders", build, "ladder_rung", lambda d: {
        "ladders": len(d.get("ladders", [])), "pairs": sum(len(x["pairs"]) for x in d.get("ladders", [])),
        "nested_pairs": sum(p["nested"] for x in d.get("ladders", []) for p in x["pairs"]),
        "violations": sum(bool(p.get("violation")) for x in d.get("ladders", []) for p in x["pairs"]),
        "actionable": sum(bool(p.get("actionable")) for x in d.get("ladders", []) for p in x["pairs"]),
        "decided_by": engine_source(p for x in d.get("ladders", []) for p in x["pairs"])})


def engine_source(rows) -> str | None:
    """"engine" / "python_fallback" / "mixed" over the rows that carry an engine block (None when none does)."""
    srcs = {(r.get("engine") or {}).get("source") for r in rows if r.get("engine")}
    return None if not srcs else srcs.pop() if len(srcs) == 1 else "mixed"


def decide_ticket(r: dict, threshold: float, now_ns: int) -> None:
    """The decision on one touch ticket with an options reference: the C++ ``touch_ticket_reference`` family
    (validated False: proposals only) when compiled, else the previous Python rule (bid at least ``threshold``
    points above the central reference mid), labelled ``source: "python_fallback"``."""
    ref = r.get("reference") or {}
    if r.get("type") != "touch_ticket" or not r.get("linkable") or not ref.get("available") \
            or ref.get("ok") is False:
        return
    eng = engine.decide_ticket(engine.ticket_tick(r, ref, now_ns), now_ns)
    if eng is None:
        central = (ref.get("central") or ref.get("touch") or {}).get("mid")
        bid = r.get("best_bid")
        ok = bid is not None and central is not None and 100.0 * (bid - central) >= threshold - 1e-9
        r["engine"] = {"family": engine.TICKET, "source": "python_fallback", "action": "propose" if ok else "hold",
                       "reason": f"python: bid {threshold:g}+ points above the central reference" if ok
                       else f"python: bid less than {threshold:g} points above the central reference, or no quote"}
        r["propose"] = ok
    else:
        r["propose"] = eng.pop("propose")
        r["engine"] = eng


def chain_rows(chain: Any) -> list[dict]:
    return [{"expiration_date": q.expiry, "strike_price": q.strike, "contract_type": q.kind, "ticker": q.ticker,
             "shares_per_contract": getattr(q, "shares_per_contract", 100) or 100}
            for q in getattr(chain, "quotes", []) if q.ticker and math.isfinite(q.strike)]


async def listed_rows(underlying: str, end_session: str) -> tuple[list[dict] | None, str]:
    """Listed contracts of one underlying from the end session day to 45 days later (Massive snapshot via
    ``app.options.chain``). (None, reason) when no key or the listing fails."""
    try:
        from ..options import chain as ch
        d0 = dt.date.fromisoformat(end_session)
        c, _stale = await ch.get_chain(underlying, expiry_from=d0, expiry_to=d0 + dt.timedelta(days=45))
        return chain_rows(c), ""
    except Exception as e:
        name = type(e).__name__
        return None, ("no MASSIVE_API_KEY: contracts not listed" if name == "NoClient" else f"contract listing failed: {name}")


async def reference(f: dict, kind: str) -> dict | None:
    try:
        from ..options import reference as ref
    except Exception:
        return None
    fn = getattr(ref, "reference_for", None)
    if fn is None:
        return None
    try:
        return await fn(f["underlying"], f["level"], "above" if f["direction"] == "up" else "below", f["window_end"],
                        "touch" if kind == "touch_ticket" else "finish")
    except Exception as e:
        return {"ok": False, "reason": f"reference failed: {type(e).__name__}"}


def ticket_rows(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        for m in e.get("markets") or []:
            if m.get("closed") or m.get("acceptingOrders") is False:
                continue
            mm = dict(m, event_title=e.get("title"), event_id=e.get("id"))
            c = rules_classify(m.get("question") or "", m.get("description"), mm)
            if c["type"] not in ("touch_ticket", "close_above_ticket"):
                continue
            out.append({"id": str(m.get("id")), "question": m.get("question"), "event_title": e.get("title"), "type": c["type"],
                        "fields": c["fields"], "checks": c["checks"], "linkable": c["linkable"], "reasons": c["reasons"],
                        **token_and_fees(m)})
    return out


def touch_threshold() -> float:
    """The registry's touch sell threshold (S21 book B0), 5 points when the registry is absent."""
    try:
        from ..closed import evidence as ev
        return float(ev.TOUCH_SELL_THRESHOLD_POINTS)
    except Exception:
        return 5.0


def _no_reference(reason: str) -> dict:
    return {"available": False, "ok": False, "reason": reason}


def _reference_only() -> dict | None:
    """For a close-above row: the reference is shown for information and points at the foundation entry, without that
    entry's status (close-above tickets are "no tested mechanism")."""
    try:
        from ..closed import evidence as ev
        ref_id = (getattr(ev, "REFERENCE_FOR", {}) or {}).get("close_above_ticket")
    except Exception:
        return None
    return {"reference_only": True, "evidence_id": ref_id} if ref_id else None


LISTING_TTL_S = 600.0            # contract listings per (underlying, expiry window) are kept 10 minutes
CHAIN_CONCURRENCY = 6            # listings in flight at once
_LISTINGS: dict[tuple[str, str, str], tuple[float, list[dict]]] = {}
_INFLIGHT: dict[tuple[str, str, str], asyncio.Task] = {}


def reset_listing_cache() -> None:
    """Tests: forget cached and in-flight listings."""
    _LISTINGS.clear()
    _INFLIGHT.clear()


def _listing_key(underlying: str, end_session: str) -> tuple[str, str, str]:
    d0 = dt.date.fromisoformat(end_session)
    return underlying, d0.isoformat(), (d0 + dt.timedelta(days=45)).isoformat()


def cached_listing(underlying: str, end_session: str) -> tuple[list[dict] | None, str] | None:
    """A listing fetched in the last LISTING_TTL_S for this (underlying, expiry window), or None."""
    hit = _LISTINGS.get(_listing_key(underlying, end_session))
    if hit is not None and time.monotonic() - hit[0] < LISTING_TTL_S:
        return hit[1], ""
    return None


def listing_task(underlying: str, end_session: str) -> asyncio.Task:
    """The in-flight listing for this key (shared by every row and build). A listing the build's deadline cut off
    keeps running and fills the cache, so the next build finds it warm."""
    key = _listing_key(underlying, end_session)
    loop = asyncio.get_running_loop()
    t = _INFLIGHT.get(key)
    if t is not None and not t.done() and t.get_loop() is loop:
        return t

    async def fetch() -> tuple[list[dict] | None, str]:
        try:
            rows, why = await listed_rows(underlying, end_session)
            if rows is not None:
                _LISTINGS[key] = (time.monotonic(), rows)
            return rows, why
        finally:
            if _INFLIGHT.get(key) is asyncio.current_task():
                _INFLIGHT.pop(key, None)

    t = loop.create_task(fetch())
    _INFLIGHT[key] = t
    return t


async def link_and_price(rows: list[dict], deadline: float) -> dict:
    """Exact contract link and options reference for every linkable row, incremental and bounded.

    Listings: one per (underlying, expiry window), at most MAX_CHAINS per build, CHAIN_CONCURRENCY in flight, cached
    LISTING_TTL_S. Every row is linked as soon as its listing arrives. References: at most MAX_REFERENCES,
    REF_CONCURRENCY in flight, ROW_TIMEOUT_S each. Touch tickets go first (they are the mechanism; close-above rows are
    reference only). When the monotonic ``deadline`` hits, what was built is kept: a row not reached keeps
    ``contract``/``reference`` with reason "budget". Returns the pending counts; nothing raises."""
    op = research.options()
    chain_sem = asyncio.Semaphore(CHAIN_CONCURRENCY)
    ref_sem = asyncio.Semaphore(REF_CONCURRENCY)
    refs_left = [MAX_REFERENCES]
    work = sorted((r for r in rows if r["linkable"]), key=lambda r: r["type"] != "touch_ticket")
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in work:
        f = r["fields"]
        groups.setdefault((f["underlying"], f["end_session"]), []).append(r)

    async def price(r: dict) -> None:
        f = r["fields"]
        if refs_left[0] <= 0:
            r["reference"] = _no_reference(BUDGET)
            return
        refs_left[0] -= 1
        try:
            async with ref_sem:
                r["reference"] = await asyncio.wait_for(reference(f, r["type"]), ROW_TIMEOUT_S)
        except asyncio.TimeoutError:
            r["reference"] = _no_reference(f"{BUDGET}: row timed out after {ROW_TIMEOUT_S:.0f} s")
        except Exception as e:  # noqa: BLE001 - one row never fails the board
            r["reference"] = _no_reference(f"reference failed: {type(e).__name__}")

    async def group(key: tuple[str, str], members: list[dict]) -> None:
        try:
            got = cached_listing(*key)
            if got is None:
                async with chain_sem:
                    got = await asyncio.shield(listing_task(*key))   # a deadline never cancels a shared listing
            listed, why = got
        except Exception as e:  # noqa: BLE001
            listed, why = None, f"contract listing failed: {type(e).__name__}"
        for r in members:
            f = r["fields"]
            try:
                r["contract"] = op.exact_ticket_link(listed, f["underlying"], f["level"], f["direction"], f["window_end"]) \
                    if listed is not None else {"ok": False, "reason": why}
            except Exception as e:  # noqa: BLE001
                r["contract"] = {"ok": False, "reason": f"link failed: {type(e).__name__}"}
            if listed is None:
                r["reference"] = _no_reference(why or "contracts not listed")
        await asyncio.gather(*(price(r) for r in members if listed is not None))

    tasks = []
    for i, (key, members) in enumerate(groups.items()):
        if i >= MAX_CHAINS and cached_listing(*key) is None:
            for r in members:
                r["contract"] = {"ok": False, "reason": "chain budget for this build used"}
                r["reference"] = _no_reference(BUDGET)
            continue
        tasks.append(asyncio.ensure_future(group(key, members)))
    if tasks:
        _done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - time.monotonic()))
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    listing_pending = reference_pending = 0
    for r in work:                                        # rows the deadline cut off
        if "contract" not in r:
            listing_pending += 1
        elif "reference" not in r:
            reference_pending += 1
        r.setdefault("contract", {"ok": False, "reason": BUDGET})
        r.setdefault("reference", _no_reference(BUDGET))
    return {"listing": listing_pending, "reference": reference_pending}


async def tickets_board(http: httpx.AsyncClient | None = None) -> dict:
    async def build() -> dict:
        t0 = time.monotonic()
        own = http is None
        client = http or httpx.AsyncClient()
        try:
            evs: list[dict] = []
            for tag in TICKET_TAGS:
                try:
                    evs += await open_events(client, tag, TICKET_PAGES)
                except Exception:
                    continue
            rows = ticket_rows(evs)
            bk = await books(client, sorted({r["token"] for r in rows if r.get("token")}))
        finally:
            if own:
                await client.aclose()
        ref_only = _reference_only()
        for r in rows:
            b = bk.get(r.get("token") or "")
            r["best_bid"], r["best_ask"] = best(b, "bids"), best(b, "asks")
            r["bid_size"], r["book_ts_ns"] = best_size(b, "bids"), book_ts_ns(b)
            if not r["linkable"]:
                r["contract"] = {"ok": False, "reason": "; ".join(r["reasons"])}
            if r["type"] == "close_above_ticket" and ref_only:
                r.update(ref_only)
        pending = await link_and_price(rows, t0 + DEADLINE_S - TICKET_MARGIN_S)
        th, now_ns = touch_threshold(), engine._now_ns()
        for r in rows:
            decide_ticket(r, th, now_ns)
        return {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(), "events_read": len(evs), "tickets": rows,
                "partial": bool(pending["listing"] or pending["reference"]), "pending": pending,
                "hedge": "not offered: the option-spread hedge for tickets was tested (S25) and raised risk",
                "budget": {"chains": MAX_CHAINS, "references": MAX_REFERENCES, "row_timeout_s": ROW_TIMEOUT_S,
                           "listing_cache_s": LISTING_TTL_S,
                           "unpriced": sum(str((t.get("reference") or {}).get("reason") or "").startswith(BUDGET)
                                           for t in rows)}}

    out = await _served("tickets", build, None, lambda d: {
        "tickets": len(d.get("tickets", [])), "linked": sum(bool((t.get("contract") or {}).get("ok")) for t in d.get("tickets", [])),
        "proposals": sum(bool(t.get("propose")) for t in d.get("tickets", [])),
        "decided_by": engine_source(d.get("tickets", []))},
        timeout=DEADLINE_S + 5.0)
    if out.get("partial") and not out.get("stale"):
        CACHE._data.pop("tickets", None)                  # a partial board is served, not kept: the next call rebuilds warm
    out.setdefault("partial", False)
    return out


async def _served(key: str, build, contract_type: str | None, counts, timeout: float | None = None) -> dict:
    t0 = time.monotonic()
    try:
        data, stale = await CACHE.get_or_set(key, lambda: asyncio.wait_for(build(), timeout or DEADLINE_S))
        out = {**data, "ok": True, "stale": stale, "error": None}
    except Exception as e:
        out = {"ok": False, "stale": False, "error": f"{type(e).__name__}: {str(e)[:160]}", key: []}
    out["counts"] = counts(out)
    out["elapsed_ms"] = round(1000 * (time.monotonic() - t0), 1)
    if contract_type:
        ev = evidence_for(contract_type)
        if ev:
            out["evidence"] = ev
    else:
        ev = {t: evidence_for(t) for t in ("touch_ticket", "close_above_ticket")}
        if any(ev.values()):
            out["evidence"] = {k: v for k, v in ev.items() if v}
    return out
