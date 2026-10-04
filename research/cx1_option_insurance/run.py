"""Offline actual-NBBO diagnostic. Run: cd research && .venv/bin/python -m cx1_option_insurance.run."""
from __future__ import annotations
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from . import config as cfg
from .data import OfflineSource,context,signal_states,underlying_at,valid_quote,RESEARCH
from .engine import gate,short_put,event_daily_returns,block_mean,daily_metrics,apply_event_to_book

OUT=RESEARCH/"results"/cfg.PACKAGE


def observe(src,bars,sess,states,i,j,oos_day):
    en=int(sess.close.iloc[i])-cfg.ENTRY_BEFORE_CLOSE_MINUTES*60
    ex=int(sess.open.iloc[j])+cfg.EXIT_AFTER_OPEN_MINUTES*60
    st=int(sess.close.iloc[i])-cfg.STRIKE_BEFORE_CLOSE_MINUTES*60
    size,reason=gate(states[i])
    r=dict(entry_day=sess.day.iloc[i],exit_day=sess.day.iloc[j],entry_index=i,exit_index=j,
           entry_timestamp=en,exit_timestamp=ex,entry_decision_timestamp=en,exit_decision_timestamp=ex,signal_timestamp=st,
           segment="OOS" if sess.day.iloc[i]>=oos_day else "IS",gate_exposure=size,gate_reason=reason,
           closure_hours=(int(sess.open.iloc[j])-int(sess.close.iloc[i]))/3600,
           status="ok",crosses_split=bool(sess.day.iloc[i]<oos_day<=sess.day.iloc[j]))
    spot=underlying_at(bars,st)
    r["spot_at_strike_cutoff"]=spot
    if spot is None:return {**r,"status":"missing underlying completed bar"}
    expiry,strikes,status=src.expiry(r["entry_day"])
    r.update(expiry=expiry,listed_strikes_count=len(strikes),listing_status=status)
    if not strikes:return {**r,"status":status}
    strike=min(strikes,key=lambda k:(abs(k-spot),k))
    call=strikes[strike];put=call[:-9]+"P"+call[-8:]
    r.update(strike=strike,put=put,dte=(pd.Timestamp(expiry)-pd.Timestamp(r["entry_day"])).days)
    for name,at,max_age,floor in [("entry",en,cfg.ENTRY_QUOTE_MAX_AGE_SECONDS,None),
                                  ("exit",ex,cfg.EXIT_QUOTE_MAX_AGE_SECONDS,int(sess.open.iloc[j]))]:
        q,msg=src.quote(put,at)
        r[name+"_cache_status"]=msg
        if q is None:return {**r,"status":name+": "+msg}
        r.update({name+("_quote_timestamp" if k=="timestamp" else "_"+k):v for k,v in q.items()})
        r[name+"_age_seconds"]=at-q["timestamp"]
        v=valid_quote(q,at,max_age,floor)
        if v!="ok":return {**r,"status":name+": "+v}
        touch_size=q["bid_size"] if name=="entry" else q["ask_size"]
        if touch_size<1:return {**r,"status":name+": less than one contract at executable side"}
    r["capacity_contracts"]=min(r["entry_bid_size"],r["exit_ask_size"])
    r["capacity_cash_dollars"]=r["capacity_contracts"]*strike*cfg.CONTRACT_MULTIPLIER
    stock_entry,stock_exit=underlying_at(bars,en),underlying_at(bars,ex)
    r.update(stock_entry_asof=stock_entry,stock_exit_asof=stock_exit,
             stock_closure_return=stock_exit/stock_entry-1 if stock_entry and stock_exit else math.nan)
    return r


def main():
    started=datetime.now(timezone.utc).isoformat()
    OUT.mkdir(parents=True,exist_ok=True)
    bars,sess,links=context()
    states,signals=signal_states(sess,links)
    n=len(sess);n_oos=int(math.ceil(n*cfg.OOS_FRACTION));oos_idx=n-n_oos;oos_day=sess.day.iloc[oos_idx]
    src=OfflineSource()
    closures=[(i-1,i) for i in range(1,n) if int(sess.open.iloc[i])-int(sess.close.iloc[i-1])>cfg.MIN_CLOSURE_HOURS*3600]
    raw=[observe(src,bars,sess,states,i,j,oos_day) for i,j in closures]
    is_gate=[r["gate_exposure"] for r in raw if r["segment"]=="IS"]
    static=float(np.mean(is_gate)) if is_gate else cfg.GATED_COLLATERAL_FRACTION
    trade_rows=[];equity_rows=[];metrics=[];audit=[]
    for cost in cfg.COST_MULTIPLIERS:
        for variant in [v.id for v in cfg.VARIANTS]+[cfg.STATIC_COMPARATOR]:
            returns=np.zeros(n);turnover=np.zeros(n);collturn=np.zeros(n);book_records=[]
            for r in raw:
                rec={**r,"variant":variant,"cost_multiplier":cost,"exposure":1.0 if variant=="V0" else r["gate_exposure"] if variant=="V1" else static}
                if r["status"]!="ok":
                    rec["event_return"]=0.0;rec["executed"]=False;book_records.append(rec);continue
                try:a=short_put(r["entry_bid"],r["entry_ask"],r["exit_bid"],r["exit_ask"],r["strike"],cost)
                except ValueError as e:
                    rec.update(status=str(e),event_return=0.0,executed=False);book_records.append(rec);continue
                # Entry equity is determined from preceding returns; events never overlap.
                before,first,second=apply_event_to_book(returns,turnover,collturn,r["entry_index"],r["exit_index"],a,rec["exposure"])
                unit_ret=a.pop("event_return")
                rec.update(a);rec.update(executed=True,unit_event_return=unit_ret,event_return=rec["exposure"]*unit_ret,
                                       entry_daily_return=first,exit_daily_return=second,entry_portfolio_equity=before)
                reconciliation=(1+first)*(1+second)-1-rec["event_return"]
                audit.append(dict(variant=variant,cost_multiplier=cost,entry_day=r["entry_day"],reconciliation_error=reconciliation,
                                  short_sign_correct=bool(abs(a["pnl"]-((a["entry_fill"]-a["exit_fill"])*100-2*cost*cfg.COMMISSION_PER_CONTRACT_SIDE))<1e-9)))
                if abs(reconciliation)>1e-12:raise AssertionError("daily/event reconciliation")
                book_records.append(rec)
            # Complete event factors must equal the full cash account even when morning exits share entry dates.
            factor=float(np.prod([1+r["event_return"] for r in book_records if r.get("executed")]))
            if abs(factor-float(np.prod(1+returns)))>1e-12:raise AssertionError("full-book event/daily reconciliation")
            trade_rows.extend(book_records)
            eq=np.cumprod(1+returns);peak=np.maximum.accumulate(np.r_[1,eq])[1:]
            for i,d in enumerate(sess.day):equity_rows.append(dict(day=d,segment="OOS" if i>=oos_idx else "IS",variant=variant,cost_multiplier=cost,
                                                                 daily_return=returns[i],equity=eq[i],drawdown=eq[i]/peak[i]-1,
                                                                 premium_turnover=turnover[i],collateral_turnover=collturn[i]))
            segments={"IS":np.arange(oos_idx),"OOS":np.arange(oos_idx,n),"ALL":np.arange(n),
                      "IS_FIRST_HALF":np.arange(oos_idx//2),"IS_SECOND_HALF":np.arange(oos_idx//2,oos_idx),
                      "OOS_FIRST_HALF":np.arange(oos_idx,oos_idx+n_oos//2),"OOS_SECOND_HALF":np.arange(oos_idx+n_oos//2,n)}
            for segment,idx in segments.items():
                start,end=sess.day.iloc[idx[0]],sess.day.iloc[idx[-1]]
                br=[r for r in book_records if start<=r["entry_day"]<=end];exe=[r for r in br if r["executed"]]
                row=dict(variant=variant,cost_multiplier=cost,segment=segment,start_day=start,end_day=end,
                         planned_entry_dates=len(br),executed_entry_dates=len(exe),missing_entry_dates=len(br)-len(exe),
                         average_planned_exposure=float(np.mean([r["exposure"] for r in br])) if br else math.nan,
                         static_is_matched_exposure=static,**daily_metrics(sess.day.iloc[idx],returns[idx]))
                mean,lo,hi=block_mean([r["event_return"] for r in exe])
                row.update(mean_executed_event_return=mean,event_ci_low=lo,event_ci_high=hi,
                           mean_planned_closure_return=float(np.mean([r["event_return"] for r in br])) if br else math.nan,
                           option_premium_turnover=float(turnover[idx].sum()),collateral_turnover=float(collturn[idx].sum()),
                           average_cost_bp=float(np.mean([r["costs_bp"] for r in exe])) if exe else math.nan,
                           average_cost_share_of_premium=float(np.mean([r["costs_share_of_premium"] for r in exe])) if exe else math.nan,
                           capacity_min_contracts=min([r["capacity_contracts"] for r in exe],default=math.nan))
                if exe:
                    best=max(exe,key=lambda x:x["event_return"]);worst=min(exe,key=lambda x:x["event_return"])
                    row.update(best_entry_day=best["entry_day"],best_event_return=best["event_return"],worst_entry_day=worst["entry_day"],worst_event_return=worst["event_return"])
                    stripped=returns[idx].copy()
                    for k,component in [(best["entry_index"],best["entry_daily_return"]),(best["exit_index"],best["exit_daily_return"])]:
                        where=np.flatnonzero(idx==k)
                        if len(where):stripped[where[0]]=(1+stripped[where[0]])/(1+component)-1
                    row["total_return_without_best_closure"]=float(np.prod(1+stripped)-1)
                else:row["total_return_without_best_closure"]=math.nan
                row["preliminary_sample_sufficient"]=bool(len(exe)>=cfg.MIN_OOS_ENTRY_DATES and len(idx)>=cfg.MIN_OOS_DAILY_OBSERVATIONS) if segment=="OOS" else False
                metrics.append(row)
    trades=pd.DataFrame(trade_rows);daily=pd.DataFrame(equity_rows);m=pd.DataFrame(metrics)
    # Paired exposure-control differences, block resampling by closure, never independent quote rows.
    for i,row in m.iterrows():
        if row.variant!="V1":continue
        sub=trades[(trades.cost_multiplier==row.cost_multiplier)&(trades.entry_day>=row.start_day)&(trades.entry_day<=row.end_day)]
        a=sub[sub.variant=="V1"]["event_return"].to_numpy();b=sub[sub.variant==cfg.STATIC_COMPARATOR]["event_return"].to_numpy()
        avg,lo,hi=block_mean(a-b)
        m.loc[i,["gate_minus_static_mean","gate_minus_static_ci_low","gate_minus_static_ci_high"]]=[avg,lo,hi]
    for i,row in m[m.segment=="OOS"].iterrows():
        counterparts=m[(m.variant==row.variant)&(m.cost_multiplier==row.cost_multiplier)]
        two=counterparts[(counterparts.segment=="OOS")&(counterparts.cost_multiplier==2)]
        # Cost condition is evaluated against the same variant's 2x OOS, not the current cost row.
        two=m[(m.variant==row.variant)&(m.segment=="OOS")&(m.cost_multiplier==2)].iloc[0]
        halves=counterparts[counterparts.segment.isin(["OOS_FIRST_HALF","OOS_SECOND_HALF"])]
        is_return=float(counterparts[counterparts.segment=="IS"].total_return.iloc[0])
        passes=bool(row.preliminary_sample_sufficient and row.annualized_sharpe>=cfg.TARGET_OOS_SHARPE and two.total_return>0
                    and row.event_ci_low>0 and is_return>0 and len(halves)==2 and (halves.total_return>0).all()
                    and row.total_return_without_best_closure>0)
        if row.variant=="V1":passes=passes and bool(row.gate_minus_static_ci_low>0)
        m.loc[i,"passes_preliminary_screen"]=passes
    trades.to_csv(OUT/"trades.csv",index=False);daily.to_csv(OUT/"equity.csv",index=False);m.to_csv(OUT/"metrics.csv",index=False)
    equity_risk_diagnostic(trades,sess,OUT)
    pd.DataFrame(raw).to_csv(OUT/"coverage.csv",index=False);pd.DataFrame(signals).to_csv(OUT/"signals.csv",index=False)
    pd.DataFrame(audit).to_csv(OUT/"accounting_audit.csv",index=False)
    provenance=[]
    for p in sorted(src.read_paths):
        provenance.append(dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    (OUT/"input_manifest.json").write_text(json.dumps(provenance,indent=2)+"\n")
    freeze=subprocess.run(["git","log","-1","--format=%h %cI %s","--","research/cx1_option_insurance/METHOD.md","research/cx1_option_insurance/config.py"],cwd=RESEARCH.parent,capture_output=True,text=True).stdout.strip()
    meta=dict(started_utc=started,finished_utc=datetime.now(timezone.utc).isoformat(),freeze_commit=freeze,
              window_start=cfg.WINDOW_START,window_end=cfg.WINDOW_END,oos_start=oos_day,calendar_sessions=n,oos_sessions=n_oos,
              closures=len(closures),spy_links=len(links),static_is_exposure=static,network_requests=0,download_bytes=0,
              cache_files_read=len(src.read_files),status_counts=pd.Series([r["status"] for r in raw]).value_counts().to_dict(),
              all_data_reused=True,future_reserve_from=cfg.FUTURE_RESERVE_FROM)
    (OUT/"run_meta.json").write_text(json.dumps(meta,indent=2)+"\n")
    plot(daily,oos_day)
    print(json.dumps(meta,indent=2))
    print(m[(m.segment.isin(["IS","OOS","ALL"]))&m.variant.isin(["V0","V1"])][["variant","cost_multiplier","segment","executed_entry_dates","daily_observations","annualized_sharpe","total_return","max_drawdown","worst_month","mean_executed_event_return","event_ci_low","event_ci_high"]].to_string(index=False))


def plot(daily,oos_day):
    for field,name,label in [("equity","equity_curve.png","Equity per $1 full-cash budget"),("drawdown","drawdown.png","Drawdown")]:
        fig,ax=plt.subplots(figsize=(10,4.5))
        for (v,c),g in daily.groupby(["variant","cost_multiplier"]):
            ax.plot(pd.to_datetime(g.day),g[field],label=f"{v} {c:g}x",ls="-" if c==1 else "--",alpha=.9)
        ax.axvline(pd.Timestamp(oos_day),color="black",ls=":",label="recent20% begins")
        ax.set(title="SPY cashsecured closure insurance — sparse reused historical quotes",ylabel=label)
        ax.grid(alpha=.2);ax.legend(fontsize=8,ncol=3);fig.autofmt_xdate();fig.tight_layout();fig.savefig(OUT/name,dpi=160);plt.close(fig)


def equity_risk_diagnostic(trades,sess,out):
    """Post-run fixed .5 stock-risk proxy. No fitted hedge or strategy pass claim."""
    paired=trades[(trades.variant=="V0")&(trades.cost_multiplier==1)&trades.executed].copy()
    paired["fixed_half_spy_return"]=cfg.DIAGNOSTIC_SPY_DELTA*paired.stock_closure_return
    paired["gross_put_minus_half_spy"]=paired.gross_event_return-paired.fixed_half_spy_return
    paired["net_put_minus_half_spy"]=paired.event_return-paired.fixed_half_spy_return
    columns=["entry_day","exit_day","segment","stock_entry_asof","stock_exit_asof","stock_closure_return",
             "fixed_half_spy_return","gross_event_return","event_return","gross_put_minus_half_spy","net_put_minus_half_spy"]
    paired[columns].to_csv(out/"equity_risk_pairs.csv",index=False)
    records=[]
    for segment in ["IS","OOS","ALL"]:
        x=paired if segment=="ALL" else paired[paired.segment==segment]
        if not len(x):continue
        beta=float(np.cov(x.stock_closure_return,x.gross_event_return,ddof=1)[0,1]/x.stock_closure_return.var(ddof=1)) if len(x)>1 and x.stock_closure_return.var(ddof=1)>0 else math.nan
        mean,lo,hi=block_mean(x.gross_put_minus_half_spy)
        records.append(dict(segment=segment,executed_entry_dates=len(x),mean_spy_return=x.stock_closure_return.mean(),
                            mean_fixed_half_spy_return=x.fixed_half_spy_return.mean(),mean_gross_put_return=x.gross_event_return.mean(),
                            mean_net_put_return=x.event_return.mean(),mean_gross_put_minus_half_spy=mean,
                            gross_residual_ci_low=lo,gross_residual_ci_high=hi,
                            mean_net_put_minus_half_spy=x.net_put_minus_half_spy.mean(),descriptive_gross_put_beta_to_spy=beta,
                            interpretation="post-run equity-risk proxy; not an executable hedge or pass candidate"))
    pd.DataFrame(records).to_csv(out/"equity_risk_diagnostic.csv",index=False)


if __name__=="__main__":main()
