"""Event clusters: ladder stems, clustering, the main market, price fields stripped, the labellers' input files."""
import gzip
import json
import re

import pytest

from linker import events as ev

PRICE_KEYS = {"outcomePrices", "lastTradePrice", "bestBid", "bestAsk", "oneDayPriceChange", "spread", "price", "closedTime"}
PRICE_LIKE = re.compile(r'"[^"]*(?:price|Price|bid|Bid|ask|Ask|lastTrade|closedTime)[^"]*"\s*:')


def mk(i, q, slug, vol=1e6, start="2025-11-01", end="2026-06-30", test=True, deadline=None):
    return {"id": f"polymarket:{i}", "question": q, "volume": vol, "start": start, "end": end, "deadline": deadline or end, "closed": False,
            "token": str(i), "event": slug, "in_test": test}


def test_stem_merges_deadlines_and_thresholds():
    assert ev.stem("US x Iran ceasefire by April 30?") == ev.stem("US x Iran ceasefire by June 30?")
    assert ev.stem("Starmer out by May 15, 2026?") == ev.stem("Starmer out in 2025?") == ev.stem("Starmer out by end of 2026?")
    assert ev.stem("Will Bitcoin be above $90,000 on December 31?") == ev.stem("Will Bitcoin be above $100,000 on December 31?")
    assert ev.stem("SpaceX IPO closing market cap above $2T?") == ev.stem("SpaceX IPO closing market cap above $1.8T?")
    assert ev.stem("Will inflation exceed 3.5% by 2026-06-30?") == ev.stem("Will inflation exceed 4% by 2026-09-30?")
    assert ev.stem("Will the best AI model at the end of June 2026 be X?") == ev.stem("Will the best AI model at the end of February 2026 be X?")


def test_stem_keeps_named_outcomes_and_events_apart():
    lula = ev.stem("Will Lula win the 2026 Brazilian presidential election?")
    assert lula != ev.stem("Will Flávio Bolsonaro win the 2026 Brazilian presidential election?")
    assert ev.stem("Will Flávio Bolsonaro win?") == ev.stem("Will Flavio Bolsonaro win?")         # accents do not split a name
    assert lula != ev.stem("Will Lula win the 2022 Brazilian presidential election?")           # a year outside a deadline names the event
    oct_, dec = (ev.stem(f"Fed decreases interest rates by 25 bps after {m} 2025 meeting?") for m in ("October", "December"))
    assert oct_ != dec                                                                           # two meetings are two events
    assert ev.stem("Fed decreases interest rates by 25 bps after October 2025 meeting?") != \
        ev.stem("Fed decreases interest rates by 50+ bps after October 2025 meeting?")
    assert ev.stem("Will OpenAI release GPT-5 by June 30?") != ev.stem("Will OpenAI release GPT-6 by June 30?")


FED = ["Fed decreases interest rates by 25 bps after October 2025 meeting?", "Fed decreases interest rates by 50+ bps after October 2025 meeting?",
       "No change in Fed interest rates after October 2025 meeting?", "Fed increases interest rates by 25+ bps after October 2025 meeting?"]


def test_cluster_structures():
    ms = [mk(1, "US x Iran ceasefire by April 30?", "ceasefire-april"), mk(2, "US x Iran ceasefire by June 30?", "ceasefire-june"),
          *[mk(10 + i, q, "fed-october") for i, q in enumerate(FED)],
          mk(20, "Will Lula win the 2026 Brazilian presidential election?", "brazil"),
          mk(21, "Will Flávio Bolsonaro win the 2026 Brazilian presidential election?", "brazil"),
          mk(30, "Will Gold (GC) hit (HIGH) $5,500 by end of June?", "gc-jun"), mk(31, "Will Gold (GC) hit (HIGH) $6,000 by end of June?", "gc-jun"),
          mk(32, "Will Gold (GC) hit (LOW) $4,000 by end of June?", "gc-jun"), mk(33, "Will Gold (GC) hit (LOW) $3,500 by end of June?", "gc-jun"),
          mk(40, "Will Elon Musk buy Ryanair?", "ryanair")]
    got = {frozenset(m["id"].split(":")[1] for m in c["markets"]): c for c in ev.cluster(ms)}
    assert len(got) == 5
    assert got[frozenset({"1", "2"})]["structure"] == "ladder" and set(got[frozenset({"1", "2"})]["slugs"]) == {"ceasefire-april", "ceasefire-june"}
    assert got[frozenset({"10", "11", "12", "13"})]["structure"] == "multi_outcome"
    assert got[frozenset({"20", "21"})]["structure"] == "multi_outcome"
    assert got[frozenset({"30", "31", "32", "33"})]["structure"] == "mixed"
    assert got[frozenset({"40"})]["structure"] == "single"


def test_windows_do_not_merge_across_slugs():
    assert ev.merge_key("US x Iran ceasefire by April 30?") == ev.merge_key("US x Iran ceasefire by June 30?")
    assert ev.merge_key("Will 7 Fed rate cuts happen in 2025?") != ev.merge_key("Will 3 Fed rate cuts happen in 2026?")
    assert ev.merge_key("Will Iran strike Oman in March?") != ev.merge_key("Will Iran strike Oman by April 30, 2026?")
    assert ev.merge_key("Will Bitcoin be above $90,000 on March 15?") != ev.merge_key("Will Bitcoin be above $90,000 on March 20?")
    ms = [*[mk(i, f"Will {n} Fed rate cuts happen in 2025?", "cuts-2025") for i, n in ((1, 7), (2, 3))],
          *[mk(i, f"Will {n} Fed rate cuts happen in 2026?", "cuts-2026") for i, n in ((3, 2), (4, "no"))],
          mk(5, "Will Iran strike Oman in March?", "iran-march"), mk(6, "Will Iran strike Oman by April 30, 2026?", "iran-april"),
          mk(7, "US x Iran ceasefire by April 30?", "ceasefire-april"), mk(8, "US x Iran ceasefire by June 30?", "ceasefire-june")]
    got = sorted(sorted(m["id"].split(":")[1] for m in c["markets"]) for c in ev.cluster(ms))
    assert got == [["1", "2"], ["3", "4"], ["5"], ["6"], ["7", "8"]]


def test_main_market_rule():
    # ladder: the furthest deadline among rungs with >= 25% of the top volume; a rung under 20 sessions is not eligible
    lad = [mk(1, "X by March 31?", "x", 10e6, end="2026-03-31"), mk(2, "X by June 30?", "x", 3e6, end="2026-06-30"),
           mk(3, "X by December 31?", "x", 1e6, end="2026-12-31"), mk(4, "X by September 30?", "x", 9e6, start="2026-09-20", end="2026-09-30")]
    assert ev.main_market({"structure": "ladder", "markets": lad}) == "polymarket:2"
    # rungs that resolved together share an end date: the deadline in the question orders them
    early = [mk(5, "Y by April 7?", "y", 10e6, end="2026-04-25"), mk(6, "Y by May 15?", "y", 4e6, end="2026-04-25")]
    assert ev.main_market(early) == "polymarket:6"
    # a rung that closed early is ordered by its scheduled deadline, never by its closing time
    closed = [mk(12, "Z?", "z", 10e6, end="2026-01-10", deadline="2026-12-31"), mk(13, "Z?", "z", 9e6, end="2026-06-30", deadline="2026-06-30")]
    assert ev.main_market({"structure": "ladder", "markets": closed}) == "polymarket:12"
    # the deadline written in the question beats the scheduled one
    written = [mk(14, "W by March 31?", "w", 10e6, deadline="2026-12-31"), mk(15, "W by June 30?", "w", 9e6, deadline="2026-07-01")]
    assert ev.main_market({"structure": "ladder", "markets": written}) == "polymarket:15"
    # otherwise the largest volume, then the longest life
    multi = [mk(7, "Will A win?", "e", 5e6), mk(8, "Will B win?", "e", 5e6, start="2025-10-01"), mk(9, "Will C win?", "e", 1e6)]
    assert ev.main_market(multi) == "polymarket:8"
    # nobody qualifies on life: all markets are used
    short = [mk(10, "Will A win?", "e", 1e6, start="2026-06-25"), mk(11, "Will B win?", "e", 2e6, start="2026-06-25")]
    assert ev.main_market(short) == "polymarket:11"


def test_deadline_reads_the_question():
    assert ev.deadline({"question": "Maduro out in 2025?", "end": "2026-01-01"}) == "2025-12-31"
    assert ev.deadline({"question": "Will US withdraw from NATO before 2027?", "end": "2027-01-01"}) == "2026-12-31"
    assert ev.deadline({"question": "Will Hamas agree to disarm by December 31?", "end": "2026-01-01"}) == "2025-12-31"
    assert ev.deadline({"question": "Will Crude Oil hit $200 by end of June?", "end": "2026-07-01"}) == "2026-06-30"
    assert ev.deadline({"question": "Will Elon Musk buy Ryanair?", "end": "2026-07-01 00:00:00+00"}) == "2026-07-01"
    assert ev.deadline({"question": "Will Elon Musk buy Ryanair?", "end": "2026-02-03", "deadline": "2026-12-31T12:00:00Z"}) == "2026-12-31"
    assert ev.deadline({"question": "Will Hamas agree to disarm by December 31?", "end": "2026-02-03", "deadline": "2027-01-01"}) == "2026-12-31"


def test_fetch_event_strips_every_price_field(tmp_path, monkeypatch):
    raw = {"slug": "s", "title": "T", "tags": [{"label": "Politics"}], "volume": 9.0, "liquidity": 5.0,
           "markets": [{"id": 7, "question": "Q?", "volumeNum": 2.5e6, "volume": "2500000", "startDate": "2025-11-01T00:00:00Z",
                        "endDate": "2026-06-30T00:00:00Z", "closedTime": "2026-03-02 14:00:00+00", "closed": True, "clobTokenIds": '["111", "222"]',
                        "outcomePrices": '["0.4", "0.6"]', "lastTradePrice": 0.4, "bestBid": 0.39, "bestAsk": 0.41,
                        "oneDayPriceChange": 0.01, "oneWeekPriceChange": 0.02, "spread": 0.02, "liquidityNum": 1e5}]}
    calls = []

    def fake(url, params=None, throttle=None, allow=(), attempts=7):
        calls.append(url)
        return raw

    monkeypatch.setattr(ev.ds, "get_json", fake)
    monkeypatch.setattr(ev, "GAMMA_CACHE", tmp_path)
    out = ev.fetch_event("s", None)
    m = out["markets"][0]
    assert m == {"id": "polymarket:7", "question": "Q?", "volume": 2.5e6, "start": "2025-11-01T00:00:00Z", "end": "2026-03-02 14:00:00+00",
                 "deadline": "2026-06-30T00:00:00Z", "closed": True, "token": "111", "event": "s"}
    assert out["tags"] == ["Politics"] and set(out) == {"slug", "title", "tags", "markets"}
    text = gzip.decompress((tmp_path / "s.json.gz").read_bytes()).decode()
    assert not any(k in text for k in PRICE_KEYS | {"liquidity", "0.39", "0.41"})
    assert ev.fetch_event("s", None) == out and len(calls) == 1                              # the second call reads the cache
    lost = ev.strip_event({"slug": "e", "endDate": "2026-12-31T00:00:00Z", "markets": [
        {"id": 8, "question": "Q?", "closedTime": "2026-02-01 10:00:00+00", "umaEndDate": "2026-02-01T10:00:00Z", "closed": True}]})
    assert lost["markets"][0]["deadline"] == "2026-12-31T00:00:00Z" and lost["markets"][0]["end"] == "2026-02-01 10:00:00+00"


def _fixture(tmp_path, n_clusters=7):
    events, markets = [], []
    for i in range(1, n_clusters + 1):
        rows = [mk(100 * i + j, f"Event {i} by {mo} 30?", f"slug-{i}", vol=(n_clusters - i + 1) * 1e6 - j, end=f"2026-0{j + 1}-15",
                   deadline=f"2026-0{j + 4}-30", test=j < 2) for j, mo in enumerate(("April", "May", "June"))]
        events.append({"cluster": f"c{i:03d}", "slugs": [f"slug-{i}"], "structure": "ladder", "main": rows[0]["id"], "seen_ladder": False,
                       "probe": False, "markets": rows})
        markets += [{k: r[k] for k in ("id", "question", "volume", "start", "end", "deadline", "closed", "token", "event")} | {"tags": [], "rank": None}
                    for r in rows if r["in_test"]]
    probe = [mk(900 + j, f"Will {n} win the 2026 Brazilian presidential election?", "brazil", vol=2e7 - j, test=False) for j, n in enumerate(("A", "B"))]
    events.append({"cluster": f"c{n_clusters + 1:03d}", "slugs": ["brazil"], "structure": "multi_outcome", "main": probe[0]["id"], "seen_ladder": False, "probe": True,
                   "markets": probe})
    (tmp_path / "universe.json").write_text(json.dumps({"rule": "r", "counts": {}, "markets": markets, "events": events}))
    inst = tmp_path / "instruments.json"
    inst.write_text(json.dumps({"as_of": "2026-10-03", "classes": {"oil_gas": [{"ticker": "USO", "name": "United States Oil Fund"}]},
                                "tickers": {"USO": {"class": "oil_gas", "name": "United States Oil Fund", "type": "ETF", "has_options": True}}}))
    return inst


def test_inputs_format(tmp_path):
    inst = _fixture(tmp_path)
    files = ev.build_inputs("fresh", root=tmp_path, instruments=inst)
    assert sorted(f.name for f in files) == ([f"input_control_{k}.json" for k in (1, 2, 3)] + [f"input_recall_{k}.json" for k in (1, 2)]
                                             + [f"input_v3_{k}.json" for k in (1, 2, 3)])
    v3 = [json.loads((tmp_path / f"input_v3_{k}.json").read_text()) for k in (1, 2, 3)]
    assert v3[0]["instructions"] == (ev.PROMPTS / "labeller_v3.md").read_text()
    assert v3[0]["instruments"] == {"oil_gas": [{"ticker": "USO", "name": "United States Oil Fund"}]}
    ids = [[e["cluster"] for e in d["events"]] for d in v3]
    assert ids == [["c001", "c004", "c007"], ["c002", "c005", "c008"], ["c003", "c006"]]        # round-robin in cluster order, probe included
    assert all(set(e) == {"cluster", "questions"} for d in v3 for e in d["events"])              # the probe is not marked
    q = v3[0]["events"][0]["questions"][0]
    assert set(q) == {"id", "question", "volume_musd", "start", "deadline", "main"}                # never the closing time
    assert q["volume_musd"] == round(7e6 / 1e6, 2) and q["start"] == "2025-11-01" and q["deadline"] == "2026-04-30" and q["main"] is True
    assert all("01-15" not in json.dumps(d["events"]) for d in v3)                                 # no closing date leaks anywhere
    assert sum(q["main"] for e in v3[0]["events"] for q in e["questions"]) == 3
    ctl = [json.loads((tmp_path / f"input_control_{k}.json").read_text()) for k in (1, 2, 3)]
    assert ctl[0]["instructions"] == (ev.PROMPTS / "labeller_control.md").read_text() and ctl[0]["tickers"] == ev.c5.MENU
    assert [e["event"] for e in ctl[0]["events"]] == ["slug-1", "slug-4", "slug-7"]
    assert all(set(x) == {"id", "question"} for d in ctl for e in d["events"] for x in e["questions"])
    assert sum(len(e["questions"]) for d in ctl for e in d["events"]) == 14                      # test markets only, no probe
    rc = [json.loads((tmp_path / f"input_recall_{k}.json").read_text()) for k in (1, 2)]
    assert rc[0]["instructions"] == (ev.PROMPTS / "recall.md").read_text() and set(rc[0]) == {"instructions", "questions"}
    rq = [q for d in rc for q in d["questions"]]
    assert all(set(q) == {"id", "question"} for q in rq) and len(rq) == len({q["id"] for q in rq}) == 14  # tests (mains among them), no probe
    order = ev.recall_questions(json.loads((tmp_path / "universe.json").read_text()))
    assert rc[0]["questions"] == order[0::2] and rc[1]["questions"] == order[1::2]                  # dealt alternately
    assert not any(q["id"].startswith("polymarket:90") for q in rq)
    dev = ev.build_inputs("dev", root=tmp_path, instruments=inst)
    assert sorted(f.name for f in dev) == ["input_control_1.json", "input_control_2.json", "input_recall_1.json", "input_recall_2.json",
                                           "input_v3_1.json", "input_v3_2.json"]


def test_recall_adds_a_main_that_is_not_a_test_market():
    e = {"cluster": "c001", "probe": False, "main": "polymarket:2", "markets": [mk(1, "A?", "a", 2e6), mk(2, "B?", "a", 1e6, test=False)]}
    p = {"cluster": "c002", "probe": True, "main": "polymarket:3", "markets": [mk(3, "C?", "b", 5e6, test=False)]}
    assert [q["id"] for q in ev.recall_questions({"events": [p, e]})] == ["polymarket:2", "polymarket:1"]


@pytest.mark.parametrize("study,minimum", [("dev", 120), ("fresh", 200)])
def test_built_universe(study, minimum):
    f = ev.STUDIES[study] / "universe.json"
    if not f.exists():
        pytest.skip("universe not built")
    u = json.loads(f.read_text())
    assert len(u["markets"]) >= minimum and all(m["cluster"] for m in u["markets"])
    keys = {k for e in u["events"] for m in e["markets"] for k in m} | {k for m in u["markets"] for k in m}
    assert not keys & PRICE_KEYS and not PRICE_LIKE.search(f.read_text())
    assert all(m.get("deadline") for e in u["events"] for m in e["markets"])
    for e in u["events"]:
        assert e["main"] in {m["id"] for m in e["markets"]}
        assert e["structure"] == ev.structure_of(e["markets"])
        years = {y for m in e["markets"] for y in re.findall(r"\bin ((?:19|20)\d\d)\b", m["question"].lower())}
        assert len(e["slugs"]) == 1 or len(years) <= 1, e["cluster"]                             # "in 2025" and "in 2026" are two events
    assert sum(e["probe"] for e in u["events"]) == (1 if study == "fresh" else 0)
    order = sorted(u["events"], key=lambda e: e["cluster"])
    tops = [max(m["volume"] for m in e["markets"]) for e in order]
    assert tops == sorted(tops, reverse=True)                                                    # ids by top volume, the probe included


@pytest.mark.parametrize("study", ["dev", "fresh"])
def test_built_inputs_hide_the_probe(study):
    d = ev.STUDIES[study]
    files = sorted(d.glob("input_v3_*.json"))
    if not files:
        pytest.skip("inputs not built")
    for f in files:
        text = f.read_text()
        assert not PRICE_LIKE.search(text) and '"end"' not in text, f.name
        evs = json.loads(text)["events"]
        ids = [e["cluster"] for e in evs]
        tops = [max(q["volume_musd"] for q in e["questions"]) for e in evs]
        assert ids == sorted(set(ids)) and tops == sorted(tops, reverse=True), f.name           # neither ids nor volumes out of order
