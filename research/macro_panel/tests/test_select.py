import json

import pytest

from macro_panel.select import candidates, classify


@pytest.mark.parametrize("q,sign,cls", [
    ("US recession in 2024?", -1, "recession"),
    ("Fed decreases interest rates by 25 bps after September 2025 meeting?", +1, "fed"),
    ("Fed increases interest rates by 25 bps after March meeting?", -1, "fed"),
    ("Fed rate cut by September?", +1, "fed"),
    ("Will inflation reach more than 5% in 2025?", -1, "inflation"),
    ("Will monthly inflation increase by ≥0.4% in June?", -1, "inflation"),
    ("Will the Consumer Price Index rise above 3%?", -1, "inflation"),
    ("CPI below 2.5% in March?", +1, "inflation"),
    ("Unemployment above 4.5% in November?", -1, "unemployment"),
    ("Unemployment rate under 4% in May?", +1, "unemployment"),
    ("Negative GDP growth in Q1 2025?", -1, "gdp"),
    ("US GDP growth in Q2 2025 above 3%?", +1, "gdp"),
])
def test_classify_signed(q, sign, cls):
    s, c, _ = classify(q)
    assert (s, c) == (sign, cls)


@pytest.mark.parametrize("q", [
    "No change in Fed interest rates after June meeting?",
    "Will monthly inflation increase by 0.2% in June?",
    "How many Fed rate cuts in 2025?",
    "Fed emergency rate cut in 2025?",
    "Canada recession in 2025?",
    "Will Trump say recession?",
    "CPI 2.9-3.1%?",
    "Will Powell be out as Fed chair?",
    "Fed cut if recession?",
    "Recession and Fed rate cut in 2025?",
    "Will the S&P 500 fall below 5000?",
    "Will it rain in Paris?",
])
def test_classify_excluded(q):
    assert classify(q)[0] == 0


def _m(slug, q, vol, start, end):
    return {"slug": slug, "question": q, "volumeNum": vol, "startDate": start, "closedTime": end, "endDate": end,
            "closed": True, "clobTokenIds": json.dumps([f"{slug}-yes", f"{slug}-no"]),
            "outcomes": json.dumps(["Yes", "No"]), "conditionId": "0x0", "enableOrderBook": True}


def test_candidates_rank_filters_and_one_per_event():
    events = [
        {"slug": "e1", "markets": [_m("a", "US recession in 2024?", 900_000, "2024-01-01", "2024-12-31")]},
        {"slug": "e2", "markets": [_m("b1", "Fed decreases interest rates by 25 bps after March meeting?", 400_000, "2024-01-10", "2024-03-21"),
                                   _m("b2", "Fed decreases interest rates by 50+ bps after March meeting?", 600_000, "2024-01-10", "2024-03-21"),
                                   _m("b3", "No change in Fed interest rates after March meeting?", 5_000_000, "2024-01-10", "2024-03-21")]},
        {"slug": "e3", "markets": [_m("c", "CPI above 3% in May?", 20_000, "2024-05-01", "2024-06-12")]},
        {"slug": "e4", "markets": [_m("d", "Unemployment above 4% in May?", 80_000, "2024-05-20", "2024-06-07")]},
        {"slug": "e5", "markets": [_m("us-recession-in-2025", "US recession in 2025?", 9e6, "2025-01-01", "2025-12-31")]},
        {"slug": "e6", "markets": [_m("old", "US recession in 2022?", 9e6, "2022-01-01", "2022-12-31")]},
    ]
    df = candidates(events)
    assert list(df["market_slug"]) == ["a", "b2"]
    assert list(df["rank"]) == [1, 2]
    assert list(df["cls"]) == ["recession", "fed"] and list(df["sign"]) == [-1, 1]
