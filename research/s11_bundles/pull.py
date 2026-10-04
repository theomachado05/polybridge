from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from s1_twin_spread import data as ds

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
S5 = RESEARCH / "s5_big_moves" / ".cache"
S9 = RESEARCH / "s9_weekend_price_markets" / ".cache"
UTC = timezone.utc


def ts(s) -> datetime | None:
    if not s:
        return None
    s = str(s).replace("Z", "+00:00")
    if "T" not in s:
        s = s.replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def source(mid: str, b_source: str) -> Path | None:
    for p in ((S9 / f"pm_{mid}.npz") if b_source == "s9" else None, S5 / f"pm_{mid}.npz", CACHE / f"pm_{mid}.npz"):
        if p is not None and p.exists():
            return p
    return None


def plan(h: dict) -> list[str]:
    todo: list[str] = []
    have = lambda i: (S5 / f"pm_{i}.npz").exists()      # noqa: E731
    for b in h["bundles"]:
        if b["kind"] in ("date", "strike") and b["source"] != "s9":
            todo += [i for i in b["legs"] if not have(i) and i not in todo]
    for b in sorted((b for b in h["bundles"] if b["kind"] == "negrisk"), key=lambda b: -b["event_volume"]):
        need = [i for i in b["legs"] if not have(i) and i not in todo]
        if len(todo) + len(need) > cfg.MAX_NEW_PULLS:
            break
        todo += need
    return todo[:cfg.MAX_NEW_PULLS]


def outcomes(h: dict, pt: ds.Throttle) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for slug in sorted({b["event"] for b in h["bundles"] if b["source"] == "s5"}):
        d = ds.get_json(f"{ds.GAMMA}/events", {"slug": slug}, throttle=pt, allow=(400, 404))
        for m in (d[0].get("markets") or []) if isinstance(d, list) and d else []:
            pr = json.loads(m["outcomePrices"]) if m.get("outcomePrices") else []
            y = float(pr[0]) if pr else float("nan")
            out[str(m["id"])] = y if m.get("closed") and y in (0.0, 1.0) else None
    for i, m in h["markets"].items():
        if "outcome" in m and i not in out:
            out[i] = m["outcome"]
    return out


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    h = json.loads((HERE / "bundles.json").read_text())
    M = h["markets"]
    todo = plan(h)
    w0 = datetime.fromisoformat(cfg.WINDOW_START).replace(tzinfo=UTC)
    w1 = datetime.fromisoformat(cfg.WINDOW_END).replace(tzinfo=UTC)
    pt, t0, fails = ds.Throttle(cfg.PULL_RATE), time.time(), []
    print(f"{len(todo)} markets to pull", flush=True)

    def job(i):
        f = CACHE / f"pm_{i}.npz"
        if f.exists():
            return 0
        m = M[i]
        try:
            a = max(ts(m.get("startDate")) or w0, w0).replace(second=0, microsecond=0)
            end = ts(m.get("closedTime")) or ts(m.get("endDate")) or w1
            b = min(end + timedelta(days=1), w1)
            hh = ds.pm_history({"token": m["token"]}, a, b, pt) if b > a else {"t": np.array([], np.int64), "p": np.array([], np.float32)}
            np.savez_compressed(f, t=hh["t"], p=hh["p"])
            return len(hh["t"])
        except Exception as e:  # noqa: BLE001
            fails.append({"market": i, "error": repr(e)[:200]})
            return 0

    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n in ex.map(job, todo):
            done += 1
            if done % 100 == 0:
                print(f"{time.time() - t0:6.0f}s {done}/{len(todo)}", flush=True)
    res = outcomes(h, pt)
    (CACHE / "outcomes.json").write_text(json.dumps(res))
    (CACHE / "pull_meta.json").write_text(json.dumps({"t1": datetime.now(UTC).isoformat(), "planned": len(todo), "failures": fails,
                                                      "seconds": round(time.time() - t0, 1), "results": sum(v is not None for v in res.values())}, indent=1))
    print(f"{time.time() - t0:.0f}s: {len(todo)} planned, {len(fails)} failures, {sum(v is not None for v in res.values())} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
