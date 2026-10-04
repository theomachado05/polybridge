from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from s1_twin_spread import data as ds
from s11_bundles import universe as u11

from . import config as cfg
from .net import GATE

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
KEEP = ("id", "question", "conditionId", "startDate", "createdAt", "endDate", "closedTime", "closed", "negRisk", "volume",
        "enableOrderBook")
QUERY = {"a": ("2024-01-01T00:00:00Z", "2025-09-30T23:59:59Z"), "b": ("2025-10-01T00:00:00Z", "2026-10-03T23:59:59Z")}


def strip(m: dict) -> dict:
    out = {k: m.get(k) for k in KEEP}
    out["id"] = str(out["id"])
    toks = json.loads(m["clobTokenIds"]) if m.get("clobTokenIds") else []
    out["token"], out["no_token"] = (toks + [None, None])[:2]
    try:
        out["outcomes"] = json.loads(m["outcomes"]) if isinstance(m.get("outcomes"), str) else m.get("outcomes")
    except ValueError:
        out["outcomes"] = None
    fs = m.get("feeSchedule") or {}
    fee_on = bool(m.get("feesEnabled")) and bool(fs)
    out["fee_rate"] = float(fs.get("rate", 0.0) or 0.0) if fee_on else 0.0
    out["fee_exponent"] = float(fs.get("exponent", 1) or 1) if fee_on else 1.0
    out["volume"] = float(out.get("volume") or 0.0)
    assert not u11.PRICE_FIELDS & set(out)
    return out


def listed(m: dict) -> str:
    return str(m.get("startDate") or m.get("createdAt") or "")[:10]


def in_set(m: dict, s: str) -> bool:
    d, v = listed(m), float(m.get("volume") or 0.0)
    if s == "a":
        return cfg.SET_A_LISTED[0] <= d <= cfg.SET_A_LISTED[1] and v >= cfg.SET_A_MIN_VOLUME
    return cfg.SET_B_LISTED[0] <= d <= cfg.SET_B_LISTED[1] and cfg.SET_B_VOLUME[0] <= v < cfg.SET_B_VOLUME[1]


def usable(m: dict) -> bool:
    return (m.get("outcomes") == cfg.YES_NO and bool(m.get("conditionId")) and bool(m.get("token"))
            and m.get("enableOrderBook") is not False)


OR_DOWN = r"\bor (?:lower|less|fewer|below|under)\b"
OR_UP = r"\bor (?:higher|more|above|greater|over)\b"


def direction_conflict(template: str, orient: int) -> bool:
    return bool((orient > 0 and re.search(OR_DOWN, template, re.I)) or (orient < 0 and re.search(OR_UP, template, re.I)))


def strike_ladders_same_date(event: str, markets: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for m in markets:
        by.setdefault((u11.date_template(m["question"])[1] or "").lower(), []).append(m)
    out = []
    for phrase, ms in sorted(by.items()):
        for b in u11.strike_ladders(event, ms):
            if direction_conflict(b["template"], b["orient"]):
                continue
            b["date_phrase"] = phrase
            out.append(b)
    return out


def event_ladders(e: dict, excluded: set[str], excluded_cond: set[str]) -> tuple[list[dict], dict]:
    ms = [strip(m) for m in e.get("markets") or [] if m.get("clobTokenIds")]
    ms = [m for m in ms if usable(m) and m["id"] not in excluded and str(m["conditionId"]).lower() not in excluded_cond]
    slug = e.get("slug") or str(e["id"])
    out = []
    for s in ("a", "b"):
        rungs = [m for m in ms if in_set(m, s)]
        if len(rungs) < 2:
            continue
        for b in u11.date_ladders(slug, rungs) + strike_ladders_same_date(slug, rungs):
            b["set"] = s
            b["event_title"] = e.get("title")
            b["event_volume"] = float(e.get("volume") or 0)
            b["event_start"] = str(e.get("startDate") or "")[:10]
            out.append(b)
    return out, {m["id"]: m for m in ms}


def order_key(b: dict):
    return (-b["event_volume"], b["event"], b["kind"], b.get("template", ""), b.get("date_phrase", ""), b["legs"][0])


def seen_markets() -> tuple[set[str], set[str], dict]:
    ids: set[str] = set()
    conds: set[str] = set()
    n = {}
    for name in ("bundles.json", "live_bundles.json"):
        d = json.loads((RESEARCH / "s11_bundles" / name).read_text())
        ids |= set(d["markets"])
        conds |= {str(m.get("conditionId")).lower() for m in d["markets"].values() if m.get("conditionId")}
        n[f"s11 {name}"] = len(d["markets"])
    k = 0
    for cache in RESEARCH.glob("*/.cache"):
        if cache.parent.name == HERE.name:
            continue
        for f in cache.rglob("*"):
            hit = re.fullmatch(r"(?:pm_|p_)?(\d{4,9})\.(?:npz|json|json\.gz|csv)", f.name)
            if hit:
                ids.add(hit.group(1))
                k += 1
    n["cached price or print files of other studies"] = k
    k = 0
    for f in list(RESEARCH.glob("*/*.json")):
        if f.parent.name in (HERE.name, "forward") or f.stat().st_size > 60e6:
            continue
        found = set(re.findall(r"0x[0-9a-fA-F]{64}", f.read_text(errors="replace")))
        conds |= {c.lower() for c in found}
        k += len(found)
    n["condition ids in other studies' lists"] = k
    return ids, conds, n


def refilter() -> int:
    L = json.loads((HERE / "ladders.json").read_text())
    keep = [b for b in L["ladders"] if not (b["kind"] == "strike" and direction_conflict(b["template"], b["orient"]))]
    L["dropped_by_direction_rule"] = L.get("dropped_by_direction_rule", 0) + len(L["ladders"]) - len(keep)
    L["ladders"] = sorted(keep, key=order_key)
    L["markets"] = {i: L["markets"][i] for b in keep for i in b["legs"]}
    (HERE / "ladders.json").write_text(json.dumps(L, indent=1))
    print("dropped", L["dropped_by_direction_rule"], "kept", len(keep))
    return 0


def main() -> int:
    excluded, excluded_cond, seen_n = seen_markets()
    print(f"excluded: {len(excluded)} market ids, {len(excluded_cond)} condition ids {seen_n}", flush=True)
    GATE.kind = "catalogue"
    ladders, meta, stats = [], {}, {}
    seen_events: set[str] = set()
    for q in ("a", "b"):
        pages = events = offset = 0
        last_vol = vol_max = None
        stop = "page cap"
        while pages < cfg.CAT_MAX_PAGES[q]:
            params = {"order": "volume", "ascending": "false", "limit": cfg.CAT_PAGE, "offset": offset,
                      "start_date_min": QUERY[q][0], "start_date_max": QUERY[q][1]}
            if vol_max is not None:
                params["volume_max"] = vol_max
            d = ds.get_json(f"{ds.GAMMA}/events", params, throttle=GATE, allow=(400, 422))
            if not isinstance(d, list) or not d:
                stop = "the catalogue served no more events"
                break
            pages += 1
            if vol_max is not None and float(d[0].get("volume") or 0) > vol_max + 1e-6:
                stop = "volume_max not honoured"
                break
            new = 0
            for e in d:
                if str(e["id"]) in seen_events:
                    continue
                seen_events.add(str(e["id"]))
                events += 1
                new += 1
                bs, mm = event_ladders(e, excluded, excluded_cond)
                for b in bs:
                    for i in b["legs"]:
                        meta[i] = mm[i]
                ladders += bs
            last_vol = float(d[-1].get("volume") or 0)
            if pages % 10 == 0:
                print(f"query {q} page {pages}: {events} events, last volume ${last_vol:,.0f}, {len(ladders)} ladders", flush=True)
            if last_vol < cfg.CAT_STOP_EVENT_VOLUME[q] or len(d) < cfg.CAT_PAGE:
                stop = "event volume under the floor" if last_vol < cfg.CAT_STOP_EVENT_VOLUME[q] else "the catalogue served no more events"
                break
            offset += cfg.CAT_PAGE
            if offset >= cfg.CAT_OFFSET_CAP:
                if vol_max is not None and last_vol >= vol_max and new == 0:
                    stop = "no progress below one volume"
                    break
                vol_max, offset = last_vol, 0
        stats[q] = {"pages": pages, "events": events, "last_event_volume": last_vol, "stopped_by": stop}
    ladders.sort(key=order_key)
    out = {"built_utc": datetime.now(timezone.utc).isoformat(), "queries": stats, "excluded": seen_n,
           "excluded_ids": len(excluded), "excluded_condition_ids": len(excluded_cond), "requests": GATE.n,
           "ladders": ladders, "markets": {i: meta[i] for b in ladders for i in b["legs"]}}
    for m in out["markets"].values():
        assert not u11.PRICE_FIELDS & set(m)
    (HERE / "ladders.json").write_text(json.dumps(out, indent=1))
    for s in ("a", "b"):
        for k in ("date", "strike"):
            bs = [b for b in ladders if b["set"] == s and b["kind"] == k]
            print(f"set {s} {k}: {len(bs)} ladders, {len({i for b in bs for i in b['legs']})} rungs, {sum(len(b['pairs']) for b in bs)} pairs, "
                  f"{len({b['event'] for b in bs})} events")
    print(stats, "requests so far", GATE.n)
    return 0


if __name__ == "__main__":
    sys.exit(refilter() if "refilter" in sys.argv[1:] else main())
