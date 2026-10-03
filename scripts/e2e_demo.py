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
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
WEB = ROOT / "web"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_REPLAY = BACKEND / "replays" / "another-fed-hike-2026-history.jsonl"
SCREEN_DIR = WEB / "e2e" / "screens"

# The default target: "Another Fed rate hike in 2026?" hedging TLT, the demo market where the prediction-market signal
# measurably beats a static hedge in-sample (fits.json: score_vs_static +0.257 over 401 hourly ticks). YES token id and
# provenance: backend/replays/another-fed-hike-2026-history.jsonl.meta.json. The Fed October 2026 market (2589813, IWM,
# fed-hike-25bps-oct-2026-history.jsonl, query "fed october") remains an alternative: pass --query/--market-id/
# --market-text/--ticker/--replay/--speed 36000.
MARKET_ID = "4620900"
QUESTION = "Another Fed rate hike in 2026?"
QUERY = "fed rate hike 2026"
MARKET_TEXT = "Another Fed rate hike in 2026"  # what the UI walk clicks in the Build search results
TICKER = "TLT"
SHARES = 1000.0  # the precompute's shares_held, so the fit matches fits.json
# 401 hourly points (about 400 h) at 21600x = 6 ticks per second, about 67 s for the whole replay.
SPEED = "21600"
COVERAGE = 0.5
DIRECTION = "down_on_yes"

results: list[tuple[str, bool, str]] = []
children: list[subprocess.Popen] = []


def say(msg: str = "") -> None:
    print(msg, flush=True)


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return bool(ok)


class Abort(Exception):
    """A step failed in a way that makes the rest of the flow meaningless."""


# ------------------------------------------------------------------ http (stdlib)

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


# ------------------------------------------------------------------ processes

def find_env_file(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    cands = [ROOT / ".env"]
    try:  # a git worktree keeps its .env in the main checkout
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


# ------------------------------------------------------------------ SSE

def read_sse(base: str, bridge_id: str, want_events: int, max_s: float, need_fill: bool):
    """Read the bridge stream. Returns (events, closed_by_server). Stops after `want_events` events, but keeps going
    (until max_s) while `need_fill` and no order has been filled yet. Heartbeats are not events."""
    host, port = base.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=15)
    events: list[tuple[str, dict]] = []
    closed = False
    t0 = time.time()
    try:
        conn.request("GET", f"/bridges/{bridge_id}/stream", headers={"accept": "text/event-stream"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise Abort(f"stream answered {resp.status}")
        kind, data = None, []
        while time.time() - t0 < max_s:
            try:
                line = resp.readline()
            except socket.timeout:
                continue  # a quiet stretch; the server sends heartbeats, keep waiting until max_s
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


# ------------------------------------------------------------------ the flow

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
    s, prop = call(base, "POST", f"/proposals/{prop['id']}/approve")
    check("approve", s == 200 and prop["status"] == "approved", f"{s}")
    out["proposal"] = prop
    ra = prop.get("algo") or {}
    say(f"     proposal {prop['id']}: {prop['label']}; will run {ra.get('family')} #{ra.get('preset_index')} "
        f"capped at coverage {ra.get('coverage_cap')} (capped params: {ra.get('capped')})")

    say("\n== 6. POST /bridges (replay of real Polymarket history, orders go to the sim account)")
    body = {"proposal_id": prop["id"], "source": "replay", "gap_per_share": 1.0, "direction": direction,
            "market": {"source": "polymarket", "id": mk["id"], "token_id": mk.get("token_id")},
            "family": fit["family"], "preset_index": fit["preset_index"],
            "replay_to_account": True}  # so GET /orders shows the fills (the default replay sandbox is invisible there)
    s, br = call(base, "POST", "/bridges", body)
    if not check("bridge started", s == 201 and "bridge_id" in br, f"{s} {br}"):
        raise Abort("bridge not started")
    bid = br["bridge_id"]
    out["bridge_id"] = bid
    _, sm0 = call(base, "GET", f"/bridges/{bid}")
    if (sm0 or {}).get("status") == "running":  # idempotent only while running; a finished bridge is never handed back
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
        # Wi-Fi off: no current Massive quote, so a replay bridge fills at the replayed under_px, labelled "recorded".
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
    # offline too: the replay fills at the recorded price, so the account must match the bridge either way
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


# ------------------------------------------------------------------ screenshots

SCREENS = [("landing", "/"), ("build", "/build"), ("connect", "/connect"), ("pipeline", "/pipeline"),
           ("bridge", None), ("portfolio", "/portfolio"), ("library", "/library"), ("profile", "/profile")]


def ui_walk(web: str, base: str, args) -> list[str]:
    """Click through the real UI (web/e2e/ui_walk.mjs, Chrome DevTools protocol) and save a screenshot per screen.
    Returns the files written. Its checks are folded into this run's results."""
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
    """Fallback: open one URL cold (no wizard state) and screenshot it; Chrome is killed on a deadline (SSE never idles)."""
    wait_for(web + path, name, 120)  # the first hit compiles the route in `next dev`
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
    say("\n== 10. UI walk + screenshots of the 8 screens -> web/e2e/screens/")
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


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backend-port", type=int, default=8000)
    ap.add_argument("--web-port", type=int, default=3000)
    ap.add_argument("--reuse", action="store_true", help="use servers already listening (stops nothing)")
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
    args = ap.parse_args()

    base, web = f"http://localhost:{args.backend_port}", f"http://localhost:{args.web_port}"
    work = Path(tempfile.mkdtemp(prefix="pb-e2e-"))
    started = time.time()
    out: dict = {}
    code = 1
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        say(f"PolyBridge e2e demo  backend={base}  web={web}  replay={Path(args.replay).name} x{args.speed}")
        if not shutil.which("uv"):
            raise Abort("uv is not installed (https://docs.astral.sh/uv/)")
        env_file = None if args.offline else find_env_file(args.env_file)
        say(f"MASSIVE_API_KEY source: {'env file (' + env_file.name + ')' if env_file else 'none found: live equity quotes degrade to recorded bars'}")
        need_web = not args.no_screens
        busy = [(n, p) for n, p in [("backend", args.backend_port)] + ([("web", args.web_port)] if need_web else []) if port_busy(p)]
        if busy and not args.reuse:
            raise Abort(f"port(s) already in use: {busy}. Stop them, pick --backend-port/--web-port, or pass --reuse.")

        if not args.reuse:
            env = {**os.environ, "POLYBRIDGE_REPLAY_PATH": str(Path(args.replay).resolve()), "POLYBRIDGE_REPLAY_SPEED": str(args.speed),
                   "BROKER": "sim", "SIM_ACCOUNT_PATH": str(work / "sim_account.json"), "PYTHONUNBUFFERED": "1"}
            for k in ("WEBULL_APP_KEY", "WEBULL_APP_SECRET"):
                env.pop(k, None)
            if args.offline:  # httpx honours these: every call to Polymarket, Kalshi, Massive, Gemini is refused at once
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
            s, _ = call(base, "POST", "/account/reset")  # reused backend: start from a clean sim account (409 if Webull is active)
            say(f"--reuse: reset sim account -> {s}")

        out = run_flow(base, args)
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
    if out:
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
