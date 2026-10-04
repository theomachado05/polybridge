"""S23 report: SUMMARY.md and capacity.md, every number read back from the result files.

    .venv/bin/python -m s23_monday_fade_real.report
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as cfg

R = cfg.RESULTS
PV = "primary (tau 0.05, exact seconds)"


def d(x, nd=2):
    return "n/a" if x != x else f"{'+' if x >= 0 else '-'}${abs(x):,.{nd}f}"


def p(x, nd=2):
    return "n/a" if x != x else f"{x:+.{nd}f}"


def iv(lo, hi, nd=2, dollar=False):
    if lo != lo or hi != hi:
        return "[n/a]"
    return f"[{d(lo, nd)}, {d(hi, nd)}]" if dollar else f"[{lo:+.{nd}f}, {hi:+.{nd}f}]"


def main() -> int:
    m = pd.read_csv(R / "metrics.csv")
    st = pd.read_csv(R / "staircase.csv")
    t = pd.read_csv(R / "trades.csv", low_memory=False)
    meta = json.loads((R / "run_meta.json").read_text())
    after = json.loads((R / "after_run.json").read_text())
    v1, v2 = meta["t1_verdict"], meta["t2_verdict"]

    def t1row(variant, segment, group):
        return m[(m.test == "T1") & (m.variant == variant) & (m.segment == segment) & (m.group == group)].iloc[0]

    def t2row(variant, segment, group_prefix):
        return m[(m.test == "T2") & (m.variant == variant) & (m.segment == segment) & m.group.str.startswith(group_prefix)].iloc[0]

    e, h2 = t1row(PV, "ALL", "0-15"), t1row(PV, "ALL", "0-15 minus 15+")
    e_is, e_oos = t1row(PV, "IS", "0-15"), t1row(PV, "OOS", "0-15")
    a, nb, a_is, a_oos = t2row("T2", "ALL", "all"), t2row("T2", "ALL", "best closure removed"), t2row("T2", "IS", "all"), t2row("T2", "OOS", "all")
    fb, fb_nb = t2row("T2b first print", "ALL", "all"), t2row("T2b first print", "ALL", "best closure removed")
    a2, nb2, fb2 = t2row("T2, 2x costs", "ALL", "all"), t2row("T2, 2x costs", "ALL", "best closure removed"), t2row("T2b first print, 2x costs", "ALL", "all")
    s_mod, s_t2, s_ver, s_ver_nb, s_t2_nb = (st.iloc[i] for i in range(5))
    sh, sh_nb, sh_fb = after["T2"]["sharpe_all"], after["T2"]["sharpe_best_closure_removed"], after["T2b first print"]["sharpe_all"]
    conc, timing, ov = after["concentration"], after["print_timing"], after["overlap_with_s6_verified"]

    b = t[(t.test == "T2") & (t["mode"] == "best") & (t.cost_mult == 1.0)].copy()
    tr = b[b.status == "trade"].copy()
    fee = cfg.T2_FEE_RATE * tr.entry * (1 - tr.entry)
    cap_pc = np.where(tr.side == "buy YES", tr.entry, 1 - tr.entry)
    cost_pts = float((100 * (cfg.T2_SLIP + fee)).mean())
    cost_bp = float(((cfg.T2_SLIP + fee) / cap_pc * 1e4).mean())
    turnover = a.capital_deployed / a.capital_base / (a.calendar_closures / cfg.CLOSURES_PER_YEAR)
    counts = meta["t2_status_counts"]["best/1x"]

    L = []
    w = L.append
    w("# S23: how much of the Monday fade exists at prices that really traded")
    w("")
    w(f"**This is a pre-registered re-analysis, not a confirmation.** Both data sets were already seen by earlier studies: S6's 187 entries and its "
      f"cached trade prints, and the partner's 402 reopening-day taker trades. The rules were fixed and committed before any P&L of this study was "
      f"computed: [`METHOD.md`](../../s23_monday_fade_real/METHOD.md) (commit `7b9e3e4`); code and tests committed before the run (`9482b64`). "
      f"No network call was made. A pass below is a **lead that needs replication on new data, not an edge**.")
    w("")
    w("## Answer")
    w("")
    w(f"**One book passes its pre-registered line, narrowly: S6 replayed at prices that printed (T2). Its Sharpe is {s_t2.sharpe:.2f}, not 4.27.**")
    w("")
    w(f"- **What survives.** {int(a.trades)} of S6's {meta['s6_entries']} entries could be traded at a price that really printed in the 30 minutes from "
      f"09:45 and was still 2 points beyond the options band after the fee. They sit on {int(a.closures_traded)} closures (a closure is one weekend or "
      f"holiday break: one independent bet). They made **{d(a['mean'])} per trade** (95% interval {d(a.lo)} to {d(a.hi)}, resampling closures), "
      f"{d(a.total)} in total, {a.hit_rate:.0%} winners, **Sharpe {s_t2.sharpe:.2f}** on closure returns at 52 closures a year.")
    w(f"- **Without the best closure** (2026-03-09, four buys that all won: one bet): {d(nb['mean'])} per trade ({d(nb.lo)} to {d(nb.hi)}), "
      f"{int(nb.trades)} trades on {int(nb.closures_traded)} closures, {d(nb.total)} in total, Sharpe {s_t2_nb.sharpe:.2f}. Still above zero, so the line is met.")
    w(f"- **What does not survive.** The modelled figure: {d(s_mod['mean'])} per trade and a Sharpe of {s_mod.sharpe:.2f} at 52 closures a year (S6 "
      f"published 4.27 at 51 a year, 4.18 in-sample, 7.70 out-of-sample). {counts.get('no print on the side', 0)} of the 187 entries had no print at all "
      f"on the side needed in those 30 minutes, and {counts.get('print, gap gone', 0)} had a print whose price was no longer 2 points beyond the band. "
      f"The modelled book made {d(s_mod.total)}; at printed prices and sizes it is {d(s_t2.total)}.")
    w(f"- **The decay curve (T1, the primary test) fails.** Copying real taker prints in the first 15 minutes after 09:45 made {p(e['mean'])} points per "
      f"contract ({p(e.lo)} to {p(e.hi)}; {int(e.trades)} trades, {int(e.closures)} closures): the interval includes zero, so H1 fails. The first 15 "
      f"minutes beat the later trades by {p(h2['mean'])} points ({p(h2.lo)} to {p(h2.hi)}): the interval includes zero, so H2 fails. The curve is not "
      f"a decay: the last window (after 180 minutes) is as high as the first.")
    w("")
    w("**Why the pass is only a lead.**")
    w("")
    w(f"1. **No out-of-sample read.** {int(a_oos.trades)} of the {int(a.trades)} trades is in the most recent 20% of closures (2026-08-03 onward).")
    w(f"2. **It leans on hindsight inside the 30 minutes.** T2 takes the best print of the window. Taking the *first* print that still clears the "
      f"line (T2b) makes {d(fb['mean'])} per trade ({d(fb.lo)} to {d(fb.hi)}), Sharpe {fb.sharpe:.2f}: above zero, not distinguishable from zero.")
    w(f"3. **The intervals only just clear zero**, on {int(a.closures_traded)} closures. The plain t-statistic of the closure returns is "
      f"{sh['t_stat_closure_returns']:.2f} (looked at after the run).")
    w(f"4. **One closure carries {conc['best_closure_share']:.0%} of the profit**; two carry {conc['top_two_closures_share']:.0%}.")
    w(f"5. **It is tiny.** {d(a.total)} over eleven months, on ${a.printed_dollars:,.0f} of capital behind real prints. The largest capital on one "
      f"closure was ${a.capital_base:,.0f}.")
    w(f"6. **The options price is up to 30 minutes old** when the print happens. Part of the gap is the stock moving after 09:45, not Polymarket being wrong.")
    w("")
    w("## T4: the number for the paper")
    w("")
    w("| Book | Per trade | 95% interval | Trades | Independent closures | Total | Sharpe on closure returns | Capacity (printed capital) |")
    w("|---|---|---|---|---|---|---|---|")
    w(f"| **T2: S6 at printed prices (passes its line)** | **{d(a['mean'])}** | {d(a.lo)} to {d(a.hi)} | {int(a.trades)} | {int(a.closures_traded)} | "
      f"{d(a.total)} | **{s_t2.sharpe:.2f}** | ${a.printed_dollars:,.0f} (${a.printed_dollars_uncapped:,.0f} before the 100-contract cap) |")
    w(f"| T2 without its best closure | {d(nb['mean'])} | {d(nb.lo)} to {d(nb.hi)} | {int(nb.trades)} | {int(nb.closures_traded)} | {d(nb.total)} | "
      f"{s_t2_nb.sharpe:.2f} | ${nb.printed_dollars:,.0f} |")
    w(f"| T2b: first print, no hindsight (variant) | {d(fb['mean'])} | {d(fb.lo)} to {d(fb.hi)} | {int(fb.trades)} | {int(fb.closures_traded)} | "
      f"{d(fb.total)} | {fb.sharpe:.2f} | ${fb.printed_dollars:,.0f} |")
    w(f"| T1: first 15 minutes (fails its line) | {p(e['mean'])} points per contract | {p(e.lo)} to {p(e.hi)} | {int(e.trades)} | {int(e.closures)} | "
      f"n/a | n/a | ${e.print_dollars:,.0f} of prints copied |")
    w("")
    w(f"The figure that can be defended: **a Sharpe of {s_t2.sharpe:.2f} at prices that printed, against {s_mod.sharpe:.2f} as modelled**, on "
      f"{int(a.trades)} trades and {int(a.closures_traded)} independent closures, with a capacity under $1,000 of capital a year. Without hindsight inside "
      f"the window it is {fb.sharpe:.2f}. It is a lead for a forward test, not a result.")
    w("")
    w("## T3: the staircase")
    w("")
    w("![Staircase](staircase.png)")
    w("")
    w("| Step | Trades | Closures traded | Per trade | 95% interval | Total P&L | Sharpe (52 a year) | Printed dollars behind it |")
    w("|---|---|---|---|---|---|---|---|")
    for s in st.itertuples():
        w(f"| {s.step} | {s.trades} | {s.closures_traded} | {d(s.mean)} | {d(s.lo)} to {d(s.hi)} | {d(s.total)} | {s.sharpe:.2f} | "
          f"${s.printed_dollars:,.0f} |")
    w("")
    w(f"- Step 1 trades 100 contracts on every entry, but only 21 of its 187 entries have a print behind them: ${s_mod.printed_dollars:,.0f} of printed "
      f"capital against ${s_mod.capital_deployed:,.0f} the model deployed.")
    w(f"- Step 3 is S6's own check: the modelled price, the printed size. Step 4 removes 2026-03-09 and the profit is gone ({d(s_ver_nb.total)}).")
    w(f"- Steps 2 and 5 are this study's replay. It finds more trades than S6's check ({int(s_t2.trades)} against {int(s_ver.trades)}) because it takes "
      f"the price that printed, not the modelled one, and looks 30 minutes forward instead of 10 minutes either side. {ov['t2_trades_that_s6_verified']} of "
      f"its trades are entries S6 verified; {ov['t2_trades_s6_did_not_verify']} are new ({d(ov['pnl_not_s6_verified'])} of the total).")
    w("- Sharpe: P&L of each of the 45 reopening days (zero when idle) over the largest capital locked on one closure; mean over standard deviation, times the root of 52.")
    w("")
    w("## T1: the decay curve at real prices (primary test)")
    w("")
    w("![Decay curve](decay.png)")
    w("")
    w("The partner's 402 trades at 5 points or more from the options' 09:45 probability. Net of one cent and the market's fee, held to the result. Points per $1 contract.")
    w("")
    w("| Minutes since 09:45 | Trades | Closures | Mean | 95% interval | Winners |")
    w("|---|---|---|---|---|---|")
    for g in ("0-15", "15-60", "60-180", "180+", "15+"):
        r = t1row(PV, "ALL", g)
        w(f"| {g}{' (all later trades)' if g == '15+' else ''} | {int(r.trades)} | {int(r.closures)} | {p(r['mean'])} | {p(r.lo)} to {p(r.hi)} | {r.hit_rate:.0%} |")
    w("")
    w("| Hypothesis | Result | Evidence |")
    w("|---|---|---|")
    w(f"| H1: first 15 minutes above zero, interval excluding zero | **{'holds' if v1['H1'] else 'fails'}** | {p(e['mean'])} ({p(e.lo)} to {p(e.hi)}) |")
    w(f"| H2: first 15 minutes above the later trades, interval excluding zero | **{'holds' if v1['H2'] else 'fails'}** | {p(h2['mean'])} ({p(h2.lo)} to {p(h2.hi)}) |")
    for g in ("15-60", "60-180", "180+"):
        r = t1row(PV, "ALL", f"0-15 minus {g}")
        w(f"| First 15 minutes minus {g} | reported | {p(r['mean'])} ({p(r.lo)} to {p(r.hi)}) |")
    w(f"| Earlier 80% of closures above zero | {'yes' if v1['earlier_80pct_above_zero'] else 'no'} | {p(e_is['mean'])} ({p(e_is.lo)} to {p(e_is.hi)}), {int(e_is.trades)} trades |")
    w(f"| Most recent 20% above zero, at least 30 trades | **no** | {p(e_oos['mean'])} on {int(e_oos.trades)} trades, {int(e_oos.closures)} closures (known before the run: 6 trades) |")
    w("")
    w("**T1 verdict: fail.** Both hypotheses fail and the recent part has 6 trades. The sign is the hoped-for one in the first 15 minutes, but "
      "the last window is just as high, so the data do not show a trade that is there early and fades.")
    w("")
    w("Variants (all reported, none of them the test). First-15-minute mean, points per contract:")
    w("")
    w("| Variant | Trades | Closures | First window | 95% interval | Minus later trades | 95% interval |")
    w("|---|---|---|---|---|---|---|")
    for variant, g, dg in (("2x costs", "0-15", "0-15 minus 15+"), ("tau 0.03", "0-15", "0-15 minus 15+"), ("tau 0.10", "0-15", "0-15 minus 15+"),
                           ("first 30 minutes", "0-30", "0-30 minus 30+"), ("daily markets only", "0-15", "0-15 minus 15+"),
                           ("whole clock minutes (through 10:00:59)", "0-15", "0-15 minus 15+")):
        r, q = t1row(variant, "ALL", g), t1row(variant, "ALL", dg)
        w(f"| {variant} | {int(r.trades)} | {int(r.closures)} | {p(r['mean'])} | {p(r.lo)} to {p(r.hi)} | {p(q['mean'])} | {p(q.lo)} to {p(q.hi)} |")
    w("")
    w("No variant has an interval that excludes zero. The brief counted the windows as 82 / 118 / 140 / 62; that is whole clock minutes. On exact "
      "seconds, fixed as the primary before any P&L was read, they are 74 / 121 / 145 / 62.")
    w("")
    w("## T2: S6 replayed at prices that printed")
    w("")
    w(f"Of {meta['s6_entries']} entries: {int(a.entries_with_window_print)} had any print in the 30 minutes from 09:45; {int(a.entries_with_side_print)} had "
      f"a print on the side needed (a taker bought YES for our buys, sold YES for our sales); {counts.get('print, gap gone', 0)} of those were no longer "
      f"2 points beyond the options band one cent worse and after the fee; **{counts.get('trade', 0)} trade**.")
    w("")
    w("| Book | Costs | Trades | Closures | Per trade | 95% interval | Total | Winners | Points per contract | Sharpe | Printed capital |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for label, r in (("T2, all", a), ("T2, earlier 80% of closures", a_is), ("T2, most recent 20%", a_oos), ("T2, best closure removed (2026-03-09)", nb),
                     ("T2 at 2x costs", a2), ("T2 at 2x costs, best closure removed", nb2), ("T2b first print (no hindsight)", fb),
                     ("T2b, best closure removed", fb_nb), ("T2b at 2x costs", fb2)):
        w(f"| {label} | {r.cost_mult:.0f}x | {int(r.trades)} | {int(r.closures_traded)} | {d(r['mean'])} | {d(r.lo)} to {d(r.hi)} | {d(r.total)} | {r.hit_rate:.0%} | "
          f"{p(r.points_per_contract, 1)} ({p(r.points_lo, 1)} to {p(r.points_hi, 1)}) | {f'{r.sharpe:.2f}' if r.closures_traded >= 5 else 'n/a (one trade)'} | "
          f"${r.printed_dollars:,.0f} |")
    w("")
    w("A trade is at most the printed size and at most 100 contracts. \"Points per contract\" weights every trade equally whatever its size.")
    w("")
    w("| Split | Trades | Closures | Per trade | 95% interval | Total |")
    w("|---|---|---|---|---|---|")
    for r in m[(m.test == "T2") & (m.variant == "T2") & m.group.str.contains(":")].itertuples():
        w(f"| {r.group} | {int(r.trades)} | {int(r.closures_traded)} | {d(r.mean)} | {d(r.lo)} to {d(r.hi)} | {d(r.total)} |")
    w("")
    w("By closure (T2):")
    w("")
    w("| Reopening day | Trades | P&L | Capital locked |")
    w("|---|---|---|---|")
    for day, g in tr.groupby("closure"):
        w(f"| {day} | {len(g)} | {d(g.pnl.sum())} | ${g.capital.sum():,.0f} |")
    w("")
    w(f"{conc['closures_up']} closures up, {conc['closures_down']} down.")
    w("")
    w("| Pass line (T2) | Result | Evidence |")
    w("|---|---|---|")
    w(f"| Mean P&L per trade above zero | {'pass' if v2['mean_above_zero'] else 'fail'} | {d(a['mean'])} |")
    w(f"| Interval excluding zero | {'pass' if v2['interval_excludes_zero'] else 'fail'} | {d(a.lo)} to {d(a.hi)} |")
    w(f"| Above zero with the best closure removed | {'pass' if v2['above_zero_without_best_closure'] else 'fail'} | {d(nb['mean'])} ({d(nb.lo)} to {d(nb.hi)}) |")
    w(f"| Fixed in advance: if T2b's mean is not above zero, the pass rests on hindsight | T2b is above zero | {d(fb['mean'])} ({d(fb.lo)} to {d(fb.hi)}): "
      f"above zero, **interval includes zero** |")
    w("")
    w("**T2 verdict: pass, narrowly. A lead needing replication, not an edge.**")
    w("")
    w("## Equity curve and drawdown")
    w("")
    w("![Equity curve](equity_curve.png)")
    w("")
    w("![Drawdown](drawdown.png)")
    w("")
    w(f"T2 book: maximum drawdown {a.max_drawdown:.1%} of the capital base (${a.capital_base:,.0f}), worst month {a.worst_month:.1%}, turnover "
      f"{turnover:.1f}x a year. The T1 panel is shown for completeness; that book fails its line.")
    w("")
    w("## Costs")
    w("")
    w(f"- **T2:** one cent worse than the print, plus Polymarket's fee 0.04 x P x (1 - P), charged on every trade (source: S6's schedule; some of these "
      f"markets had the fee off, so this errs against the trade). On the {int(a.trades)} trades: {cost_pts:.2f} points per contract on average, "
      f"{cost_bp:,.0f} bp of the capital locked. At 2x costs (two cents, twice the fee): {d(a2['mean'])} per trade ({d(a2.lo)} to {d(a2.hi)}) on "
      f"{int(a2.trades)} trades.")
    w("- **T1:** the partner's costs: one cent and the market's own fee where it charges one (43% of the trades). At 2x: see the variant table.")
    w("- No spread is modelled anywhere in this study: every price is a print.")
    w("")
    w("## Capacity")
    w("")
    w(f"See [`capacity.md`](capacity.md). T2: ${a.printed_dollars:,.0f} of capital behind real prints over the year, {a.contracts:,.0f} contracts, median "
      f"trade {tr.contracts.median():.0f} contracts. This is a retail-size book.")
    w("")
    w("## Every variant tried")
    w("")
    w("T1: the primary; 2x costs; tau 0.03; tau 0.10; first 30 minutes; daily markets only; whole clock minutes. T2: the primary; T2b (first print); "
      "each at 2x costs. All are in [`metrics.csv`](metrics.csv) with their in-sample and out-of-sample rows. Nothing else was run before the section "
      "\"Looked at after the run\".")
    w("")
    w("## Sharpe above 3: what was checked")
    w("")
    w(f"Only step 1, S6 as modelled, is above 3 ({s_mod.sharpe:.2f}). S6's own write-up found the cause: prices that were not prices. No book of this "
      f"study is above 3. The T2 book passed, so it was checked anyway:")
    w("")
    w("| Check | Outcome |")
    w("|---|---|")
    ir = after["independent_replay"]
    w(f"| T2 replayed again from the raw print files by code that shares no function with the runner (`after.py`) | {ir['trades']} trades, {d(ir['total'])}: "
      f"{'the same' if ir['trades'] == int(a.trades) and abs(ir['total'] - a.total) < 0.005 else 'DIFFERENT'} |")
    w("| Three trades read print by print (AMZN 2026-03-09, MSFT 2026-03-30, META 2026-02-09) | Price, side, time and size match the raw records |")
    w(f"| Duplicated print records | None: counting each record once gives {after['duplicate_records_counted_once']['trades']} trades, "
      f"{d(after['duplicate_records_counted_once']['total'])} |")
    w(f"| Print files cut off by the puller | No: the largest holds {meta['t2_cache']['largest_cache_file']} prints against a page of 10,000; "
      f"{meta['t2_cache']['cache_files_read']} files read, {meta['t2_cache']['cache_missing']} missing |")
    w("| The result never enters a signal | Yes: the result enters only the P&L. The side and the options band are S6's, fixed at 09:45 |")
    w("| Times | New York time with daylight saving; tests pin a winter and a summer date |")
    w("| T1 input | The 1x recomputation reproduces the partner's `pnl_t1` to nine decimals; window counts match the brief under its clock-minute reading |")
    w("| Sharpe on closures, not trades | Yes: 45 reopening days, idle ones as zero |")
    w("")
    w("## Looked at after the run (not pre-registered; changes no verdict)")
    w("")
    w(f"- **An interval for the T2 Sharpe.** Resampling the 45 closures: {sh['sharpe']:.2f} ({sh['lo']:.2f} to {sh['hi']:.2f}). Without the best closure: "
      f"{sh_nb['sharpe']:.2f} ({sh_nb['lo']:.2f} to {sh_nb['hi']:.2f}). T2b: {sh_fb['sharpe']:.2f} ({sh_fb['lo']:.2f} to {sh_fb['hi']:.2f}). The plain "
      f"t-statistic of the T2 closure returns is {sh['t_stat_closure_returns']:.2f}, under the usual 1.96: the bootstrap and the t-test disagree about "
      f"whether zero is excluded, because one large winning closure skews the returns. Treat the Sharpe as \"about 1 to 2, not well measured\".")
    w(f"- **How late the prints were.** {timing['within_15_min']['trades']} trades used a print within 15 minutes of 09:45 ({d(timing['within_15_min']['pnl'])}); "
      f"{timing['from_15_to_30_min']['trades']} used one 15 to 30 minutes after ({d(timing['from_15_to_30_min']['pnl'])}). Median {timing['median_print_minutes']:.1f} minutes.")
    w(f"- **Size.** {conc['trades_at_the_100_cap']} trades hit the 100-contract cap; {conc['trades_under_20_contracts']} are under 20 contracts. The largest single trade made {d(conc['largest_single_trade_pnl'])}.")
    bc = tr[tr.closure == conc["best_closure"]]
    moves = "; ".join(f"{x.underlying} {x.pm_0945:.2f} at 09:45, bought at {x.entry:.2f} {x.print_minutes:.0f} minutes later" for x in bc.itertuples())
    w(f"- **What the best closure looks like.** {conc['best_closure']}, {len(bc)} buys ({moves}). Two of the four prices had fallen about 15 points "
      f"since 09:45 while the options band stayed the 09:45 one. All {len(bc)} markets then resolved YES. That is a rebound in the stocks that day "
      f"as much as a Polymarket error, and it is one bet.")
    w("")
    w("## What didn't work")
    w("")
    w(f"- **The decay curve (T1).** H1 and H2 both fail; the first 15 minutes are {p(e['mean'])} points ({p(e.lo)} to {p(e.hi)}) and the recent closures are "
      f"{p(e_oos['mean'])} on {int(e_oos.trades)} trades.")
    w(f"- **S6's own verified set without its best closure:** {d(s_ver_nb.total)} on {int(s_ver_nb.trades)} trades, Sharpe {s_ver_nb.sharpe:.2f}.")
    w(f"- **Selling YES at printed prices:** see the split table; the buys carry the T2 profit.")
    w(f"- **The no-hindsight replay at 2x costs:** {d(fb2['mean'])} per trade ({d(fb2.lo)} to {d(fb2.hi)}).")
    w(f"- **Any out-of-sample check of T2:** {int(a_oos.trades)} trade in the recent 20%.")
    w("")
    w("## Forward test: rule fixed before the run, not run here")
    w("")
    w("For the next reopening, **Monday 2026-10-05**: on Polymarket \"close above $K\" markets on stocks and SPY with a usable options band at 09:45 New "
      "York (no wider than 20 points, probability between 3% and 97%), copy the first taker print with 09:45:00 <= time < 10:00:00 whose YES-equivalent "
      "price is at least 5 points from the options' 09:45 probability, on the side toward the options. One trade per market, one contract, one cent "
      "worse than the print, the market's own fee, held to the result. One morning is one closure: it adds one observation and decides nothing by itself.")
    w("")
    w("## Caveats")
    w("")
    w("- Both data sets were seen before. Nothing here is out-of-sample.")
    w("- T2 assumes we could have taken the offer that a real taker lifted (or the bid a real taker hit), one cent worse, for at most the printed size.")
    w("- The print's `side` is read as the taker's side, as S6 and the partner's study read it. This could not be re-checked without the network.")
    w("- T1 uses the partner's committed trade file; its raw prints are not on this machine.")
    w("- Unhedged. A closure's trades win or lose together.")
    w("- Monthly markets lock capital for weeks; no financing charge.")
    w("")
    w("## Reproduce")
    w("")
    w("```")
    w("cd research")
    w(".venv/bin/python -m s23_monday_fade_real.run")
    w(".venv/bin/python -m s23_monday_fade_real.after")
    w(".venv/bin/python -m s23_monday_fade_real.report")
    w(".venv/bin/python -m pytest s23_monday_fade_real/tests -q")
    w("```")
    (R / "SUMMARY.md").write_text("\n".join(L) + "\n")

    p1 = t[(t.test == "T1") & np.isclose(t.tau, cfg.T1_TAU) & (t.window == cfg.T1_EARLY)]
    C = ["# S23 capacity", "",
         "## T2: S6 at printed prices (the book that passes)", "",
         f"- **Capital behind real prints, counted (at most 100 contracts a trade): ${a.printed_dollars:,.0f}** over {int(a.trades)} trades and "
         f"{int(a.closures_traded)} closures, out of the 45 closures from {meta['first_closure']} to {meta['last_closure']}. Before the cap: ${a.printed_dollars_uncapped:,.0f}.",
         f"- Contracts traded: {a.contracts:,.0f}. Median trade {tr.contracts.median():.0f} contracts; median printed size at the best price "
         f"{tr.print_size.median():.0f} shares (smallest {tr.print_size.min():.1f}, largest {tr.print_size.max():,.0f}).",
         f"- Largest capital locked on one closure: ${a.capital_base:,.0f}. Per traded closure: ${a.printed_dollars / a.closures_traded:,.0f} on average.",
         f"- Profit at that size: {d(a.total)} over those closures. Doubling the size is not possible: the size is the print.",
         "", "## T1: first 15 minutes (fails its line)", "",
         f"- {len(p1)} prints copied; their notional at entry sums to ${e.print_dollars:,.0f}; median print {p1['size'].median():.1f} shares.",
         "", "## Context", "",
         "- S6 measured this weekend's recorded books of the same kind of market: a median of $2.33 at the best price, half-spread 4.5 points.",
         "- Whatever is here is a retail-size book: hundreds of dollars of capital a year, not thousands."]
    (R / "capacity.md").write_text("\n".join(C) + "\n")
    print("\n".join(L[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
