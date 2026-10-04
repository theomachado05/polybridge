"""Event rosters, clusters, ladders, the main market, the fresh held-out set and the labellers' input files
(linker/heldout2/PLAN.md sections 1, 2.1, 6 and 9). Names, dates and volumes only: no price field is kept, printed or cached.

1. Every test market's Polymarket event is read from Gamma; per market only id, question, volume, start, end (closing
   time, else scheduled end: used for pulls and the 20-session life test), deadline (Gamma's scheduled endDate only),
   closed and token are kept (a whitelist; stripped rosters are cached gzipped in `linker/.cache/gamma/<slug>.json.gz`).
2. Markets are merged into clusters: the same event slug, or the same ladder stem (the question with its deadline and
   threshold replaced by placeholders) across slugs, where only a cumulative deadline ("by", "before", "end of") merges.
3. Each cluster gets a structure (single, ladder, multi_outcome, mixed), a main market and a seen_ladder flag.
4. Input files: version 3 (questions with id, question, volume_musd, start, deadline, main; never the closing time),
   the control arm (by event slug) and the recall check (PLAN section 9), each with its instructions embedded.

Run from `research/`:
    python -m linker.events universe dev|fresh     # writes linker/dev/universe.json or linker/heldout2/universe.json
    python -m linker.events inputs dev|fresh       # writes input_v3_*, input_control_*, input_recall_* next to it
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pandas as pd

from polybridge_research.calendar import TradingCalendar
from s1_twin_spread import data as ds
from s5_big_moves import config as c5
from s5_big_moves.universe import sessions_alive

from . import store

HERE = Path(__file__).resolve().parent
STUDIES = {"dev": HERE / "dev", "fresh": HERE / "heldout2"}
CANDIDATES = HERE.parent / "s5_big_moves" / "candidates.json"
AI_MAP = HERE.parents[1] / "backend" / "app" / "data" / "ai_map.json"
INSTRUMENTS = HERE / "instruments.json"
PROMPTS = HERE / "prompts"
GAMMA_CACHE = store.NEW / "gamma"
SEEN_RANKS = 360                 # ranks 1..360 of candidates.json: S5 and the first held-out test
DEV_SEEN_RANKS = 240             # the dev set is ranks 241..360, so its seen ladders are S5's
PROBE_MARKET = "601826"          # "Will Flavio Bolsonaro win the 2026 Brazilian presidential election?"
MIN_SESSIONS, SIBLING_MIN_VOLUME, MAX_SHOWN = 20, 100_000.0, 14
LADDER_SHARE = 0.25
CHUNKS = {"dev": 2, "fresh": 3}
RECALL_CHUNKS = 2
MARKET_KEEP = ("id", "question", "volume", "start", "end", "deadline", "closed", "token")

MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
DAYS = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
YEAR = r"(?:19|20)\d\d"
ORD = r"\d{1,2}(?:st|nd|rd|th)?"
DATE = (rf"(?:(?:early|mid|late)[- ]?)?(?:(?:{MONTHS})\.?(?:\s+{ORD})?(?:,?\s+{YEAR})?|{ORD}\s+(?:of\s+)?(?:{MONTHS})(?:,?\s+{YEAR})?"
        rf"|{YEAR}-\d\d-\d\d|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|q[1-4](?:\s+{YEAR})?|(?:h[12]|[1-4]q)\s+{YEAR}|{YEAR}|{DAYS}"
        r"|this\s+(?:year|month|week|quarter)|next\s+(?:year|month|week)|year[- ]end)")
END_OF = r"(?:the\s+)?end\s+of\s+(?:the\s+)?(?:year|month|week|quarter|" + DATE + ")"
DEADLINE = re.compile(rf"\b(by|before|on|in|until|till|through|thru|end of)\s+(?:the\s+)?(?:{END_OF}|{DATE})(?![\w])|\b{END_OF}(?![\w])"
                      rf"|\b{YEAR}-\d\d-\d\d\b")
NUMBER = re.compile(r"(?<![\w.\-])(-)?([$€£])?(\d[\d,]*(?:\.\d+)?)(\s*(?:k|m|b|t|bn|mn|million|billion|trillion)\b)?"
                    r"(\+)?(\s*(?:%|percent\b|bps\b|bp\b|basis points\b))?(\+)?")


def _stem(question: str, keep_windows: bool) -> str:
    q = unicodedata.normalize("NFKD", question).encode("ascii", "ignore").decode().lower()
    q = q.replace("’", "'").strip().rstrip("?").strip()
    windows: list[str] = []

    def date(m: re.Match) -> str:
        if keep_windows and m.group(1) in ("in", "on") and "end of" not in m.group(0):
            windows.append(m.group(0))
            return f"<w{len(windows) - 1}>"
        return "<date>"

    q = DEADLINE.sub(date, q)

    def num(m: re.Match) -> str:
        sign, cur, digits, scale, plus1, unit, plus2 = m.groups()
        plus = plus1 or plus2
        if not (sign or cur or scale or unit or plus) and re.fullmatch(YEAR, digits):
            return m.group(0)                      # a year outside a deadline phrase names the event ("2026 election")
        u = (unit or "").strip()
        tag = "<usd>" if cur else "<pct>" if u in ("%", "percent") else "<bp>" if u else "<n>"
        return tag + ("+" if plus else "")

    q = NUMBER.sub(num, q)
    q = re.sub(r"<w(\d+)>", lambda m: windows[int(m.group(1))], q)
    return re.sub(r"\s+", " ", q).strip(" ,.")


def stem(question: str) -> str:
    """The ladder stem: the question with deadlines and numeric thresholds replaced by placeholders."""
    return _stem(question, False)


def merge_key(question: str) -> str:
    """The stem that joins markets across event slugs: a window ("in 2025", "in March", "on June 30") is kept as written,
    so only cumulative deadlines ("by", "before", "until", "end of") merge, and a count in 2025 stays apart from 2026."""
    return _stem(question, True)


@lru_cache(maxsize=1)
def _cal() -> TradingCalendar:
    return TradingCalendar("2025-01-01", "2027-12-31")


def alive(m: dict) -> int:
    """Trading sessions of the market's life inside S5's window."""
    if not m.get("start") or not m.get("end"):
        return 0
    return sessions_alive(str(m["start"]), str(m["end"]).replace(" ", "T"), _cal())


def _life_days(m: dict) -> float:
    try:
        return (pd.Timestamp(str(m["end"])[:10]) - pd.Timestamp(str(m["start"])[:10])).days
    except (KeyError, ValueError, TypeError):
        return 0.0


MONTH_DAY = re.compile(rf"\b({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+({YEAR}))?")
END_MONTH = re.compile(rf"\bend\s+of\s+(?:the\s+)?({MONTHS})\b(?:,?\s+({YEAR}))?")
IN_YEAR = re.compile(rf"\b(by|in|before|during|through)\s+(?:the\s+end\s+of\s+)?({YEAR})\b")


def _scheduled(m: dict) -> str:
    """Gamma's scheduled end date (never the closing time); the end only for a record that lacks it."""
    return str(m.get("deadline") or m.get("end") or "")[:10]


def deadline(m: dict) -> str:
    """The rung's deadline as YYYY-MM-DD: the one written in the question when there is one, else the scheduled end
    date. Never the closing time, which would give away an early resolution."""
    end = pd.Timestamp(_scheduled(m))
    q = unicodedata.normalize("NFKD", m["question"]).encode("ascii", "ignore").decode().lower()
    d = None
    if (x := MONTH_DAY.search(q)):
        try:
            d = pd.Timestamp(f"{x.group(3) or end.year}-{x.group(1)[:3]}-{x.group(2)}")
        except ValueError:
            d = None
    elif (x := END_MONTH.search(q)):
        d = pd.Timestamp(f"{x.group(2) or end.year}-{x.group(1)[:3]}-01") + pd.offsets.MonthEnd(0)
    elif (x := IN_YEAR.search(q)):
        y = int(x.group(2)) - (x.group(1) == "before")
        return f"{y}-12-31"
    if d is None:
        return str(end.date())
    if not (x and x.lastindex and x.group(x.lastindex) and re.fullmatch(YEAR, x.group(x.lastindex))) and (d - end).days > 300:
        d = d - pd.DateOffset(years=1)
    return str(d.date())


# ---------------------------------------------------------------------------------------------------- Gamma rosters

def _strip_market(m: dict, slug: str, event_end: str | None = None) -> dict:
    tokens = m.get("clobTokenIds")
    tokens = json.loads(tokens) if isinstance(tokens, str) else (tokens or [])
    return {"id": f"polymarket:{m.get('id')}", "question": m.get("question") or "", "volume": float(m.get("volumeNum") or m.get("volume") or 0),
            "start": m.get("startDate") or m.get("createdAt"), "end": str(m.get("closedTime") or m.get("endDate") or "") or None,
            "deadline": str(m.get("endDate") or m.get("endDateIso") or event_end or "") or None, "closed": bool(m.get("closed")), "token": tokens[0] if tokens else None, "event": slug}


def strip_event(ev: dict) -> dict:
    """Keep the event's slug, title, tag labels and per market only MARKET_KEEP (a whitelist: every price field goes).
    A closed market that lost its own endDate takes the event's scheduled endDate (never umaEndDate or closedTime)."""
    slug = ev.get("slug") or ""
    return {"slug": slug, "title": ev.get("title") or "", "tags": [t.get("label") or "" for t in (ev.get("tags") or [])],
            "markets": [_strip_market(m, slug, ev.get("endDate")) for m in (ev.get("markets") or [])]}


def fetch_event(slug: str, throttle: ds.Throttle | None) -> dict | None:
    """The event's stripped roster, from the cache or Gamma (`/events/slug/<slug>`, then `/events?slug=`)."""
    f = GAMMA_CACHE / f"{slug}.json.gz"
    if f.exists():
        return json.loads(gzip.decompress(f.read_bytes()))
    ev = ds.get_json(f"{ds.GAMMA}/events/slug/{slug}", throttle=throttle, allow=(404, 422))
    if not isinstance(ev, dict) or "_status" in ev or not ev.get("markets"):
        lst = None
        for closed in (None, "true"):
            p = {"slug": slug} | ({"closed": closed} if closed else {})
            lst = ds.get_json(f"{ds.GAMMA}/events", p, throttle=throttle, allow=(404, 422))
            if isinstance(lst, list) and lst:
                break
        ev = lst[0] if isinstance(lst, list) and lst else None
    if not ev:
        return None
    out = strip_event(ev)
    GAMMA_CACHE.mkdir(parents=True, exist_ok=True)
    f.write_bytes(gzip.compress(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0))
    (GAMMA_CACHE / f"{slug}.json").unlink(missing_ok=True)       # the older roster format, without the scheduled deadline
    return out


def event_slug_of(market_id: str, throttle: ds.Throttle | None) -> str | None:
    """The event slug of one Polymarket market (Gamma `/markets?id=`); names only."""
    lst = ds.get_json(f"{ds.GAMMA}/markets", {"id": market_id}, throttle=throttle, allow=(404, 422))
    evs = (lst[0].get("events") or []) if isinstance(lst, list) and lst else []
    return evs[0].get("slug") if evs else None


# ---------------------------------------------------------------------------------------------------- clusters

def structure_of(markets: list[dict]) -> str:
    if len(markets) <= 1:
        return "single"
    n = Counter(stem(m["question"]) for m in markets)
    if len(n) == 1:
        return "ladder"
    return "mixed" if max(n.values()) > 1 else "multi_outcome"


def cluster(markets: list[dict]) -> list[dict]:
    """Union of same event slug and same merge_key. Returns [{"slugs", "structure", "markets"}], markets in input order."""
    parent = list(range(len(markets)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first: dict[tuple, int] = {}
    for i, m in enumerate(markets):
        for key in (("slug", m.get("event")), ("stem", merge_key(m["question"]))):
            if key[1] is None:
                continue
            if key in first:
                parent[find(i)] = find(first[key])
            else:
                first[key] = i
    groups: dict[int, list[dict]] = {}
    for i, m in enumerate(markets):
        groups.setdefault(find(i), []).append(m)
    out = []
    for ms in groups.values():
        slugs = list(dict.fromkeys(m.get("event") for m in ms if m.get("event")))
        out.append({"slugs": slugs, "structure": structure_of(ms), "markets": ms})
    return out


def main_market(cl: dict | list[dict]) -> str:
    """Among markets with at least 20 sessions of life in the window (else all): for a ladder the rung with the latest
    deadline (written in the question, else scheduled; never the closing time) among rungs with at least 25% of the
    largest rung's volume; otherwise the largest volume, then the longest life."""
    ms = cl["markets"] if isinstance(cl, dict) else cl
    st = cl.get("structure") if isinstance(cl, dict) else structure_of(ms)
    pool = [m for m in ms if alive(m) >= MIN_SESSIONS] or list(ms)
    if st == "ladder":
        top = max(m["volume"] for m in pool)
        rungs = [m for m in pool if m["volume"] >= LADDER_SHARE * top]
        return max(rungs, key=lambda m: (deadline(m), _scheduled(m), m["volume"], m["id"]))["id"]
    return max(pool, key=lambda m: (m["volume"], _life_days(m), m["id"]))["id"]


def seen_stems(ranks: int = SEEN_RANKS) -> set[str]:
    """Stems of candidates.json ranks 1..`ranks` and of every question in the product's map (ai_map.json)."""
    cands = json.loads(CANDIDATES.read_text())[:ranks]
    items = json.loads(AI_MAP.read_text())["items"].values()
    return {stem(m["question"]) for m in cands} | {stem(v["question"]) for v in items if v.get("question")}


# ---------------------------------------------------------------------------------------------------- universe

def _shown(ms: list[dict]) -> list[dict]:
    """All test markets, then non-test siblings with >= 20 sessions and >= $100k by volume, up to 14 in total."""
    test = sorted([m for m in ms if m["in_test"]], key=lambda m: -m["volume"])
    sib = sorted([m for m in ms if not m["in_test"] and alive(m) >= MIN_SESSIONS and m["volume"] >= SIBLING_MIN_VOLUME],
                 key=lambda m: (-m["volume"], m["id"]))
    return test + sib[: max(0, MAX_SHOWN - len(test))]


def _roster(test: list[dict], rosters: dict[str, dict | None]) -> list[dict]:
    """Every market of the test markets' events, test markets marked in_test (their own record kept)."""
    tid = {m["id"]: m for m in test}
    out, seen = [], set()
    for slug in dict.fromkeys(m["event"] for m in test):
        for m in (rosters.get(slug) or {}).get("markets", []):
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            base = tid.get(m["id"], m)
            out.append({**{k: base.get(k) for k in MARKET_KEEP}, "deadline": base.get("deadline") or m.get("deadline"),
                        "event": m.get("event") or slug, "in_test": m["id"] in tid})
    for m in test:
        if m["id"] not in seen:
            out.append({**{k: m.get(k) for k in MARKET_KEEP}, "event": m["event"], "in_test": True})
    return out


def assemble(test: list[dict], rosters: dict[str, dict | None], seen: set[str], probe: list[dict] | None = None) -> dict:
    """Clusters of the test markets' rosters, shown rosters, main markets, flags and cluster ids (by top volume)."""
    events = []
    for cl in cluster(_roster(test, rosters)):
        if not any(m["in_test"] for m in cl["markets"]):
            continue
        shown = _shown(cl["markets"])
        st = structure_of(shown)
        events.append({"slugs": list(dict.fromkeys(m["event"] for m in shown)), "structure": st,
                       "main": main_market({"structure": st, "markets": shown}),
                       "seen_ladder": any(stem(m["question"]) in seen for m in cl["markets"]), "probe": False, "markets": shown})
    if probe:
        shown = _shown([{**m, "in_test": False} for m in probe])
        st = structure_of(shown)
        events.append({"slugs": list(dict.fromkeys(m["event"] for m in shown)), "structure": st,
                       "main": main_market({"structure": st, "markets": shown}), "seen_ladder": False, "probe": True, "markets": shown})
    events.sort(key=lambda e: (-max(m["volume"] for m in e["markets"]), e["main"]))
    out = []
    for i, e in enumerate(events, 1):
        out.append({"cluster": f"c{i:03d}", **e})
    where = {m["id"]: e["cluster"] for e in out if not e["probe"] for m in e["markets"] if m["in_test"]}
    return {"events": out, "where": where}


def _fetch_all(slugs: list[str], pt: ds.Throttle) -> dict[str, dict | None]:
    out = {}
    for i, s in enumerate(slugs, 1):
        out[s] = fetch_event(s, pt)
        if i % 50 == 0:
            print(f"  rosters {i}/{len(slugs)}", flush=True)
    return out


def _counts(events: list[dict]) -> dict:
    ev = [e for e in events if not e["probe"]]
    return {"clusters": len(ev), "by_structure": dict(Counter(e["structure"] for e in ev)),
            "seen_ladder_clusters": sum(e["seen_ladder"] for e in ev), "probe_clusters": len(events) - len(ev),
            "questions_shown": sum(len(e["markets"]) for e in events)}


def build_universe(study: str, throttle: ds.Throttle | None = None) -> dict:
    pt = throttle or ds.Throttle(4.0)
    cands = json.loads(CANDIDATES.read_text())
    rank = {m["id"]: i for i, m in enumerate(cands, 1)}
    if study == "dev":
        test = json.loads((HERE / "heldout" / "universe.json").read_text())["markets"]
        rosters = _fetch_all(list(dict.fromkeys(m["event"] for m in test)), pt)
        built = assemble(test, rosters, seen_stems(DEV_SEEN_RANKS))
        rule = "the first held-out set (candidates.json ranks 241-360), with every market of their Polymarket events; a development run"
        counts = {"test_markets": len(test), "events": len(rosters), "events_not_found": sum(v is None for v in rosters.values())}
        probe_note = {}
    elif study == "fresh":
        seen_ev = {m["event"] for m in cands[:SEEN_RANKS]}
        rest = cands[SEEN_RANKS:]
        kept = [m for m in rest if m["event"] not in seen_ev]
        rosters = _fetch_all(list(dict.fromkeys(m["event"] for m in kept)), pt)
        ai_ids = set(json.loads(AI_MAP.read_text())["items"])
        bad = {s for s, r in rosters.items() if r and any(m["id"] in ai_ids for m in r["markets"])}
        test = [m for m in kept if m["event"] not in bad]
        rosters = {s: r for s, r in rosters.items() if s not in bad}
        pslug = event_slug_of(PROBE_MARKET, pt)
        probe = (fetch_event(pslug, pt) or {}).get("markets", []) if pslug else []
        built = assemble(test, rosters, seen_stems(SEEN_RANKS), probe)
        rule = ("candidates.json ranks 361-892 less every market whose event has a market in ranks 1-360 or in ai_map.json, "
                "with every market of their Polymarket events, merged into clusters; plus the Brazil probe")
        counts = {"candidates_ranks_361_on": len(rest), "dropped_by_seen_event": len(rest) - len(kept),
                  "dropped_by_ai_map": len(kept) - len(test), "test_markets": len(test), "events": len(rosters),
                  "events_not_found": sum(v is None for v in rosters.values())}
        probe_note = {"probe_event": pslug}
    else:
        raise ValueError(study)
    sched = {m["id"]: m.get("deadline") for r in rosters.values() if r for m in r["markets"]}
    test = [{**m, "deadline": m.get("deadline") or sched.get(m["id"])} for m in test]
    markets = [{**{k: m.get(k) for k in (*MARKET_KEEP, "event", "tags")}, "rank": rank.get(m["id"]), "cluster": built["where"].get(m["id"])}
               for m in sorted(test, key=lambda m: -m["volume"])]
    out = {"rule": rule, "counts": {**counts, **_counts(built["events"]), **probe_note}, "markets": markets, "events": built["events"]}
    STUDIES[study].mkdir(parents=True, exist_ok=True)
    (STUDIES[study] / "universe.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ---------------------------------------------------------------------------------------------------- inputs

def _day(s) -> str | None:
    return str(s)[:10] if s else None


def _deal(items: list, k: int) -> list[list]:
    return [items[i::k] for i in range(k)]


def v3_cluster(e: dict) -> dict:
    """A cluster as the version-3 labellers see it: the scheduled deadline, never the closing time; a ladder by deadline."""
    ms = (sorted(e["markets"], key=lambda m: (deadline(m), _scheduled(m), -m["volume"], m["id"])) if e["structure"] == "ladder"
          else e["markets"])
    return {"cluster": e["cluster"], "questions": [{"id": m["id"], "question": m["question"], "volume_musd": round(m["volume"] / 1e6, 2),
                                                    "start": _day(m["start"]), "deadline": _day(m.get("deadline")), "main": m["id"] == e["main"]}
                                                   for m in ms]}


def recall_questions(uni: dict) -> list[dict]:
    """Every test market and every cluster's main market, once each, the probe left out: by cluster, main first,
    then the test markets by volume."""
    out, seen = [], set()
    for e in sorted(uni["events"], key=lambda e: e["cluster"]):
        if e["probe"]:
            continue
        ms = [m for m in e["markets"] if m["id"] == e["main"]] + sorted([m for m in e["markets"] if m.get("in_test")],
                                                                        key=lambda m: (-m["volume"], m["id"]))
        for m in ms:
            if m["id"] not in seen:
                seen.add(m["id"])
                out.append({"id": m["id"], "question": m["question"]})
    return out


def _write(f: Path, obj: dict) -> Path:
    f.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    return f


def build_inputs(study: str, root: Path | None = None, instruments: Path = INSTRUMENTS) -> list[Path]:
    """The version-3, control-arm and recall input files of a study, from <study>/universe.json."""
    d = root or STUDIES[study]
    uni = json.loads((d / "universe.json").read_text())
    inst = json.loads(instruments.read_text())["classes"]
    v3_text, ctl_text = (PROMPTS / "labeller_v3.md").read_text(), (PROMPTS / "labeller_control.md").read_text()
    recall_text = (PROMPTS / "recall.md").read_text()
    chunks = _deal(sorted(uni["events"], key=lambda e: e["cluster"]), CHUNKS[study])    # the probe is dealt like any other cluster
    written = [_write(d / f"input_v3_{k}.json", {"instructions": v3_text, "instruments": inst, "events": [v3_cluster(e) for e in ch]})
               for k, ch in enumerate(chunks, 1)]
    by_ev: dict[str, list[dict]] = {}
    for m in uni["markets"]:                                    # test markets only: the control arm never sees the probe
        by_ev.setdefault(m["event"], []).append(m)
    order = sorted(by_ev, key=lambda s: (-max(m["volume"] for m in by_ev[s]), s))
    for k, ch in enumerate(_deal(order, CHUNKS[study]), 1):
        written.append(_write(d / f"input_control_{k}.json", {"instructions": ctl_text, "tickers": c5.MENU, "events": [
            {"event": s, "questions": [{"id": m["id"], "question": m["question"]} for m in sorted(by_ev[s], key=lambda m: (-m["volume"], m["id"]))]}
            for s in ch]}))
    for k, qs in enumerate(_deal(recall_questions(uni), RECALL_CHUNKS), 1):
        written.append(_write(d / f"input_recall_{k}.json", {"instructions": recall_text, "questions": qs}))
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("universe", "inputs") or argv[1] not in STUDIES:
        print(__doc__)
        return 2
    cmd, study = argv
    if cmd == "inputs":
        for f in build_inputs(study):
            d = json.loads(f.read_text())
            evs = d.get("events", [])
            nq = sum(len(e["questions"]) for e in evs) if evs else len(d["questions"])
            print(f"{f.relative_to(HERE.parent)}: {len(evs)} {'clusters' if 'v3' in f.name else 'events'}, {nq} questions, "
                  f"{f.stat().st_size / 1024:.0f} KB")
        return 0
    out = build_universe(study)
    print(json.dumps(out["counts"], indent=1))
    for e in out["events"][:3]:                                  # three short samples of names, nothing else
        print(f"  {e['cluster']} {e['structure']:<13} {len(e['markets']):>2} q | main: {next(m['question'] for m in e['markets'] if m['id'] == e['main'])[:50]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
