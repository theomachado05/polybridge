"""Reusable verified-input evaluator. Synthetic states never count as evidence."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import math
import numpy as np
import pandas as pd
from . import config as cfg

class EvidenceError(ValueError):
    """The input cannot support the preregistered executable performance test."""

@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    timestamp: datetime
    bid_size: float
    ask_size: float
    source: str

    def validate(self, at: datetime, age: float, binary=False):
        vals=(self.bid,self.ask,self.bid_size,self.ask_size)
        if not all(math.isfinite(x) for x in vals) or self.bid < 0 or self.ask < self.bid or self.bid_size < 0 or self.ask_size < 0:
            raise EvidenceError('invalid crossed, negative or nonfinite quote')
        if binary and self.ask > 1:raise EvidenceError('binary price above one')
        if self.timestamp.tzinfo is None or at.tzinfo is None:raise EvidenceError('timezone required')
        elapsed=(at-self.timestamp).total_seconds()
        if elapsed < 0 or elapsed > age:raise EvidenceError('future or stale quote')
        if not self.source:raise EvidenceError('quote source required')

    @property
    def mid(self):return (self.bid+self.ask)/2

    def cost_price(self, side: str, multiplier: float):
        """Stress costs around the observed midpoint; 2x is a scenario, not a quote."""
        if side not in {'buy','sell'} or multiplier not in cfg.COST_MULTIPLIERS:raise ValueError('bad cost scenario')
        return self.mid + (1 if side=='buy' else -1)*multiplier*(self.ask-self.bid)/2

@dataclass(frozen=True)
class Deal:
    deal_id: str
    agreement_id: str
    entry: datetime
    deadline: datetime
    cash_offer: float
    strike: float
    preannouncement_closes: tuple[float,...]
    put_expiry: datetime
    stock_entry: Quote
    event_entry: Quote
    put_entry: Quote
    prior20_share_volume: float
    completion_contract: bool
    exact_agreement: bool
    signed_cash_deal: bool
    rule_known_asof: bool
    deliverable_verified: bool
    entry_clock_verified: bool
    evidence_urls: tuple[str,...]
    event_entry_fee_per_token: float=0.0
    event_exit_fee_per_token: float=0.0

    @property
    def event_tokens_per_lot(self):return math.floor(cfg.UNIT_TARGET_SHARES*max(self.cash_offer-self.strike,0))

    def validate(self):
        proofs=(self.completion_contract,self.exact_agreement,self.signed_cash_deal,self.rule_known_asof,self.deliverable_verified,self.entry_clock_verified)
        if not all(type(x) is bool and x for x in proofs):
            raise EvidenceError('completion/agreement/as-of/entry/deliverable proof missing')
        if not self.deal_id or not self.agreement_id or not self.evidence_urls:raise EvidenceError('identity and evidence required')
        dates=(self.entry,self.deadline,self.put_expiry)
        if any(x.tzinfo is None for x in dates) or not self.entry < self.deadline < self.put_expiry:raise EvidenceError('deadline/expiry misaligned')
        if len(self.preannouncement_closes)!=cfg.PREANNOUNCEMENT_SESSIONS or not all(math.isfinite(x) and x>0 for x in self.preannouncement_closes):
            raise EvidenceError('20 preannouncement closes required')
        # The selected strike is externally checked against the historical listed chain.
        if not all(math.isfinite(x) and x>0 for x in (self.cash_offer,self.strike,self.prior20_share_volume)):raise EvidenceError('cash, strike and volume must be finite positive values')
        if self.event_tokens_per_lot<=0:raise EvidenceError('positive hedge required')
        if not all(math.isfinite(x) and x>=0 for x in (self.event_entry_fee_per_token,self.event_exit_fee_per_token)):raise EvidenceError('invalid fee')
        for q,age,binary in ((self.stock_entry,60,False),(self.event_entry,60,True),(self.put_entry,30,False)):
            q.validate(self.entry,age,binary)
        if self.put_entry.bid<=0:raise EvidenceError('put needs positive bid')
        if self.prior20_share_volume<=0:raise EvidenceError('volume evidence missing')


def no_payoff(*, basis: str, deadline: datetime, announcement: datetime|None, completion: datetime|None):
    """Do not confuse announcement with completed control transfer; cutoff is inclusive."""
    if basis not in {'announcement','completion'}:raise ValueError('unknown settlement basis')
    instant=announcement if basis=='announcement' else completion
    if deadline.tzinfo is None or (instant is not None and instant.tzinfo is None):raise ValueError('timezone required')
    return float(instant is None or instant>deadline)


def terminal_values(stock_price: float, cash_distribution: float, event_no: float, strike: float, tokens: int, shares=100, put_cash_deliverable: float|None=None):
    """State truth table, not a forecast or backtest. Failure stock_price is observed/input."""
    if not all(math.isfinite(x) and x>=0 for x in (stock_price,cash_distribution,strike,tokens,shares)) or event_no not in (0,1):raise ValueError('invalid terminal state')
    put=max(strike-stock_price,0)*shares if put_cash_deliverable is None else put_cash_deliverable
    if not math.isfinite(put) or put<0:raise ValueError('invalid option cash deliverable')
    stock=shares*(stock_price+cash_distribution)
    return {'unhedged':stock,'event_hedge':stock+tokens*event_no,'put_hedge':stock+put}


def unit_entry_cost(deal: Deal, strategy: str, mult: float):
    stock=100*deal.stock_entry.cost_price('buy',mult)
    if strategy=='unhedged':return stock
    if strategy=='event_hedge':return stock+deal.event_tokens_per_lot*(deal.event_entry.cost_price('buy',mult)+mult*deal.event_entry_fee_per_token)
    if strategy=='put_hedge':return stock+100*deal.put_entry.cost_price('buy',mult)+mult*cfg.OPTION_COMMISSION_PER_CONTRACT_SIDE
    raise ValueError('unknown comparator')


def executable_lots(deal: Deal, allocation: float):
    """Common lots for same target exposure, funded for the expensive 2x comparator."""
    deal.validate()
    if not math.isfinite(allocation) or allocation<=0 or allocation>cfg.STARTING_CAPITAL*cfg.MAX_DEAL_CAPITAL_FRACTION:
        raise EvidenceError('allocation exceeds preregistered deal cap')
    capital=math.floor(allocation/max(unit_entry_cost(deal,s,2) for s in ('unhedged','event_hedge','put_hedge')))
    limits=(capital,math.floor(deal.stock_entry.ask_size*0.01/100),math.floor(deal.event_entry.ask_size*0.01/deal.event_tokens_per_lot),math.floor(deal.put_entry.ask_size*0.01),math.floor(deal.prior20_share_volume*0.01/100))
    lots=max(0,min(limits))
    if lots<1:raise EvidenceError('capital or verified depth insufficient for one common lot')
    return lots


def evaluate(deal: Deal, marks: pd.DataFrame, allocation: float, strategy: str, cost_mult: float):
    """Marks columns: date, stock/event/put mid and exit value, dividend_per_share.

    Last exit values must already encode quote-side liquidation or actual independent cash
    settlements. Exit costs (spread shortfall + fee + commission) are explicit nonnegative
    dollars per lot. Each leg may settle on a different day: replace its marks with cash
    value thereafter. Mark and terminal sources are mandatory, not silently forward-filled.
    """
    lots=executable_lots(deal,allocation)
    required={'date','stock_value','event_value','put_value','dividend_per_share','stock_exit_cost','event_exit_cost','put_exit_cost','source','terminal_evidence_verified'}
    if not required.issubset(marks):raise EvidenceError('missing daily input columns')
    m=marks.copy();m['date']=pd.to_datetime(m['date'],utc=True)
    if len(m)<2 or not m.date.is_monotonic_increasing or m.date.duplicated().any():raise EvidenceError('nonunique or insufficient daily marks')
    if m.date.iloc[0] != pd.Timestamp(deal.entry):raise EvidenceError('entry mark timestamp mismatch')
    if m.source.fillna('').eq('').any() or m.terminal_evidence_verified.iloc[-1] != True:raise EvidenceError('missing mark/terminal evidence')
    if m[list(required-{'date','source','terminal_evidence_verified'})].isna().any().any():raise EvidenceError('missing values')
    numeric=m[list(required-{'date','source','terminal_evidence_verified'})].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric<0).any():raise EvidenceError('invalid values')
    if (m.event_value>1).any():raise EvidenceError('invalid binary marks')
    if (m[['stock_exit_cost','event_exit_cost','put_exit_cost']].iloc[:-1].to_numpy()!=0).any():raise EvidenceError('liquidation costs only on final row')
    capital_used=lots*unit_entry_cost(deal,strategy,cost_mult)
    cash=allocation-capital_used
    if cash < -1e-8:raise EvidenceError('unfunded collateral/premium')
    values=100*m.stock_value.to_numpy()
    costs=m.stock_exit_cost.to_numpy()
    if strategy=='event_hedge':
        values=values+deal.event_tokens_per_lot*m.event_value.to_numpy();costs=costs+m.event_exit_cost.to_numpy()
    elif strategy=='put_hedge':
        values=values+100*m.put_value.to_numpy();costs=costs+m.put_exit_cost.to_numpy()
    elif strategy!='unhedged':raise ValueError('unknown comparator')
    distributions=100*m.dividend_per_share.cumsum().to_numpy()
    nav=cash+lots*(values+distributions-cost_mult*costs)
    # Append pre-entry NAV so the first actual daily return includes entry friction.
    out=pd.DataFrame({'date':m.date,'deal_id':deal.deal_id,'strategy':strategy,'cost_mult':cost_mult,'nav':nav,'allocation':allocation,'lots':lots,'capital_used':capital_used})
    out['daily_pnl']=out.nav.diff();out.loc[out.index[0],'daily_pnl']=out.nav.iloc[0]-allocation
    out['terminal_pnl']=nav[-1]-allocation
    # Redemption/settlement cash is not automatically traded turnover.
    turnover_column=f'{strategy}_traded_dollars_per_lot'
    out['turnover_dollars']=lots*float(m[turnover_column].sum()) if turnover_column in m else np.nan
    return out


def portfolio(deal_curves: list[pd.DataFrame], calendar: list[str], capital=cfg.STARTING_CAPITAL):
    """Aggregate concurrent, fully funded deals without dropping inactive calendar days."""
    if not calendar or capital<=0:raise EvidenceError('calendar/capital required')
    days=pd.DatetimeIndex(pd.to_datetime(calendar,utc=True)).normalize()
    if days.duplicated().any() or not days.is_monotonic_increasing:raise EvidenceError('invalid calendar')
    pnl=pd.Series(0.,index=days);live=pd.Series(0.,index=days)
    for curve in deal_curves:
        c=curve.copy();c['day']=pd.to_datetime(c.date,utc=True).dt.normalize()
        if c.day.duplicated().any() or not c.day.isin(days).all():raise EvidenceError('curve/calendar mismatch')
        required_days=days[(days>=c.day.iloc[0])&(days<=c.day.iloc[-1])]
        if list(c.day)!=list(required_days):raise EvidenceError('missing active daily marks')
        pnl.loc[c.day]+=c.daily_pnl.to_numpy();live.loc[required_days]+=float(c.allocation.iloc[0])
    if (live>capital+1e-8).any():raise EvidenceError('portfolio collateral exceeds starting capital')
    nav=capital+pnl.cumsum()
    if (nav<=0).any():raise EvidenceError('insolvent portfolio')
    prior=nav.shift(1,fill_value=capital)
    return pd.DataFrame({'date':days,'nav':nav.to_numpy(),'return':(nav/prior-1).to_numpy(),'active_allocation':live.to_numpy()})


def metrics(curve: pd.DataFrame):
    if curve.empty:return {'observations':0,'sharpe':None,'total_return':None,'max_drawdown':None,'worst_month':None}
    r=curve['return'].to_numpy();n=len(r);sd=np.std(r,ddof=1) if n>1 else 0
    sharpe=float(np.mean(r)/sd*np.sqrt(252)) if sd>0 else None
    nav=curve.nav.to_numpy();peak=np.maximum.accumulate(np.r_[cfg.STARTING_CAPITAL,nav])[1:]
    month=curve.assign(month=pd.to_datetime(curve.date).dt.strftime('%Y-%m')).groupby('month')['return'].agg(lambda x:float(np.prod(1+x)-1))
    return {'observations':n,'sharpe':sharpe,'total_return':float(np.prod(1+r)-1),'max_drawdown':float(np.min(nav/peak-1)),'worst_month':float(month.min())}


def cluster_interval(values: list[float], minimum=cfg.MIN_DEAL_CLUSTERS):
    """Call once per independent deal, never once per deal-day."""
    x=np.asarray(values,dtype=float)
    if len(x)<minimum or not np.isfinite(x).all():return None
    rng=np.random.default_rng(cfg.BOOTSTRAP_SEED)
    sample=x[rng.integers(0,len(x),(cfg.BOOTSTRAP_REPLICATIONS,len(x)))].mean(axis=1)
    return tuple(float(z) for z in np.quantile(sample,[.025,.975]))


def daily_block_interval(returns: list[float]):
    """Circular five-session blocks retain short runs of correlated daily returns."""
    x=np.asarray(returns,dtype=float);n=len(x)
    if n<cfg.MIN_RECENT_DAILY_OBSERVATIONS or not np.isfinite(x).all():return None
    rng=np.random.default_rng(cfg.BOOTSTRAP_SEED)
    block=cfg.DAILY_BOOTSTRAP_BLOCK
    starts=rng.integers(0,n,(cfg.BOOTSTRAP_REPLICATIONS,math.ceil(n/block)))
    indices=(starts[:,:,None]+np.arange(block))%n
    means=x[indices.reshape(cfg.BOOTSTRAP_REPLICATIONS,-1)[:,:n]].mean(axis=1)
    return tuple(float(v) for v in np.quantile(means,[.025,.975]))
