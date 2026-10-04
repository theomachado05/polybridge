"""S24 pull: public trade prints of every rung, ladders in the pre-registered order, then each rung's result.

One worker, one request a second (net.GATE), cached and resumable. Only prints of ladder rungs are kept, as small arrays.

Run from `research/`:
    python -m s24_ladder_fresh.pull            # prints, then results
    python -m s24_ladder_fresh.pull results    # results only
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from s1_twin_spread import data as ds

from . import config as cfg
from .net import CACHE, GATE, BudgetExhausted

HERE = Path(__file__).resolve().parent
PRINTS = CACHE / "prints"
STATE = CACHE / "pull_state.json"
ET = ZoneInfo("America/New_York")


def deadline() -> float:
    return datetime.strptime(cfg.PULL_DEADLINE_ET, "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp()


def compact(prints: list[dict]) -> dict[str, np.ndarray]:
    """Raw prints to arrays, oldest first, duplicates removed. side: +1 BUY, -1 SELL (the taker). out: 1 Yes, 0 No, -1 other."""
    seen, rows = set(), []
    for x in prints:
        key = (x.get("transactionHash"), x.get("asset"), x.get("timestamp"), x.get("price"), x.get("size"), x.get("side"), x.get("proxyWallet"))
        if key in seen:
            continue
        seen.add(key)
        sd = str(x.get("side", "")).upper()
        oc = str(x.get("outcome", "")).lower()
        try:
            rows.append((int(float(x["timestamp"])), float(x["price"]), 1 if sd == "BUY" else (-1 if sd == "SELL" else 0),
                         1 if oc == "yes" else (0 if oc == "no" else -1), float(x.get("size") or 0.0)))
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r[0])
    a = np.array(rows, dtype=float).reshape(-1, 5)
    return {"t": a[:, 0].astype(np.int64), "price": a[:, 1].astype(np.float64), "side": a[:, 2].astype(np.int8),
            "out": a[:, 3].astype(np.int8), "size": a[:, 4].astype(np.float64)}


def fetch_prints(cond: str) -> tuple[list[dict], int, list[int]]:
    """S11's call: data-api /trades, market=<conditionId>, limit=10000, offset=0 then 10000. Returns prints, requests, page sizes."""
    out, sizes = [], []
    n0 = GATE.n
    for i in range(cfg.PRINT_PAGES):
        d = ds.get_json(ds.DATA_API, {"market": cond, "limit": cfg.PRINT_PAGE, "offset": i * cfg.PRINT_PAGE}, throttle=GATE, allow=(400, 404))
        if not isinstance(d, list) or not d:
            sizes.append(0)
            break
        out.extend(d)
        sizes.append(len(d))
        if len(d) < cfg.PRINT_PAGE:
            break
    return out, GATE.n - n0, sizes


def pull_market(mid: str, M: dict) -> dict:
    f = PRINTS / f"{mid}.npz"
    if f.exists():
        return {"cached": True}
    raw, used, sizes = fetch_prints(M[mid]["conditionId"])
    arr = compact(raw)
    np.savez_compressed(f, **arr, served=np.array([len(raw)]), pages=np.array(sizes))
    return {"cached": False, "requests": used, "served": len(raw), "kept": int(len(arr["t"])), "pages": sizes}


def pull_prints(L: dict) -> dict:
    PRINTS.mkdir(parents=True, exist_ok=True)
    M = L["markets"]
    st = json.loads(STATE.read_text()) if STATE.exists() else {"done": [], "left_out": {}, "used": {"a": 0, "b": 0}, "log": []}
    done = set(st["done"])
    queues = {s: [k for k, b in enumerate(L["ladders"]) if b["set"] == s] for s in ("a", "b")}      # already in the fixed order
    pos = {"a": 0, "b": 0}
    closed = {"a": False, "b": False}
    t_end = deadline()
    t0 = time.time()

    def need(k: int) -> int:
        return 2 * sum(1 for i in L["ladders"][k]["legs"] if not (PRINTS / f"{i}.npz").exists())

    def run(phase: int) -> None:
        turn = "a"
        while not (closed["a"] and closed["b"]):
            s = turn
            turn = "b" if turn == "a" else "a"
            if closed[s]:
                continue
            while pos[s] < len(queues[s]) and queues[s][pos[s]] in done:
                pos[s] += 1
            if pos[s] >= len(queues[s]):
                closed[s] = True
                continue
            if time.time() >= t_end:
                closed["a"] = closed["b"] = True
                st["stopped_by"] = "deadline"
                break
            k = queues[s][pos[s]]
            n = need(k)
            total = st["used"]["a"] + st["used"]["b"]
            if (phase == 1 and st["used"][s] + n > cfg.PRINT_REQUESTS_PER_SET) or total + n > cfg.MAX_PRINT_REQUESTS:
                closed[s] = True            # the set stops at the first ladder that does not fit
                continue
            GATE.kind = f"prints_{s}"
            for i in L["ladders"][k]["legs"]:
                r = pull_market(i, M)
                if not r.get("cached"):
                    st["used"][s] += r["requests"]
                    st["log"].append({"market": i, "set": s, **{x: r[x] for x in ("requests", "served", "kept", "pages")}})
            done.add(k)
            st["done"] = sorted(done)
            pos[s] += 1
            STATE.write_text(json.dumps(st))
            if len(done) % 10 == 0:
                print(f"{time.time() - t0:6.0f}s phase {phase}: {len(done)} ladders, requests a={st['used']['a']} b={st['used']['b']}, gate {GATE.n}", flush=True)

    try:
        run(1)
        closed.update({"a": False, "b": False})
        if st.get("stopped_by") != "deadline":
            run(2)                           # what one set left goes to the other
            st.setdefault("stopped_by", "budget or end of list")
    except BudgetExhausted as e:
        st["stopped_by"] = f"request budget: {e}"
    st["left_out"] = {s: [k for k in queues[s] if k not in done] for s in ("a", "b")}
    st["finished_utc"] = datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(st))
    print(f"prints done in {time.time() - t0:.0f}s: {len(done)} ladders, used {st['used']}, stopped by {st.get('stopped_by')}, "
          f"left out a={len(st['left_out']['a'])} b={len(st['left_out']['b'])}", flush=True)
    return st


def pull_results(L: dict) -> dict:
    """Each pulled rung's result from the catalogue: closed markets only (an open market is not returned)."""
    st = json.loads(STATE.read_text())
    ids = sorted({i for k in st["done"] for i in L["ladders"][k]["legs"]}, key=int)
    f = CACHE / "outcomes.json"
    res = json.loads(f.read_text()) if f.exists() else {}
    todo = [i for i in ids if i not in res]
    GATE.kind = "results"
    for a in range(0, len(todo), cfg.RESULT_BATCH):
        batch = todo[a:a + cfg.RESULT_BATCH]
        d = ds.get_json(f"{ds.GAMMA}/markets", [("id", i) for i in batch] + [("limit", 100), ("closed", "true")], throttle=GATE, allow=(400, 422))
        got = {str(m["id"]): m for m in d} if isinstance(d, list) else {}
        for i in batch:
            m = got.get(i)
            if m is None:
                res[i] = {"outcome": None, "closedTime": None, "closed": False}
                continue
            try:
                pr = json.loads(m["outcomePrices"]) if m.get("outcomePrices") else []
                y = float(pr[0]) if pr else float("nan")
            except (ValueError, TypeError):
                y = float("nan")
            res[i] = {"outcome": y if m.get("closed") and y in (0.0, 0.5, 1.0) else None, "closedTime": m.get("closedTime"),
                      "closed": bool(m.get("closed")), "uma": m.get("umaResolutionStatus")}
        f.write_text(json.dumps(res))
    print(f"results: {len(ids)} rungs, {sum(1 for i in ids if res[i]['outcome'] is not None)} resolved", flush=True)
    return res


def main() -> int:
    L = json.loads((HERE / "ladders.json").read_text())
    if "results" not in sys.argv[1:]:
        pull_prints(L)
    pull_results(L)
    print("requests", GATE.n, GATE.by, "recorder pauses", GATE.pauses)
    return 0


if __name__ == "__main__":
    sys.exit(main())
