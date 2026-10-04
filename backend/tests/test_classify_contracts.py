"""Four-type contract classifier: rule parser, year re-derivation (ladder_replay amendment 5), Gemini cross-check."""
import asyncio

import pytest

from app.contracts import classify as cc
from app.pipeline import classify as pipeline_classify
from app.pipeline.llm import LLMError, RulesProvider


def run(coro):
    return asyncio.run(coro)


def rc(q, **m):
    return cc.rules_classify(q, None, m)


def test_pipeline_module_exposes_the_four_types():
    assert pipeline_classify.CONTRACT_TYPES == ("ladder_rung", "touch_ticket", "close_above_ticket", "other")
    assert pipeline_classify.classify_contract is cc.classify_contract


def test_touch_ticket_fields():
    r = rc("Will NVIDIA (NVDA) reach $220 in October?", createdAt="2026-10-01T00:00:00Z",
           event_title="What will NVIDIA (NVDA) hit in October?")
    assert r["type"] == "touch_ticket" and r["linkable"]
    f = r["fields"]
    assert (f["underlying"], f["level"], f["direction"], f["window_end"], f["end_session"]) == ("NVDA", 220.0, "up", "2026-10-31", "2026-10-30")
    low = rc("Will S&P 500 (SPY) hit (LOW) $680 in June?", createdAt="2026-05-29T00:00:00Z")
    assert low["fields"]["underlying"] == "SPY" and low["fields"]["direction"] == "down"
    spx = rc("Will S&P 500 (SPX) dip to $6,500 by December 31?", createdAt="2026-03-01T00:00:00Z")
    assert spx["fields"]["option_root"] == "O:SPXW" and spx["fields"]["level"] == 6500.0


def test_touch_ticket_without_direction_or_ambiguous_index_is_flagged_not_linked():
    r = rc("Will S&P 500 hit $7000 by December 31?", createdAt="2026-03-01T00:00:00Z")
    assert r["type"] == "touch_ticket" and not r["linkable"]
    assert any("ambiguous" in x for x in r["reasons"]) and any("direction" in x for x in r["reasons"])
    # the universe label's arrow gives the direction when the question has no direction word
    ok = rc("Will Tesla (TSLA) hit $500 by December 31?", createdAt="2026-03-01T00:00:00Z", label="↑ $500")
    assert ok["linkable"] and ok["fields"]["direction"] == "up"


def test_close_above_ticket():
    r = rc("Will Apple (AAPL) close above $250 on October 9?", createdAt="2026-10-05T00:00:00Z")
    assert r["type"] == "close_above_ticket" and r["linkable"]
    assert r["fields"]["window_end"] == "2026-10-09" and r["fields"]["direction"] == "up"


def test_stock_names_containing_commodity_words_are_still_tickets():
    # "Goldman" contains "gold": the exclusion list matches whole words only
    r = rc("Will Goldman Sachs (GS) close above $800 on October 9?", createdAt="2026-10-05T00:00:00Z")
    assert r["type"] == "close_above_ticket" and r["linkable"] and r["fields"]["underlying"] == "GS"
    t = rc("Will Goldman Sachs (GS) reach $900 in October?", createdAt="2026-10-01T00:00:00Z")
    assert t["type"] == "touch_ticket" and t["fields"]["underlying"] == "GS"
    # the real commodity is still excluded
    assert rc("Will gold close above $4,000 on October 9?", createdAt="2026-10-05T00:00:00Z")["type"] != "close_above_ticket"


def test_ladder_rung_and_year_re_derivation():
    # amendment 5: "by December 31" in a market created in March 2026 is 2026-12-31 (S11's rule read it as 2025)
    r = rc("Will the US strike Iran by December 31?", createdAt="2026-03-02T00:00:00Z", endDate="2026-01-01T00:00:00Z", event_id="e1")
    assert r["type"] == "ladder_rung" and r["fields"]["date"] == "2026-12-31"
    assert r["fields"]["year_source"] == "re-derived from the creation date"
    early = rc("Will the US strike Iran by December 31?", createdAt="2025-12-10T00:00:00Z", event_id="e1")
    assert early["fields"]["date"] == "2025-12-31"
    jan = rc("Will the US strike Iran by January 31?", createdAt="2025-10-15T00:00:00Z", event_id="e1")
    assert jan["fields"]["date"] == "2026-01-31"                        # not 2025-01-31
    explicit = rc("Will the US strike Iran by June 30, 2027?", createdAt="2026-03-02T00:00:00Z", event_id="e1")
    assert explicit["fields"]["date"] == "2027-06-30" and explicit["fields"]["year_source"] == "explicit year"


def test_ladder_rung_without_creation_date_is_not_linkable():
    r = rc("Will the US strike Iran by December 31?", event_id="e1")
    assert r["type"] == "ladder_rung" and not r["linkable"]
    assert any("year cannot be re-derived" in x for x in r["reasons"])


def test_other_and_btc_watch_only():
    assert rc("Who will win the 2026 World Cup?")["type"] == "other"
    assert rc("Who will win the 2026 World Cup?")["reasons"] == ["no tested mechanism"]
    b = rc("Bitcoin Up or Down - October 4, 3:15PM-3:30PM ET")
    assert b["type"] == "other" and b["mechanism"] == "btc_15m_watch" and not b["linkable"]
    # a crypto "hit" is never a stock ticket; with a "by <date>" it is a ladder rung
    c = rc("Will Bitcoin hit $150k by December 31?", createdAt="2026-03-01T00:00:00Z", event_id="btc")
    assert c["type"] == "ladder_rung"


class FakeGemini:
    label = "gemini:fake"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.prompts = answer, error, []

    async def _generate(self, prompt, schema):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.answer


Q = "Will NVIDIA (NVDA) reach $220 in October?"
M = {"createdAt": "2026-10-01T00:00:00Z"}


def test_gemini_agreement():
    g = FakeGemini({"type": "touch_ticket", "underlying": "nvda", "level": 220, "direction": "up", "date": "2026-10-31"})
    r = run(cc.classify_contract(Q, None, M, g))
    assert r["gemini_agreement"]["used"] and r["gemini_agreement"]["agree"] is True and not r["flagged"]


def test_gemini_disagreement_rule_parser_wins_and_item_is_flagged():
    g = FakeGemini({"type": "touch_ticket", "underlying": "NVDA", "level": 230, "direction": "down", "date": "2026-10-31"})
    r = run(cc.classify_contract(Q, None, M, g))
    assert r["flagged"] and r["gemini_agreement"]["agree"] is False
    assert {d["field"] for d in r["gemini_agreement"]["disagreements"]} == {"level", "direction"}
    assert r["fields"]["level"] == 220.0 and r["fields"]["direction"] == "up"          # the rule parser's values are served
    t = run(cc.classify_contract(Q, None, M, FakeGemini({"type": "other", "underlying": "", "level": 0, "direction": "none", "date": ""})))
    assert t["type"] == "touch_ticket" and t["gemini_agreement"]["disagreements"][0]["field"] == "type"


def test_gemini_failure_and_no_key_fall_back_to_rules():
    r = run(cc.classify_contract(Q, None, M, FakeGemini(error=LLMError("Gemini call failed: HTTP 503"))))
    assert r["gemini_agreement"]["agree"] is None and "503" in r["gemini_agreement"]["error"] and r["linkable"]
    n = run(cc.classify_contract(Q, None, M, RulesProvider()))
    assert n["gemini_agreement"]["used"] is False and n["type"] == "touch_ticket"


def test_gemini_rung_rule_comparison_is_checked_against_the_rule_verdict():
    pair = {"checks": [{"check": "order", "ok": True}, {"check": "nested", "ok": False}], "nested": False}
    out = run(cc.check_pair_with_gemini(FakeGemini({"same": True}), pair, {"description": "a"}, {"description": "b"}))
    assert out["flagged"] and out["gemini"]["agree"] is False and out["nested"] is False
    ok = run(cc.check_pair_with_gemini(FakeGemini({"same": False}), pair, {}, {}))
    assert not ok["flagged"]


def test_bare_ticker_cashtag_and_company_name_resolve_the_underlying():
    r = rc("Will AAPL close above $250 on October 30, 2026?")
    assert r["type"] == "close_above_ticket" and r["fields"]["underlying"] == "AAPL" and r["fields"]["direction"] == "up"
    assert r["linkable"]
    assert rc("Will $TSLA reach $500 in October?", createdAt="2026-10-01T00:00:00Z")["fields"]["underlying"] == "TSLA"
    assert rc("Will Apple (AAPL) dip to $200 in November?", createdAt="2026-10-01T00:00:00Z")["fields"]["underlying"] == "AAPL"
    assert rc("Will Bank of America hit $60 by December 31, 2026?")["fields"]["underlying"] == "BAC"   # names.json
    # ordinary uppercase words are not tickers; two different tickers are refused
    # (a price question with no stock ticker is no longer a ticket: it falls to the rung rule, so there is no underlying)
    assert rc("Will the US CEO of AI ETF hit $5 by December 31, 2026?")["fields"].get("underlying") is None
    two = rc("Will AAPL or MSFT hit $300 by December 31, 2026?")
    assert two["fields"]["underlying"] is None and "more than one ticker" in " ".join(two["reasons"])


def test_hit_without_direction_word_is_flagged_unless_a_price_is_given():
    q = "Will AAPL hit $300 by October 30, 2026?"
    r = rc(q)
    assert r["fields"]["underlying"] == "AAPL" and r["fields"]["direction"] is None and not r["linkable"]
    assert any("direction unknown" in x for x in r["reasons"])
    up = rc(q, underlying_price=255.0)
    assert up["fields"]["direction"] == "up" and up["linkable"] and "latest price" in up["fields"]["direction_source"]
    down = rc(q, last_price=320.0)
    assert down["fields"]["direction"] == "down"
    # an explicit direction word is never overridden by the price
    assert rc("Will AAPL dip to $300 by October 30, 2026?", underlying_price=255.0)["fields"]["direction"] == "down"
