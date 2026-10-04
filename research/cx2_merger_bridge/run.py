"""Run audit or supplied normalized evidence. No fetching and no synthetic performance."""
from __future__ import annotations
import argparse
import json
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from . import config as cfg
from .engine import Deal, Quote, EvidenceError, evaluate, portfolio, metrics, terminal_values, cluster_interval, daily_block_interval

STRATEGIES=('event_hedge','unhedged','put_hedge')

def load_deals(path):
    rows=json.loads(path.read_text());out=[]
    if 'synthetic' in path.read_text().lower() or 'fixture' in path.read_text().lower():raise EvidenceError('synthetic fixtures cannot be performance evidence')
    for r in rows:
        for k in ('entry','deadline','put_expiry'):r[k]=datetime.fromisoformat(r[k])
        for k in ('stock_entry','event_entry','put_entry'):
            r[k]['timestamp']=datetime.fromisoformat(r[k]['timestamp']);r[k]=Quote(**r[k])
        r['preannouncement_closes']=tuple(r['preannouncement_closes']);r['evidence_urls']=tuple(r['evidence_urls'])
        out.append(Deal(**r))
    return out


def normalized_evaluation(input_dir):
    # Inputs are user-supplied evidence, not shared caches or sealed OOS paths.
    allowed=(cfg.PACKAGE.resolve(),cfg.RESULTS.resolve())
    resolved=input_dir.resolve()
    if not any(resolved.is_relative_to(a) for a in allowed):raise EvidenceError('normalized inputs must be inside owned package/results')
    deals=load_deals(input_dir/'deals.json')
    marks=pd.read_csv(input_dir/'marks.csv')
    cal=pd.read_csv(input_dir/'calendar.csv')['date'].tolist()
    if not deals:raise EvidenceError('no deals supplied')
    rows=[];trades=[];curves=[]
    for strategy in STRATEGIES:
        for mult in cfg.COST_MULTIPLIERS:
            dc=[]
            for d in deals:
                m=marks[marks.deal_id==d.deal_id]
                c=evaluate(d,m,cfg.STARTING_CAPITAL*cfg.MAX_DEAL_CAPITAL_FRACTION,strategy,mult)
                dc.append(c)
                trades.append({'deal_id':d.deal_id,'entry_date':d.entry.date().isoformat(),'exit_date':pd.Timestamp(c.date.iloc[-1]).date().isoformat(),'strategy':strategy,'cost_mult':mult,'terminal_pnl':float(c.terminal_pnl.iloc[-1]),'allocation':float(c.allocation.iloc[0]),'lots':int(c.lots.iloc[0]),'capital_used':float(c.capital_used.iloc[0]),'turnover_dollars':float(c.turnover_dollars.iloc[0])})
            p=portfolio(dc,cal);p['strategy']=strategy;p['cost_mult']=mult;curves.append(p)
            cut=len(p)-math.ceil(len(p)*cfg.OOS_FRACTION)
            for segment,g in [('all',p),('earlier',p.iloc[:cut]),('recent',p.iloc[cut:])]:
                start_day=pd.Timestamp(g.date.iloc[0]).date().isoformat() if len(g) else ''
                end_day=pd.Timestamp(g.date.iloc[-1]).date().isoformat() if len(g) else ''
                segment_trades=[x for x in trades if x['strategy']==strategy and x['cost_mult']==mult and start_day<=x['entry_date']<=x['exit_date']<=end_day]
                dates={x['entry_date'] for x in segment_trades}
                vals=[x['terminal_pnl']/x['allocation'] for x in segment_trades]
                ci=cluster_interval(vals)
                daily_ci=daily_block_interval(g['return'].tolist())
                total_pnl=sum(x['terminal_pnl'] for x in segment_trades)
                concentration=max((x['terminal_pnl'] for x in segment_trades),default=0)/total_pnl if total_pnl>0 else None
                mm=metrics(g)
                status='INSUFFICIENT' if len(dates)<cfg.MIN_INDEPENDENT_ENTRY_DATES or len(p)-cut<cfg.MIN_RECENT_DAILY_OBSERVATIONS or len(deals)<cfg.MIN_DEAL_CLUSTERS else 'EXPLORATORY_VALIDATION_ONLY'
                rows.append({'status':status,'strategy':strategy,'cost_mult':mult,'segment':segment,'verified_deals':len(segment_trades),'entry_dates':len(dates),**mm,'daily_mean_ci_low':daily_ci[0] if daily_ci else None,'daily_mean_ci_high':daily_ci[1] if daily_ci else None,'largest_profit_fraction':concentration,'worst_deal_return':min(vals) if vals else None,'sharpe_above_3_requires_audit':bool(mm['sharpe'] is not None and mm['sharpe']>3),'deal_return_ci_low':ci[0] if ci else None,'deal_return_ci_high':ci[1] if ci else None})
    pd.DataFrame(trades).to_csv(cfg.RESULTS/'trades.csv',index=False)
    pd.DataFrame(rows).to_csv(cfg.RESULTS/'metrics.csv',index=False)
    pd.concat(curves).to_csv(cfg.RESULTS/'equity.csv',index=False)
    return {'status':'EVALUATED_EXPLORATORY_INPUT','verified_deals':len(deals),'rows':len(rows)}


def current_metadata():
    cache=cfg.PACKAGE/'.cache';rows=[]
    if (cache/'event_metadata.json').exists():rows+=json.loads((cache/'event_metadata.json').read_text())
    if (cache/'metadata_2154920.json').exists():rows.append(json.loads((cache/'metadata_2154920.json').read_text()))
    return {str(r['id']):r for r in rows}


def audit():
    local=json.loads((cfg.RESULTS/'local_catalog_audit.json').read_text())
    metadata=current_metadata();rows=[]
    tickers={'694936':'NBIS','2154920':'EBAY','700396':'PRIVATE','694938':'VKTX','694940':'GTLB','694937':'BP'}
    for r in local['candidates']:
        mid=r['id'].split(':')[-1];m=metadata.get(mid,{});text=(m.get('description') or '').lower()
        announcement=bool(('announc' in text or 'enters into an agreement' in text) and ('regardless of whether' in text or 'regardless of whether or when' in text))
        if not text:status='UNVERIFIED_RULE_TEXT'
        elif announcement:status='REJECTED_ANNOUNCEMENT_BASIS'
        else:status='MANUAL_SEMANTICS_REVIEW_REQUIRED'
        rows.append({'market_id':mid,'question':r['question'],'target_ticker':tickers[mid],'source_catalog':'s5_big_moves/candidates.json','entry_basis':'announcement_or_agreement' if announcement else 'unverified','completion_matched':False,'historical_rule_asof_verified':False,'stock_quote_history':False,'option_quote_and_deliverable_history':False,'event_historical_book':False,'status':status,'extra_exclusion':'private_target' if mid=='700396' else '','market_start':m.get('startDate',r.get('start')),'deadline':m.get('endDate',r.get('end')),'current_rule_updated_at':m.get('updatedAt',''),'source_url':'https://polymarket.com/event/'+('will-gamestop-acquire-ebay' if mid=='2154920' else 'which-companies-will-be-acquired-before-2027')})
    df=pd.DataFrame(rows);df.to_csv(cfg.RESULTS/'matched_universe_audit.csv',index=False)
    (cfg.RESULTS/'current_rules.json').write_text(json.dumps(list(metadata.values()),indent=2))
    pd.DataFrame([{'buyer':b,'target':t,'ticker':tk,'frozen_local_contract_match':False,'verified_public_completion_contract':False,'performance_eligible':False,'status':'NO_MATCH_VERIFIED_IN_LIMITED_DISCOVERY'} for b,t,tk in cfg.NAMED_HISTORICAL_DEALS]).to_csv(cfg.RESULTS/'named_historical_discovery.csv',index=False)
    totals={'status':'NOT_TESTABLE','catalog_candidates':int(local['candidate_catalog_count']),'corporate_acquisition_questions':len(df),'verified_current_rule_texts':len(metadata),'announcement_contracts':int((df.status=='REJECTED_ANNOUNCEMENT_BASIS').sum()),'private_targets':int((df.extra_exclusion=='private_target').sum()),'eligible_completion_contracts':int(df.completion_matched.sum()),'verified_deals':0,'verified_entry_dates':0,'daily_observations':0,'recent_daily_observations':0,'historical_price_requests':0,'synthetic_performance_used':False}
    (cfg.RESULTS/'feasibility.json').write_text(json.dumps(totals,indent=2))
    pd.DataFrame([{'status':'NOT_TESTABLE','strategy':s,'cost_mult':c,'segment':seg,'verified_deals':0,'entry_dates':0,'observations':0,'sharpe':None,'total_return':None,'max_drawdown':None,'worst_month':None,'turnover':None,'capacity':None,'deal_return_ci_low':None,'deal_return_ci_high':None} for s in STRATEGIES for c in cfg.COST_MULTIPLIERS for seg in ('all','earlier','recent')]).to_csv(cfg.RESULTS/'metrics.csv',index=False)
    pd.DataFrame(columns=['deal_id','entry_date','strategy','cost_mult','terminal_pnl','allocation','lots','capital_used','turnover_dollars']).to_csv(cfg.RESULTS/'trades.csv',index=False)
    pd.DataFrame(columns=['date','strategy','cost_mult','nav','return','active_allocation']).to_csv(cfg.RESULTS/'equity.csv',index=False)
    for name in ('equity_curve','drawdown'):
        fig,ax=plt.subplots(figsize=(7,3.2));ax.axis('off')
        ax.text(.5,.65,'NOT TESTABLE',ha='center',va='center',fontsize=23,weight='bold')
        ax.text(.5,.38,'0 verified completion-contract trades\nNo historical '+name.replace('_',' ')+' exists.',ha='center',va='center',fontsize=12)
        fig.savefig(cfg.RESULTS/f'{name}.png',dpi=120,bbox_inches='tight');plt.close(fig)
    # Deterministic mechanics illustration kept separate from performance artifacts.
    fixture=[]
    for state,price,no,div in [('timely completion',100,0,0),('moderate failure',70,1,0),('severe failure',10,1,0),('late completion',100,1,0),('revised offer closes',110,0,0),('failure with distribution',70,1,3)]:
        fixture.append({'fixture_only':True,'state':state,'stock_terminal':price,'event_no_payoff':no,'cash_distribution':div,**terminal_values(price,div,no,80,2000)})
    pd.DataFrame(fixture).to_csv(cfg.RESULTS/'synthetic_truth_table.csv',index=False)
    return totals


def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path);args=p.parse_args()
    cfg.RESULTS.mkdir(parents=True,exist_ok=True)
    result=normalized_evaluation(args.inputs) if args.inputs else audit()
    print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
