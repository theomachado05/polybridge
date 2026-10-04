"""Generate plain-language deliverables strictly from saved result tables."""
from __future__ import annotations
import json
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from .run import OUT
from . import config as cfg


def pct(v):return "unavailable" if pd.isna(v) else f"{100*v:+.3f}%"
def bp(v):return "unavailable" if pd.isna(v) else f"{1e4*v:+.2f} bp"
def num(v):return "unavailable" if pd.isna(v) else f"{v:.3f}"


def main():
    m=pd.read_csv(OUT/"metrics.csv");t=pd.read_csv(OUT/"trades.csv");c=pd.read_csv(OUT/"coverage.csv")
    d=pd.read_csv(OUT/"equity.csv");risk=pd.read_csv(OUT/"equity_risk_diagnostic.csv");aud=pd.read_csv(OUT/"accounting_audit.csv")
    meta=json.loads((OUT/"run_meta.json").read_text())
    pull=json.loads((OUT/"data_completion_log.json").read_text()) if (OUT/"data_completion_log.json").exists() else dict(requests=0,response_bytes=0,error=None)
    pick=lambda v,cost,seg:m[(m.variant==v)&(m.cost_multiplier==cost)&(m.segment==seg)].iloc[0]
    one,two=pick("V0",1,"OOS"),pick("V0",2,"OOS");gate=pick("V1",1,"OOS");static=pick(cfg.STATIC_COMPARATOR,1,"OOS")
    complete=bool((c.status=="ok").all())
    status="Complete fixed-rule historical diagnostic; underpowered and not confirmed" if complete else "Incomplete fixed-rule historical diagnostic; missing quotes and underpowered"
    lines=[f"# CX1 option insurance: {status}","",
           f"Selling fully cashsecured ATM SPY puts over market closures earned {pct(one.total_return)} in the recent period at 1x costs "
           f"and {pct(two.total_return)} at 2x. The 1x OOS daily Sharpe was {num(one.annualized_sharpe)}. "
           f"There were only {int(one.executed_entry_dates)} independent OOS entry dates and {int(one.daily_observations)} daily observations, "
           f"below the frozen 30/60 minimum. Its mean net closure return was {bp(one.mean_executed_event_return)}, "
           f"with a 95% four-closure block interval [{bp(one.event_ci_low)}, {bp(one.event_ci_high)}]. "
           "This cannot pass the preliminary screen or establish an insurance or prediction-market edge.","",
           f"The only event sizing variant earned {pct(gate.total_return)} OOS at 1x, with Sharpe {num(gate.annualized_sharpe)}. "
           f"Its exposure control earned {pct(static.total_return)} with Sharpe {num(static.annualized_sharpe)}. "
           f"The paired gate-minus-static mean was {bp(gate.gate_minus_static_mean)} "
           f"(95% interval [{bp(gate.gate_minus_static_ci_low)}, {bp(gate.gate_minus_static_ci_high)}]). "
           "The historical evidence does not establish that the event gate improves returns.","",
           "| Book | Costs | Segment | Entries | Daily Sharpe | Total return | Max drawdown | Worst month |",
           "|---|---:|---|---:|---:|---:|---:|---:|"]
    for v in ["V0","V1",cfg.STATIC_COMPARATOR]:
        for cost in cfg.COST_MULTIPLIERS:
            for seg in ["IS","OOS","ALL"]:
                r=pick(v,cost,seg)
                lines.append(f"| {v} | {cost:g}x | {seg} | {int(r.executed_entry_dates)} | {num(r.annualized_sharpe)} | {pct(r.total_return)} | {pct(r.max_drawdown)} | {pct(r.worst_month)} |")
    lines.extend(["",f"The fixed window is {meta['window_start']} to {meta['window_end']}; OOS starts {meta['oos_start']}. "
                  f"The strategy planned {len(c)} closures and executed {int((c.status=='ok').sum())}. "
                  f"DATA_ONLY completion made {pull['requests']} Massive requests, received {pull['response_bytes']:,} bytes, "
                  "and preserved the same rules, chronological split and strike selection. "
                  "All history is reused exploratory evidence. Untouched observations from 2026-10-05 onward remain reserved.","",
                  "| Post-run directional-risk diagnostic | IS | OOS | All |",
                  "|---|---:|---:|---:|"])
    for name,col,fmt in [("Mean full SPY closure return","mean_spy_return",bp),("Fixed half-SPY proxy","mean_fixed_half_spy_return",bp),
                         ("Mean gross put return","mean_gross_put_return",bp),("Gross put minus half-SPY","mean_gross_put_minus_half_spy",bp),
                         ("Net put minus half-SPY","mean_net_put_minus_half_spy",bp),("Descriptive put beta to SPY","descriptive_gross_put_beta_to_spy",num)]:
        lines.append("| "+name+" | "+" | ".join(fmt(risk[risk.segment==seg].iloc[0][col]) for seg in ["IS","OOS","ALL"])+" |")
    lines.extend(["","The half-SPY comparison was requested after the first run and uses completed five-minute stock bars at the "
                  "same frozen entry/exit clocks. It has no stock spread, commissions, interest or rebalance costs and is not an executable "
                  "hedged strategy. It is a fixed equity-risk proxy, not another pass candidate. The descriptive beta is not used for sizing. "
                  "A cashsecured put owns stock downside, and these results cannot be described as pure option premium harvesting.","",
                  "| Event gate state | Planned IS | Planned OOS | Executed IS | Executed OOS |",
                  "|---|---:|---:|---:|---:|"])
    for reason in ["active event","observed quiet event state","unobserved event state"]:
        counts=[len(c[(c.segment==seg)&(c.gate_reason==reason)&((c.status=="ok") if exe else True)]) for exe,seg in [(False,"IS"),(False,"OOS"),(True,"IS"),(True,"OOS")]]
        lines.append(f"| {reason} | "+" | ".join(map(str,counts))+" |")
    all_one=pick("V0",1,"ALL")
    exe=t[(t.variant=="V0")&(t.cost_multiplier==1)&t.executed]
    lines.extend(["",f"Actual NBBO crossing plus the stated $0.65 per contract per side averaged {all_one.average_cost_bp:.3f} bp "
                  f"of strike cash and {100*all_one.average_cost_share_of_premium:.3f}% of the entry mid premium per closure at 1x. "
                  "2x doubles both half-spreads and both commissions. Short fills are independently computed at bid/ask; "
                  "they are not the negation of S7 long net returns.","",
                  f"Entry SIP quote age reached {exe.entry_age_seconds.max():.3f} seconds and exit age {exe.exit_age_seconds.max():.3f} seconds. "
                  "NBBO-side execution is a historical fill assumption, not a certified live trade. Both displayed entry bid and exit ask "
                  "sizes are recorded. Entry cash P&L is marked at the contemporaneous liquidating ask, with fixed contracts through exit. "
                  "Daily account snapshots leave the last five minutes of the entry session unmarked; the account is cash after exit. "
                  f"The maximum compounded daily/event reconciliation error was {aud.reconciliation_error.abs().max():.2e}.","",
                  "Every variant and both cost cases appear in metrics.csv. Subperiods and leave-best-closure-out results follow; "
                  "no subset changes the trading rule.","",
                  "| Book | Costs | Period | Entries | Return | Sharpe | Return without best closure |",
                  "|---|---:|---|---:|---:|---:|---:|"])
    for _,r in m[(m.variant.isin(["V0","V1"]))&m.segment.isin(["IS_FIRST_HALF","IS_SECOND_HALF","OOS_FIRST_HALF","OOS_SECOND_HALF","OOS"])].iterrows():
        lines.append(f"| {r.variant} | {r.cost_multiplier:g}x | {r.segment} | {int(r.executed_entry_dates)} | {pct(r.total_return)} | {num(r.annualized_sharpe)} | {pct(r.total_return_without_best_closure)} |")
    lines.extend(["","The initial archive retains the 48-trade offline result before seven missing dates were completed. The halfday calendar "
                  "correction changes the two previously omitted holiday query times to 12:55. Output timestamp labels were corrected so "
                  "scheduled decision clocks and earlier SIP quote clocks remain separate. Calendar/gate comparison to that archive is in RUN_LOG.md.","",
                  "Capacity and fractional-contract limitations are in capacity.md. ATM cashsecured downside and possible early assignment remain "
                  "economic risks; early assignment, dividend-related exercise and share-liquidation costs are not modeled. "
                  "Reused option reference requests omitted an entry-date as_of parameter: actual entry NBBO proves selected-contract existence, "
                  "but the precise nearest-expiry/nearest-strike chain at historical entry remains unverified. "
                  "No sealed research/results/oos or 8-K outcome file was opened. Neither variant passes the frozen independent-observation minimum."])
    if not complete:
        lines.extend(["", "Missing observations are recorded as cash in the plotted incomplete data diagnostic. They do not establish zero strategy returns:"])
        for _,r in c[c.status!="ok"].iterrows():lines.append(f"- {r.entry_day} to {r.exit_day}: {r.status}")
    (OUT/"SUMMARY.md").write_text("\n".join(lines)+"\n")
    capacity(exe,m,meta)
    log(meta,pull,c,t,aud)


def capacity(exe,m,meta):
    x=exe.copy();entry=x.entry_bid_size;exit=x.exit_ask_size;cash=x.collateral
    # A 2-lot full exposure book needs 1 lot on half-gated dates and 2 on quiet full-size dates.
    lots=np.where(x.gate_exposure==.5,1,2)
    feasible=(x.capacity_contracts>=lots)
    lines=["# Capacity and trading-unit limits","",
           f"The fixed rule has {len(x)} executable quoted closure dates. Weakest displayed entry bid size: {entry.min():g} contracts; "
           f"weakest exit ask size: {exit.min():g}; minimum bottleneck: {x.capacity_contracts.min():g}. "
           f"Median bottleneck: {x.capacity_contracts.median():g}; 10th percentile: {x.capacity_contracts.quantile(.1):g}.","",
           f"One put contract needs full strike cash of ${cash.min():,.0f} to ${cash.max():,.0f}, median ${cash.median():,.0f}. "
           f"The median displayed bottleneck corresponds to ${x.capacity_cash_dollars.median():,.0f} cash collateral; "
           f"the smallest date to ${x.capacity_cash_dollars.min():,.0f}. These figures are quote touch sizes, not executable capacity guarantees.","",
           "The portfolio curves use fractional normalized contracts and compound account equity. At one-contract cash capital, the half/full gate "
           "cannot be implemented exactly. An integer gate needs at least two strike cash obligations at full exposure and one at half exposure, "
           f"roughly ${2*cash.min():,.0f} to ${2*cash.max():,.0f}. That exact two-lot/full and one-lot/half book fits the historical displayed "
           f"entry-and-exit bottleneck on {int(feasible.sum())}/{len(x)} dates. Capital changes, rounding and changing strikes make a live integer "
           "book different from the fractional research curve; no integer-capital optimization was run.","",
           "Capacity uses the lesser of the observed entry bid size and later exit ask size. Those are not simultaneous quotes, and no option "
           "volume or order-book-depth data were pulled. Larger orders, queue position, market movement, impact and assignment liquidation are "
           "unsupported. The $0.65 commission per contract per side is a stated S7-compatible assumption; it is not a claimed universal tariff.","",
           "| Book | Costs | All-period premium turnover / initial cash | All-period collateral turnover / initial cash |",
           "|---|---:|---:|---:|"]
    for _,r in m[m.segment=="ALL"].iterrows():lines.append(f"| {r.variant} | {r.cost_multiplier:g}x | {r.option_premium_turnover:.4f} | {r.collateral_turnover:.4f} |")
    lines.extend(["","Premium turnover sums actual entry plus exit option consideration per initial portfolio cash. Collateral turnover counts "
                  "the full allocated strike obligation at entry and exit. Both use compounded portfolio capital. Their different magnitudes show "
                  "why returns and capacity must be normalized by full cash, not the small premium received."])
    (OUT/"capacity.md").write_text("\n".join(lines)+"\n")


def log(meta,pull,c,t,aud):
    initial=OUT/"initial_offline/trades.csv";old=pd.read_csv(initial)
    new=t[(t.variant=="V0")&(t.cost_multiplier==1)&t.executed]
    first=old[(old.variant=="V0")&(old.cost_multiplier==1)&old.executed]
    same=first.merge(new,on="entry_day",suffixes=("_initial","_final"))
    pnl_diff=float((same.pnl_initial-same.pnl_final).abs().max())
    gate_changes=int((same.gate_exposure_initial!=same.gate_exposure_final).sum())
    lines=["# Run log","",f"Generated {datetime.now(timezone.utc).isoformat()}.","",
           "Pre-outcome freeze: 6e33ff0 (2026-10-03 23:46:48 New York). Root sent FREEZE_ACK before prices were read.",
           "Data-only/calendar amendment commit: c77233f, root acknowledged before any Massive request.",
           f"Latest method/config commit recorded by runner: {meta['freeze_commit']}.","",
           "Initial offline run started 2026-10-04T03:52:09.658372+00:00 and finished 03:52:11.001579+00:00, before report plotting. "
           "It used 48/55 closures and five OOS entries. Its CSVs are preserved under initial_offline/.",
           f"Final computation started {meta['started_utc']} and finished {meta['finished_utc']} (before report plotting).",
           f"Completion requests started {pull.get('started_utc','not run')} and finished {pull.get('finished_utc','not run')}. "
           f"HTTP requests {pull['requests']}; response bytes {pull['response_bytes']:,}; cap 60 requests/2,000,000 bytes; max rate0.5/s. "
           f"Completion error: {pull.get('error') or 'none'}.","",
           "Read-only source paths: research/s5_big_moves/.cache/eq_SPY.npz; S5 labels/universe metadata via merge_links; "
           "the 18 agreed SPY-link pm_<id>.npz odds histories; research/.massive_cache/ cached contract/NBBO responses. "
           "New responses are only in this package's ignored .cache/massive/. No Kalshi or Polymarket requests were made. "
           "No shared study, environment, recorder, sealed OOS array or API key output was used. Input file hashes are in input_manifest.json.","",
           "The public ICE/NYSE 2025 calendar was read to verify 13:00 halfday closes. The two local 13:00 auction-stamped bars made the "
           "generic timestamp helper infer 13:05; the corrected 12:55 entry and12:30 strike/signal cutoff follow the existing actual-close rule.",
           f"All {len(same)} original executable V0 trades retain identical P&L (maximum absolute change ${pnl_diff:.12f}). "
           f"Correcting prior-close timestamps changed the gate exposure on {gate_changes} of those original dates.","",
           "Initial CSV timestamp field expansion accidentally replaced scheduled clocks with earlier SIP timestamps. It never changed quote "
           "requests, age validation or computed fills. Final tables preserve both quote and decision clocks separately.","",
           f"Accounting audit: all short-side signs correct={bool(aud.short_sign_correct.all())}; maximum event/daily compound reconciliation "
           f"error={aud.reconciliation_error.abs().max():.3e}. Costs stress is applied to both half-spreads and both commissions.",
           "A V1 IS daily Sharpe above3 triggered a sign, quote-time, strike-cutoff, gate-cutoff, size, funded-cash denominator and daily-reconciliation "
           "audit. No remaining accounting or lookahead error was found. A high historical Sharpe remains exploratory and does not overcome sparse OOS.","",
           "Validation command: cd research && .venv/bin/python -m pytest cx1_option_insurance/tests -q (14 tests passed before completion; "
           "final rerun exit status recorded by parent). Runnable commands: python -m cx1_option_insurance.run (offline); "
           "python -m cx1_option_insurance.report. pull_missing is budgeted data completion and needs the previously granted root acknowledgment.","",
           "Matplotlib initially warned that the user font-cache directories are read only and created a temporary cache. "
           "Final plotting uses a writable temporary MPLCONFIGDIR. This did not affect prices or accounting.","",
           "Full cache-response status counts:"]
    for k,v in meta['status_counts'].items():lines.append(f"- {k}: {v}")
    (OUT/"RUN_LOG.md").write_text("\n".join(lines)+"\n")


if __name__=="__main__":main()
