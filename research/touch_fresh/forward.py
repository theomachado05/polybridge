"""touch_fresh forward runner (FORWARD.md). Stages: snapshot (Friday 15:55 New York), prints (after Sunday 20:00), evaluate.

Run from `research/`:  python -m touch_fresh.forward snapshot|prints|evaluate
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from s1_twin_spread import data as ds
from s21_options_anchor import engine as eg
from s21_options_anchor import pull as p21
from s7_weekend_straddle.run import boot_mean

from . import config as cfg
from . import forward_config as fc
from .pull import anchor_epoch, build_anchor, stock_quote
from .run import matched_touch
from .universe import asset_class, entry_instant

HERE = Path(__file__).resolve().parent
LOG = HERE / fc.LOG_DIR
ET = ZoneInfo("America/New_York")


def log(stage: str, rec: dict) -> None:
    LOG.mkdir(exist_ok=True)
    with open(LOG / f"{stage}.jsonl", "a") as f:
        f.write(json.dumps({"logged_utc": datetime.now(timezone.utc).isoformat(), **rec}) + "\n")


def read(stage: str) -> list[dict]:
    f = LOG / f"{stage}.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []


def open_markets() -> list[dict]:
    out, off, s = [], 0, requests.Session()
    first = pd.Timestamp(fc.FIRST_LISTING_ET, tz=ET).timestamp()
    while True:
        d = s.get(f"{ds.GAMMA}/events", params={"tag_slug": fc.TAG, "closed": "false", "limit": 100, "offset": off}, timeout=30).json()
        if not d:
            return out
        for e in d:
            cls = asset_class(e["title"])
            if cls is None or not re.search(r"\bhit\b", e["title"], re.I) or re.search(r"all time high", e["title"], re.I):
                continue
            for m in e.get("markets") or []:
                if not m.get("startDate") or pd.Timestamp(m["startDate"]).timestamp() < first:
                    continue
                label = m.get("groupItemTitle") or ""
                text = f"{m['question']} {label}"
                sign = 1 if ("(HIGH)" in text or "↑" in text) else -1 if ("(LOW)" in text or "↓" in text) else 0
                rec = {"id": str(m["id"]), "event": str(e["id"]), "event_title": e["title"], "asset_class": cls, "question": m["question"],
                       "label": label, "sign": sign, "start": m["startDate"], "condition": m.get("conditionId")}
                fs = m.get("feeSchedule") or {}
                on = bool(m.get("feesEnabled")) and bool(fs)
                rec["fee_rate"], rec["fee_exponent"] = (float(fs.get("rate", 0.0)), float(fs.get("exponent", 1))) if on else (0.0, 1.0)
                out.append(rec)
        off += 100
        time.sleep(0.3)


def snapshot() -> int:
    done = {r["id"] for r in read("snapshot")}
    p21.CACHE = HERE / ".cache_forward"
    p21.CACHE.mkdir(exist_ok=True)
    src = p21.Src(offline=False)
    today = datetime.now(ET).date()
    for m in open_markets():
        if m["id"] in done:
            continue
        p, why = eg.parse_market(m)
        if p is None:
            continue
        es = date.fromisoformat(p["end_session"])
        while es.isoformat() in cfg.HOLIDAYS or es.weekday() >= 5:
            es = date.fromordinal(es.toordinal() - 1)
        p["end_session"] = es.isoformat()
        day, at = entry_instant(m["start"])
        if day != today or date.fromisoformat(p["end_session"]) <= day:
            continue
        m = {**m, **p, "entry_day": day.isoformat(), "entry_epoch": at}
        try:
            a = build_anchor(src, m)
            q = stock_quote(src, m["ticker"], anchor_epoch(m["entry_day"])) if m["ticker"] != "SPX" else None
        except p21.FetchError as e:
            a, q = {"status": f"fetch error: {e}"}, None
        if a.get("status") == "ok":
            a["anchor_central"] = matched_touch(a["p_mid"], a["T_days"], a["tau_days"])
        log("snapshot", {**m, **a, "stock_quote": q})
    return 0


def prints() -> int:
    done = {r["id"] for r in read("prints")}
    pt = ds.Throttle(3.0)
    for m in read("snapshot"):
        if m["id"] in done or time.time() < m["entry_epoch"] + fc.PRINT_WINDOW_S:
            continue
        raw = ds.pm_trades(m["condition"], m["entry_epoch"], pt, max_pages=2)
        keep = [t for t in raw if m["entry_epoch"] <= float(t.get("timestamp", 0)) <= m["entry_epoch"] + fc.PRINT_WINDOW_S]
        vol = float(ds.get_json(f"{ds.GAMMA}/markets/{m['id']}", throttle=pt).get("volume") or 0)
        log("prints", {"id": m["id"], "volume_at_snapshot": vol,
                       "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]})
    return 0


def evaluate() -> int:
    from s18_price_market_calibration.prints import weighted, yes_terms
    snap = {r["id"]: r for r in read("snapshot")}
    rows, pt = [], ds.Throttle(3.0)
    for pr in read("prints"):
        m = snap[pr["id"]]
        ys = [y for y in (yes_terms(t) for t in pr["prints"]) if y]
        ps, _, n_s = weighted(ys, "SELL")
        tot = sum(z for _, _, z in ys)
        pa = sum(p * z for p, _, z in ys) / tot if tot else float("nan")
        if m.get("status") != "ok" or not n_s or pr["volume_at_snapshot"] < fc.MIN_MARKET_VOLUME or not (fc.PRICE_BAND[0] <= pa <= fc.PRICE_BAND[1]):
            continue
        if 100 * (ps - m["anchor_central"]) < fc.THRESHOLD - 1e-9:
            continue
        g = ds.get_json(f"{ds.GAMMA}/markets/{m['id']}", throttle=pt)
        op = json.loads(g["outcomePrices"]) if g.get("outcomePrices") else []
        if not (g.get("closed") and op and float(op[0]) in (0.0, 1.0)):
            continue
        o = float(op[0])
        for c in fc.FEE_MULTIPLES:
            fee = c * m["fee_rate"] * (ps * (1 - ps)) ** m["fee_exponent"]
            rows.append({"event": m["event"], "fee": c, "pnl": 100 * (ps - fee - o)})
    d = pd.DataFrame(rows, columns=["event", "fee", "pnl"])
    one = d[d.fee == 1.0]
    n, ev = len(one), one.event.nunique()
    res = {c: boot_mean({str(e): list(v) for e, v in d[d.fee == c].groupby("event").pnl}) for c in fc.FEE_MULTIPLES}
    ready = (n >= fc.MIN_MARKETS and ev >= fc.MIN_EVENTS) or date.today().isoformat() > fc.EVALUATE_BY
    print(f"B0 resolved: {n} markets, {ev} events; " + "; ".join(f"fee {c}x: {r[0]:.2f} [{r[1]:.2f}, {r[2]:.2f}]" for c, r in res.items()))
    if not ready:
        print("not evaluated: the minimum is not met and the date has not passed")
    elif n < fc.MIN_MARKETS or ev < fc.MIN_EVENTS:
        print("INSUFFICIENT")
    else:
        print("PASS" if all(r[1] > 0 for r in res.values()) else "FAIL")
    return 0


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"snapshot": snapshot, "prints": prints, "evaluate": evaluate}.get(stage, lambda: print(__doc__) or 2)())
