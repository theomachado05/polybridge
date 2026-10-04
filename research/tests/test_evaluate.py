import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.evaluate import evaluate
from polybridge_research.pricing import price_events
from polybridge_research.strategies import STRATEGIES
from tests.fakes import FakeClient, FakeMarket

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def _priced():
    ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")],
                       "t_pre": [T("2024-06-03")], "family": ["hedge"]})
    priced, _ = price_events(FakeClient(market=FakeMarket({"AAPL": 100.0})), ev, CAL, CFG, max_workers=1)
    return priced


def test_columns_rows_and_flat_market_values():
    res = evaluate(_priced(), CAL, CFG, last_session=T("2026-09-30"))
    assert set(STRATEGIES) <= set(res.columns) and {"ratio", "family", "implied_scaled"} <= set(res.columns)
    base = res[(res.bucket == "3-6m") & (res.entry == "post") & (res.otm == 0.05)]
    assert set(base.horizon) == {0, 1, 2, 3, 5, 10, 21, 42, 63, "exp"}
    assert (base.family == "hedge").all()
    h21 = base[base.horizon == 21].iloc[0]
    assert abs(h21["stock"]) < 5e-3
    assert abs(h21["protective_put"]) < 5e-3


def test_unresolved_horizons_are_absent():
    res = evaluate(_priced(), CAL, CFG, last_session=T("2024-06-20"))
    base = res[(res.bucket == "3-6m") & (res.entry == "post") & (res.otm == 0.05)]
    assert 21 not in set(base.horizon) and 10 in set(base.horizon)
    assert "exp" not in set(base.horizon)


def test_empty_input():
    res = evaluate([], CAL, CFG, last_session=T("2026-09-30"))
    assert res.empty and "ratio" in res.columns
