import math

import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.costs import cost_table, half_spread
from polybridge_research.evaluate import evaluate
from polybridge_research.pricing import price_events
from tests.fakes import FakeClient, FakeMarket

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


class QuoteClient(FakeClient):
    def __init__(self, market, spread):
        super().__init__(market=market)
        self.spread = spread
        self.quote_params = []

    def get(self, path_or_url, params=None):
        if path_or_url.startswith("/v3/quotes/"):
            self.quote_params.append(params)
            if self.spread is None:
                return {"results": []}
            return {"results": [{"bid_price": 1.0, "ask_price": 1.0 + self.spread}]}
        return super().get(path_or_url, params)


def _setup(spread):
    c = QuoteClient(FakeMarket({"AAPL": 100.0}), spread)
    ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")],
                       "t_pre": [T("2024-06-03")], "family": ["hedge"]})
    priced, _ = price_events(c, ev, CAL, CFG, max_workers=1)
    return c, priced, evaluate(priced, CAL, CFG, last_session=T("2026-09-30"))


def test_half_spread_and_timestamp_bound():
    c, _, _ = _setup(0.10)
    assert math.isclose(half_spread(c, "O:X", T("2024-06-04")), 0.05)
    ts = c.quote_params[-1]["timestamp.lte"]
    assert ts == int(pd.Timestamp("2024-06-04 16:00", tz="America/New_York").value)


def test_cost_table_haircut_and_spread():
    c, priced, res = _setup(0.10)
    tbl = cost_table(res, priced, "protective_put", 21, CFG, client=c)
    row = tbl.iloc[0]
    assert math.isclose(row.premium_traded, 1.0 / row_spot(res), rel_tol=1e-6)
    assert math.isclose(row.haircut_cost_2x, 2 * row.haircut_cost_1x)
    assert math.isclose(row.spread_cost, (0.05 + 0.05) / row_spot(res), rel_tol=1e-6)
    assert row.leg_volume == 50
    assert math.isclose(row.net_spread, row.gross - row.spread_cost)


def test_missing_quotes_give_nan_spread_not_zero():
    c, priced, res = _setup(None)
    row = cost_table(res, priced, "protective_put", 21, CFG, client=c).iloc[0]
    assert math.isnan(row.spread_cost) and not math.isnan(row.haircut_cost_1x)


def row_spot(res):
    r = res[(res.bucket == "3-6m") & (res.entry == "post") & (res.otm == 0.05) & (res.horizon == 21)]
    return float(r.S_entry.iloc[0])
