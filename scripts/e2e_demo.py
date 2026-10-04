#!/usr/bin/env python3
"""End-to-end demo driver for PolyBridge v4 (spec section 8: honest labels, graceful degradation, paper/sim only).

Starts the backend (engine group, offline replay) and the web dev server, waits for health, then drives the core flow
over HTTP exactly as the UI does:

    search market -> POST /map -> POST /pipeline/fit -> POST /proposals (with the fit) -> approve
    -> POST /bridges (replay) -> read SSE for N events -> GET /account /positions /orders

and asserts that orders reached the broker and that the fit's algo family is the one that ran. Then a headless-Chrome
screenshot pass over the 8 screens (web/e2e/screens/). Both servers are always stopped on exit.

    python3 scripts/e2e_demo.py                 # everything
    python3 scripts/e2e_demo.py --no-screens    # API flow only (no web server, no Chrome)
    python3 scripts/e2e_demo.py --reuse         # use servers already on :8000/:3000, stop nothing
    python3 scripts/e2e_demo.py --reuse --no-screens --api-base http://localhost:3000/api
                                                # tunnel mode (`SHARE_NO_NGROK=1 make share`): the API flow and the SSE
                                                # stream through the Next.js /api proxy
    python3 scripts/e2e_demo.py --opportunity   # the Opportunity division (API only): options fit -> approved options
                                                # proposal -> replay bridge with simulated multi-leg option orders
    python3 scripts/e2e_demo.py --weekend       # closed-market mode (API only): the recorded weekend on the validated
                                                # market -> expected gap -> staged order approved -> executes at the
                                                # first tradable moment -> P&L vs no hedge

Only the standard library is used, so it runs with any python3 >= 3.9. Keys: MASSIVE_API_KEY is read from --env-file
(default: ./.env, or the main checkout's .env when run from a git worktree) and handed to the backend through
`uv run --env-file`; it is never printed. Without it the backend degrades (no live equity quote, recorded bars only).
The simulated account used here is a throwaway file (SIM_ACCOUNT_PATH), never backend/.sim_account.json, and BROKER is
forced to "sim": this script never places a Webull order.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
WEB = ROOT / "web"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_REPLAY = BACKEND / "replays" / "another-fed-hike-2026-history.jsonl"
SCREEN_DIR = WEB / "e2e" / "screens"

MARKET_ID = "4620900"
QUESTION = "Another Fed rate hike in 2026?"
QUERY = "fed rate hike 2026"
MARKET_TEXT = "Another Fed rate hike in 2026"
TICKER = "TLT"
SHARES = 1000.0
SPEED = "21600"
COVERAGE = 0.5
DIRECTION = "down_on_yes"

OPP_MARKET_ID = "3961215"
OPP_QUERY = "NVIDIA close above $230 end of September"
OPP_TICKER = "NVDA"
OPP_REPLAY = BACKEND / "replays" / "nvda-230-sep-2026-history.jsonl"
OPP_FAMILIES = ("binary_vs_spread_arb", "vol_vs_pm_move", "eightk_opportunity")
OPP_CAPS = {"max_contracts": 10, "max_notional": 10_000.0}

WK_MARKET_ID = "516710"
WK_TOKEN = "104173557214744537570424345347209544585775842950109756851652855913015295701992"
WK_TICKER = "SPY"
WK_REPLAY = BACKEND / "replays" / "us-recession-in-2025-weekend-2025-04-04.jsonl"
WK_SPEED = "3600"
WK_ALGO = {"family": "equity_delta_bridge", "params": {"sigma_k": 0.0, "fee_ratio": 0.5, "band_shares": 10.0}}

results: list[tuple[str, bool, str]] = []
children: list[subprocess.Popen] = []


def say(msg: str = "") -> None:
    print(msg, flush=True)


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return bool(ok)


class Abort(Exception):
    pass


def call(base: str, method: str, path: str, body=None, timeout: float = 60.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"content-type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")[:300]
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        return 0, f"{type(e).__name__}: {e}"


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, what: str, timeout: float, proc: subprocess.Popen | None = None) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.7)
    return False


def find_env_file(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    cands = [ROOT / ".env"]
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        if common:
            cands.append(Path(common).parent / ".env")
    except Exception:
        pass
    return next((c for c in cands if c.is_file()), None)


def spawn(cmd: list[str], cwd: Path, env: dict, log: Path) -> subprocess.Popen:
    fh = open(log, "wb")
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    children.append(p)
    return p


def stop_all() -> None:
    for p in children:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.time() + 8
    for p in children:
        while p.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    children.clear()


def read_sse(base: str, bridge_id: str, want_events: int, max_s: float, need_fill: bool):
    u = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=15)
    events: list[tuple[str, dict]] = []
    closed = False
    t0 = time.time()
    try:
        conn.request("GET", f"{u.path.rstrip('/')}/bridges/{bridge_id}/stream", headers={"accept": "text/event-stream"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise Abort(f"stream answered {resp.status}")
        kind, data = None, []
        while time.time() - t0 < max_s:
            try:
                line = resp.readline()
            except socket.timeout:
                continue
            if not line:
                closed = True
                break
            line = line.decode().rstrip("\n")
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif line == "" and kind:
                try:
                    events.append((kind, json.loads("".join(data))))
                except ValueError:
                    pass
                kind, data = None, []
                filled = any(k == "fill" and d.get("status") == "filled" for k, d in events)
                if len(events) >= want_events and (filled or not need_fill):
                    break
    finally:
        conn.close()
    return events, closed


def approve_gated(base: str, prop: dict) -> dict:
    ev = prop.get("evidence") or {}
    cap = prop.get("capacity") or {}
    eq = cap.get("equity") or {}
    say(f"     evidence: {ev.get('status')} - {str(ev.get('evidence'))[:160]}")
    if eq.get("available"):
        say(f"     capacity: hedge {eq.get('hedge_shares')} sh vs max order {eq.get('max_order_shares')} sh "
            f"(10% of the opening 5 min), {eq.get('per_day_shares')} sh/day (1% ADV); est. cost "
            f"{eq.get('est_cost_bp') or float('nan'):.1f} bp; capacity ${eq.get('book_usd_capacity') or 0:,.0f}")
    else:
        say(f"     capacity: {eq.get('reason') or cap.get('options', {}).get('note') or 'n/a'}")
    capital = cap.get("capital") or {}
    say(f"     capital: fits={capital.get('fits')} {[b.get('kind') for b in capital.get('breaches') or []]}")
    check("the proposal carries a capacity block before approval", bool(cap) and "caps" in cap, "")
    fit = (prop.get("algo") or {}).get("source") == "ai_fit"
    if ev.get("validated") and not fit:
        s, out = call(base, "POST", f"/proposals/{prop['id']}/approve")
    else:
        code = "EVIDENCE_UNVALIDATED" if not ev.get("validated") else "GENERIC_FIT_UNVALIDATED"
        s0, refused = call(base, "POST", f"/proposals/{prop['id']}/approve")
        check(f"approval without the acknowledgement is refused (409 {code})",
              s0 == 409 and code in str(refused), f"{s0}")
        s, out = call(base, "POST", f"/proposals/{prop['id']}/approve", {"ack_unvalidated": True})
    check("approve", s == 200 and out["status"] == "approved", f"{s}")
    return out


def run_flow(base: str, args) -> dict:
    out: dict = {}
    say("\n== 1. health")
    s, b = call(base, "GET", "/health")
    check("GET /health", s == 200 and isinstance(b, dict) and b.get("status") == "ok", f"{s} {b}")
    if s != 200:
        raise Abort("backend not healthy")

    say("\n== 2. search market (Polymarket + Kalshi, falls back to the bundled list offline)")
    s, b = call(base, "GET", "/markets/search?q=" + urllib.request.quote(args.query), timeout=45)
    mk = None
    if s == 200:
        mk = next((m for m in b["markets"] if m["source"] == "polymarket" and m["id"] == args.market_id), None)
        check("search finds the target market", mk is not None,
              f"{len(b['markets'])} results, stale={b.get('stale')}" + (f", note={b.get('note')!r}" if b.get("note") else ""))
    else:
        check("search answered", False, f"{s} {b}")
    if mk is None:
        raise Abort(f"market {args.market_id} not in search results")
    out["market"] = mk
    say(f"     market: {mk['question']}  yes={mk['yes_price']}  vol24h={mk['volume_24h']:,.0f}")

    say("\n== 3. POST /map (market -> tickers, AI estimate, precomputed)")
    s, b = call(base, "POST", "/map", {"source": "polymarket", "market_id": mk["id"], "question": mk["question"]})
    items = (b or {}).get("items", []) if s == 200 else []
    check("map returns the ticker", any(i["ticker"] == args.ticker for i in items),
          f"{s} label={b.get('label') if s == 200 else b!r} items={[(i['ticker'], i['impact_pct']) for i in items]}")
    direction = next((i["direction"] for i in items if i["ticker"] == args.ticker), DIRECTION)

    say("\n== 4. POST /pipeline/fit (classify -> shortlist -> tune on real history -> explain)")
    t = time.time()
    s, fit = call(base, "POST", "/pipeline/fit", {
        "market": {"source": "polymarket", "id": mk["id"]}, "question": mk["question"], "ticker": args.ticker,
        "direction": direction, "shares_held": args.shares}, timeout=120)
    ok = s == 200 and isinstance(fit, dict) and fit.get("family") and fit.get("preset_index") is not None
    check("fit picks a family and preset", ok, f"{s} in {time.time() - t:.1f}s" if ok else f"{s} {fit}")
    if not ok:
        raise Abort("no fit")
    check("fit is a hedge-division family (the only division a bridge runs)", fit["division"] == "hedge", fit["division"])
    out["fit"] = fit
    say(f"     class={fit['event_class']} family={fit['family']} preset=#{fit['preset_index']} score={fit['score']:.3f} "
        f"llm={fit['llm']} ticks={fit['n_ticks']} ({fit['ticks_source']}) alternatives={[a['family'] for a in fit['alternatives']]}")
    say(f"     rationale: {fit['rationale'][:200]}")

    say("\n== 5. POST /proposals with the fit, then approve (the approval gate)")
    algo = {"family": fit["family"], "preset_index": fit["preset_index"], "source": "ai_fit"}
    s, prop = call(base, "POST", "/proposals", {
        "ticker": args.ticker, "market": {"source": "polymarket", "id": mk["id"], "token_id": mk.get("token_id")},
        "direction": direction, "shares_held": args.shares, "target_coverage": args.coverage, "algo": algo})
    check("proposal created pending with the fit pinned", s == 201 and prop["status"] == "proposed"
          and (prop.get("algo") or {}).get("family") == fit["family"], f"{s} {prop if s != 201 else prop['id']}")
    if s != 201:
        raise Abort("proposal refused")
    s2, nope = call(base, "POST", "/bridges", {"proposal_id": prop["id"], "source": "replay", "gap_per_share": 1.0})
    check("a bridge on an unapproved proposal is refused (409)", s2 == 409, f"{s2}")
    prop = approve_gated(base, prop)
    out["proposal"] = prop
    ra = prop.get("algo") or {}
    say(f"     proposal {prop['id']}: {prop['label']}; will run {ra.get('family')} #{ra.get('preset_index')} "
        f"capped at coverage {ra.get('coverage_cap')} (capped params: {ra.get('capped')})")

    say("\n== 6. POST /bridges (replay of real Polymarket history, orders go to the sim account)")
    body = {"proposal_id": prop["id"], "source": "replay", "gap_per_share": 1.0, "direction": direction,
            "market": {"source": "polymarket", "id": mk["id"], "token_id": mk.get("token_id")},
            "family": fit["family"], "preset_index": fit["preset_index"],
            "replay_to_account": True}
    s, br = call(base, "POST", "/bridges", body)
    if not check("bridge started", s == 201 and "bridge_id" in br, f"{s} {br}"):
        raise Abort("bridge not started")
    bid = br["bridge_id"]
    out["bridge_id"] = bid
    _, sm0 = call(base, "GET", f"/bridges/{bid}")
    if (sm0 or {}).get("status") == "running":
        s, again = call(base, "POST", "/bridges", body)
        check("re-POST is idempotent (200, same bridge)", s == 200 and again.get("bridge_id") == bid, f"{s}")
    else:
        say("     bridge already finished: skipping the idempotency re-POST (it would start a fresh run)")
    s, other = call(base, "POST", "/bridges", {**body, "family": "equity_delta_bridge", "preset_index": 0})
    check("a different algo than the approved one is refused (409)", s == 409, f"{s}")

    say(f"\n== 7. SSE /bridges/{bid}/stream (>= {args.events} events)")
    events, closed = read_sse(base, bid, args.events, args.stream_timeout, need_fill=True)
    kinds: dict[str, int] = {}
    for k, _ in events:
        kinds[k] = kinds.get(k, 0) + 1
    say(f"     read {len(events)} events: {kinds}  (server closed stream: {closed})")
    check(f"read at least {args.events} SSE events", len(events) >= args.events or closed, f"{len(events)}")
    decisions = [d for k, d in events if k == "decision"]
    fills = [d for k, d in events if k == "fill"]
    check("decision events come from hedgecore.Algo (engine=algo)", bool(decisions) and all(d.get("engine") == "algo" for d in decisions),
          f"{len(decisions)} decisions")
    check("every decision names the fitted family", bool(decisions) and all(d.get("family") == fit["family"] for d in decisions),
          f"families={sorted({d.get('family') for d in decisions})}")
    if args.offline:
        filled_now = [f for f in fills if f.get("status") == "filled"]
        check("offline: orders fill at the recorded price (no current quote), labelled",
              bool(filled_now) and all(f.get("price_source") == "recorded" and "recorded price" in str(f.get("price_note"))
                                       for f in filled_now)
              and not any("no_price" in str(f.get("reject_reason")) for f in fills),
              f"{len(fills)} fills, statuses={sorted({f.get('status') for f in fills})}, "
              f"sources={sorted({str(f.get('price_source')) for f in fills})}, first={fills[0].get('fill_px') if fills else None}")
    else:
        check("at least one order was filled by the broker", any(f.get("status") == "filled" for f in fills),
              f"fills={[(f.get('status'), f.get('side'), f.get('qty'), f.get('fill_px')) for f in fills[:4]]}")
    if fills:
        out["first_fill"] = fills[0]

    say("\n== 8. let the replay finish, then read the bridge summary")
    deadline = time.time() + args.finish_timeout
    summ = None
    while time.time() < deadline:
        s, summ = call(base, "GET", f"/bridges/{bid}")
        if s == 200 and summ.get("status") != "running":
            break
        time.sleep(1.0)
    check("bridge finished (replay complete)", bool(summ) and summ.get("status") != "running", f"status={summ and summ.get('status')}")
    out["summary"] = summ
    sa = summ.get("algo") or {}
    check("the algo that ran is the fit (family + preset)", sa.get("family") == fit["family"] and sa.get("preset_index") == fit["preset_index"],
          f"ran {sa.get('family')} #{sa.get('preset_index')} source={sa.get('source')} engine={summ.get('engine')}")
    check("summary engine is the algo, not the legacy Engine", summ.get("engine") == "algo")
    check("hedge never exceeds the approved coverage cap",
          summ.get("coverage", 0) <= args.coverage + 1e-9 and summ.get("broker_coverage", 0) <= args.coverage + 1e-9,
          f"coverage={summ.get('coverage'):.3f} broker_coverage={summ.get('broker_coverage'):.3f} cap={summ.get('coverage_cap')} cap_holds={summ.get('cap_holds')}")
    say(f"     ticks={summ['ticks']} orders={summ['orders']} broker_filled={summ['broker_filled']} rejects={summ['broker_rejects']} "
        f"errors={summ['broker_errors']} hedge={summ['hedge']:.1f} sh coverage={summ['coverage']:.2%} equity_price={summ['equity_price']} "
        f"latency p50={summ['latency_ns']['p50']}ns p99={summ['latency_ns']['p99']}ns")
    say(f"     decision reasons: {summ['reasons']}")

    say("\n== 9. GET /account /positions /orders (the sim account the bridge traded in)")
    s, acct = call(base, "GET", "/account")
    check("GET /account", s == 200, f"{s}")
    s, pos = call(base, "GET", "/positions")
    check("GET /positions", s == 200, f"{s}")
    s, orders = call(base, "GET", "/orders")
    check("GET /orders", s == 200, f"{s}")
    mine = [o for o in orders if o.get("tag") == bid] if isinstance(orders, list) else []
    filled = [o for o in mine if o.get("status") == "filled"]
    check("orders reached the broker (tagged with the bridge id)", len(mine) >= 1, f"{len(mine)} orders for {bid}")
    check("broker order count matches the bridge summary", len(filled) == summ["broker_filled"],
          f"filled in /orders={len(filled)} vs summary.broker_filled={summ['broker_filled']}")
    short = next((p for p in pos if p.get("symbol") == args.ticker), None) if isinstance(pos, list) else None
    net = -sum(o["qty"] for o in filled if o["side"] == "sell") + sum(o["qty"] for o in filled if o["side"] == "buy")
    check(f"{args.ticker} position is the net short the orders built", short is not None and abs(short["qty"] - net) < 1e-6 and net < 0,
          f"position qty={short and short['qty']} vs net filled {net}")
    check("broker hedge in the summary equals the position", short is not None and abs(-short["qty"] - summ["broker_hedge"]) < 1e-6,
          f"short={short and -short['qty']} vs broker_hedge={summ['broker_hedge']}")
    out.update(account=acct, positions=pos, orders=mine)
    if isinstance(acct, dict):
        say(f"     account: broker={acct.get('broker')} cash=${acct['cash']:,.2f} equity=${acct['equity']:,.2f} "
            f"fees=${acct.get('fees_paid') or 0:,.4f} note={acct.get('note')}")
    for p in (pos if isinstance(pos, list) else []):
        say(f"     position: {p['symbol']} qty={p['qty']} avg={p.get('avg_px')} mark={p.get('market_px')} upl={p.get('unrealized_pnl')}")
    for o in mine[:5]:
        say(f"     order: {o['side']} {o['qty']:g} {o['symbol']} {o['status']} @ {o.get('fill_px')} fee={o.get('fee')} src={o.get('price_source')}")
    if len(mine) > 5:
        say(f"     ... {len(mine)} orders in total")
    return out


def options_pick(fit: dict) -> dict | None:
    cands = [{"family": fit.get("family"), "preset_index": fit.get("preset_index"), "score": fit.get("score"),
              "stats": None}] + list(fit.get("alternatives") or [])
    for c in cands:
        if c.get("family") in OPP_FAMILIES and c.get("preset_index") is not None and isinstance(c.get("score"), (int, float)):
            return c
    return None


def run_opportunity_flow(base: str, args) -> dict:
    out: dict = {"mode": "opportunity"}
    say("\n== 1. health")
    s, b = call(base, "GET", "/health")
    check("GET /health", s == 200 and isinstance(b, dict) and b.get("status") == "ok", f"{s} {b}")
    if s != 200:
        raise Abort("backend not healthy")

    say("\n== 2. search the market (a resolved market stays listed when the backend has its recording)")
    s, b = call(base, "GET", "/markets/search?q=" + urllib.request.quote(args.query), timeout=45)
    mk = next((m for m in (b or {}).get("markets", []) if m["source"] == "polymarket" and m["id"] == args.market_id), None) if s == 200 else None
    check("search finds the target market", mk is not None, f"{s} {len((b or {}).get('markets', []))} results stale={(b or {}).get('stale')}")
    if mk is None:
        raise Abort(f"market {args.market_id} not in search results")
    check("the search row names its recording", mk.get("recorded") == Path(args.replay).name, f"recorded={mk.get('recorded')}")
    out["market"] = mk
    say(f"     market: {mk['question']}  yes={mk['yes_price']}  end={mk.get('end_date')}  recorded={mk.get('recorded')}")

    say("\n== 3. GET /options/implied (the Opportunity card's live estimate)")
    s, imp = call(base, "GET", f"/options/implied?market_source=polymarket&market_id={mk['id']}", timeout=45)
    check("options/implied answers honestly (200; a resolved market has no live estimate)",
          s == 200 and isinstance(imp, dict) and imp.get("available") is False and bool(imp.get("reason")),
          f"{s} available={(imp or {}).get('available')} reason={(imp or {}).get('reason')!r}")

    say("\n== 4. POST /pipeline/fit (division opportunity: the recorded options history is replayed)")
    t = time.time()
    s, fit = call(base, "POST", "/pipeline/fit", {
        "market": {"source": "polymarket", "id": mk["id"]}, "question": mk["question"], "ticker": args.ticker,
        "shares_held": 0, "division": "opportunity", "end_date": mk.get("end_date")}, timeout=120)
    ok = s == 200 and isinstance(fit, dict) and fit.get("division") == "opportunity"
    check("fit answers in the Opportunity division", ok, f"{s} in {time.time() - t:.1f}s division={(fit or {}).get('division')}")
    if not ok:
        raise Abort("no opportunity fit")
    check("fit replays the recording (ticks_source replay)", fit.get("ticks_source") == "replay", f"{fit.get('ticks_source')} n={fit.get('n_ticks')}")
    check("score basis is net P&L per drawdown", fit.get("score_basis") == "net_pnl_per_drawdown", str(fit.get("score_basis")))
    pick = options_pick(fit)
    arb = next((c for c in [{"family": fit["family"], "preset_index": fit["preset_index"], "score": fit["score"]}] + fit["alternatives"]
                if c.get("family") == "binary_vs_spread_arb"), None)
    check("binary_vs_spread_arb is scored on the replay (engine, real orders)",
          arb is not None and isinstance(arb.get("score"), (int, float)) and (arb.get("stats") or {}).get("n_orders", 1) > 0,
          f"{arb}")
    if pick is None:
        raise Abort("no scored options family to propose")
    out["fit"], out["pick"] = fit, pick
    st = pick.get("stats") or {}
    say(f"     top opportunity pick: {fit['family']} #{fit['preset_index']} score={fit['score']:.3f} (ticks={fit['n_ticks']}, {fit['ticks_source']})")
    say(f"     options family offered: {pick['family']} #{pick['preset_index']} score={pick['score']:.3f} "
        f"(in-sample; orders={st.get('n_orders')} pnl=${st.get('pnl', float('nan')):.2f} max_dd=${st.get('max_dd', float('nan')):.2f})")
    say(f"     rationale: {fit['rationale'][:200]}")

    say("\n== 5. POST /proposals (opportunity, the options family, risk caps), then approve")
    s, prop = call(base, "POST", "/proposals", {
        "ticker": args.ticker, "market": {"source": "polymarket", "id": mk["id"], "token_id": mk.get("token_id")},
        "division": "opportunity", **OPP_CAPS,
        "algo": {"family": pick["family"], "preset_index": pick["preset_index"], "source": "ai_fit"}})
    check("opportunity proposal created pending with the options algo", s == 201 and prop.get("family") == "opportunity"
          and prop["status"] == "proposed" and (prop.get("algo") or {}).get("family") == pick["family"], f"{s} {prop if s != 201 else prop['id']}")
    if s != 201:
        raise Abort("proposal refused")
    body = {"proposal_id": prop["id"], "source": "replay", "market": {"source": "polymarket", "id": mk["id"], "token_id": mk.get("token_id")},
            "replay_to_account": True}
    s2, _ = call(base, "POST", "/bridges", body)
    check("a bridge on an unapproved proposal is refused (409)", s2 == 409, f"{s2}")
    prop = approve_gated(base, prop)
    out["proposal"] = prop

    say("\n== 6. POST /bridges (replay; option orders go to the SimBroker)")
    s, br = call(base, "POST", "/bridges", body)
    if not check("bridge started", s == 201 and "bridge_id" in br, f"{s} {br}"):
        raise Abort("bridge not started")
    bid = br["bridge_id"]
    out["bridge_id"] = bid

    say(f"\n== 7. SSE /bridges/{bid}/stream until the replay ends")
    events, closed = read_sse(base, bid, 10 ** 9, args.finish_timeout, need_fill=False)
    kinds: dict[str, int] = {}
    for k, _ in events:
        kinds[k] = kinds.get(k, 0) + 1
    say(f"     read {len(events)} events: {kinds}  (server closed stream: {closed})")
    decisions = [d for k, d in events if k == "decision"]
    fills = [d for k, d in events if k == "fill"]
    positions = [d for k, d in events if k == "position"]
    gaps = [d["options"]["gap"] for k, d in events if k == "tick" and (d.get("options") or {}).get("gap") is not None]
    check("decisions come from hedgecore.Algo running the approved options family",
          bool(decisions) and all(d.get("engine") == "algo" and d.get("family") == pick["family"] for d in decisions), f"{len(decisions)} decisions")
    check("ticks carry the PM-vs-options gap", len(gaps) > 0, f"{len(gaps)} ticks with a gap; first={gaps[0] if gaps else None}")
    filled = [f for f in fills if f.get("status") == "filled"]
    check("option orders filled as multi-leg combos (all legs filled)", bool(filled) and all(
        f.get("instrument") == "option" and len(f.get("legs") or []) >= 2 and all(lg.get("status") == "filled" for lg in f["legs"])
        for f in filled), f"{len(filled)}/{len(fills)} filled")
    check("option fills are labelled simulated, with their price source", bool(filled) and all(
        f.get("simulated") and f.get("price_note") for f in filled),
          f"price sources={sorted({str(f.get('price_source')) for f in filled})} note={filled[0].get('price_note') if filled else None!r}")
    pmax = max((abs(d.get("option_position") or 0) for d in positions), default=0)
    rmax = max((d.get("risk_used") or 0 for d in positions), default=0)
    check("open structures never exceed the approved caps", pmax <= OPP_CAPS["max_contracts"] and rmax <= OPP_CAPS["max_notional"],
          f"max open {pmax} (cap {OPP_CAPS['max_contracts']}), max risk ${rmax:,.2f} (cap ${OPP_CAPS['max_notional']:,.0f})")
    out["fills"] = fills

    say("\n== 8. bridge summary")
    deadline = time.time() + 30
    summ = None
    while time.time() < deadline:
        s, summ = call(base, "GET", f"/bridges/{bid}")
        if s == 200 and summ.get("status") != "running":
            break
        time.sleep(1.0)
    check("bridge finished (replay complete)", bool(summ) and summ.get("status") == "finished", f"status={summ and summ.get('status')}")
    out["summary"] = summ
    sa = summ.get("algo") or {}
    check("the algo that ran is the approved options family", summ.get("division") == "opportunity" and sa.get("family") == pick["family"]
          and sa.get("preset_index") == pick["preset_index"], f"{summ.get('division')} {sa.get('family')} #{sa.get('preset_index')}")
    check("no option structure is left open at the end", summ.get("option_position") == 0 and summ.get("option_structure") is None,
          f"position={summ.get('option_position')}")
    det = summ.get("options_detail") or {}
    say(f"     ticks={summ['ticks']} orders={summ['orders']} broker_filled={summ['broker_filled']} rejects={summ['broker_rejects']} "
        f"recorded_option_fills={summ.get('recorded_option_fills')} option_data={summ.get('option_data')}")
    say(f"     structure: {det.get('underlying_used')} {det.get('method')} {det.get('k_lo')}/{det.get('k_hi')} exp {det.get('expiry')} "
        f"(source={det.get('source')}; live: {det.get('live_reason')})")
    say(f"     decision reasons: {summ['reasons']}")
    for f in fills:
        legs = "; ".join(f"{lg['side']} {lg['ticker']} @ {lg['fill_px']:.4f} (rec {lg.get('quote_mid')})" for lg in f.get("legs") or [])
        say(f"     fill: {f.get('status')} {f.get('side')} {f.get('qty'):g} {f.get('structure')} net {f.get('fill_px')} fee {f.get('fee')} "
            f"[{f.get('reason') or f.get('close_reason')}] {legs}")
    pnl = sum((-1 if f["side"] == "buy" else 1) * f["qty"] * f["fill_px"] * 100 - (f.get("fee") or 0) for f in filled)
    out["bridge_pnl"] = pnl
    say(f"     bridge round trips net of fees: ${pnl:,.2f} (simulated fills at recorded closes +/- 2%; not the engine's fill model)")

    say("\n== 9. GET /orders /positions (the sim account the bridge traded in)")
    s, orders = call(base, "GET", "/orders")
    mine = [o for o in orders if o.get("tag") == bid] if isinstance(orders, list) else []
    check("every option leg reached the broker (tagged with the bridge id)",
          len(mine) == sum(len(f.get("legs") or []) for f in filled) and all(o.get("asset") == "option" for o in mine),
          f"{len(mine)} leg orders for {bid}")
    s, pos = call(base, "GET", "/positions")
    left = [p for p in pos if str(p.get("symbol", "")).startswith("O:NVDA")] if isinstance(pos, list) else None
    check("no option legs left in the account", left == [], f"{left}")
    return out


def run_weekend_flow(base: str, args) -> dict:
    out: dict = {"mode": "weekend"}
    market = {"source": "polymarket", "id": args.market_id, "token_id": WK_TOKEN}
    say("\n== 1. health")
    s, b = call(base, "GET", "/health")
    check("GET /health", s == 200 and isinstance(b, dict) and b.get("status") == "ok", f"{s} {b}")
    if s != 200:
        raise Abort("backend not healthy")

    say("\n== 2. GET /closed/evidence (the evidence gate)")
    s, e = call(base, "GET", f"/closed/evidence?market_source=polymarket&market_id={args.market_id}&token_id={WK_TOKEN}")
    ok = s == 200 and e.get("validated_markets") == ["us-recession-in-2025"] and (e.get("market") or {}).get("validated")
    check("only the recession market is validated out of sample, and it is this one", bool(ok),
          f"{s} validated={(e or {}).get('validated_markets')} market={((e or {}).get('market') or {}).get('status')}")
    check("hedge A is an estimate off by default, hedge B the default, opportunity research-only",
          s == 200 and e["hedge_a"]["default"] is False and e["hedge_a"]["verdict"] == "no evidence"
          and e["hedge_b"]["default"] is True and e["opportunity"]["research_only"] is True,
          f"A={e['hedge_a'].get('verdict')} B={e['hedge_b'].get('verdict')} R3={e['opportunity'].get('verdict')}" if s == 200 else str(s))
    out["evidence"] = e

    say("\n== 3. POST /proposals (SPY, down on YES, 1,000 shares, 50% cap, equity_delta_bridge), then approve")
    s, prop = call(base, "POST", "/proposals", {"ticker": args.ticker, "market": market, "direction": "down_on_yes",
                                                "shares_held": args.shares, "target_coverage": args.coverage,
                                                "algo": {**WK_ALGO, "source": "user"}})
    check("proposal created, hedge A not opted in", s == 201 and prop.get("closed_pm_hedge") is False, f"{s}")
    if s != 201:
        raise Abort(f"proposal refused: {prop}")
    check("the evidence gate: US recession 2025 on SPY is validated out of sample (no override needed)",
          (prop.get("evidence") or {}).get("validated") is True, (prop.get("evidence") or {}).get("status", ""))
    prop = approve_gated(base, prop)
    check("approved without an acknowledgement (validated market)", prop.get("ack_unvalidated") is False, "")
    out["proposal"] = prop

    say("\n== 4. POST /bridges (replay of the recorded weekend, replay sandbox)")
    s, br = call(base, "POST", "/bridges", {"proposal_id": prop["id"], "source": "replay", "market": market})
    if not check("bridge started", s == 201 and "bridge_id" in br, f"{s} {br}"):
        raise Abort("bridge not started")
    bid = br["bridge_id"]
    out["bridge_id"] = bid

    say("\n== 5. follow the replay; approve the staged plan once it is sized at the full expected gap")
    approved: list[dict] = []
    seen_phases: list[str] = []
    deadline = time.time() + args.finish_timeout
    summ = None
    while time.time() < deadline:
        s, summ = call(base, "GET", f"/bridges/{bid}")
        if s != 200:
            time.sleep(0.3)
            continue
        ph = (summ.get("session") or {}).get("phase")
        if ph and (not seen_phases or seen_phases[-1] != ph):
            seen_phases.append(ph)
            g = summ.get("expected_gap") or {}
            say(f"     [{(summ.get('session') or {}).get('at')}] {ph}: {(summ.get('session') or {}).get('label')}"
                + (f"; expected gap {g['bp']:.1f} bp ({g['status']})" if g.get("bp") is not None else ""))
        _, st = call(base, "GET", f"/staged?bridge_id={bid}")
        for o in (st or {}).get("orders", []):
            cur = o.get("current") or o["estimate"]
            if o["status"] == "staged" and cur["gap_bp"] <= -o["full_size_gap_bp"] and o["id"] not in {a["id"] for a in approved}:
                s2, a = call(base, "POST", f"/staged/{o['id']}/approve", {"qty": o["qty"]})
                if s2 == 200:
                    approved.append(a)
                    say(f"     approved staged plan {a['id']}: sell {a['qty']} {a['ticker']} for the "
                        f"{a['session_target'].replace('_', ' ')} (gap {cur['gap_bp']:.1f} bp, {cur.get('status') or a['estimate'].get('status')})")
        if summ.get("status") != "running":
            break
        time.sleep(0.25)
    check("bridge finished (replay complete)", bool(summ) and summ.get("status") == "finished", f"status={summ and summ.get('status')}")
    check("a staged plan was approved through POST /staged/{id}/approve before the open", bool(approved), f"{len(approved)} approved")

    say(f"\n== 6. SSE /bridges/{bid}/stream (the whole run)")
    events, closed = read_sse(base, bid, 10 ** 9, 60, need_fill=False)
    kinds: dict[str, int] = {}
    for k, _ in events:
        kinds[k] = kinds.get(k, 0) + 1
    say(f"     read {len(events)} events: {kinds}  (server closed stream: {closed})")
    ticks = [d for k, d in events if k == "tick"]
    phases = [((d.get("closed") or {}).get("session") or {}).get("phase") for d in ticks]
    check("every tick carries its session (recorded time): Friday regular -> after-hours -> weekend -> pre-market -> regular",
          len(ticks) == 799 and phases[0] == "regular" and "weekend" in phases and "pre_market" in phases and phases[-1] == "regular",
          f"{len(ticks)} ticks, phases {sorted(set(p for p in phases if p))}")
    gaps = [d["closed"]["expected_gap"] for d in ticks if ((d.get("closed") or {}).get("expected_gap") or {}).get("active")]
    check("the expected gap is validated (own rate, n closures, 80% band) while closed",
          bool(gaps) and all(g["validated"] and g["rate_source"] == "market" and g["n"] == 231 and g["band"] for g in gaps),
          f"{len(gaps)} closed ticks; peak {min(g['bp'] for g in gaps):.1f} bp" if gaps else "none")
    phase, bad = None, []
    for k, d in events:
        if k == "tick":
            phase = ((d.get("closed") or {}).get("session") or {}).get("phase")
        elif k == "fill" and d.get("status") == "filled" and phase != "regular":
            bad.append(phase)
    check("the equity algo holds while closed (no algo order outside the regular session)",
          not bad and summ["reasons"].get("session_closed", 0) > 0,
          f"session_closed holds={summ['reasons'].get('session_closed')} off-session fills={bad}")
    check("handoff at the open", any(k == "handoff" for k, _ in events))

    say("\n== 7. the staged order (hedge B) and the P&L vs no hedge")
    _, st = call(base, "GET", f"/staged?bridge_id={bid}")
    orders = (st or {}).get("orders", [])
    filled = [o for o in orders if o["status"] == "filled"]
    o = filled[0] if filled else None
    check("one approved plan executed at the first tradable moment, on a fresh recorded price, in the sandbox",
          o is not None and len(filled) == 1 and "APPROVED" in [d["code"] for d in o["decisions"]]
          and o["clock"] == "replay" and o["ref_source"] == "recorded" and o["broker"] == "sim-replay",
          f"{o['qty']} @ {o['fill_px']} {o['session_target']} at {o['executed_at']}" if o else f"{[(x['status'], x['qty']) for x in orders]}")
    out["staged"] = o
    if o:
        for d in o["decisions"]:
            if d["code"] in ("AWAITING_APPROVAL", "APPROVED", "EXPECTED_GAP", "REPLAY_NEEDS_TICK_PRICE", "SUBMITTED", "FILLED"):
                say(f"     {d['at']}  {d['code']:<24} {d['detail'] or ''}"[:220])
    cm = summ.get("closed_mode") or {}
    p = cm.get("pnl") or {}
    cap = int(args.coverage * args.shares)
    check("PM + equity legs stay within the approved cap", p and p["carried_hedge_shares"] + p["staged_short_shares"] <= cap,
          f"carried {p.get('carried_hedge_shares')} + staged {p.get('staged_short_shares')} <= {cap}")
    check("P&L vs no hedge is reported, marked at the recorded price", bool(p) and p.get("price_source") == "recorded"
          and abs(p["hedged_usd"] - p["unhedged_usd"] - p["vs_no_hedge_usd"]) < 1e-6, f"{p.get('vs_no_hedge_usd')}")
    check("hedge A stays off without the opt-in", (summ.get("hedge_a") or {}).get("enabled") is False)
    out["summary"], out["pnl"] = summ, p
    for r in cm.get("timeline") or []:
        if r["event"] in ("close", "plan", "staged_approved", "staged_filled", "open", "staged_cancelled"):
            say(f"     {r['at_et']}  {r['event']:<17} {(r.get('detail') or '')[:150]}")
    if p:
        say(f"     SPY {p['s_close']} at the Friday close -> {p['s_now']} on Monday 10:00 ET ({p['price_source']})")
        say(f"     holding, no hedge:            ${p['unhedged_usd']:>11,.2f}")
        say(f"     Friday hedge carried ({p['carried_hedge_shares']:g} sh): ${p['carried_hedge_usd']:>11,.2f}")
        say(f"     staged order, hedge B ({p['staged_short_shares']:g} sh): ${p['staged_usd']:>11,.2f}")
        say(f"     algo after the open ({p['algo_short_shares']:g} sh):   ${p['algo_usd']:>11,.2f}")
        say(f"     hedged total:                 ${p['hedged_usd']:>11,.2f}   (vs no hedge {p['vs_no_hedge_usd']:+,.2f})")
        say(f"     note: {p['note']}")
    return out


SCREENS = [("landing", "/"), ("build", "/build"), ("connect", "/connect"), ("pipeline", "/build/fit"),
           ("bridge", None), ("portfolio", "/portfolio"), ("library", "/library"), ("profile", "/profile"),
           ("ladders", "/pipeline"), ("tickets", "/bridge")]


def ui_walk(web: str, base: str, args) -> list[str]:
    node = shutil.which("node")
    if not node or not Path(CHROME).exists():
        check("UI walk can run (node + Chrome)", False, "node or Chrome missing; falling back to direct-URL screenshots")
        return []
    p = subprocess.Popen([node, str(WEB / "e2e" / "ui_walk.mjs"), "--web", web, "--api", base, "--out", str(SCREEN_DIR),
                          "--chrome", CHROME, "--query", args.query, "--market", args.market_text, "--ticker", args.ticker,
                          "--fill-deadline-s", str(args.fill_deadline)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    children.append(p)
    files: list[str] = []
    timer_end = time.time() + 300 + args.fill_deadline
    try:
        for line in p.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "check" in d:
                check(d["check"], d["ok"], d.get("detail", ""))
            elif "shots" in d:
                files = d["shots"]
            if time.time() > timer_end:
                break
    finally:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return files


def direct_shot(web: str, i: int, name: str, path: str, wait_ms: int, prof: Path) -> None:
    wait_for(web + path, name, 120)
    dest = SCREEN_DIR / f"{i:02d}-{name}.png"
    dest.unlink(missing_ok=True)
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", f"--user-data-dir={prof}",
           "--window-size=1440,1000", f"--virtual-time-budget={wait_ms}", f"--screenshot={dest}", f"--timeout={wait_ms}", web + path]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    end = time.time() + wait_ms / 1000 + 15
    while p.poll() is None and time.time() < end and not (dest.exists() and dest.stat().st_size > 0):
        time.sleep(0.3)
    time.sleep(0.5)
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def screenshots(web: str, base: str, bridge_id: str | None, args) -> None:
    say("\n== 10. UI walk + screenshots of the 10 screens -> web/e2e/screens/")
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    for old in SCREEN_DIR.glob("*.png"):
        old.unlink()
    ui_walk(web, base, args)
    missing = [(i, n, p) for i, (n, p) in enumerate(SCREENS, 1) if not any(SCREEN_DIR.glob(f"{i:02d}-{n}.png"))]
    if missing and Path(CHROME).exists():
        say(f"     UI walk did not produce {[n for _, n, _ in missing]}; capturing those by direct URL (no wizard state)")
        prof = Path(tempfile.mkdtemp(prefix="pb-chrome-"))
        try:
            for i, n, p in missing:
                direct_shot(web, i, n, p or (f"/bridge/{bridge_id}" if bridge_id else "/bridge"), args.screen_wait_ms, prof)
        finally:
            subprocess.run(["pkill", "-f", f"--user-data-dir={prof}"], capture_output=True)
            shutil.rmtree(prof, ignore_errors=True)
    for i, (n, _) in enumerate(SCREENS, 1):
        f = next(iter(SCREEN_DIR.glob(f"{i:02d}-{n}.png")), None)
        check(f"screenshot {i:02d}-{n}.png", bool(f) and f.stat().st_size > 5000, f"{f.stat().st_size // 1024} KB" if f else "missing")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backend-port", type=int, default=8000)
    ap.add_argument("--web-port", type=int, default=3000)
    ap.add_argument("--reuse", action="store_true", help="use servers already listening (stops nothing)")
    ap.add_argument("--api-base", help="with --reuse: send the API flow through this base instead of the backend, e.g. "
                    "http://localhost:3000/api (tunnel mode: Next.js proxy + server-side X-Agent-Secret)")
    ap.add_argument("--no-screens", action="store_true", help="skip the web server and the Chrome pass")
    ap.add_argument("--events", type=int, default=40, help="minimum SSE events to read (default 40)")
    ap.add_argument("--stream-timeout", type=float, default=120.0)
    ap.add_argument("--finish-timeout", type=float, default=150.0, help="how long to wait for the replay to finish")
    ap.add_argument("--replay", default=str(DEFAULT_REPLAY), help="replay JSONL (POLYBRIDGE_REPLAY_PATH)")
    ap.add_argument("--speed", default=SPEED, help="POLYBRIDGE_REPLAY_SPEED (default 21600: the 401-point default replay in ~67 s; "
                                                   "36000 plays the month-long Fed October replay in ~72 s)")
    ap.add_argument("--env-file", help="dotenv file for MASSIVE_API_KEY (default: ./.env or the main checkout's)")
    ap.add_argument("--query", default=QUERY, help="market search text; the search must list --market-id")
    ap.add_argument("--market-text", default=MARKET_TEXT, help="text of the market row the UI walk clicks in Build")
    ap.add_argument("--fill-deadline", type=float, default=90.0,
                    help="UI walk: seconds to wait on the Bridge screen for the first broker fill or the replay's end")
    ap.add_argument("--offline", action="store_true",
                    help="simulate Wi-Fi off: the backend's outbound traffic goes to a dead proxy and no env file is loaded")
    ap.add_argument("--market-id", default=MARKET_ID)
    ap.add_argument("--ticker", default=TICKER)
    ap.add_argument("--shares", type=float, default=SHARES)
    ap.add_argument("--coverage", type=float, default=COVERAGE,
                    help="approved target_coverage (the cap on the fitted algo's coverage; the UI sends Max hedge, 100%% by default)")
    ap.add_argument("--screen-wait-ms", type=int, default=9000, help="how long Chrome lets each page render")
    ap.add_argument("--opportunity", action="store_true",
                    help="drive the Opportunity division instead (API only): NVDA > $230 end of September, its recorded "
                         "options history, an approved binary_vs_spread_arb proposal, a replay bridge with option legs")
    ap.add_argument("--weekend", action="store_true",
                    help="drive closed-market mode instead (API only): the recorded 2025-04-04 weekend on the US "
                         "recession 2025 market, expected gap, staged order approved, executed, P&L vs no hedge")
    args = ap.parse_args()
    if args.weekend:
        args.no_screens = True
        args.market_id = WK_MARKET_ID if args.market_id == MARKET_ID else args.market_id
        args.ticker = WK_TICKER if args.ticker == TICKER else args.ticker
        args.replay = str(WK_REPLAY) if args.replay == str(DEFAULT_REPLAY) else args.replay
        args.speed = WK_SPEED if args.speed == SPEED else args.speed
    if args.opportunity:
        args.no_screens = True
        args.market_id = OPP_MARKET_ID if args.market_id == MARKET_ID else args.market_id
        args.query = OPP_QUERY if args.query == QUERY else args.query
        args.ticker = OPP_TICKER if args.ticker == TICKER else args.ticker
        args.replay = str(OPP_REPLAY) if args.replay == str(DEFAULT_REPLAY) else args.replay

    base, web = f"http://localhost:{args.backend_port}", f"http://localhost:{args.web_port}"
    if args.api_base:
        if not args.reuse:
            raise SystemExit("--api-base needs --reuse (servers already running, e.g. SHARE_NO_NGROK=1 make share)")
        base = args.api_base.rstrip("/")
    work = Path(tempfile.mkdtemp(prefix="pb-e2e-"))
    started = time.time()
    out: dict = {}
    code = 1
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        say(f"PolyBridge e2e demo  backend={base}  web={web}  replay={Path(args.replay).name} x{args.speed}")
        if not shutil.which("uv"):
            raise Abort("uv is not installed (https://docs.astral.sh/uv/)")
        env_file = None if (args.offline or args.weekend) else find_env_file(args.env_file)
        say(f"MASSIVE_API_KEY source: {'env file (' + env_file.name + ')' if env_file else ('not passed (--weekend; POLYBRIDGE_REPLAY_PRICES=recorded: every fill and the closure P&L use the recorded 2025 prices)' if args.weekend else 'none found: live equity quotes degrade to recorded bars')}")
        need_web = not args.no_screens
        busy = [(n, p) for n, p in [("backend", args.backend_port)] + ([("web", args.web_port)] if need_web else []) if port_busy(p)]
        if busy and not args.reuse:
            raise Abort(f"port(s) already in use: {busy}. Stop them, pick --backend-port/--web-port, or pass --reuse.")

        if not args.reuse:
            env = {**os.environ, "POLYBRIDGE_REPLAY_PATH": str(Path(args.replay).resolve()), "POLYBRIDGE_REPLAY_SPEED": str(args.speed),
                   "BROKER": "sim", "SIM_ACCOUNT_PATH": str(work / "sim_account.json"), "PYTHONUNBUFFERED": "1"}
            if args.weekend:
                env["POLYBRIDGE_REPLAY_PRICES"] = "recorded"
            for k in ("WEBULL_APP_KEY", "WEBULL_APP_SECRET"):
                env.pop(k, None)
            if args.offline:
                env.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9",
                           NO_PROXY="localhost,127.0.0.1")
                for k in ("MASSIVE_API_KEY", "GEMINI_API_KEY"):
                    env.pop(k, None)
            cmd = ["uv", "run", "--group", "engine"] + (["--env-file", str(env_file)] if env_file else []) + \
                  ["uvicorn", "app.main:app", "--port", str(args.backend_port)]
            say("\nstarting backend ...")
            be = spawn(cmd, BACKEND, env, work / "backend.log")
            if not wait_for(base + "/health", "backend", 120, be):
                tail = (work / "backend.log").read_text(errors="replace")[-600:]
                raise Abort(f"backend did not become healthy:\n{tail}")
            say(f"backend healthy ({time.time() - started:.0f}s)")
            if need_web:
                if not (WEB / "node_modules").exists():
                    subprocess.run(["pnpm", "install", "--frozen-lockfile"], cwd=WEB, check=True, capture_output=True)
                wenv = {**os.environ, "NEXT_PUBLIC_API_URL": base, "NEXT_TELEMETRY_DISABLED": "1", "PORT": str(args.web_port)}
                say("starting web dev server ...")
                wb = spawn(["pnpm", "exec", "next", "dev", "-p", str(args.web_port)], WEB, wenv, work / "web.log")
                if not wait_for(web + "/", "web", 180, wb):
                    tail = (work / "web.log").read_text(errors="replace")[-600:]
                    raise Abort(f"web dev server did not come up:\n{tail}")
                say(f"web ready ({time.time() - started:.0f}s)")
        elif not wait_for(base + "/health", "backend", 5):
            raise Abort(f"--reuse but nothing answers on {base}/health")
        else:
            s, _ = call(base, "POST", "/account/reset")
            say(f"--reuse: reset sim account -> {s}")

        out = (run_weekend_flow(base, args) if args.weekend else
               run_opportunity_flow(base, args) if args.opportunity else run_flow(base, args))
        if need_web:
            screenshots(web, base, out.get("bridge_id"), args)
    except Abort as e:
        check("flow completed", False, str(e))
    except KeyboardInterrupt:
        check("flow completed", False, "interrupted")
    finally:
        say("\nstopping servers ...")
        if not args.reuse:
            stop_all()
            left = [p for p in (args.backend_port, args.web_port) if port_busy(p)]
            say("servers stopped" if not left else f"WARNING: still listening on {left}")
        shutil.rmtree(work, ignore_errors=True)

    failed = [r for r in results if not r[1]]
    say("\n================ SUMMARY ================")
    if out and out.get("mode") == "weekend":
        sm, p, o = out.get("summary") or {}, out.get("pnl") or {}, out.get("staged") or {}
        say(f"market   : US recession in 2025? (validated out of sample) -> {args.ticker}, weekend 2025-04-04 -> 2025-04-07")
        if o:
            say(f"hedge B  : staged sell {o.get('qty')} approved, filled {o.get('filled_qty')} @ {o.get('fill_px')} "
                f"({o.get('session_target')}, {o.get('executed_at')}, recorded price)")
        if p:
            say(f"P&L      : no hedge ${p['unhedged_usd']:,.2f}; hedged ${p['hedged_usd']:,.2f}; vs no hedge {p['vs_no_hedge_usd']:+,.2f} "
                f"(staged order alone {p['staged_usd']:+,.2f})")
    elif out and out.get("mode") == "opportunity":
        f, pk, sm = out.get("fit", {}), out.get("pick") or {}, out.get("summary") or {}
        say(f"market   : {out['market']['question']}")
        if f:
            say(f"fit      : {f.get('event_class')} -> top {f.get('family')} #{f.get('preset_index')} ({f.get('score') and round(f['score'], 3)}); "
                f"options family {pk.get('family')} #{pk.get('preset_index')} score {pk.get('score') and round(pk['score'], 3)} "
                f"({f.get('score_basis')}, in-sample, {f.get('ticks_source')})")
        if sm:
            say(f"bridge   : {out['bridge_id']} ran {(sm.get('algo') or {}).get('family')} ticks={sm.get('ticks')} orders={sm.get('orders')} "
                f"filled={sm.get('broker_filled')} recorded-price option fills={sm.get('recorded_option_fills')} "
                f"P&L net of fees ${out.get('bridge_pnl', 0):,.2f} (simulated)")
    elif out:
        f, sm = out.get("fit", {}), out.get("summary", {})
        say(f"market   : {out['market']['question']}")
        say(f"fit      : {f.get('event_class')} -> {f.get('family')} #{f.get('preset_index')} (score {f.get('score') and round(f['score'], 3)}, llm={f.get('llm')}, {f.get('ticks_source')})")
        if sm:
            say(f"bridge   : {out['bridge_id']} engine={sm.get('engine')} ran {(sm.get('algo') or {}).get('family')} "
                f"ticks={sm.get('ticks')} orders={sm.get('orders')} filled={sm.get('broker_filled')} coverage={sm.get('coverage', 0):.1%} (cap {args.coverage:.0%})")
        a = out.get("account")
        if isinstance(a, dict):
            say(f"account  : {a.get('broker')} cash=${a['cash']:,.2f} equity=${a['equity']:,.2f}")
    say(f"checks   : {len(results) - len(failed)} passed, {len(failed)} failed, of {len(results)}  ({time.time() - started:.0f}s)")
    for n, _, d in failed:
        say(f"  FAILED: {n} -- {d}")
    code = 0 if not failed else 1
    say("RESULT   : " + ("PASS" if code == 0 else "FAIL"))
    return code


if __name__ == "__main__":
    sys.exit(main())
