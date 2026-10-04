import math
import numpy as np
import pytest
from cx1_option_insurance.engine import short_put,event_daily_returns,gate,block_mean,daily_metrics,apply_event_to_book
from cx1_option_insurance.data import valid_quote,underlying_at,OfflineSource,correct_early_closes


def test_flat_mid_short_loses_crossings_and_commissions():
    a=short_put(1,1.2,1,1.2,100,1)
    assert a["gross_pnl"]==0
    assert a["pnl"]==pytest.approx(-21.3)
    assert a["collateral"]==10000
    assert a["event_return"]==pytest.approx(-.00213)


def test_double_costs_cannot_turn_long_loss_into_short_gain():
    one=short_put(2,2.2,1.5,1.9,100,1)
    two=short_put(2,2.2,1.5,1.9,100,2)
    assert one["gross_pnl"]==pytest.approx(two["gross_pnl"])
    assert two["costs_dollars"]==pytest.approx(2*one["costs_dollars"])
    assert two["pnl"]<one["pnl"]


def test_daily_compounding_matches_event_with_fixed_contracts():
    a=short_put(2,2.2,1.5,1.9,100,1)
    for exposure in [0,.5,1]:
        first,second=event_daily_returns(a,exposure)
        assert (1+first)*(1+second)-1==pytest.approx(exposure*a["event_return"])
        assert first<=0


def test_worst_cash_loss_is_bounded_by_full_strike_obligation():
    a=short_put(2,2.2,.01,.02,100,1)
    assert a["max_terminal_loss"]==pytest.approx(9800.65)
    assert a["max_terminal_loss"]<a["collateral"]
    assert a["entry_premium_mid"]!=a["collateral"]


def test_quote_cutoffs_exclude_stale_future_and_preopen():
    q=dict(bid=1,ask=1.1,bid_size=2,ask_size=2,timestamp=1000)
    assert valid_quote(q,1100,600)=="ok"
    assert valid_quote(q,2000,600)=="stale quote"
    assert valid_quote(q,900,600)=="future quote"
    assert valid_quote(q,1100,600,1050)=="quote predates session"


def test_strike_price_uses_completed_bar_and_never_future_close():
    b={"t":np.array([0,300,600]),"c":np.array([100,101,999])}
    assert underlying_at(b,600)==101
    assert underlying_at(b,599)==100


def test_risk_gate_requires_odds_and_activity_on_same_observed_question():
    assert gate([(.5,4)])[0]==.5
    assert gate([(.95,9),(.5,1)])[0]==1
    assert gate([(math.nan,4)])[0]==.5


def test_offline_missing_cache_cannot_make_http_requests(tmp_path,monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session,"get",lambda *a,**k:pytest.fail("network forbidden"))
    src=OfflineSource(tmp_path)
    assert src.quote("O:SPY260101P00100000",1000)[0] is None
    assert "not cached" in src.expiry("2025-12-01")[2]


def test_drawdown_includes_initial_equity_and_compounds():
    m=daily_metrics(["2026-01-01","2026-01-02"],[-.1,.05])
    assert m["total_return"]==pytest.approx(-.055)
    assert m["max_drawdown"]==pytest.approx(-.1)


def test_block_ci_is_deterministic_and_needs_independent_dates():
    assert block_mean([.01]*8)==pytest.approx((.01,.01,.01))
    assert np.isnan(block_mean([.01]*4)[1])


def test_invalid_widened_bid_cannot_be_filled():
    with pytest.raises(ValueError,match="nonpositive"):
        short_put(.1,1,.1,1,100,2)


def test_auction_bar_cannot_push_nyse_halfday_close_to_1305():
    import pandas as pd
    at=int(pd.Timestamp("2025-11-28 13:05",tz="America/New_York").timestamp())
    x=correct_early_closes(pd.DataFrame([dict(day="2025-11-28",open=at-12900,close=at)]))
    close=int(x.close.iloc[0])
    assert pd.Timestamp(close,unit="s",tz="UTC").tz_convert("America/New_York").strftime("%H:%M")=="13:00"
    assert pd.Timestamp(close-300,unit="s",tz="UTC").tz_convert("America/New_York").strftime("%H:%M")=="12:55"


def test_observation_preserves_decision_time_separately_from_quote_time():
    import pandas as pd
    from cx1_option_insurance.run import observe
    class Src:
        def expiry(self,day):return "2026-01-16",{100:"O:SPY260116C00100000"},"ok"
        def quote(self,symbol,at):return dict(bid=1,ask=1.2,bid_size=3,ask_size=4,timestamp=at-.5),"ok"
    op=int(pd.Timestamp("2026-01-09 09:30",tz="America/New_York").timestamp())
    cl=op+390*60;nextop=op+3*86400
    sess=pd.DataFrame([dict(day="2026-01-09",open=op,close=cl),dict(day="2026-01-12",open=nextop,close=nextop+390*60)])
    ts=np.r_[np.arange(op,cl,300),np.arange(nextop,nextop+390*60,300)]
    r=observe(Src(),dict(t=ts,c=np.full(len(ts),100)),sess,{0:[(.5,1)]},0,1,"2026-02-01")
    assert r["entry_timestamp"]==cl-300
    assert r["entry_decision_timestamp"]==cl-300
    assert r["entry_quote_timestamp"]==cl-300-.5
    assert r["exit_timestamp"]==nextop+900
    assert r["exit_quote_timestamp"]==nextop+900-.5


def test_same_session_morning_exit_and_afternoon_entry_compound_nav_and_add_turnover():
    first=short_put(2,2.2,1,1.2,100,1)
    second=short_put(3,3.2,2,2.2,100,1)
    returns=np.zeros(3);turn=np.zeros(3);collturn=np.zeros(3)
    apply_event_to_book(returns,turn,collturn,0,1,first,1)
    morning_nav=1+first["event_return"]
    before,_,_=apply_event_to_book(returns,turn,collturn,1,2,second,1)
    expected=(1+first["event_return"])*(1+second["event_return"])
    assert float(np.prod(1+returns))==pytest.approx(expected,abs=1e-13)
    assert before==pytest.approx(morning_nav)
    assert turn[1]==pytest.approx(first["exit_fill"]*100/first["collateral"]+morning_nav*second["entry_fill"]*100/second["collateral"])
    assert collturn[1]==pytest.approx(1+morning_nav)
