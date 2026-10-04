"""The contract link agent, measured blind (linker/contract_eval/PLAN.md sections 1 to 3).

`sample` reads Polymarket's public listing, names and rules text only: the open events the product's boards read
(backend/app/contracts/live.py: the two TICKET_TAGS and the open events of $100,000 volume or more, the same keyset
paging) and closed events of the last twelve months under the same tags and volume rule (one page per source per
month). Every price-like field is dropped at parse time (a whitelist); the stripped events are cached gzipped in
`linker/.cache/contract_eval/events.json.gz`. Every market goes through `link_map.classify` with the dict the ticket
board passes (the market plus event_title and event_id), every event through `link_map.link_ladders` with the markets
the ladder board passes (volume >= $50,000; open events also not closed and accepting orders). The sample is drawn
with random.Random(20261004), stratified by the parser's type, dealt alternately into half A and half B, and written to
`contract_eval/universe.json`, `predictions.json` (the parser's answers and the sha256 of the parser files, kept apart)
and the blind input files `input_fields_{A1,A2,B1,B2}.json`, `input_pairs_{A,B}.json`.

`score` reads the two labellers' files of a half, takes as truth what both agree on field by field, re-runs the parser
as it is on disk on universe.json, and writes the measures of PLAN section 3 to
`results/linker/contract_eval_<half>[_<tag>].json` and `..._errors.csv`. With `--stored` it also scores the answers
stored in predictions.json at step 1 (PLAN section 4: half B with the step-1 parser and the fixed one) and writes them
to `contract_eval_<half>_stepone[_<tag>].json`, so no old parser file has to be put back on disk.

Run from `research/`:
    python -m linker.contract_eval sample [--refresh]
    python -m linker.contract_eval score --half A|B [--tag NAME] [--stored] [--strict-dates]

Amendment 1: a ticket's date is compared on its end session (the last weekday on or before the parser's window end
against the same of the readers' date); `--strict-dates` keeps the calendar-day rule as first written.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from s21_options_anchor.engine import last_weekday

from . import link_map as lm
from .study import binom_ci

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "contract_eval"
CACHE = HERE / ".cache" / "contract_eval" / "events.json.gz"
RESULTS = HERE.parent / "results" / "linker"
PROMPTS = HERE / "prompts"
PARSER_FILES = {"link_map.py": HERE / "link_map.py", "options.py": HERE / "options.py",
                "ladder_replay/replay.py": HERE.parent / "ladder_replay" / "replay.py"}
SEED = 20261004
AS_OF = date(2026, 10, 4)
PER_TYPE, PER_EVENT, PAIRS_PER_HALF, PAIRS_PER_EVENT = 110, 6, 40, 3
RULES_CUT = 900
MAX_REQUESTS = 80
TICKET_TAGS = ({"tag_slug": "hit-price"}, {"tag_id": 102676})     # live.TICKET_TAGS (not imported: the backend needs httpx)
LADDER_FILTER, TICKET_PAGES, LADDER_PAGES = {"volume_min": 100000}, 2, 3
MIN_RUNG_VOLUME = 50_000.0                                         # live.MIN_RUNG_VOLUME
TICKETS = ("touch_ticket", "close_above_ticket")
TICKET_FIELDS = ("underlying", "level", "direction", "date")
STRATA = ("touch_ticket", "close_above_ticket", "ladder_rung", "other")
MARKET_KEEP = ("id", "question", "description", "resolutionSource", "createdAt", "startDate", "endDate", "groupItemTitle",
               "closed", "volume", "acceptingOrders")
EVENT_KEEP = ("id", "slug", "title", "resolutionSource")
PARSER_KEYS = {"type", "stratum", "half", "linkable", "reasons", "underlying", "level", "direction", "date", "window_end",
               "nested", "rich_date", "cheap_date", "year_source", "checks", "fields", "mechanism"}
PRICEY = re.compile(r"\$\s?\d|\bprice\b|\bhits?\b|\breach|\bclose[sd]?\b|\bfinish|\babove\b|\bbelow\b|\bdips?\b|\bfalls?\b", re.I)
YEAR = re.compile(r"\b20\d\d\b")


# ------------------------------------------------------------------------------------------------ fetch (names only)

def strip_market(m: dict) -> dict:
    out = {k: m.get(k) for k in MARKET_KEEP}
    out["id"] = str(out["id"])
    try:
        out["volume"] = float(m.get("volumeNum") or m.get("volume") or 0)
    except (TypeError, ValueError):
        out["volume"] = 0.0
    out["closed"] = bool(out["closed"])
    return out


def strip_event(e: dict, source: str) -> dict:
    out = {k: e.get(k) for k in EVENT_KEEP}
    out.update(id=str(out["id"]), closed=bool(e.get("closed")), tags=[t.get("label") or "" for t in e.get("tags") or []],
               sources=[source], markets=[strip_market(m) for m in e.get("markets") or []])
    return out


def _months(n: int = 12) -> list[tuple[str, str]]:
    out, hi = [], AS_OF
    for _ in range(n):
        lo = date(hi.year - (hi.month == 1), (hi.month - 2) % 12 + 1, min(hi.day, 28))
        out.append((lo.isoformat(), hi.isoformat()))
        hi = lo
    return out


def fetch() -> tuple[list[dict], dict]:
    """The stripped events (deduplicated by id) and the request log. At most MAX_REQUESTS Gamma requests, 4 per second."""
    from s1_twin_spread import data as ds
    throttle, log = ds.Throttle(4.0), {"requests": 0, "pages": []}
    events: dict[str, dict] = {}

    def keyset(source: str, params: dict, n: int) -> None:
        cur = None
        for _ in range(n):
            if log["requests"] >= MAX_REQUESTS:
                return
            p = {"limit": 100, **params} | ({"after_cursor": cur} if cur else {})
            log["requests"] += 1
            try:
                d = ds.get_json(f"{ds.GAMMA}/events/keyset", p, throttle=throttle, allow=(400, 404, 422))
            except Exception as e:                     # noqa: BLE001 - one page never fails the fetch; no text is kept
                log["pages"].append({"source": source, **params, "error": type(e).__name__})
                return
            ok = isinstance(d, dict) and "_status" not in d
            evs = (d.get("events") or []) if ok else []
            log["pages"].append({"source": source, **params, "events": len(evs)})
            for e in evs:
                s = strip_event(e, source)
                if s["id"] in events:
                    events[s["id"]]["sources"] = sorted(set(events[s["id"]]["sources"]) | {source})
                else:
                    events[s["id"]] = s
            cur = d.get("next_cursor") if ok else None
            if not cur or not evs:
                return

    for i, tag in enumerate(TICKET_TAGS):
        keyset(f"open_ticket_{i}", {"closed": "false", "active": "true", **tag}, TICKET_PAGES)
    keyset("open_ladder", {"closed": "false", "active": "true", **LADDER_FILTER}, LADDER_PAGES)
    for lo, hi in _months():
        win = {"closed": "true", "end_date_min": lo, "end_date_max": hi}
        for i, tag in enumerate(TICKET_TAGS):
            keyset(f"closed_ticket_{i}", {**win, **tag}, 1)
        keyset("closed_ladder", {**win, **LADDER_FILTER}, 1)
    return list(events.values()), log


def load_events(refresh: bool = False) -> tuple[list[dict], dict]:
    if CACHE.exists() and not refresh:
        d = json.loads(gzip.decompress(CACHE.read_bytes()))
        return d["events"], d["log"]
    events, log = fetch()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(gzip.compress(json.dumps({"events": events, "log": log}, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0))
    return events, log


# ------------------------------------------------------------------------------------------------ the parser's answer

def ticket_dict(m: dict, e: dict) -> dict:
    """The market dict the ticket board passes to classify (live.ticket_rows)."""
    return dict(m, event_title=e.get("title"), event_id=e.get("id"))


def answer(c: dict) -> dict:
    f = c.get("fields") or {}
    t = c["type"]
    d = f.get("window_end") if t in TICKETS else f.get("date") if t == "ladder_rung" else None
    return {"type": t, "linkable": bool(c.get("linkable")), "reasons": list(c.get("reasons") or []),
            "underlying": f.get("underlying") if t in TICKETS else None, "level": f.get("level") if t in TICKETS else None,
            "direction": f.get("direction") if t in TICKETS else None, "date": d, "year_source": f.get("year_source")}


def classify_q(q: dict) -> dict:
    m = {k: q.get(k) for k in MARKET_KEEP}
    return answer(lm.classify(q.get("question") or "", q.get("description"), ticket_dict(m, {"title": q.get("event_title"), "id": q.get("event_id")})))


def board_markets(e: dict) -> list[dict]:
    """The markets the ladder board passes to link_ladders (live._rung_market); a closed event's markets are all closed."""
    return [m for m in e["markets"] if (m.get("volume") or 0) >= MIN_RUNG_VOLUME
            and (e.get("closed") or (not m.get("closed") and m.get("acceptingOrders") is not False))]


def pair_verdict(a: dict, b: dict, ev: dict) -> dict:
    """The code's verdict on one rung pair (earlier a, later b), re-run on the two markets alone."""
    for lad in lm.link_ladders([a, b], ev):
        for p in lad["pairs"]:
            if {p["rich"], p["cheap"]} == {str(a["id"]), str(b["id"])}:
                return {"nested": bool(p["nested"]), "reasons": p["reasons"], "rich": p["rich"], "rich_date": p["rich_date"],
                        "cheap_date": p["cheap_date"]}
    return {"nested": False, "reasons": ["not linked as one ladder pair"], "rich": str(a["id"]), "rich_date": None, "cheap_date": None}


def sha256s() -> dict:
    return {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in PARSER_FILES.items()}


# ------------------------------------------------------------------------------------------------ the sample

def draw(cands: list[dict], n: int, cycle: list[tuple], key, rng: random.Random, cap: int = PER_EVENT) -> list[dict]:
    """Up to n candidates, buckets visited in `cycle` order (a bucket is key(c)), at most `cap` per event."""
    rng.shuffle(cands)
    buckets: dict[tuple, list[dict]] = {}
    for c in cands:
        buckets.setdefault(key(c), []).append(c)
    per_ev: Counter = Counter()
    out: list[dict] = []
    while len(out) < n and any(buckets.get(k) for k in set(cycle)):
        for k in cycle:
            b = buckets.get(k) or []
            while b:
                c = b.pop(0)
                if per_ev[c["event_id"]] < cap:
                    per_ev[c["event_id"]] += 1
                    out.append(c)
                    break
            if len(out) >= n:
                break
    return out


def q_record(m: dict, e: dict) -> dict:
    return {**{k: m.get(k) for k in MARKET_KEEP}, "event_id": e["id"], "event_slug": e.get("slug"), "event_title": e.get("title"),
            "event_resolutionSource": e.get("resolutionSource") or "", "event_closed": bool(e.get("closed"))}


def build_sample(events: list[dict]) -> tuple[dict, dict]:
    rng = random.Random(SEED)
    qs, preds = [], {}
    for e in events:
        for m in e["markets"]:
            if not m.get("question"):
                continue
            r = q_record(m, e)
            preds[r["id"]] = answer(lm.classify(m["question"], m.get("description"), ticket_dict(m, e)))
            qs.append(r)
    seen: set[str] = set()
    qs = [q for q in qs if not (q["id"] in seen or seen.add(q["id"]))]
    typed_events = {q["event_id"] for q in qs if preds[q["id"]]["type"] != "other"}
    sampled: list[dict] = []
    for s in STRATA:
        cands = [q for q in qs if preds[q["id"]]["type"] == s]
        if s == "other":
            cyc = [(True, False), (True, True)] * 3 + [(False, False), (False, True)]
            key = lambda q: (q["event_id"] in typed_events or bool(PRICEY.search(q["question"])), bool(q["closed"]))
        else:
            cyc = [(True, False), (True, True), (False, False), (False, True)]
            key = lambda q: (not YEAR.search(q["question"]), bool(q["closed"]))
        for i, q in enumerate(draw(cands, PER_TYPE, cyc, key, rng)):
            sampled.append({**q, "stratum": s, "half": "AB"[i % 2], "year_written": bool(YEAR.search(q["question"]))})
    # rung pairs from the ladder board's ladders
    by_ev = {e["id"]: e for e in events}
    pool = []
    for e in events:
        ms = board_markets(e)
        if len(ms) < 2:
            continue
        byid = {m["id"]: m for m in ms}
        for lad in lm.link_ladders(ms, e):
            for p in lad["pairs"]:
                pool.append({"event_id": e["id"], "earlier": byid[p["rich"]], "later": byid[p["cheap"]], "nested": p["nested"],
                             "reasons": p["reasons"], "rich_date": p["rich_date"], "cheap_date": p["cheap_date"]})
    n_tot = 2 * PAIRS_PER_HALF
    per_ev: Counter = Counter()
    picked = {True: [], False: []}
    for want, target in ((False, n_tot // 4), (True, n_tot - n_tot // 4)):
        c = [p for p in pool if p["nested"] == want]
        rng.shuffle(c)
        for p in c:
            if len(picked[want]) >= target:
                break
            if per_ev[p["event_id"]] < PAIRS_PER_EVENT:
                per_ev[p["event_id"]] += 1
                picked[want].append(p)
    pairs = []
    for want in (True, False):
        for i, p in enumerate(picked[want]):
            pairs.append({**p, "stratum": "nested" if want else "not_nested", "half": "AB"[i % 2]})
    # ids: shuffled per half so that the order shows no stratum
    k = 0
    for h in "AB":
        hp = [p for p in pairs if p["half"] == h]
        random.Random(SEED).shuffle(hp)
        for p in hp:
            k += 1
            p["pair"] = f"p{k:03d}"
    pairs.sort(key=lambda p: p["pair"])
    pair_preds = {p["pair"]: {"nested": p["nested"], "reasons": p["reasons"], "rich_date": p["rich_date"], "cheap_date": p["cheap_date"]}
                  for p in pairs}
    uni_pairs = [{"pair": p["pair"], "half": p["half"], "stratum": p["stratum"], "event_id": p["event_id"],
                  "event_slug": by_ev[p["event_id"]].get("slug"), "event_title": by_ev[p["event_id"]].get("title"),
                  "event_resolutionSource": by_ev[p["event_id"]].get("resolutionSource") or "",
                  "earlier": p["earlier"], "later": p["later"]} for p in pairs]
    counts = {"events_read": len(events), "markets_read": len(qs),
              "parser_types_all": dict(Counter(preds[q["id"]]["type"] for q in qs)),
              "questions": {s: {h: sum(1 for q in sampled if q["stratum"] == s and q["half"] == h) for h in "AB"} for s in STRATA},
              "closed_questions": {s: sum(1 for q in sampled if q["stratum"] == s and q["closed"]) for s in STRATA},
              "year_not_written": {s: sum(1 for q in sampled if q["stratum"] == s and not q["year_written"]) for s in STRATA},
              "pairs": {st: {h: sum(1 for p in uni_pairs if p["stratum"] == st and p["half"] == h) for h in "AB"} for st in ("nested", "not_nested")},
              "pair_pool": {"nested": sum(p["nested"] for p in pool), "not_nested": sum(not p["nested"] for p in pool)}}
    universe = {"plan": "linker/contract_eval/PLAN.md", "seed": SEED, "built": AS_OF.isoformat(), "counts": counts,
                "questions": sampled, "pairs": uni_pairs}
    predictions = {"sha256": sha256s(), "questions": {q["id"]: preds[q["id"]] for q in sampled}, "pairs": pair_preds}
    return universe, predictions


def _day(s) -> str:
    return str(s or "")[:10]


def field_item(q: dict) -> dict:
    return {"id": q["id"], "question": q["question"], "event_title": q.get("event_title") or "",
            "rules": (q.get("description") or "")[:RULES_CUT], "created": _day(q.get("createdAt") or q.get("startDate"))}


def pair_side(m: dict, ev_src: str) -> dict:
    return {"question": m.get("question") or "", "rules": m.get("description") or "",
            "resolution_source": m.get("resolutionSource") or ev_src or "", "created": _day(m.get("createdAt") or m.get("startDate"))}


def build_inputs(universe: dict) -> dict[str, dict]:
    fields_text, pairs_text = (PROMPTS / "contract_fields.md").read_text(), (PROMPTS / "contract_pairs.md").read_text()
    out: dict[str, dict] = {}
    for h in "AB":
        items = [field_item(q) for q in universe["questions"] if q["half"] == h]
        random.Random(SEED).shuffle(items)
        cut = (len(items) + 1) // 2
        out[f"input_fields_{h}1.json"] = {"instructions": fields_text, "questions": items[:cut]}
        out[f"input_fields_{h}2.json"] = {"instructions": fields_text, "questions": items[cut:]}
        ps = [{"pair": p["pair"], "earlier": pair_side(p["earlier"], p["event_resolutionSource"]),
               "later": pair_side(p["later"], p["event_resolutionSource"])} for p in universe["pairs"] if p["half"] == h]
        out[f"input_pairs_{h}.json"] = {"instructions": pairs_text, "pairs": ps}
    return out


def leaks(inp: dict) -> list[str]:
    """Parser, stratum or half keys found in an input file's items (must be empty)."""
    bad = []
    for it in inp.get("questions", []) + inp.get("pairs", []):
        for side in (it, it.get("earlier") or {}, it.get("later") or {}):
            bad += [k for k in side if k in PARSER_KEYS]
    return bad


def _dump(f: Path, obj) -> int:
    f.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    return f.stat().st_size


def sample(refresh: bool = False) -> int:
    events, log = load_events(refresh)
    universe, predictions = build_sample(events)
    universe["fetch"] = {"requests": log["requests"], "pages": len(log["pages"]),
                         "errors": sum("error" in p for p in log["pages"])}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _dump(OUT_DIR / "universe.json", universe)
    _dump(OUT_DIR / "predictions.json", predictions)
    print(json.dumps({"fetch": universe["fetch"], **universe["counts"]}, indent=1))
    for name, inp in build_inputs(universe).items():
        assert not leaks(inp), f"{name} holds parser fields"
        size = _dump(OUT_DIR / name, inp)
        print(f"{name}: {len(inp.get('questions') or inp.get('pairs'))} items, {size / 1024:.0f} KB")
    for q in random.Random(SEED + 1).sample(universe["questions"], min(5, len(universe["questions"]))):
        print("example:", q["question"][:110])
    return 0


# ------------------------------------------------------------------------------------------------ scoring

class FileFault(Exception):
    pass


def read_labels(f: Path, ids: list[str], key: str) -> dict[str, dict]:
    """A labeller file's answers by item id; FileFault when it is missing, not JSON or leaves an item unanswered."""
    if not f.exists():
        raise FileFault(f"{f.name}: missing")
    try:
        d = json.loads(f.read_text())
        ans = {str(a[key]): a for a in d["answers"]}
    except Exception as e:                             # noqa: BLE001
        raise FileFault(f"{f.name}: not valid JSON in the prompt's format ({type(e).__name__})") from None
    miss = [i for i in ids if i not in ans]
    if miss:
        raise FileFault(f"{f.name}: {len(miss)} item(s) unanswered, first {miss[0]}")
    bad = [i for i in ids if key == "id" and ans[i].get("type") not in lm.TYPES]
    if bad:
        raise FileFault(f"{f.name}: {len(bad)} answer(s) without a valid type, first {bad[0]}")
    return ans


def _norm(field: str, v):
    if field == "underlying":
        return str(v or "").strip().upper()
    if field == "level":
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return None
    if field == "direction":
        d = str(v or "").strip().lower()
        return d if d in ("up", "down") else "none"
    if field in ("date", "earlier_date", "later_date"):
        return str(v or "")[:10]
    if field == "nested":
        return bool(v) if isinstance(v, bool) else None
    return v


def same(field: str, a, b) -> bool:
    a, b = _norm(field, a), _norm(field, b)
    if field == "level":
        return a is not None and b is not None and abs(a - b) <= 1e-6
    return a == b and a is not None


def truth_fields(a: dict, b: dict) -> tuple[dict, list[str]]:
    """What two labellers agree on, field by field, and the fields they disagree on. Ticket fields count only when both
    give the same ticket type; a rung's date only when both say rung."""
    t, dis = {}, []
    if a.get("type") != b.get("type"):
        return t, ["type"]
    t["type"] = a["type"]
    fields = ("underlying", "level", "direction", "date") if t["type"] in TICKETS else ("date",) if t["type"] == "ladder_rung" else ()
    for f in fields:
        if same(f, a.get(f), b.get(f)):
            t[f] = _norm(f, a.get(f))
        else:
            dis.append(f)
    return t, dis


def truth_pair(a: dict, b: dict) -> tuple[dict, list[str]]:
    t, dis = {}, []
    for f in ("nested", "earlier_date", "later_date"):
        if same(f, a.get(f), b.get(f)):
            t[f] = _norm(f, a.get(f))
        else:
            dis.append(f)
    return t, dis


def rate(k: int, n: int) -> dict:
    lo, hi = binom_ci(k, n)
    return {"k": k, "n": n, "share": (k / n) if n else None, "interval_95_exact": [lo, hi] if n else None}


def bar(k: int, n: int, at: float = 0.95) -> dict:
    return {**rate(k, n), "bar": at, "result": ("pass" if k / n >= at else "fail") if n else "no data"}


DATE_RULES = ("end session", "calendar day")                          # PLAN Amendment 1; "calendar day" as first written
FAIL_CAUSES = (("type differs", "type"), ("ticker", "underlying"), ("level", "level"), ("direction", "direction"), ("date", "date"))


def field_ok(f: str, parser, truth) -> bool:
    return same(f, parser, truth)


def end_session(v) -> str | None:
    """The last weekday on or before a date (the session the option link uses, link_map end_session); None if unreadable."""
    try:
        return last_weekday(date.fromisoformat(str(v or "")[:10])).isoformat()
    except ValueError:
        return None


def ticket_field_ok(f: str, parser, truth, date_rule: str = "end session") -> bool:
    """A ticket field against the truth. Under "end session" (Amendment 1) a ticket's date is compared on the last
    weekday on or before each side; under "calendar day" as first written. Rung and pair dates never come here."""
    if f == "date" and date_rule == "end session":
        a, b = end_session(parser), end_session(truth)
        return a is not None and a == b
    return field_ok(f, parser, truth)


def measures(uni: dict, preds: dict, pair_preds: dict, lab_q: tuple[dict, dict], lab_p: tuple[dict, dict],
             date_rule: str = "end session") -> tuple[dict, list[dict]]:
    """Every measure of PLAN section 3 on one half. `preds` and `pair_preds`: the parser's answers by id (re-run).
    `date_rule` sets how a ticket's date is compared (DATE_RULES); rung and pair dates are always compared exactly."""
    assert date_rule in DATE_RULES, date_rule
    tok = lambda f, a, b: ticket_field_ok(f, a, b, date_rule)
    errors: list[dict] = []
    truth, dis_counts, agree = {}, Counter(), Counter()
    qs = uni["questions"]
    for q in qs:
        t, dis = truth_fields(lab_q[0][q["id"]], lab_q[1][q["id"]])
        truth[q["id"]] = t
        dis_counts.update(dis)
    # agreement rate per field
    a_rate = {"type": rate(sum("type" in truth[q["id"]] for q in qs), len(qs))}
    for f in ("underlying", "level", "direction", "date"):
        base = [q for q in qs if truth[q["id"]].get("type") in TICKETS]
        a_rate[f"ticket_{f}"] = rate(sum(f in truth[q["id"]] for q in base), len(base))
    base = [q for q in qs if truth[q["id"]].get("type") == "ladder_rung"]
    a_rate["rung_date"] = rate(sum("date" in truth[q["id"]] for q in base), len(base))
    # type table, precision, recall
    typed = [q for q in qs if "type" in truth[q["id"]]]
    table = {pt: {tt: sum(1 for q in typed if preds[q["id"]]["type"] == pt and truth[q["id"]]["type"] == tt) for tt in lm.TYPES} for pt in lm.TYPES}
    prec = {t: rate(table[t][t], sum(table[t].values())) for t in lm.TYPES}
    rec = {t: rate(table[t][t], sum(table[p][t] for p in lm.TYPES)) for t in lm.TYPES}
    rec_w = weighted_recall(typed, preds, truth, uni.get("counts") or {})
    for q in typed:
        p, t = preds[q["id"]], truth[q["id"]]
        if p["type"] != t["type"]:
            errors.append(_err(q["id"], q["question"], "type", p["type"], t["type"], p))
    # bar 1: exact ticket links. A link is wrong as soon as the agreed type or any agreed field differs from the parser;
    # it leaves the bar only when everything agreed matches and some field is undecided (a disagreement drops the field,
    # never a link already shown wrong).
    k = n = 0
    excluded, causes, type_differs = Counter(), Counter(), []
    for q in qs:
        p, t = preds[q["id"]], truth[q["id"]]
        if p["type"] not in TICKETS or not p["linkable"]:
            continue
        if "type" not in t:
            excluded["type disagreement"] += 1
            continue
        wrong = [] if t["type"] != p["type"] else [f for f in TICKET_FIELDS if f in t and not tok(f, p[f], t[f])]
        errors += [_err(q["id"], q["question"], f, p[f], t[f], p) for f in wrong]
        if t["type"] == p["type"] and not wrong and any(f not in t for f in TICKET_FIELDS):
            excluded["field disagreement, every agreed field matches"] += 1
            continue
        n += 1
        k += t["type"] == p["type"] and not wrong
        if t["type"] != p["type"]:                     # each failure once, under the first cause of FAIL_CAUSES
            causes["type differs"] += 1
            type_differs.append({"id": q["id"], "question": q["question"], "parser_type": p["type"],
                                 "parser_ticker": p["underlying"], "truth_type": t["type"]})
        elif wrong:
            causes[next(c for c, f in FAIL_CAUSES if f in wrong)] += 1
    bar1 = {**bar(k, n), "date_rule": date_rule, "excluded": dict(excluded),
            "failures_by_first_cause": {c: causes[c] for c, _ in FAIL_CAUSES},
            "type_differs": type_differs}
    # bar 2: rung dates
    both = [q for q in qs if preds[q["id"]]["type"] == "ladder_rung" and truth[q["id"]].get("type") == "ladder_rung"]
    with_date = [q for q in both if "date" in truth[q["id"]]]
    k2 = 0
    for q in with_date:
        p, t = preds[q["id"]], truth[q["id"]]
        if field_ok("date", p["date"], t["date"]):
            k2 += 1
        else:
            errors.append(_err(q["id"], q["question"], "date", p["date"], t["date"], p))
    bar2 = {**bar(k2, len(with_date)), "excluded": {"date disagreement": len(both) - len(with_date)}}
    # each ticket field among questions both labellers call a ticket of that type
    field_acc = {}
    for tt in TICKETS:
        base = [q for q in qs if truth[q["id"]].get("type") == tt]
        field_acc[tt] = {"questions": len(base), "parser_other_type": sum(preds[q["id"]]["type"] != tt for q in base)}
        for f in ("underlying", "level", "direction", "date"):
            b = [q for q in base if f in truth[q["id"]]]
            field_acc[tt][f] = rate(sum(preds[q["id"]]["type"] == tt and tok(f, preds[q["id"]][f], truth[q["id"]][f]) for q in b), len(b))
    # tickets the parser refuses to link
    refused = [q for q in qs if preds[q["id"]]["type"] in TICKETS and not preds[q["id"]]["linkable"]]
    readable = [q for q in refused if _readable(truth[q["id"]])]
    refusals = {"tickets": len(refused), "by_reason": dict(Counter(r for q in refused for r in preds[q["id"]]["reasons"])),
                "labellers_read_in_full": len(readable), "read_in_full_ids": [q["id"] for q in readable]}
    # pairs
    pairs = uni["pairs"]
    pt, pdis = {}, Counter()
    for p in pairs:
        t, dis = truth_pair(lab_p[0][p["pair"]], lab_p[1][p["pair"]])
        pt[p["pair"]] = t
        pdis.update(dis)
    for f in ("nested", "earlier_date", "later_date"):
        a_rate[f"pair_{f}"] = rate(sum(f in pt[p["pair"]] for p in pairs), len(pairs))
    code_nested = [p for p in pairs if pair_preds[p["pair"]]["nested"] and "nested" in pt[p["pair"]]]
    k3 = sum(pt[p["pair"]]["nested"] for p in code_nested)
    bar3 = {**bar(k3, len(code_nested)), "excluded": {"nested disagreement": sum(pair_preds[p["pair"]]["nested"] and "nested" not in pt[p["pair"]] for p in pairs)}}
    missed = [p for p in pairs if not pair_preds[p["pair"]]["nested"] and pt[p["pair"]].get("nested") is True]
    truly = [p for p in pairs if pt[p["pair"]].get("nested") is True]
    for p in pairs:
        pp, t = pair_preds[p["pair"]], pt[p["pair"]]
        q = f"{p['earlier']['question']} || {p['later']['question']}"
        if "nested" in t and pp["nested"] != t["nested"]:
            errors.append(_err(p["pair"], q, "nested", pp["nested"], t["nested"], pp))
        for f, pf in (("earlier_date", "rich_date"), ("later_date", "cheap_date")):
            if f in t and not field_ok("date", pp[pf], t[f]):
                errors.append(_err(p["pair"], q, f, pp[pf], t[f], pp))
    pair_dates = {f: rate(sum(field_ok("date", pair_preds[p["pair"]][pf], pt[p["pair"]][f]) for p in pairs if f in pt[p["pair"]]),
                          sum(f in pt[p["pair"]] for p in pairs)) for f, pf in (("earlier_date", "rich_date"), ("later_date", "cheap_date"))}
    out = {"date_rule": date_rule, "bars": {"exact_ticket_links": bar1, "rung_dates": bar2, "nested_pairs": bar3},
           "type_table_parser_rows_truth_columns": table, "precision": prec, "recall_within_sample": rec,
           "recall_weighted_by_stratum": rec_w, "ticket_field_accuracy": field_acc,
           "refused_tickets": refusals,
           "nested_pairs_missed": {**rate(len(missed), len(truly)), "pairs": [{"pair": p["pair"], "reasons": pair_preds[p["pair"]]["reasons"]} for p in missed]},
           "pair_date_accuracy": pair_dates, "labeller_agreement": a_rate,
           "disagreements_dropped": {"questions": dict(dis_counts), "pairs": dict(pdis)},
           "questions": len(qs), "pairs": len(pairs), "errors": len(errors)}
    return out, errors


def weighted_recall(typed: list[dict], preds: dict, truth: dict, counts: dict) -> dict:
    """Recall per type with each sampled question weighted by its stratum's size over the stratum's sample in this half
    (counts.parser_types_all / counts.questions[stratum][half]). The strata are the parser's types at step 1, so this
    is the recall in the fetched listing, not in the sample. No exact interval: the counts are weighted."""
    N, sampled = counts.get("parser_types_all") or {}, counts.get("questions") or {}
    note = ("weights: stratum size / sampled in this half. Within a stratum the draw favoured some questions (price-like "
            "and same-event ones for 'other', no written year for the rest), so this is an approximate population figure.")
    def w(q):
        s, h = q.get("stratum"), q.get("half")
        n = (sampled.get(s) or {}).get(h) or 0
        return N.get(s, 0) / n if n else None
    ws = {q["id"]: w(q) for q in typed}
    if not typed or any(v is None for v in ws.values()):
        return {"note": "no stratum weights for these questions", "by_type": None}
    out = {}
    for t in lm.TYPES:
        den = sum(ws[q["id"]] for q in typed if truth[q["id"]]["type"] == t)
        num = sum(ws[q["id"]] for q in typed if truth[q["id"]]["type"] == t and preds[q["id"]]["type"] == t)
        out[t] = {"weighted_hits": round(num, 3), "weighted_truth": round(den, 3), "share": num / den if den else None,
                  "questions": sum(truth[q["id"]]["type"] == t for q in typed)}
    return {"note": note, "by_type": out}


def _readable(t: dict) -> bool:
    return (t.get("type") in TICKETS and bool(t.get("underlying")) and (t.get("level") or 0) > 0
            and t.get("direction") in ("up", "down") and bool(t.get("date")))


def _err(i: str, q: str, field: str, pv, tv, p: dict) -> dict:
    return {"id": i, "question": q, "field": field, "parser": pv, "truth": tv, "parser_reasons": "; ".join(p.get("reasons") or [])}


def score(half: str, tag: str | None = None, root: Path = OUT_DIR, results: Path = RESULTS, use_stored: bool = False,
          strict_dates: bool = False) -> int:
    """Score one half. A ticket's date is compared on its end session (PLAN Amendment 1); `strict_dates` gives the rule
    as first written (calendar day) and appends "_strictdates" to the file names."""
    date_rule = "calendar day" if strict_dates else "end session"
    uni = json.loads((root / "universe.json").read_text())
    uni = {**uni, "questions": [q for q in uni["questions"] if q["half"] == half], "pairs": [p for p in uni["pairs"] if p["half"] == half]}
    inputs = {c: json.loads((root / f"input_fields_{half}{c}.json").read_text())["questions"] for c in "12"}
    faults, lab_q, lab_p = [], [{}, {}], [{}, {}]
    for j, lab in enumerate(("L1", "L2")):
        for c in "12":
            try:
                lab_q[j].update(read_labels(root / f"labels_fields_{lab}_{half}{c}.json", [x["id"] for x in inputs[c]], "id"))
            except FileFault as e:
                faults.append(str(e))
        try:
            lab_p[j] = read_labels(root / f"labels_pairs_{lab}_{half}.json", [p["pair"] for p in uni["pairs"]], "pair")
        except FileFault as e:
            faults.append(str(e))
    if faults:
        print(json.dumps({"half": half, "scored": False, "file_faults": faults}, indent=1))
        return 2
    preds = {q["id"]: classify_q(q) for q in uni["questions"]}
    pair_preds = {p["pair"]: pair_verdict(p["earlier"], p["later"], {"id": p["event_id"], "slug": p.get("event_slug"),
                                                                     "title": p.get("event_title"), "resolutionSource": p.get("event_resolutionSource")})
                  for p in uni["pairs"]}
    stored = json.loads((root / "predictions.json").read_text())
    changed = {"questions": sum(preds[i] != stored["questions"].get(i) for i in preds),
               "pairs": sum(pair_preds[i]["nested"] != stored["pairs"].get(i, {}).get("nested") for i in pair_preds)}
    runs = [("", "parser on disk at scoring time", preds, pair_preds, sha256s())]
    if use_stored:                                     # PLAN section 4: the parser as it stood at step 1, from predictions.json
        sq, sp = stored["questions"], stored["pairs"]
        missing = [i for i in preds if i not in sq] + [i for i in pair_preds if i not in sp]
        if missing:
            print(json.dumps({"half": half, "scored": False, "stored_answers_missing": missing[:20]}, indent=1))
            return 2
        runs.append(("stepone", "parser at step 1 (stored predictions.json)", {i: sq[i] for i in preds},
                     {i: sp[i] for i in pair_preds}, stored["sha256"]))
    results.mkdir(parents=True, exist_ok=True)
    summary = []
    for label, what, qp, pp, sha in runs:
        out, errors = measures(uni, qp, pp, tuple(lab_q), tuple(lab_p), date_rule)
        out = {"half": half, "tag": tag, "parser": what, "plan": "linker/contract_eval/PLAN.md", "sha256_of_parser_scored": sha,
               "sha256_at_scoring": sha256s(), "sha256_at_sample": stored["sha256"], "parser_changed_answers": changed, **out}
        stem = f"contract_eval_{half}" + (f"_{label}" if label else "") + (f"_{tag}" if tag else "") + ("_strictdates" if strict_dates else "")
        (results / f"{stem}.json").write_text(json.dumps(out, indent=1))
        with open(results / f"{stem}_errors.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "question", "field", "parser", "truth", "parser_reasons"])
            w.writeheader()
            w.writerows(errors)
        summary.append({"parser": what, "date_rule": date_rule, "bars": {k: {x: v[x] for x in ("k", "n", "share", "result")} for k, v in out["bars"].items()},
                        "errors": len(errors), "written": str(results / f"{stem}.json")})
    print(json.dumps({"half": half, "parser_changed_answers": changed, "scores": summary}, indent=1))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m linker.contract_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--refresh", action="store_true")
    c = sub.add_parser("score")
    c.add_argument("--half", choices=("A", "B"), required=True)
    c.add_argument("--tag")
    c.add_argument("--stored", action="store_true", help="also score the step-1 answers in predictions.json (_stepone)")
    c.add_argument("--strict-dates", action="store_true",
                   help="compare ticket dates by calendar day, the rule as first written (_strictdates)")
    a = ap.parse_args(argv)
    return sample(a.refresh) if a.cmd == "sample" else score(a.half, a.tag, use_stored=a.stored, strict_dates=a.strict_dates)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
