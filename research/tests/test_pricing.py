import math

import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.pricing import fetch_chain, locate_spot, price_events, select_strikes
from tests.fakes import FakeClient, FakeMarket

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def _client():
    return FakeClient(market=FakeMarket({"AAPL": 100.0, "MSFT": 400.0, "ILLQ": 50.0}))


def test_locate_spot_recovers_price_from_parity():
    c = _client()
    chain = fetch_chain(c, "AAPL", T("2024-06-03"), 2, 180)
    loc = locate_spot(c, chain, T("2024-06-03"), CFG.risk_free)
    assert loc is not None and abs(loc["spot"] / 100.0 - 1) < 0.01


def test_select_strikes_atm_and_otm():
    c = _client()
    chain = fetch_chain(c, "AAPL", T("2024-06-03"), 90, 180)
    e = chain[chain.expiration_date == chain.expiration_date.min()]
    s = select_strikes(e, 100.0, [0.05], CFG.strike_window)
    assert s["K"] == 100.0 and s["U0.05"] == 105.0 and s["L0.05"] == 95.0


def test_price_events_all_buckets_and_input_order():
    ev = pd.DataFrame({"ticker": ["MSFT", "AAPL"], "filing_date": [T("2024-06-04")] * 2,
                       "t_0": [T("2024-06-04")] * 2, "t_pre": [T("2024-06-03")] * 2, "family": ["hedge", "opportunity"]})
    priced, dropped = price_events(_client(), ev, CAL, CFG, max_workers=4)
    assert dropped.empty
    assert [p.ticker for p in priced][:3] == ["MSFT"] * 3
    assert {p.bucket for p in priced} == {"1m", "2m", "3-6m"}
    pe = next(p for p in priced if p.ticker == "AAPL" and p.bucket == "3-6m")
    assert pe.family == "opportunity"
    assert set(pe.legs) == {"C_K", "P_K", "C_U0.03", "P_L0.03", "C_U0.05", "P_L0.05", "C_U0.1", "P_L0.1"}
    assert abs(pe.synthetic_spot(T("2024-06-04")) / 100.0 - 1) < 0.02


def test_illiquid_underlying_is_dropped_with_reason_not_priced_at_zero():
    ev = pd.DataFrame({"ticker": ["ILLQ"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")], "t_pre": [T("2024-06-03")]})
    priced, dropped = price_events(_client(), ev, CAL, CFG, max_workers=1)
    assert priced == []
    assert len(dropped) == 1 and "spot" in dropped.reason.iloc[0]


def test_stale_mark_is_nan():
    ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")], "t_pre": [T("2024-06-03")]})
    priced, _ = price_events(_client(), ev, CAL, CFG, max_workers=1)
    leg = priced[0].legs["C_K"]
    leg.bars = leg.bars.loc[: T("2024-06-03")]
    assert math.isnan(leg.mark(T("2024-06-12")))
    assert not math.isnan(leg.mark(T("2024-06-05")))


def test_empty_events_returns_empty():
    ev = pd.DataFrame(columns=["ticker", "filing_date", "t_0", "t_pre"])
    priced, dropped = price_events(_client(), ev, CAL, CFG)
    assert priced == [] and dropped.empty and list(dropped.columns) == ["ticker", "t_0", "reason"]
