from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import numpy as np
import pandas as pd
import pytest
from cx2_merger_bridge.engine import Deal, Quote, EvidenceError, no_payoff, terminal_values, executable_lots, evaluate, portfolio, metrics, cluster_interval, daily_block_interval

T=datetime(2025,1,3,20,45,tzinfo=timezone.utc)
DEADLINE=datetime(2025,6,30,23,59,tzinfo=timezone.utc)

def quote(bid,ask,size=1_000_000):return Quote(bid,ask,T,size,size,'SYNTHETIC fixture')

def deal():
    return Deal('fixture','synthetic-signed-agreement',T,DEADLINE,100,80,tuple([100.]*20),DEADLINE+timedelta(days=30),quote(89.98,90),quote(.04,.06),quote(.99,1.01),1_000_000,True,True,True,True,True,True,('SYNTHETIC fixture, not evidence',))

def marks():
    return pd.DataFrame([
        {'date':T,'stock_value':89.99,'event_value':.05,'put_value':1.,'dividend_per_share':0.,'stock_exit_cost':0.,'event_exit_cost':0.,'put_exit_cost':0.,'source':'SYNTHETIC','terminal_evidence_verified':False},
        {'date':T+timedelta(days=3),'stock_value':85.,'event_value':.15,'put_value':2.,'dividend_per_share':1.,'stock_exit_cost':1.,'event_exit_cost':20.,'put_exit_cost':1.65,'source':'SYNTHETIC','terminal_evidence_verified':True},
    ])

def test_announcement_contract_cannot_insure_postannouncement_failure():
    announced=T;completed=None
    assert no_payoff(basis='announcement',deadline=DEADLINE,announcement=announced,completion=completed)==0
    assert no_payoff(basis='completion',deadline=DEADLINE,announcement=announced,completion=completed)==1

def test_deadline_cutoff_is_inclusive_and_late_close_different():
    assert no_payoff(basis='completion',deadline=DEADLINE,announcement=T,completion=DEADLINE)==0
    assert no_payoff(basis='completion',deadline=DEADLINE,announcement=T,completion=DEADLINE+timedelta(seconds=1))==1

def test_failure_price_distribution_changes_event_hedge_loss():
    moderate=terminal_values(70,0,1,80,2000)
    severe=terminal_values(10,0,1,80,2000)
    assert moderate['event_hedge']==9000
    assert severe['event_hedge']==3000
    assert severe['put_hedge']==8000
    assert severe['event_hedge']<severe['put_hedge']

def test_late_completion_can_pay_stock_and_no():
    terminal=terminal_values(100,0,1,80,2000)
    assert terminal['event_hedge']==12000
    assert terminal['unhedged']==10000

def test_revised_cash_offer_not_frozen_original_success_price():
    original=terminal_values(100,0,0,80,2000)
    revised=terminal_values(110,0,0,80,2000)
    assert revised['event_hedge']-original['event_hedge']==1000

def test_cash_dividend_counted_once_and_adjusted_put_independent():
    x=terminal_values(70,3,1,80,2000,put_cash_deliverable=400)
    assert x['unhedged']==7300
    assert x['put_hedge']==7700
    assert x['event_hedge']==9300

@pytest.mark.parametrize('field',['completion_contract','exact_agreement','signed_cash_deal','rule_known_asof','deliverable_verified','entry_clock_verified'])
def test_required_semantics_and_asof_proof(field):
    with pytest.raises(EvidenceError):executable_lots(replace(deal(),**{field:False}),10000)

@pytest.mark.parametrize('seconds',[-1,61])
def test_no_future_or_stale_fill(seconds):
    d=deal();q=replace(d.event_entry,timestamp=T-timedelta(seconds=seconds))
    with pytest.raises(EvidenceError):executable_lots(replace(d,event_entry=q),10000)

def test_crossed_binary_or_missing_depth_rejected():
    d=deal()
    for q in (quote(.06,.04),quote(.99,1.01),quote(.04,.06,size=10)):
        with pytest.raises(EvidenceError):executable_lots(replace(d,event_entry=q),10000)

def test_expiry_must_follow_contract_deadline():
    with pytest.raises(EvidenceError):executable_lots(replace(deal(),put_expiry=DEADLINE),10000)

def test_cost_mult_fully_funded_and_monotone():
    a=evaluate(deal(),marks(),10000,'event_hedge',1)
    b=evaluate(deal(),marks(),10000,'event_hedge',2)
    assert a.capital_used.iloc[0]<=10000
    assert b.nav.iloc[-1]<a.nav.iloc[-1]
    # A $1 dividend on 100 shares adds $100, not $1 or $10,000.
    no_div=marks();no_div['dividend_per_share']=0
    c=evaluate(deal(),no_div,10000,'event_hedge',1)
    assert a.nav.iloc[-1]-c.nav.iloc[-1]==pytest.approx(100)

def test_first_nav_return_includes_entry_spread():
    c=evaluate(deal(),marks(),10000,'event_hedge',1)
    p=portfolio([c],['2025-01-03','2025-01-06'])
    assert p['return'].iloc[0]<0
    assert p.nav.iloc[-1]-100000==pytest.approx(c.terminal_pnl.iloc[-1])

def test_cash_only_dates_included():
    c=evaluate(deal(),marks(),10000,'event_hedge',1)
    p=portfolio([c],['2025-01-02','2025-01-03','2025-01-06','2025-01-07'])
    assert len(p)==4
    assert p['return'].iloc[0]==0
    assert p['return'].iloc[-1]==0

def test_no_missing_daily_mark_or_double_collateral():
    c=evaluate(deal(),marks(),10000,'event_hedge',1)
    with pytest.raises(EvidenceError):portfolio([c],['2025-01-03','2025-01-04','2025-01-06'])
    with pytest.raises(EvidenceError):portfolio([c]*11,['2025-01-03','2025-01-06'])

def test_no_confidence_or_sharpe_from_no_sample():
    assert cluster_interval([.1]*9) is None
    assert metrics(pd.DataFrame())['sharpe'] is None
    assert cluster_interval([.1]*10)==pytest.approx((.1,.1))

def test_no_fake_last_quote_or_missing_source():
    m=marks();m.loc[1,'terminal_evidence_verified']=False
    with pytest.raises(EvidenceError):evaluate(deal(),m,10000,'event_hedge',1)
    m=marks();m.loc[0,'source']=''
    with pytest.raises(EvidenceError):evaluate(deal(),m,10000,'event_hedge',1)


def test_daily_bootstrap_requires_enough_observations_and_keeps_cash_days():
    assert daily_block_interval([.001]*59) is None
    assert daily_block_interval([.001]*60)==pytest.approx((.001,.001))
    assert daily_block_interval([0.]*60)==pytest.approx((0.,0.))


def test_manual_proof_string_cannot_impersonate_boolean():
    with pytest.raises(EvidenceError):executable_lots(replace(deal(),rule_known_asof="False"),10000)


def test_nonfinite_fee_and_terminal_cash_rejected():
    with pytest.raises(EvidenceError):executable_lots(replace(deal(),event_entry_fee_per_token=float("nan")),10000)
    with pytest.raises(ValueError):terminal_values(float("nan"),0,1,80,2000)
    with pytest.raises(ValueError):terminal_values(70,0,1,80,2000,put_cash_deliverable=float("nan"))
