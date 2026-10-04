"""Exact contract links (ladders, tickets) and the /contracts, /ladders, /tickets API, offline with fixtures."""
import json

import pytest
from fastapi.testclient import TestClient

from app.contracts import live, research
from app.contracts import router as crouter
from app.pipeline.llm import RulesProvider

DESC = ("This market will resolve to \"Yes\" if the US strikes Iran by the listed date, 11:59 PM ET. Otherwise \"No\". "
        "The resolution source will be a consensus of credible reporting.")


def rung(i, q, created="2026-03-02T00:00:00Z", desc=DESC, src="", end="2026-01-01T00:00:00Z", **kw):
    return {"id": str(i), "question": q, "description": desc, "resolutionSource": src, "startDate": created, "endDate": end,
            "volume": 100000, "clobTokenIds": json.dumps([f"tok{i}", f"no{i}"]), "orderPriceMinTickSize": 0.01, **kw}


EVENT = {"id": "e1", "title": "US strikes Iran by...?", "resolutionSource": ""}


def test_ladder_rungs_in_re_derived_date_order():
    lm = research.link_map()
    ms = [rung(1, "Will the US strike Iran by December 31?", end="2026-01-01T04:59:00Z"),
          rung(2, "Will the US strike Iran by June 30?", end="2026-06-30T23:59:00Z"),
          rung(3, "Will the US strike Iran by March 31?", end="2026-03-31T23:59:00Z")]
    [lad] = lm.link_ladders(ms, EVENT)
    assert [r["date"] for r in lad["rungs"]] == ["2026-03-31", "2026-06-30", "2026-12-31"]
    # S11's end-date year rule would have put December 31 in 2025 (first rung): flagged as corrected
    assert [r["year_corrected"] for r in lad["rungs"]] == [False, False, True]
    assert lad["valid"] and all(p["nested"] for p in lad["pairs"])
    assert [(p["rich"], p["cheap"]) for p in lad["pairs"]] == [("3", "2"), ("2", "1")]


def test_nesting_failures_give_explicit_reasons():
    lm = research.link_map()
    ms = [rung(1, "Will the US strike Iran by March 31?"),
          rung(2, "Will the US strike Iran by June 30?", desc=DESC.replace("11:59 PM ET", "11:59 PM UTC")),
          rung(3, "Will the US strike Iran by September 30?", src="https://example.org/other")]
    [lad] = lm.link_ladders([ms[0], ms[1]], EVENT)
    assert not lad["pairs"][0]["nested"] and "descriptions differ" in lad["pairs"][0]["reasons"]
    [lad] = lm.link_ladders([ms[0], ms[2]], EVENT)
    assert not lad["pairs"][0]["nested"] and "sources differ" in lad["pairs"][0]["reasons"]


def test_creation_window_cheap_rung_created_later_is_not_nested():
    lm = research.link_map()
    d = "Resolves Yes if the price trades above the line at any point after market creation and by the listed date."
    ms = [rung(1, "Will the US strike Iran by March 31?", desc=d, created="2026-01-01T00:00:00Z"),
          rung(2, "Will the US strike Iran by June 30?", desc=d, created="2026-02-01T00:00:00Z")]
    [lad] = lm.link_ladders(ms, EVENT)
    assert not lad["pairs"][0]["nested"]
    assert "window starts at creation and the cheap rung was created later" in lad["pairs"][0]["reasons"]
    ms[1]["startDate"] = "2026-01-01T00:00:30Z"                         # within the 60 s tolerance
    [lad] = lm.link_ladders(ms, EVENT)
    assert lad["pairs"][0]["nested"]


def test_two_rungs_on_one_date_invalidate_the_ladder():
    lm = research.link_map()
    ms = [rung(1, "Will the US strike Iran by March 31?"), rung(2, "Will the US strike Iran by March 31, 2026?")]
    lads = lm.link_ladders(ms, EVENT)
    # different templates ("March 31" vs "March 31, 2026" are the same phrase slot): one ladder, same date twice
    assert len(lads) == 1 and not lads[0]["valid"] and "two rungs on one date" in lads[0]["reasons"][0]


def chain(underlying, exps, strikes):
    root = "SPXW" if underlying == "SPX" else underlying
    return [{"expiration_date": e, "strike_price": k, "contract_type": ct, "shares_per_contract": 100,
             "ticker": f"O:{root}{e[2:4]}{e[5:7]}{e[8:]}{ct[0].upper()}{int(k * 1000):08d}"}
            for e in exps for k in strikes for ct in ("call", "put")]


def test_ticket_exact_link_expiry_and_bracketing_strikes():
    op = research.options()
    rows = chain("NVDA", ("2026-10-23", "2026-10-30", "2026-11-06"), (210, 215, 220, 225, 230))
    up = op.exact_ticket_link(rows, "NVDA", 220, "up", "2026-10-31")   # Saturday: end session is Friday 30 October
    assert up["ok"] and up["expiry"] == "2026-10-30" and (up["lower_strike"], up["upper_strike"]) == (215.0, 225.0)
    assert up["long_leg"] == "O:NVDA261030C00215000" and up["short_leg"] == "O:NVDA261030C00225000"
    down = op.exact_ticket_link(rows, "NVDA", 222, "down", "2026-10-31")
    assert down["option_type"] == "put" and (down["long_strike"], down["short_strike"]) == (225.0, 220.0)
    far = op.exact_ticket_link(rows, "NVDA", 400, "up", "2026-10-31")
    assert not far["ok"] and "bracketing" in far["reason"]
    late = op.exact_ticket_link(rows, "NVDA", 220, "up", "2027-03-31")
    assert not late["ok"] and "45 days" in late["reason"]
    spx = op.exact_ticket_link(chain("SPX", ("2026-12-31",), (6400, 6500, 6600)), "SPX", 6450, "down", "2026-12-31")
    assert spx["ok"] and spx["long_leg"].startswith("O:SPXW")
    assert not op.exact_ticket_link(rows, "NVDA", 220, None, "2026-10-31")["ok"]


def test_legacy_resolver_still_works(monkeypatch):
    op = research.options()

    def rows(s, url, params=None):
        if "options/contracts" in url:
            return chain("EWZ", ("2026-10-09",), (37.0, 38.0, 39.0))
        return [{"c": 38.19}]

    monkeypatch.setattr(op.d4, "massive_rows", rows)
    r = op.resolve(object(), "base", "EWZ", "up_on_yes", "2026-10-05", "2026-10-02")
    assert r["strike"] == 38.0 and r["directional_leg"].endswith("C00038000")


def test_pair_edge_after_fees_and_one_tick():
    a = {"tick": 0.01, "fee_rate": 0.0, "fee_exponent": 1.0}
    assert live.pair_edge(0.60, 0.57, a, a) == pytest.approx(1.0)        # 0.59 - 0.58
    assert live.pair_edge(0.60, 0.58, a, a) <= 0                         # only one tick each side: no lock-in
    f = {"tick": 0.01, "fee_rate": 0.25, "fee_exponent": 2.0}
    assert live.pair_edge(0.60, 0.57, f, f) < live.pair_edge(0.60, 0.57, a, a)
    assert live.pair_edge(None, 0.5, a, a) is None


@pytest.fixture
def client(monkeypatch):
    live.CACHE._data.clear()
    live.reset_listing_cache()
    monkeypatch.setattr(crouter, "provider", lambda: RulesProvider())
    from app.main import create_app
    yield TestClient(create_app())
    live.CACHE._data.clear()


def test_post_classify(client):
    r = client.post("/contracts/classify", json={"question": "Will Apple (AAPL) close above $250 on October 9?",
                                                 "market": {"createdAt": "2026-10-05T00:00:00Z"}})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["type"] == "close_above_ticket" and d["gemini_agreement"]["used"] is False
    assert {"type", "fields", "checks", "gemini_agreement"} <= set(d)


def test_get_ladders_offline(client, monkeypatch):
    ms = [rung(1, "Will the US strike Iran by December 31?"), rung(2, "Will the US strike Iran by June 30?")]

    async def events(http, extra, pages):
        return [{**EVENT, "markets": ms}]

    async def books(http, tokens):
        return {"tok2": {"bids": [{"price": "0.40", "size": "50"}], "asks": [{"price": "0.42", "size": "50"}]},
                "tok1": {"bids": [{"price": "0.30", "size": "50"}], "asks": [{"price": "0.35", "size": "50"}]}}

    monkeypatch.setattr(live, "open_events", events)
    monkeypatch.setattr(live, "books", books)
    d = client.get("/ladders").json()
    assert d["ok"] and d["counts"]["ladders"] == 1
    [lad] = d["ladders"]
    assert [r["id"] for r in lad["rungs"]] == ["2", "1"]
    p = lad["pairs"][0]
    assert p["bid_rich"] == 0.40 and p["ask_cheap"] == 0.35 and p["violation"] and p["actionable"]
    assert p["edge_points"] == pytest.approx(3.0)


def test_get_ladders_never_500(client, monkeypatch):
    async def boom(http, extra, pages):
        raise RuntimeError("gamma down")

    monkeypatch.setattr(live, "open_events", boom)
    r = client.get("/ladders")
    assert r.status_code == 200 and r.json()["ok"] is False and "gamma down" in r.json()["error"]


def test_get_tickets_offline(client, monkeypatch):
    ev = {"id": "t1", "title": "What will NVIDIA (NVDA) hit in October?",
          "markets": [{"id": "9", "question": "Will NVIDIA (NVDA) reach $220 in October?", "startDate": "2026-10-01T00:00:00Z",
                       "clobTokenIds": json.dumps(["tk9", "no9"])},
                      {"id": "10", "question": "Will NVIDIA (NVDA) hit $200 in October?", "startDate": "2026-10-01T00:00:00Z"}]}

    async def events(http, extra, pages):
        return [ev] if extra.get("tag_slug") == "hit-price" else []

    async def books(http, tokens):
        return {"tk9": {"bids": [{"price": "0.20", "size": "10"}], "asks": [{"price": "0.23", "size": "10"}]}}

    async def listed(underlying, end_session):
        return chain(underlying, ("2026-10-30",), (210, 215, 220, 225, 230)), ""

    async def reference(f, kind):
        return {"ok": True, "kind": kind}

    monkeypatch.setattr(live, "open_events", events)
    monkeypatch.setattr(live, "books", books)
    monkeypatch.setattr(live, "listed_rows", listed)
    monkeypatch.setattr(live, "reference", reference)
    d = client.get("/tickets").json()
    assert d["ok"] and {k: d["counts"][k] for k in ("tickets", "linked")} == {"tickets": 2, "linked": 1}
    t = {x["id"]: x for x in d["tickets"]}
    assert t["9"]["contract"]["expiry"] == "2026-10-30" and t["9"]["best_ask"] == 0.23 and t["9"]["reference"]["kind"] == "touch_ticket"
    assert not t["10"]["contract"]["ok"] and "direction" in t["10"]["contract"]["reason"]
    assert "not offered" in d["hedge"]


def test_post_classify_btc_15min_serves_watch_only(client):
    d = client.post("/contracts/classify", json={"question": "Bitcoin Up or Down - October 4, 3:15PM-3:30PM ET"}).json()
    assert d["ok"] and d["type"] == "other" and d["mechanism"] == "btc_15m_watch"
    assert d["evidence"]["id"] == "btc_15min" and d["evidence"]["status"] == "WATCH_ONLY"
    assert d["evidence"]["trade_mechanism"] is False


def test_post_classify_close_above_is_no_tested_mechanism(client):
    d = client.post("/contracts/classify", json={"question": "Will NVDA close above $190 on October 9?",
                                                 "market": {"createdAt": "2026-10-05T00:00:00Z"}}).json()
    assert d["type"] == "close_above_ticket"
    assert d["evidence"]["status"] == "NO_TESTED_MECHANISM" and d["evidence"]["trade_mechanism"] is False


def _many_ticket_events(n_names):
    names = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "NFLX", "PLTR", "HOOD", "COIN", "AMD", "AVGO", "ORCL", "INTC",
             "UBER", "SHOP"][:n_names]
    evs = []
    for i, tk in enumerate(names):
        evs.append({"id": f"e{i}", "title": f"What will ({tk}) hit in October?",
                    "markets": [{"id": f"{i}-{k}", "question": f"Will ({tk}) reach ${100 + 10 * k} in October?",
                                 "startDate": "2026-10-01T00:00:00Z", "clobTokenIds": json.dumps([f"t{i}{k}", "n"])}
                                for k in range(3)]})
    return evs


def test_get_tickets_is_bounded_and_returns_what_was_built(client, monkeypatch):
    monkeypatch.setattr(live, "MAX_CHAINS", 12)  # the fixture has 16 underlyings: check the budget binds
    import asyncio
    evs = _many_ticket_events(16)                       # 16 underlyings x 3 tickets: more chains than the budget
    calls = {"listed": 0, "ref": 0}

    async def events(http, extra, pages):
        return evs if extra.get("tag_slug") == "hit-price" else []

    async def books(http, tokens):
        return {}

    async def listed(underlying, end_session):
        calls["listed"] += 1
        return chain(underlying, ("2026-10-30",), tuple(range(80, 200, 10))), ""

    async def reference(f, kind):
        calls["ref"] += 1
        if f["underlying"] == "TSLA":
            await asyncio.sleep(5)                      # one slow underlying: its rows hit the row timeout
        return {"ok": True, "available": True, "kind": kind}

    monkeypatch.setattr(live, "open_events", events)
    monkeypatch.setattr(live, "books", books)
    monkeypatch.setattr(live, "listed_rows", listed)
    monkeypatch.setattr(live, "reference", reference)
    monkeypatch.setattr(live, "ROW_TIMEOUT_S", 0.2)
    monkeypatch.setattr(live, "MAX_REFERENCES", 20)
    d = client.get("/tickets").json()
    assert d["ok"] and len(d["tickets"]) == 48
    assert calls["listed"] == live.MAX_CHAINS               # one listing per underlying, within the chain budget
    assert calls["ref"] <= 20
    reasons = [str((t.get("reference") or {}).get("reason") or "") for t in d["tickets"]]
    assert sum(r.startswith("budget") for r in reasons) >= 48 - 20
    assert any("row timed out" in r for r in reasons)
    assert all("contract" in t and "reference" in t for t in d["tickets"])
    assert d["budget"]["unpriced"] == sum(r.startswith("budget") for r in reasons)


def test_get_tickets_deadline_keeps_the_rows(client, monkeypatch):
    import asyncio
    evs = _many_ticket_events(4)

    async def events(http, extra, pages):
        return evs if extra.get("tag_slug") == "hit-price" else []

    async def books(http, tokens):
        return {}

    async def listed(underlying, end_session):
        return chain(underlying, ("2026-10-30",), tuple(range(80, 200, 10))), ""

    async def reference(f, kind):
        await asyncio.sleep(10)
        return {"ok": True}

    monkeypatch.setattr(live, "open_events", events)
    monkeypatch.setattr(live, "books", books)
    monkeypatch.setattr(live, "listed_rows", listed)
    monkeypatch.setattr(live, "reference", reference)
    monkeypatch.setattr(live, "DEADLINE_S", 2.6)
    monkeypatch.setattr(live, "TICKET_MARGIN_S", 2.0)          # 0.6 s for linking and pricing
    d = client.get("/tickets").json()
    assert d["ok"] and len(d["tickets"]) == 12                  # the board is served, not failed
    assert d["partial"] is True and d["pending"] == {"listing": 0, "reference": 12}
    assert all((t["reference"] or {}).get("available") is False for t in d["tickets"])
    assert all(t["contract"]["ok"] for t in d["tickets"])       # listings came back: every row linked before the deadline
    assert "tickets" not in live.CACHE._data                    # a partial board is not kept


def test_get_tickets_partial_listing_then_warm_from_listing_cache(client, monkeypatch):
    import asyncio
    evs = _many_ticket_events(3)
    calls = {"listed": 0}

    async def events(http, extra, pages):
        return evs if extra.get("tag_slug") == "hit-price" else []

    async def books(http, tokens):
        return {}

    async def listed(underlying, end_session):
        calls["listed"] += 1
        if underlying == "AAPL":
            await asyncio.sleep(0.3 if calls["listed"] <= 3 else 0)   # cold: slower than the deadline
        return chain(underlying, ("2026-10-30",), tuple(range(80, 200, 10))), ""

    async def reference(f, kind):
        return {"ok": True, "available": True}

    monkeypatch.setattr(live, "open_events", events)
    monkeypatch.setattr(live, "books", books)
    monkeypatch.setattr(live, "listed_rows", listed)
    monkeypatch.setattr(live, "reference", reference)
    monkeypatch.setattr(live, "DEADLINE_S", 2.15)
    monkeypatch.setattr(live, "TICKET_MARGIN_S", 2.0)          # 0.15 s for linking and pricing
    d = client.get("/tickets").json()
    assert d["ok"] and d["partial"] is True and d["pending"]["listing"] == 3
    aapl = [t for t in d["tickets"] if "AAPL" in t["question"]]
    assert all(t["contract"]["reason"] == "budget" for t in aapl)
    assert sum(t["contract"]["ok"] for t in d["tickets"]) == 6
    assert calls["listed"] == 3
    # NVDA and TSLA listings are cached for LISTING_TTL_S; only AAPL (cut off in the cold build) is listed again
    d2 = client.get("/tickets").json()
    assert d2["ok"] and d2["partial"] is False and d2["pending"] == {"listing": 0, "reference": 0}
    assert all(t["contract"]["ok"] for t in d2["tickets"])
    assert calls["listed"] <= 4


def test_close_above_rows_are_reference_only(client, monkeypatch):
    ev = {"id": "c1", "title": "NVDA close above on October 9?",
          "markets": [{"id": "c9", "question": "Will NVIDIA (NVDA) close above $190 on October 9?",
                       "startDate": "2026-10-05T00:00:00Z", "clobTokenIds": json.dumps(["tc9", "n"])}]}

    async def events(http, extra, pages):
        return [ev] if extra.get("tag_id") else []

    async def books(http, tokens):
        return {}

    async def listed(underlying, end_session):
        return chain(underlying, ("2026-10-09",), (180, 185, 190, 195, 200)), ""

    async def reference(f, kind):
        return {"ok": True, "available": True}

    monkeypatch.setattr(live, "open_events", events)
    monkeypatch.setattr(live, "books", books)
    monkeypatch.setattr(live, "listed_rows", listed)
    monkeypatch.setattr(live, "reference", reference)
    d = client.get("/tickets").json()
    [t] = d["tickets"]
    assert t["type"] == "close_above_ticket" and t["reference_only"] is True and t["evidence_id"] == "foundation"
    assert d["evidence"]["close_above_ticket"]["status"] == "NO_TESTED_MECHANISM"
