"""Twin matcher: extraction, proposal and verification (offline; claims built from small market dicts)."""
from __future__ import annotations

from datetime import date

import pytest

from app.twins.claims import clock_times, extract_dates, extract_numbers, from_kalshi, from_polymarket
from app.twins.matcher import match_all, propose, verify, idf_table, similarity


def poly(id_, question, end="2026-12-31T16:59:00Z", desc="", **kw):
    return from_polymarket({"id": id_, "question": question, "description": desc, "endDate": end,
                            "token_id": f"tok{id_}", **kw})


def kal(ticker, title, close="2027-01-01T04:59:00Z", rules="", sub="", **kw):
    return from_kalshi({"ticker": ticker, "title": title, "yes_sub_title": sub, "rules_primary": rules,
                        "close_time": close, **kw})


def verdict(p, k):
    return verify(p, k, similarity(p, k, idf_table([p, k])))


def test_extractors():
    nums, years = extract_numbers("Will BTC close above $100,000 or 2.5% in 2027 with 25 bps and 3k and 1.2 billion?")
    assert (100000.0, "$") in nums and (2.5, "%") in nums and (25.0, "bp") in nums
    assert (3000.0, "") in nums and (1.2e9, "") in nums and years == {2027}
    dates, periods, rest = extract_dates("by December 31, 2027 or Oct 5, 2026 in October 2026", None)
    assert dates == {date(2027, 12, 31), date(2026, 10, 5)} and periods == {(2026, 10)} and "2027" not in rest
    d2, _, _ = extract_dates("before Jan 1", 2027)
    assert d2 == {date(2027, 1, 1)}
    assert clock_times("at 12:00 PM ET and 11:59 PM ET and 9 am EST and 3pm PT") == {"12:00", "09:00"}


def test_deadlines_are_new_york_calendar_dates():
    p = poly("1", "Will X happen?", end="2028-01-01T04:59:00Z")  # 11:59 PM ET on Dec 31
    assert p.deadline == date(2027, 12, 31)
    k = kal("K-1", "Will X happen?", close="2027-12-31T15:00:00Z")
    assert k.deadline == date(2027, 12, 31)


FED_DESC = ("The FED interest rates are defined in this market by the upper bound of the target federal funds range. "
            "The resolution source is the FOMC's statement.")
FED_RULES = "If the Federal Reserve does a Cut of 25bps on October 28, 2026, then the market resolves to Yes."


def fed_pair():
    return (poly("p1", "Will the Fed decrease interest rates by 25 bps after the October 2026 meeting?",
                 end="2026-10-29T03:59:00Z", desc=FED_DESC),
            kal("KXFEDDECISION-26OCT-C25", "Will the Federal Reserve Cut rates by 25bps at their October 2026 meeting?",
                close="2026-10-28T18:00:00Z", rules=FED_RULES, sub="Cut 25bps", strike_type="custom"))


def test_positive_pair_verifies_with_every_check_recorded():
    v = verdict(*fed_pair())
    assert v.status == "verified", v.note
    names = {c.name for c in v.checks}
    assert {"event", "subject", "criteria", "predicate", "threshold", "period", "deadline", "direction",
            "source"} <= names
    assert "25bp vs 25bp" in v.note and "gap 0d" in v.note and "shared source ['fed']" in v.note


def test_positive_event_pair_with_one_day_deadline_gap_and_synonyms():
    p = poly("2", "Will Discord IPO by October 31, 2026?", end="2026-11-01T03:59:00Z",
             desc='This market will resolve to "Yes" if Discord shares are listed on a public securities exchange.')
    k = kal("KXIPODISCORD-26NOV01", "When will Discord IPO?", close="2026-11-01T04:59:00Z", sub="Before Nov 1, 2026",
            rules="If Discord confirms an IPO before Nov 1, 2026, then the market resolves to Yes.")
    v = verdict(p, k)
    assert v.status == "verified", v.note
    assert "gap 1d" in v.note


def test_different_threshold_is_rejected_not_ambiguous():
    p = poly("3", "Will the price of Bitcoin be above $100,000 on December 31?", desc="Source: Binance.")
    k = kal("KXBTC-100", "Will the price of Bitcoin be above $110,000 on December 31?", rules="CF Benchmarks.")
    v = verdict(p, k)
    assert v.status == "rejected" and "threshold" in v.reasons


def test_threshold_on_one_side_only_is_not_enough():
    v = verdict(poly("4", "Will unemployment be above 5% in 2026?"), kal("K4", "Will unemployment go above in 2026?"))
    assert v.status in ("ambiguous", "rejected") and "threshold" in v.reasons


def test_deadline_within_a_day_passes_a_few_days_is_ambiguous_a_month_is_rejected():
    mk = lambda close: (poly("5", "Will Acme release Widget 2?", end="2026-12-31T16:59:00Z"),
                        kal("K5", "Will Acme release Widget 2?", close=close))
    assert verdict(*mk("2027-01-01T15:00:00Z")).status == "verified"
    v = verdict(*mk("2027-01-04T15:00:00Z"))
    assert v.status == "ambiguous" and v.reasons == ["deadline"]
    v = verdict(*mk("2027-02-15T15:00:00Z"))
    assert v.status == "rejected" and "deadline" in v.reasons


def test_inverted_direction_is_refused_and_flagged():
    p, _ = fed_pair()
    k = kal("KXFEDDECISION-26OCT-H25", "Will the Federal Reserve Hike rates by 25bps at their October 2026 meeting?",
            close="2026-10-28T18:00:00Z", rules="If the Federal Reserve does a Hike of 25bps on October 28, 2026, "
                                                "then the market resolves to Yes.", sub="Hike 25bps")
    v = verdict(p, k)
    assert v.status == "ambiguous" and "direction_inverted" in v.reasons
    assert "refused" in v.note


def test_negation_is_an_inversion():
    p = poly("6", "Will there be no Google Gemini 5 release by October 31, 2026?", end="2026-11-01T03:59:00Z")
    k = kal("K6", "Will Google release Gemini 5 before Nov 1, 2026?", close="2026-11-01T04:59:00Z")
    v = verdict(p, k)
    assert v.status == "ambiguous" and "direction_inverted" in v.reasons


def test_different_subject_is_rejected():
    p = poly("7", "Will Ted Cruz be the next Supreme Court nominee?")
    k = kal("K7", "Will Ted Lieu be the next Supreme Court nominee?")
    v = verdict(p, k)
    assert v.status == "rejected" and "subject" in v.reasons


def test_different_predicate_nominated_vs_confirmed():
    p = poly("8", "Will Ted Cruz be the next Supreme Court nominee?", end="2029-01-20T04:59:00Z",
             desc="Resolves to the next individual formally nominated to be a Justice.")
    k = kal("K8", "Will Ted Cruz become the next Justice on the Supreme Court?", close="2029-01-21T04:59:00Z",
            rules="If Ted Cruz is the first person confirmed by the Senate as Justice, then Yes.")
    v = verdict(p, k)
    assert v.status == "ambiguous" and "wording_differs" in v.reasons


def test_resolution_condition_naming_something_else_is_not_verified():
    p = poly("9", "New pandemic in 2026?", end="2027-01-01T04:59:00Z",
             desc='Resolves to "Yes" if the WHO declares any disease a pandemic in 2026.')
    k = kal("K9", "New pandemic by 2026?", close="2027-01-01T04:59:00Z",
            rules="If Ebola becomes a pandemic in 2026, then the market resolves to Yes.")
    v = verdict(p, k)
    assert v.status == "ambiguous" and "criteria" in v.reasons


def test_price_markets_need_a_shared_named_source():
    p = poly("10", "Will the price of Bitcoin be above $100,000 on December 31?", end="2027-01-01T04:59:00Z",
             desc="Resolves per the Binance one minute candle.")
    k = kal("K10", "Will the price of Bitcoin be above $100,000 on December 31?", close="2027-01-01T04:59:00Z",
            rules="Resolves per the CF Benchmarks real-time index.")
    v = verdict(p, k)
    assert v.status == "ambiguous" and "source" in v.reasons
    k2 = kal("K11", "Will the price of Bitcoin be above $100,000 on December 31?", close="2027-01-01T04:59:00Z", rules="Per Binance.")
    assert verdict(p, k2).status == "verified"
    # a price market that names no source on either side cannot be verified either
    bare_p = poly("12", "Will the price of Bitcoin be above $100,000 on December 31?", end="2027-01-01T04:59:00Z")
    bare_k = kal("K12", "Will the price of Bitcoin be above $100,000 on December 31?", close="2027-01-01T04:59:00Z")
    assert verdict(bare_p, bare_k).status == "ambiguous"


def test_snapshot_times_must_agree():
    mk = lambda t: kal("K13", "Will claude-x be the top AI model on Oct 5, 2026?", close="2026-10-05T16:00:00Z",
                       rules=f"If claude-x is ranked first on Oct 5, 2026 at {t} ET, then Yes.")
    p = poly("13", "Will claude-x be the best AI model on October 5, 2026?", end="2026-10-05T16:00:00Z",
             desc="Checked on the specified date, 12:00 PM ET, on the leaderboard.")
    assert verdict(p, mk("10:00 AM")).status == "ambiguous"
    assert "snapshot_time" in verdict(p, mk("10:00 AM")).reasons
    assert verdict(p, mk("12:00 PM")).status == "verified"


def test_boundary_inclusivity_must_agree():
    p = poly("14", "Will US CPI inflation be above 3.5% in September?", end="2026-10-15T03:59:00Z")
    k = kal("K14", "Will US CPI inflation be at or above 3.5% in September?", close="2026-10-14T12:00:00Z")
    v = verdict(p, k)
    assert v.status == "ambiguous" and "boundary" in v.reasons


def test_kalshi_strike_type_beats_prose_for_direction():
    k = kal("K15", "CPI for September", close="2026-10-14T12:00:00Z", strike_type="greater_or_equal")
    assert k.directions == {"up"} and k.inclusive is True
    k = kal("K16", "CPI for September", close="2026-10-14T12:00:00Z", strike_type="less")
    assert k.directions == {"down"} and k.inclusive is False


def test_comparison_symbols_are_content():
    p, _ = fed_pair()
    k = kal("KXFEDDECISION-26OCT-C26", "Will the Federal Reserve Cut rates by >25bps at their October 2026 meeting?",
            close="2026-10-28T18:00:00Z", rules=FED_RULES, sub="Cut >25bps")
    assert verdict(p, k).status != "verified"


def test_propose_finds_candidates_and_skips_far_deadlines():
    p, k = fed_pair()
    far = kal("KXFEDDECISION-27JUN-C25", "Will the Federal Reserve Cut rates by 25bps at their June 2027 meeting?",
              close="2027-06-16T18:00:00Z", rules=FED_RULES)
    other = kal("KXOTHER", "Will it rain in Paris?", close="2026-10-28T18:00:00Z")
    cands = propose([p], [k, far, other])
    assert [c[1].id for c in cands] == ["KXFEDDECISION-26OCT-C25"]


def test_one_to_one_two_equally_good_counterparts_are_both_ambiguous():
    p = poly("20", "Will Acme release Widget 2?", end="2026-12-31T16:59:00Z")
    k1 = kal("KA", "Will Acme release Widget 2?", close="2026-12-31T16:59:00Z")
    k2 = kal("KB", "Will Acme release Widget 2?", close="2026-12-31T16:59:00Z")
    pairs = match_all([p], [k1, k2])
    assert {x.verdict.status for x in pairs} == {"ambiguous"}
    assert all(x.verdict.reasons == ["multiple_counterparts"] for x in pairs)


def test_one_to_one_clearly_better_counterpart_wins():
    p = poly("21", "Will Acme release Widget 2?", end="2026-12-31T16:59:00Z")
    good = kal("KA", "Will Acme release Widget 2?", close="2026-12-31T16:59:00Z")
    worse = kal("KB", "Will Acme release Widget 2 with extras?", close="2026-12-31T16:59:00Z",
                rules="Widget 2 extras.")
    st = {x.kalshi.id: x.verdict.status for x in match_all([p], [good, worse])}
    assert st["KA"] == "verified" and st.get("KB") != "verified"
