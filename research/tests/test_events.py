import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.events import build_confirmatory_events, build_tag_events
from tests.fakes import FakeClient, disclosure

CAL = TradingCalendar()
UNIVERSE = ("AAPL", "MSFT", "BRK.B")


def _client():
    return FakeClient({
        "material_litigation": [disclosure("a1", "1", ["AAPL"], "2024-03-01"),
                                disclosure("a9", "9", ["ZZZZ"], "2024-03-01")],
        "class_action_filing": [disclosure("a1", "1", ["AAPL"], "2024-03-01")],
        "restructuring_plan": [disclosure("a2", "2", ["MSFT"], "2024-05-04"),
                               disclosure("a3", "3", ["BRK/B"], "2024-06-03")],
        "asset_impairment": [disclosure("a3", "3", ["BRK/B"], "2024-06-03")],
    })


def test_one_event_per_filer_date_family_and_tag_union():
    ev, excluded = build_confirmatory_events(_client(), "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert list(ev.ticker) == ["AAPL", "MSFT"]
    aapl = ev.iloc[0]
    assert aapl.family == "hedge" and aapl.tags == frozenset({"material_litigation", "class_action_filing"})
    assert ev.iloc[1].family == "opportunity"


def test_cross_family_filing_is_excluded_and_counted():
    ev, excluded = build_confirmatory_events(_client(), "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert "BRK.B" not in set(ev.ticker)
    assert list(excluded.accession_number) == ["a3"]
    assert excluded.iloc[0].ticker == "BRK.B"


def test_naive_sessions_from_filing_date():
    ev, _ = build_confirmatory_events(_client(), "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    msft = ev[ev.ticker == "MSFT"].iloc[0]
    assert msft.t_0 == pd.Timestamp("2024-05-06") and msft.t_pre == pd.Timestamp("2024-05-03")


def test_window_filter_and_empty_result_has_columns():
    ev, excluded = build_confirmatory_events(_client(), "2025-01-01", "2025-12-31", UNIVERSE, CAL)
    assert ev.empty and excluded.empty
    assert {"ticker", "family", "t_0", "t_pre", "tags"} <= set(ev.columns)


def test_build_tag_events_single_tag():
    ev = build_tag_events(_client(), "restructuring_plan", "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert list(ev.ticker) == ["MSFT", "BRK.B"]
    empty = build_tag_events(_client(), "cfo_appointment", "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert empty.empty and "t_0" in empty.columns


def test_disclosures_without_tickers_key():
    client = FakeClient({
        "missing_tickers_tag": [
            {"accession_number": "a1", "cik": "1", "filing_date": "2024-03-01",
             "filing_url": "https://www.sec.gov/Archives/edgar/data/1/a1.txt", "supporting_text": "",
             "ticker": "AAPL"}
        ]
    })
    ev = build_tag_events(client, "missing_tickers_tag", "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert list(ev.ticker) == ["AAPL"]
    assert "t_0" in ev.columns


def test_mixed_valid_and_missing_tickers():
    client = FakeClient({
        "mixed_tickers_tag": [
            disclosure("a1", "1", ["AAPL"], "2024-03-01"),
            {"accession_number": "a2", "cik": "2", "tickers": None, "filing_date": "2024-03-02",
             "filing_url": "https://www.sec.gov/Archives/edgar/data/2/a2.txt", "supporting_text": ""},
            disclosure("a3", "3", [], "2024-03-03"),
            disclosure("a4", "4", ["MSFT"], "2024-03-04"),
        ]
    })
    ev = build_tag_events(client, "mixed_tickers_tag", "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert set(ev.ticker) == {"AAPL", "MSFT"}
    assert len(ev) == 2


def test_ticker_singular_fallback_when_tickers_absent():
    client = FakeClient({
        "ticker_fallback_tag": [
            {"accession_number": "a1", "cik": "1", "filing_date": "2024-03-01",
             "filing_url": "https://www.sec.gov/Archives/edgar/data/1/a1.txt", "supporting_text": "",
             "ticker": "AAPL"},
            {"accession_number": "a2", "cik": "2", "filing_date": "2024-03-02",
             "filing_url": "https://www.sec.gov/Archives/edgar/data/2/a2.txt", "supporting_text": "",
             "ticker": "MSFT"},
        ]
    })
    ev = build_tag_events(client, "ticker_fallback_tag", "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert set(ev.ticker) == {"AAPL", "MSFT"}
    assert len(ev) == 2
