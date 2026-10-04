import datetime as dt

import pytest

from app.options.match import match_question, why_no_match

AS_OF = "2026-10-03"


@pytest.mark.parametrize("question,res,expected", [
    ("Will NVDA close above $150 on Dec 31?", None, ("NVDA", 150.0, "2026-12-31", "above")),
    ("S&P 500 above 6000 by end of year", None, ("I:SPX", 6000.0, "2026-12-31", "above")),
    ("Will the S&P 500 be above 7,000 at end of day on Oct 30?", None, ("I:SPX", 7000.0, "2026-10-30", "above")),
    ("Will Apple (AAPL) close above $250 on December 31, 2026 at 4 PM ET?", None, ("AAPL", 250.0, "2026-12-31", "above")),
    ("Will Tesla close below $300 on Nov 20?", None, ("TSLA", 300.0, "2026-11-20", "below")),
    ("Will Tesla finish 2026 below $300?", None, ("TSLA", 300.0, "2026-12-31", "below")),
    ("Nasdaq-100 above 25k on Dec 31?", None, ("I:NDX", 25000.0, "2026-12-31", "above")),
    ("Will Russell 2000 close above 2,500 on Nov 20?", None, ("I:RUT", 2500.0, "2026-11-20", "above")),
    ("Will Nvidia be above $200 on 2027-01-15?", None, ("NVDA", 200.0, "2027-01-15", "above")),
    ("Will Microsoft close at or above $500 by end of December?", None, ("MSFT", 500.0, "2026-12-31", "above")),
    ("Will SPY close above 700 on Dec 18?", None, ("SPY", 700.0, "2026-12-18", "above")),
    ("Will AAPL be above 300?", "2026-11-20T21:00:00Z", ("AAPL", 300.0, "2026-11-20", "above")),
    ("Will Google close above $250 on Jan 15?", "2027-01-16T00:00:00Z", ("GOOGL", 250.0, "2027-01-15", "above")),
    ("S&P 500 above 7000 by end of year?", "2027-01-01T04:59:00Z", ("I:SPX", 7000.0, "2026-12-31", "above")),
    ("Will NVDA close above $250 on Dec 31?", "2027-01-01T04:59:00Z", ("NVDA", 250.0, "2026-12-31", "above")),
    ("Will NVDA close above $250 at the end of December?", "2027-01-01T04:59:00Z",
     ("NVDA", 250.0, "2026-12-31", "above")),
    ("Will NVDA close above $250 on Dec 31?", "2027-01-02T17:00:00Z", ("NVDA", 250.0, "2026-12-31", "above")),
    ("Will NVDA close above $250 on Dec 31?", "2027-01-01", ("NVDA", 250.0, "2026-12-31", "above")),
    ("Will NVDA close above $250 on Dec 31?", "2027-12-31T21:00:00Z", ("NVDA", 250.0, "2027-12-31", "above")),
    ("Nvidia price on Dec 31, 2026? $250 or above", "2027-01-01T04:59:00Z", ("NVDA", 250.0, "2026-12-31", "above")),
    ("S&P 500 on Dec 31, 2026? $6,000 or below", None, ("I:SPX", 6000.0, "2026-12-31", "below")),
])
def test_supported_questions(question, res, expected):
    m = match_question(question, res, as_of=AS_OF)
    assert m is not None, why_no_match(question, res, as_of=AS_OF)
    assert (m.underlying, m.strike, m.expiry.isoformat(), m.direction) == expected
    u, k, e = m
    assert (u, k, e) == (m.underlying, m.strike, m.expiry)


def test_index_proxy_fallback_and_dow_scaling():
    spx = match_question("S&P 500 above 6000 by end of year", as_of=AS_OF)
    assert spx.fallback == ("SPY", 0.1) and not spx.approx
    dow = match_question("Dow Jones above 45000 on December 18?", as_of=AS_OF)
    assert (dow.underlying, dow.strike, dow.approx, dow.level) == ("DIA", 450.0, True, 45000.0)
    assert "approximate" in dow.notes[0]
    assert dow.to_dict()["expiry"] == "2026-12-18"


def test_date_source_is_reported():
    assert match_question("Will NVDA close above $150 on Dec 31?", as_of=AS_OF).date_source == "question"
    assert match_question("Will AAPL be above 300?", "2026-11-20", as_of=AS_OF).date_source == "resolution_date"


@pytest.mark.parametrize("question,reason", [
    ("Will NVDA hit $300 by December 31?", "path"),
    ("Will NVDA reach $300 in 2026?", "path"),
    ("Will Tesla dip to $200 by Dec 31?", "path"),
    ("Will Apple hit an all-time high in 2026?", "path"),
    ("Will Tesla fall below $200 by December 31?", "path"),
    ("Will NVDA drop below $120 by Dec 31?", "path"),
    ("Will Apple rise above $300 by Dec 31?", "path"),
    ("Will Microsoft climb above $600 by end of year?", "path"),
    ("Will TSLA sink below $150 on Dec 31?", "path"),
    ("Will NVDA go above $250 by Dec 31?", "path"),
    ("Nvidia price on Dec 31, 2026? $240 to $249.99", "range"),
    ("Will NVDA close at $240-$250 on Dec 31?", "range"),
    ("Will the price of Bitcoin be above $74,000 on October 3?", "crypto"),
    ("Will Nvidia market cap be above $5 trillion on Dec 31?", "market-cap"),
    ("Will NVDA close between 150 and 160 on Dec 31?", "range"),
    ("Will NVDA be up 10% by Dec 31?", "percent"),
    ("Will CPI be above 3 in December?", "macro"),
    ("Will the Fed cut rates in December?", "no listed underlying"),
    ("Will there be a recession in 2026?", "no listed underlying"),
    ("Will TSLA or NVDA close above $300 on Dec 31?", "more than one"),
    ("Will NVDA close above $150?", "no resolution date"),
    ("Will NVDA close above $150 on Jan 5, 2025?", "no resolution date"),
    ("Will NVDA announce a split on Dec 31?", "no single numeric threshold"),
    ("Will NVDA close above $150 or below $100 on Dec 31?", "no single numeric threshold"),
    ("Will the target price be above 4 on Dec 31?", "no listed underlying"),
    ("Will the market close above 4 PM ET levels on Dec 31?", "no listed underlying"),
    ("", "no question"),
])
def test_refusals_never_guess(question, reason):
    assert match_question(question, as_of=AS_OF) is None
    assert reason in why_no_match(question, as_of=AS_OF)


def test_non_string_input():
    assert match_question(None) is None  # type: ignore[arg-type]
    assert match_question(123) is None  # type: ignore[arg-type]


def test_defaults_to_today_and_next_occurrence_of_month_day():
    m = match_question("Will NVDA close above $150 on Jan 15?", as_of=dt.date(2026, 10, 3))
    assert m.expiry == dt.date(2027, 1, 15)
