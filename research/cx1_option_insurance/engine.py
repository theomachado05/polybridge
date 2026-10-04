"""Pure cashsecured-short accounting and chronological block inference."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from . import config as cfg


def short_put(entry_bid: float, entry_ask: float, exit_bid: float, exit_ask: float,
              strike: float, cost_multiplier: float) -> dict:
    vals = np.array([entry_bid, entry_ask, exit_bid, exit_ask, strike, cost_multiplier])
    if not np.all(np.isfinite(vals)) or min(entry_bid, exit_bid, strike, cost_multiplier) <= 0:
        raise ValueError("invalid short-put inputs")
    if entry_ask < entry_bid or exit_ask < exit_bid:
        raise ValueError("crossed quotes")
    em, eh = (entry_bid + entry_ask) / 2, (entry_ask - entry_bid) / 2
    xm, xh = (exit_bid + exit_ask) / 2, (exit_ask - exit_bid) / 2
    fill_entry, mark_entry, fill_exit = em-cost_multiplier*eh, em+cost_multiplier*eh, xm+cost_multiplier*xh
    if fill_entry <= 0:
        raise ValueError("nonpositive stressed entry bid")
    fee = cost_multiplier * cfg.COMMISSION_PER_CONTRACT_SIDE
    mult = cfg.CONTRACT_MULTIPLIER
    collateral = strike*mult
    entry_pnl = (fill_entry-mark_entry)*mult-fee
    exit_pnl = (mark_entry-fill_exit)*mult-fee
    pnl = entry_pnl+exit_pnl
    gross = (em-xm)*mult
    cost = gross-pnl
    return dict(entry_fill=fill_entry, entry_liquidation_mark=mark_entry, exit_fill=fill_exit,
                collateral=collateral, entry_pnl=entry_pnl, exit_pnl=exit_pnl, pnl=pnl,
                gross_pnl=gross, costs_dollars=cost, costs_bp=1e4*cost/collateral,
                costs_share_of_premium=cost/(em*mult), event_return=pnl/collateral,
                gross_event_return=gross/collateral,
                max_terminal_loss=collateral-fill_entry*mult+fee,
                entry_premium_mid=em*mult, roundtrip_premium_notional=(fill_entry+fill_exit)*mult)


def event_daily_returns(accounting: dict, exposure: float) -> tuple[float, float]:
    """Fixed contracts through the closure; second return uses actual reduced Friday equity."""
    if not 0 <= exposure <= 1:
        raise ValueError("collateral exposure must be between zero and one")
    r_entry = exposure*accounting["entry_pnl"]/accounting["collateral"]
    r_exit = exposure*accounting["exit_pnl"]/accounting["collateral"]/(1+r_entry)
    return r_entry, r_exit


def apply_event_to_book(returns,turnover,collateral_turnover,entry_index,exit_index,accounting,exposure):
    """Morning prior exit precedes afternoon new entry; use actual current NAV and add cash flows."""
    before=float(np.prod(1+returns[:entry_index+1]))
    first,second=event_daily_returns(accounting,exposure)
    returns[entry_index]=(1+returns[entry_index])*(1+first)-1
    returns[exit_index]=(1+returns[exit_index])*(1+second)-1
    turnover[entry_index]+=before*exposure*accounting["entry_fill"]*100/accounting["collateral"]
    turnover[exit_index]+=before*exposure*accounting["exit_fill"]*100/accounting["collateral"]
    collateral_turnover[entry_index]+=before*exposure
    collateral_turnover[exit_index]+=before*exposure
    return before,first,second


def gate(states: list[tuple[float, float]]) -> tuple[float, str]:
    """Each pair is current odds and strictly prior/current-morning five-night activity."""
    observed = [(p,a) for p,a in states if np.isfinite(p) and np.isfinite(a)]
    if any(cfg.ODDS_LOW <= p <= cfg.ODDS_HIGH and a >= cfg.ACTIVITY_THRESHOLD_POINTS for p,a in observed):
        return cfg.GATED_COLLATERAL_FRACTION, "active event"
    if not observed:
        return cfg.GATED_COLLATERAL_FRACTION, "unobserved event state"
    return cfg.FULL_COLLATERAL_FRACTION, "observed quiet event state"


def block_mean(values, block: int = cfg.BOOTSTRAP_BLOCK_CLOSURES) -> tuple[float,float,float]:
    arr=np.asarray(values,dtype=float)
    arr=arr[np.isfinite(arr)]
    if len(arr)==0:return math.nan,math.nan,math.nan
    avg=float(arr.mean())
    if len(arr)<5:return avg,math.nan,math.nan
    rng=np.random.default_rng(cfg.BOOTSTRAP_SEED)
    n=len(arr);nblock=int(math.ceil(n/block))
    start=rng.integers(0,n,size=(cfg.BOOTSTRAP_DRAWS,nblock))
    idx=(start[:,:,None]+np.arange(block))%n
    res=arr[idx.reshape(cfg.BOOTSTRAP_DRAWS,-1)[:,:n]].mean(axis=1)
    lo,hi=np.percentile(res,[2.5,97.5])
    return avg,float(lo),float(hi)


def daily_metrics(days, returns) -> dict:
    arr=np.asarray(returns,dtype=float)
    if not len(arr):return {}
    equity=np.cumprod(1+arr)
    peaks=np.maximum.accumulate(np.r_[1.0,equity])[1:]
    dd=equity/peaks-1
    series=pd.Series(arr,index=pd.to_datetime(days))
    monthly=series.groupby(series.index.to_period("M")).apply(lambda x:float(np.prod(1+x)-1))
    sd=float(np.std(arr,ddof=1)) if len(arr)>1 else math.nan
    return dict(daily_observations=len(arr),active_daily_observations=int(np.count_nonzero(arr)),
                mean_daily_return=float(arr.mean()),daily_volatility=sd,
                annualized_sharpe=float(arr.mean()/sd*np.sqrt(cfg.DAYS_PER_YEAR)) if sd>0 else math.nan,
                total_return=float(equity[-1]-1),max_drawdown=float(dd.min()),worst_month=float(monthly.min()),
                annualized_return=float(equity[-1]**(cfg.DAYS_PER_YEAR/len(arr))-1))
