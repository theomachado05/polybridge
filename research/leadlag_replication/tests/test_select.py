"""Sign rule, stem de-duplication and ranking on synthetic gamma metadata (no network)."""
import json

import pandas as pd
import pytest

from leadlag_replication.select import candidates, classify, question_stem


@pytest.mark.parametrize("q,sign", [
    ("Russia x Ukraine ceasefire in 2025?", +1),
    ("Will China invade Taiwan in 2024?", -1),
    ("US government shutdown in 2025?", -1),
    ("Will Trump lower tariffs on China?", +1),
    ("Will the EU impose new tariffs on US goods in 2025?", -1),
    ("US recession by end of 2026?", -1),
    ("Israel x Iran ceasefire broken by December 31?", 0),      # negated
    ("Next Israel x Hamas ceasefire not in 2024?", 0),         # negated
    ("Fed decreases interest rates by 25 bps after September 2025 meeting?", 0),  # monetary policy
    ("Will Trump win the 2024 election?", 0),                  # election
    ("Will the S&P 500 close above 6000?", 0),                 # the outcome itself
    ("Will Bitcoin hit $100k?", 0),                            # no sign term / excluded
    ("Nothing Ever Happens: Military Edition", 0),
    ("Will it rain in Paris?", 0),                             # no sign term
])
def test_classify(q, sign):
    assert classify(q)[0] == sign


def test_question_stem_drops_dates():
    assert question_stem("Russia x Ukraine ceasefire before July?") == question_stem("Russia x Ukraine ceasefire in 2025?") \
        == "russia x ukraine ceasefire"
    assert question_stem("Will China invade Taiwan by end of 2026?") == "china invade taiwan"


def _m(slug, q, vol, start, end, closed=True):
    return {"slug": slug, "question": q, "volumeNum": vol, "startDate": start, "closedTime": end if closed else None,
            "endDate": end, "closed": closed, "clobTokenIds": json.dumps([f"{slug}-yes", f"{slug}-no"]),
            "outcomes": json.dumps(["Yes", "No"]), "conditionId": "0x0", "enableOrderBook": True}


def test_candidates_dedupe_rank_and_one_per_event():
    events = [
        {"slug": "e1", "markets": [_m("a", "Russia x Ukraine ceasefire in 2025?", 100, "2025-01-01", "2025-12-31")]},
        {"slug": "e2", "markets": [_m("b", "Russia x Ukraine ceasefire before July?", 50, "2025-02-01", "2025-07-01")]},
        {"slug": "e3", "markets": [_m("c", "Russia x Ukraine ceasefire in 2024?", 10, "2024-03-01", "2024-12-31")]},
        {"slug": "e4", "markets": [_m("d", "Will China invade Taiwan in 2025?", 80, "2025-01-01", "2025-12-31"),
                                   _m("d2", "Will China blockade Taiwan in 2025?", 90, "2025-01-01", "2025-12-31")]},
        {"slug": "e5", "markets": [_m("e", "US recession in 2025?", 70, "2025-03-01", "2025-04-01")]},   # < 92 days
        {"slug": "e6", "markets": [_m("us-recession-in-2025", "US recession in 2025?", 999, "2025-01-01", "2025-12-31")]},  # original
    ]
    df = candidates(events)
    assert list(df["market_slug"]) == ["a", "d2", "c"]          # b dropped (same stem, overlaps a); one per event; e too short
    assert list(df["rank"]) == [1, 2, 3]
    assert set(df["sign"]) == {1, -1}
    assert (df["window_days"] >= 92).all()
    assert pd.Timestamp(df.iloc[0]["start"]).tzinfo is not None
