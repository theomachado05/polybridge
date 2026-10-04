"""Read-only S6/S18/S19 reproduction and labelled post-hoc micro cuts. No network or original-file writes.

Run from research/: .venv/bin/python -m cx5_strategy_selection.option_micro_audit
Outputs OPTION_MICRO_*.csv under results/cx5_strategy_selection/.
"""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
import numpy as np
import pandas as pd

RESEARCH=Path(__file__).resolve().parents[1]
OUT=RESEARCH/"results/cx5_strategy_selection"
READ=set()
BOOT_DRAWS=2000
BOOT_SEED=0


def cash_requirement(flows):
    """Minimum initial free cash, with redemptions available before entries at equal times."""
    ordered=sorted(flows,key=lambda a:(a[0],-a[1]))
    free=minimum=0.0
    for _,v in ordered:
        free+=v;minimum=min(minimum,free)
    needed=-minimum
    funded=needed
    for _,v in ordered:
        funded+=v
        assert funded>=-1e-8, "Unfunded entry in minimum-cash diagnostic"
    assert math.isclose(funded,needed+free,abs_tol=1e-8)
    return needed,free


def financial_self_checks():
    # Fully funded NO purchased for 50 + 1 fee; wins 100 or loses the stake.
    assert cash_requirement([(1,-51),(2,100)])==(51,49)
    assert cash_requirement([(1,-51),(2,0)])==(51,-51)
    # Same-time redemption funds a later position; a prior loss increases required cash.
    assert cash_requirement([(1,-51),(2,-80),(2,100),(3,0)])==(51,-31)
    assert cash_requirement([(1,-51),(2,0),(3,-80),(4,100)])==(131,-31)
    assert cash_requirement([(1,-51),(1,-20),(2,100),(3,10)])==(71,39)


def read(study,name):
    p=RESEARCH/"results"/study/name
    READ.add(p)
    return pd.read_csv(p)


def cluster_ci(frame,col,group="event",string_keys=False):
    d=frame[frame[col].notna()].copy()
    if string_keys:d[group]=d[group].astype(str)
    g=d.groupby(group,sort=True)[col].agg(["sum","count"])
    if not len(g):return math.nan,math.nan,math.nan,0
    means=d[col].mean();ix=np.random.default_rng(BOOT_SEED).integers(0,len(g),size=(BOOT_DRAWS,len(g)))
    draws=g["sum"].to_numpy()[ix].sum(1)/g["count"].to_numpy()[ix].sum(1)
    lo,hi=np.percentile(draws,[2.5,97.5])
    return float(means),float(lo),float(hi),len(g)


def cash_book(d,col,pcol,zcol,entry_col):
    """Reproduce fixed-capital settlement-P&L metric, plus transparent cash/time diagnostics."""
    x=d[d[col].notna()].copy()
    if not len(x):return {}
    x["q"]=np.minimum(x[zcol],100)
    x["pnl_cash"]=x.q*x[col]/100
    x["capital_cash"]=x.q*(1-x[pcol])
    x["fee_cash"]=x.q*(x[pcol]-x.outcome)-x.pnl_cash
    x["payoff_cash"]=x.q*(1-x.outcome)
    x["locked_days"]=(x.result_epoch-x[entry_col])/86400
    x["result_month"]=pd.to_datetime(x.result_epoch,unit="s",utc=True).dt.strftime("%Y-%m")
    months=pd.period_range(x.result_month.min(),x.result_month.max(),freq="M").astype(str)
    pc=x.groupby("result_month").pnl_cash.sum().reindex(months,fill_value=0)
    # Peak locked stakes, as original code, and separate funded-cash availability with fee/payment flows.
    marks=sorted([(a,c) for a,c in zip(x[entry_col],x.capital_cash)]+[(a,-c) for a,c in zip(x.result_epoch,x.capital_cash)],key=lambda a:(a[0],a[1]))
    locked=peak=0.0
    for _,v in marks:locked+=v;peak=max(peak,locked)
    flows=[(a,-(c+f)) for a,c,f in zip(x[entry_col],x.capital_cash,x.fee_cash)]+[(a,p) for a,p in zip(x.result_epoch,x.payoff_cash)]
    minimum_cash,terminal_cash=cash_requirement(flows)
    assert math.isclose(terminal_cash,x.pnl_cash.sum(),abs_tol=1e-8), "Cash flows must reconcile with net P&L"
    assert (x.locked_days>=0).all(), "Entry must precede result"
    curve=np.r_[0,pc.cumsum()/peak];dd=np.maximum.accumulate(curve)-curve
    ev=x.groupby("event").pnl_cash.sum()
    durations=x.capital_cash*x.locked_days
    return dict(capped_book_markets=len(x),capped_book_events=x.event.nunique(),settlement_months=len(pc),
                capped_book_pnl=x.pnl_cash.sum(),peak_locked_cash=peak,minimum_initial_cash_with_recycling=minimum_cash,
                settlement_month_sharpe=pc.mean()/pc.std(ddof=1)*math.sqrt(12) if len(pc)>2 and pc.std(ddof=1)>0 else math.nan,
                drawdown_in_units_of_fixed_peak_cash=dd.max(),worst_month_in_units_of_fixed_peak_cash=(pc/peak).min(),
                worst_event_cash=ev.min(),best_event_cash=ev.max(),
                best_event_id=str(ev.idxmax()),best_event_share_of_net_pnl=ev.max()/x.pnl_cash.sum() if x.pnl_cash.sum()>0 else math.nan,
                net_pnl_ex_best_event=x.pnl_cash.sum()-ev.max(),capital_days=durations.sum(),
                median_days_locked=x.locked_days.median(),capital_weighted_days_locked=durations.sum()/x.capital_cash.sum(),
                capital_opportunity_cost_at_assumed_4pct=durations.sum()*.04/365,
                net_cash_after_assumed_4pct_opportunity_cost=x.pnl_cash.sum()-durations.sum()*.04/365,
                printed_sell_size_median=x[zcol].median(),listing_calendar_days=pd.to_datetime(x[entry_col],unit="s",utc=True).dt.date.nunique(),
                listing_calendar_months=pd.to_datetime(x[entry_col],unit="s",utc=True).dt.strftime("%Y-%m").nunique())


def add_cut(rows,study,cut,d,entry_col,string_keys=False):
    for segment in ["IS","OOS","ALL"]:
        x=d if segment=="ALL" else d[d.segment==segment]
        x=x[x.sell_pnl_points.notna()].copy()
        for costs,col in [(1,"sell_pnl_points"),(2,"sell_pnl_points_2x_fee")]:
            mean,lo,hi,n=cluster_ci(x,col,string_keys=string_keys)
            row=dict(study=study,cut=cut,segment=segment,fee_multiplier=costs,markets=len(x),events=n,
                     mean_pnl_points=mean,event_cluster_ci_low=lo if n>=5 else math.nan,event_cluster_ci_high=hi if n>=5 else math.nan,
                     descriptive_small_n_boot_ci_low=lo if 0<n<5 else math.nan,descriptive_small_n_boot_ci_high=hi if 0<n<5 else math.nan,
                     ci_note="Original >=5-event reporting convention" if n>=5 else "Fewer than5events; small-n empirical bootstrap only, no tail guarantee",
                     mean_traded_price=x.sell_price.mean(),resolved_yes_share=x.outcome.mean(),
                     gross_mean_pnl_points=100*(x.sell_price-x.outcome).mean(),
                     fee_mean_pnl_points=100*(x.sell_price-x.outcome).mean()-mean)
            row.update(cash_book(x,col,"sell_price","sell_size",entry_col))
            if len(x):
                removed=x[x.event.astype(str)!=row["best_event_id"]]
                em,el,eh,en=cluster_ci(removed,col,string_keys=string_keys)
                row.update(mean_pnl_points_ex_best_cash_event=em,events_ex_best_cash_event=en,
                           ex_best_cash_event_ci_low=el if en>=5 else math.nan,ex_best_cash_event_ci_high=eh if en>=5 else math.nan)
                carry_per_contract=(1-x.sell_price)*(x.result_epoch-x[entry_col])/86400*.04/365*100
                row["mean_pnl_points_less_assumed_4pct_carry"]=float((x[col]-carry_per_contract).mean())
            rows.append(row)


def add_buyer_cut(rows,study,cut,d,string_keys=False):
    for segment in ["IS","OOS","ALL"]:
        x=d if segment=="ALL" else d[d.segment==segment]
        for costs,col in [(1,"buy_pnl_points"),(2,"buy_pnl_points_2x_fee")]:
            y=x[x[col].notna()]
            mean,lo,hi,n=cluster_ci(y,col,string_keys=string_keys)
            rows.append(dict(study=study,cut=cut+"_BUYER_COUNTERPART",segment=segment,fee_multiplier=costs,
                             markets=len(y),events=n,mean_pnl_points=mean,
                             event_cluster_ci_low=lo if n>=5 else math.nan,event_cluster_ci_high=hi if n>=5 else math.nan,
                             descriptive_small_n_boot_ci_low=lo if 0<n<5 else math.nan,descriptive_small_n_boot_ci_high=hi if 0<n<5 else math.nan,
                             mean_traded_price=y.buy_price.mean(),resolved_yes_share=y.outcome.mean(),
                             printed_buy_size_median=y.buy_size.median()))


def verify_saved(rows,tests,books,study):
    """Headline reconstruction must match committed outputs rather than merely look similar."""
    for segment,scope in [("ALL","all markets"),("IS","in-sample events"),("OOS","out-of-sample events")]:
        r=next(a for a in rows if a["study"]==study and a["cut"]=="ALL_TRADED_SELLERS" and a["segment"]==segment and a["fee_multiplier"]==1)
        t=tests[(tests.test=="sellers: sold YES into a bid, held to the result")&(tests.scope==scope)].iloc[0]
        b=books[(books.book=="sellers")&(books.segment==segment)].iloc[0]
        for key,original in [("mean_pnl_points",t.mean_pnl_points),("event_cluster_ci_low",t.ci_lo),("event_cluster_ci_high",t.ci_hi),
                             ("capped_book_pnl",b.pnl),("peak_locked_cash",b.capital_base),("settlement_month_sharpe",b.sharpe),
                             ("drawdown_in_units_of_fixed_peak_cash",b.max_drawdown)]:
            assert math.isclose(r[key],original,rel_tol=1e-9,abs_tol=1e-8),(study,segment,key,r[key],original)


def main():
    financial_self_checks()
    rows=[]
    s18=read("s18_price_market_calibration","prints_markets.csv")
    e18=read("s18_price_market_calibration","entries.csv")
    s18=s18.merge(e18[["market","entry_epoch","result_epoch","kind"]],on="market",validate="one_to_one")
    tests18=read("s18_price_market_calibration","prints_tests.csv");books18=read("s18_price_market_calibration","prints_book.csv")
    index=s18[s18.asset_class=="sp500"]
    spy=index[index.question.str.contains(r"\bSPY\b",regex=True)]
    spx=index[index.question.str.contains(r"\bSPX\b",regex=True)]
    assert len(spy)+len(spx)==len(index), "Every S&P question must have an explicit reference"
    monthly_spy=spy[~spy.question.str.contains("Week",case=False)]
    cuts={"ALL_TRADED_SELLERS":s18,"ACTUAL_VWAP_50_TO_75":s18[(s18.sell_price>=.5)&(s18.sell_price<.75)],
          "SP500_MIXED_ROOT_HORIZON":index,"SPY_ALL_HORIZONS_COMPARATOR":spy,"SPY_MONTHLY_TOUCH_PRIMARY_CANDIDATE":monthly_spy,
          "SPY_WEEKLY_TOUCH_COMPARATOR":spy[spy.question.str.contains("Week",case=False)],
          "SPX_MONTHLY_TOUCH_COMPARATOR":spx[~spx.question.str.contains("Week",case=False)],"SPY_MONTHLY_TOUCH_VWAP50_TO75_DIAGNOSTIC":monthly_spy[(monthly_spy.sell_price>=.5)&(monthly_spy.sell_price<.75)],
          "STOCK_TOUCH_COMPARATOR":s18[s18.asset_class=="stock"],"CRUDE_TOUCH_COMPARATOR":s18[s18.asset_class=="crude"]}
    for cut,frame in cuts.items():add_cut(rows,"S18",cut,frame,"entry_epoch")
    add_buyer_cut(rows,"S18","ALL_TRADED",s18)
    add_buyer_cut(rows,"S18","ACTUAL_BUY_VWAP_50_TO_75",s18[(s18.buy_price>=.5)&(s18.buy_price<.75)])
    for cut in ["SP500_MIXED_ROOT_HORIZON","SPY_MONTHLY_TOUCH_PRIMARY_CANDIDATE","SPX_MONTHLY_TOUCH_COMPARATOR"]:
        add_buyer_cut(rows,"S18",cut,cuts[cut])
    verify_saved(rows,tests18,books18,"S18")
    s19=read("s19_crypto_price_markets","markets.csv")
    tests19=read("s19_crypto_price_markets","tests.csv");books19=read("s19_crypto_price_markets","book.csv");read("s19_crypto_price_markets","book_monthly_sellers.csv")
    add_cut(rows,"S19","ALL_TRADED_SELLERS",s19,"start_epoch",True)
    add_buyer_cut(rows,"S19","ALL_TRADED",s19,True)
    verify_saved(rows,tests19,books19,"S19")
    # Reproduce the S6 all/verified cohorts without calling its protected forward-data calibration.
    s6=read("s6_monday_fade","trades.csv");eq=read("s6_monday_fade","equity.csv");m=read("s6_monday_fade","metrics.csv")
    for cost in [1,2]:
        t=s6[(s6.variant=="V0")&(s6.cost_mult==cost)]
        source=m[(m.variant=="V0")&(m.cost_mult==cost)&(m.segment=="ALL")].iloc[0]
        annual=(source.sharpe/source.daily_sharpe)**2
        for segment in ["IS","OOS","ALL"]:
            x=t if segment=="ALL" else t[t.segment==segment]
            for cohort in ["MODELLED_100_CONTRACTS","PRINT_SUPPORTED_CAPPED_SIZE"]:
                y=x if cohort.startswith("MODELLED") else x[x.verified]
                col="pnl" if cohort.startswith("MODELLED") else "pnl_verified"
                mean,lo,hi,n=cluster_ci(y,col,"closure")
                grid=eq[(eq.variant=="V0")&(eq.cost_mult==cost)].copy()
                if segment!="ALL":
                    cutoff=m[(m.variant=="V0")&(m.cost_mult==cost)&(m.segment=="OOS")].iloc[0]
                    # The original45-closure grid is independently split into its latest9closures.
                    count=int(cutoff.closures)
                    dates=grid.closure.tolist();allowed=dates[-count:] if segment=="OOS" else dates[:-count]
                    grid=grid[grid.closure.isin(allowed)]
                pc=y.groupby("closure")[col].sum().reindex(grid.closure,fill_value=0)
                rows.append(dict(study="S6",cut=cohort,segment=segment,fee_multiplier=cost,markets=len(y),events=n,
                                 mean_pnl_dollars_capped_cohort=mean,event_cluster_ci_low_dollars=lo if n>=5 else math.nan,
                                 event_cluster_ci_high_dollars=hi if n>=5 else math.nan,capped_book_pnl=y[col].sum(),
                                 closure_grid_sharpe=pc.mean()/pc.std(ddof=1)*math.sqrt(annual) if len(pc)>2 and pc.std(ddof=1)>0 else math.nan,
                                 closure_annualization=annual,closure_calendar_observations=len(grid)))
    OUT.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT/"OPTION_MICRO_METRICS.csv",index=False)
    events=[]
    for cut in ["SP500_MIXED_ROOT_HORIZON","SPY_MONTHLY_TOUCH_PRIMARY_CANDIDATE","SPX_MONTHLY_TOUCH_COMPARATOR","SPY_WEEKLY_TOUCH_COMPARATOR"]:
        d=cuts[cut]
        for event,x in d.groupby("event"):
            seller=x[x.sell_pnl_points.notna()];buyer=x[x.buy_pnl_points.notna()]
            q=np.minimum(seller.sell_size,100)
            events.append(dict(cut=cut,event=event,segment=x.segment.iloc[0],seller_markets=len(seller),buyer_markets=len(buyer),
                               seller_mean_points_1x=seller.sell_pnl_points.mean(),seller_mean_points_2x=seller.sell_pnl_points_2x_fee.mean(),
                               seller_cash_pnl_1x=(q*seller.sell_pnl_points/100).sum(),seller_cash_pnl_2x=(q*seller.sell_pnl_points_2x_fee/100).sum(),
                               buyer_mean_points_1x=buyer.buy_pnl_points.mean(),all_seller_outcomes_no=bool(seller.outcome.eq(0).all()) if len(seller) else None))
    pd.DataFrame(events).to_csv(OUT/"OPTION_MICRO_EVENTS.csv",index=False)
    for pkg in ["s6_monday_fade","s18_price_market_calibration","s19_crypto_price_markets"]:
        for name in ["METHOD.md","config.py","run.py","report.py","prints.py"]:
            p=RESEARCH/pkg/name
            if p.is_file():READ.add(p)
        for name in ["run_meta.json","prints_meta.json","SUMMARY.md","capacity.md"]:
            p=RESEARCH/"results"/pkg/name
            if p.is_file():READ.add(p)
    READ.add(Path(__file__).resolve())
    metadata=OUT/"sp500_contract_examples.json"
    if metadata.is_file():READ.add(metadata)
    hashes=[dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(READ)]
    pd.DataFrame(hashes).to_csv(OUT/"OPTION_MICRO_SOURCE_HASHES.csv",index=False)
    print(pd.DataFrame(rows)[["study","cut","segment","fee_multiplier","markets","events","mean_pnl_points","settlement_month_sharpe","capped_book_pnl"]].to_string(index=False))


if __name__=="__main__":main()
