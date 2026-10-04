"""S16 (overnight options): the plain-language answer of SUMMARY.md, built from the result files so that no number is typed by hand.

The wording was written after the run; the rules it reports on were fixed before it (METHOD.md)."""
from __future__ import annotations

import pandas as pd

from . import config as cfg
from .report import R, RESULTS, ci, num, pct, tier_state, upct


def excl(lo, hi) -> bool:
    """A 95% interval that excludes zero."""
    return lo == lo and hi == hi and (lo > 0 or hi < 0)


def says(lo, hi) -> str:
    return "the interval excludes zero" if excl(lo, hi) else "the interval includes zero"


def answer(r: R) -> tuple[list[str], list[str], list[str]]:
    st = r.meta["status"]
    fin, stopped = tier_state(r.meta)
    verdict = {h: r.v[r.v.hypothesis == h].verdict.iloc[0] for h in cfg.HYPOTHESES}
    row = r.row
    ov_d, ov_s = r.speed("directional", cfg.PREV_CLOSE, cfg.T0931), r.speed("straddle", cfg.PREV_CLOSE, cfg.T0931)
    sd = {k: r.speed("directional", k) for k in cfg.MORNING}
    ss = {k: r.speed("straddle", k) for k in cfg.MORNING}
    sp = {k: r.spread("straddle", k) for k in (cfg.PREV_CLOSE,) + cfg.MORNING + (cfg.CLOSE,)}
    spc = {k: r.spread("straddle", k, "control") for k in cfg.MORNING}
    spd = {k: r.spread("directional", k) for k in cfg.MORNING}
    n_ev, n_ok = sum(st["main"]["event"].values()), st["main"]["event"].get("ok", 0)
    n_ct, n_ct_ok = sum(st["main"]["control"].values()), st["main"]["control"].get("ok", 0)
    oos_n = r.meta["main_events_ok_by_segment"]["OOS"]
    any_speed = [(inst, k) for inst, d in (("straddle", ss), ("directional", sd)) for k, x in d.items() if x is not None and excl(x.diff_ci_lo, x.diff_ci_hi)]
    ev = r.obs[(r.obs["sample"] == "main") & (r.obs.kind == "event") & (r.obs.status == "ok")]
    ct = r.obs[(r.obs["sample"] == "main") & (r.obs.kind == "control") & (r.obs.status == "ok")]
    gap_signed = float((ev.direction * ev.gap_bp).mean())
    td = r.t[(r.t.variant == "V0") & (r.t.hypothesis == "H-dir") & (r.t.kind == "event")]
    after_signed = float((td.direction * td.underlying_move_bp).mean())
    all_lose = all(row(h, "ALL", "1x").ci_hi < 0 for h in cfg.HYPOTHESES)

    A: list[str] = []
    # ---- the lead: what is significant and true
    A += [f"**The overnight move is already in the option's price at the first reading of the day.** At 09:31, one minute into the session, the option "
          f"that points the way the odds moved (a call if the odds said up, a put if down) was worth {pct(ov_d['mean'])} more on average than at 15:55 the "
          f"day before (95% interval {ci(ov_d.ci_lo, ov_d.ci_hi)}; median {pct(ov_d['median'])}; {int(ov_d.trades)} ticker-days, mid prices; "
          f"{says(ov_d.ci_lo, ov_d.ci_hi)}). "
          f"The stock itself had opened {gap_signed:+.0f} bp in the direction of the odds (S5 found +137 bp).", ""]
    if not any_speed:
        A += ["**After that first reading there is nothing left that shows up against ordinary mornings.** Bought at the mid price at 09:31, 09:35, 09:45, "
              "10:00 or 10:30 and held to 15:55, the options on event mornings did no better and no worse than the same options on quiet mornings of the "
              "same ticker. All ten intervals include zero. The first three:", ""]
    else:
        A += ["**After that first reading, most of the comparison with ordinary mornings is flat. These cells have an interval that excludes zero:** "
              + "; ".join(f"{inst} bought at {k}" for inst, k in any_speed) + ". They are single cells of a ten-cell table and are read with that in mind.", ""]
    A += ["| Bought at | Option in the direction of the odds: event minus control | Straddle: event minus control |", "|---|---|---|"]
    for k in (cfg.T0931, cfg.T0935, cfg.T0945):
        A.append(f"| {k} | {pct(sd[k].diff_mean)} {ci(sd[k].diff_ci_lo, sd[k].diff_ci_hi)} ({int(sd[k].pairs)} pairs) | "
                 f"{pct(ss[k].diff_mean)} {ci(ss[k].diff_ci_lo, ss[k].diff_ci_hi)} ({int(ss[k].pairs)} pairs) |")
    A += ["", "(Return from that instant to 15:55, mid price to mid price, event morning minus its matched quiet morning. A straddle is a call plus a put at "
          "the same strike: it gains from a large move either way.) "
          f"After 09:35 the stock moved {after_signed:+.0f} bp in the direction of the odds by 15:55, which is nothing, as S5 found for shares.", "",
          f"**Options are {sp[cfg.T0931].median_spread_share / sp[cfg.T1030].median_spread_share:.1f} times as wide in the first minute as an hour later.** "
          f"The median straddle is quoted "
          f"{upct(sp[cfg.T0931].median_spread_share)} wide at 09:31, as a share of its own price; {upct(sp[cfg.T0935].median_spread_share)} at 09:35; "
          f"{upct(sp[cfg.T0945].median_spread_share)} at 09:45; {upct(sp[cfg.T1030].median_spread_share)} at 10:30; "
          f"{upct(sp[cfg.PREV_CLOSE].median_spread_share)} at the previous close. For the single option in the direction of the odds: "
          f"{upct(spd[cfg.T0931].median_spread_share)} at 09:31 and {upct(spd[cfg.T0935].median_spread_share)} at 09:35. Quiet mornings are just as wide "
          f"({upct(spc[cfg.T0931].median_spread_share)} at 09:31, {upct(spc[cfg.T0935].median_spread_share)} at 09:35), so the width is the open, not the "
          f"event. Whatever is not yet priced in the first minutes is smaller than the cost of crossing that spread twice.", "",
          "**The three pre-registered trades, in at the 09:35 quote and out at the 15:55 quote, at real bid and ask:**", ""]
    for hyp, what in (("H-dir", "Theo's literal claim: buy the option in the direction of the odds move"),
                      ("H-slow", "Options too cheap at the open: buy the straddle"), ("H-rich", "Options too dear at the open: sell the straddle")):
        o, a, m, i, o2 = row(hyp, "OOS", "1x"), row(hyp, "ALL", "1x"), row(hyp, "ALL", "mid"), row(hyp, "IS", "1x"), row(hyp, "OOS", "2x")
        failed = [x.line.split(")")[0] + ")" for x in r.v[r.v.hypothesis == hyp].itertuples() if not x.met]
        A.append(f"- **{hyp}. {what}. Verdict: {verdict[hyp]}"
                 + (f" (lines not met: {', '.join(failed)})" if failed else "") + f".** Out-of-sample: {pct(o['mean'])} of the premium per trade "
                 f"{ci(o.ci_lo, o.ci_hi)} on {int(o.trades)} trades and {int(o.dates)} dates; at doubled costs {pct(o2['mean'])} (median {pct(o2['median'])}); "
                 f"in-sample {pct(i['mean'])} on {int(i.trades)} trades. Whole sample: {pct(a['mean'])} {ci(a.ci_lo, a.ci_hi)} on {int(a.trades)} trades, "
                 f"median {pct(a['median'])}, {upct(a.hit_rate, 0)} winners; before any cost (mid to mid) {pct(m['mean'])} {ci(m.ci_lo, m.ci_hi)}."
                 + (f" Against matched control mornings, at real quotes: {pct(a.diff_mean)} {ci(a.diff_ci_lo, a.diff_ci_hi)} ({int(a.pairs)} pairs)." if a.pairs else ""))
    passed = [h for h in cfg.HYPOTHESES if verdict[h].startswith("pass")]
    A += ["", ("**No hypothesis passes" + (", and at real quotes all three trades lose with intervals that exclude zero.**" if all_lose else ".**")
               if not passed else
               f"**{', '.join(passed)} meets the pre-registered pass line. One pass out of three hypotheses is a lead that needs replication, not an edge.**")
          + " H-slow and H-rich are mirror trades: before costs one earns what the other loses, and at real quotes both pay the spread. "
          "The mean of H-rich at doubled costs is driven by a few quotes whose bid falls to almost nothing when the spread is doubled; its median is the "
          "fairer figure.", "",
          f"**Counts.** {n_ev} event ticker-days at 10+ points on {r.meta['main_event_dates']} dates; {n_ok} had valid quotes at 09:35 and 15:55 "
          f"({n_ev - n_ok} dropped: " + ", ".join(f"{k}: {v}" for k, v in st["main"]["event"].items() if k != "ok") + f"). Controls: {n_ct} matched, "
          f"{n_ct_ok} with valid quotes ({n_ev - n_ct} events had no quiet session within 30 trading days). Out-of-sample event trades: {oos_n} "
          f"(the pass line needs 30).", ""]
    v4m, v4n, v4o, v4i = row("H-dir", "ALL", "mid", "V4"), row("H-dir", "ALL", "1x", "V4"), row("H-dir", "OOS", "mid", "V4"), row("H-dir", "IS", "mid", "V4")
    if v4m is not None and excl(v4m.diff_ci_lo, v4m.diff_ci_hi):
        A += [f"**One variant gets a flag, not a claim.** After weekends and holidays (V4, {int(v4m.trades)} trades), the option in the direction of the odds "
              f"returned {pct(v4m['mean'])} mid to mid {ci(v4m.ci_lo, v4m.ci_hi)} against {pct(v4m.control_mean)} for the same side on quiet mornings: a "
              f"difference of {pct(v4m.diff_mean)} {ci(v4m.diff_ci_lo, v4m.diff_ci_hi)} ({int(v4m.pairs)} pairs). In-sample {pct(v4i.diff_mean)} "
              f"{ci(v4i.diff_ci_lo, v4i.diff_ci_hi)}; out-of-sample {pct(v4o.diff_mean)} {ci(v4o.diff_ci_lo, v4o.diff_ci_hi)} on {int(v4o.pairs)} pairs, "
              f"which {'excludes' if excl(v4o.diff_ci_lo, v4o.diff_ci_hi) else 'includes'} zero. At real quotes the trade returned {pct(v4n['mean'])} "
              f"{ci(v4n.ci_lo, v4n.ci_hi)}. It is one of 15 looks, its own return before costs is not distinguishable from zero, its controls are mostly "
              f"weekday mornings ({r.meta['controls_of_weekend_events']['themselves_after_a_weekend']} of {r.meta['controls_of_weekend_events']['n']} follow a "
              "weekend), and it does not survive the spread.", ""]
    # ---- the case files in one line each
    bz, oil_d, oil_s = row("H-dir", "ALL", "1x", "V0", "case: brazil"), row("H-dir", "ALL", "1x", "V0", "case: oil"), row("H-slow", "ALL", "1x", "V0", "case: oil")
    bzs = row("H-slow", "ALL", "1x", "V0", "case: brazil")
    bzm = row("H-dir", "ALL", "mid", "V0", "case: brazil")
    fd_s, fd_m, fd_r = row("H-slow", "ALL", "1x", "V0", "case: fed"), row("H-slow", "ALL", "mid", "V0", "case: fed"), row("H-rich", "ALL", "1x", "V0", "case: fed")
    A.append("**Case files (exploratory, details below).**")
    if bz is not None and bzs is not None:
        bsm, brn = row("H-slow", "ALL", "mid", "V0", "case: brazil"), row("H-rich", "ALL", "1x", "V0", "case: brazil")
        A.append(f"- Brazil, EWZ options, {int(bzs.trades)} of 13 mornings with a 5+ point move in a first-round question had quotes. Option in the direction "
                 f"of the odds: {pct(bz['mean'])} net {ci(bz.ci_lo, bz.ci_hi)}, {pct(bzm['mean'])} mid to mid, but the same option on quiet mornings did as well "
                 f"(event minus control {pct(bzm.diff_mean)} {ci(bzm.diff_ci_lo, bzm.diff_ci_hi)}). Straddle: {pct(bsm['mean'])} mid to mid against "
                 f"{pct(bsm.control_mean)} on quiet mornings, a difference of {pct(bsm.diff_mean)} {ci(bsm.diff_ci_lo, bsm.diff_ci_hi)}"
                 + (", an interval that excludes zero: EWZ straddles were dearer at 09:35 on those mornings than they turned out to be worth"
                    if (bsm.diff_ci_hi < 0 or bsm.diff_ci_lo > 0) else "")
                 + f". Selling that straddle at real quotes returned {pct(brn['mean'])} {ci(brn.ci_lo, brn.ci_hi)}; buying it returned {pct(bzs['mean'])}. "
                 f"{int(bzs.trades)} mornings, one of many looks: an observation for the forward test, not a finding.")
    else:
        A.append("- Brazil: not pulled.")
    if oil_d is not None:
        om, osm = row("H-dir", "ALL", "mid", "V0", "case: oil"), row("H-slow", "ALL", "mid", "V0", "case: oil")
        A.append(f"- Oil (USO, XLE, XOP), {int(oil_d.trades)} ticker-days: directional option {pct(oil_d['mean'])} net {ci(oil_d.ci_lo, oil_d.ci_hi)}, "
                 f"{pct(om['mean'])} mid to mid {ci(om.ci_lo, om.ci_hi)}; straddle {pct(oil_s['mean'])} net, {pct(osm['mean'])} mid to mid; against controls "
                 f"mid to mid: directional {pct(om.diff_mean)} {ci(om.diff_ci_lo, om.diff_ci_hi)}, straddle {pct(osm.diff_mean)} {ci(osm.diff_ci_lo, osm.diff_ci_hi)}.")
    if fd_s is not None:
        A.append(f"- Fed and banks (TLT, KRE, XLF straddles on mornings when a Fed question moved 5+ points), {int(fd_s.trades)} ticker-days"
                 + ("" if 4 in fin else " (incomplete pull)") + f": bought at 09:35, {pct(fd_s['mean'])} net {ci(fd_s.ci_lo, fd_s.ci_hi)}, {pct(fd_m['mean'])} "
                 f"mid to mid {ci(fd_m.ci_lo, fd_m.ci_hi)}; sold at 09:35, {pct(fd_r['mean'])} net {ci(fd_r.ci_lo, fd_r.ci_hi)}; against controls mid to mid "
                 f"{pct(fd_m.diff_mean)} {ci(fd_m.diff_ci_lo, fd_m.diff_ci_hi)} ({int(fd_m.pairs)} pairs). Before costs the difference from quiet mornings "
                 "is not distinguishable from zero; at real quotes neither side pays.")
    else:
        A.append("- Fed and banks: not pulled.")
    sm = row("H-slow", "ALL", "mid")
    tilt = [("main sample", sm), ("oil (part of the main sample)", row("H-slow", "ALL", "mid", "V0", "case: oil")), ("Fed and banks", fd_m),
            ("Brazil", row("H-slow", "ALL", "mid", "V0", "case: brazil"))]
    tilt = [(n_, x) for n_, x in tilt if x is not None]
    if tilt and all(x.diff_mean < 0 for _, x in tilt):
        A += ["", "**If there is a tilt, it points the other way from the claim.** In every sample the straddle bought at 09:35 did a little worse on event "
              "mornings than on quiet mornings, mid to mid: " + "; ".join(f"{n_} {pct(x.diff_mean)} {ci(x.diff_ci_lo, x.diff_ci_hi)}" for n_, x in tilt)
              + ". Intervals that exclude zero: " + (", ".join(n_ for n_, x in tilt if excl(x.diff_ci_lo, x.diff_ci_hi)) or "none")
              + ". That is options slightly too dear at 09:35 after an odds move, not too cheap, and in every sample it "
              "is a fraction of the spread a seller would have to cross."]
    A += ["",
          "**What this does and does not say about the claim.** The claim was that the whole overnight move cannot be perfectly priced into the options in "
          "the first moments of the session. This study's first reading is at 09:31, sixty seconds in. It does not see the first second, and at 09:31 the "
          "quotes are so wide that \"the price\" is a band, not a number. What it does say: inside that band the options had already moved with the odds, "
          "and from 09:31 onward event mornings cannot be told apart from quiet mornings, before costs. If part of the move is still unpriced at 09:31, "
          f"it is smaller than this sample can see: the interval on the directional option is {ci(sd[cfg.T0931].diff_ci_lo, sd[cfg.T0931].diff_ci_hi)} "
          f"and on the straddle {ci(ss[cfg.T0931].diff_ci_lo, ss[cfg.T0931].diff_ci_hi)}, against a spread of "
          f"{upct(sp[cfg.T0931].median_spread_share)}."]

    # ---- looked at after the run
    after: list[str] = []
    hi = r.m[(r.m.scope == "main") & (r.m.sharpe > 3)]
    if len(hi):
        x = row("H-rich", "OOS", "mid")
        n1 = row("H-rich", "OOS", "1x")
        pa = r.meta["parity_gap_share_abs"]
        after += ["## Bug hunt (a Sharpe above 3 appeared)", "",
                  "Rows of `metrics.csv` with a Sharpe above 3: " + "; ".join(f"{y.hypothesis} {y.variant} {y.segment} at {y.costs} ({num(y.sharpe)})" for y in hi.itertuples())
                  + (". Every one of them is **mid to mid, with no cost**: selling a straddle at the mid price and buying it back at the mid price, which nobody can do. "
                     if set(hi.costs) == {"mid"} else ". **Not all of them are mid to mid: see the rows.** ")
                  +
                  f"The primary one: {pct(x['mean'])} a trade out-of-sample {ci(x.ci_lo, x.ci_hi)}, and control mornings show the same ({pct(x.control_mean)}). "
                  f"That is one day of ordinary time decay with little variance, on {int(x.dates)} days of trades among {int(x.sessions)} sessions; it is not specific to events "
                  f"(event minus control {pct(x.diff_mean)} {ci(x.diff_ci_lo, x.diff_ci_hi)}). At real quotes the same trade's Sharpe is {num(n1.sharpe)}. Checked anyway: "
                  "every entry quote is stamped at or after 09:30:00 and at or before its instant (enforced in code and in the tests); the strike uses only the "
                  "09:30 price; entry and exit are at opposite sides of the quote; "
                  f"put-call parity at 09:35 holds to a median of {upct(pa['median'], 2)} of the stock price, with {pa['over_2pct']} of {pa['n']} above 2% "
                  f"({', '.join(sorted(set(r.obs[r.obs.parity_gap_share.abs() > 0.02].ticker)))}): mornings with a very wide quote or a stock that moved several "
                  "percent in its first five minutes. In each of them the strike is the listed one nearest the opening price, so none is a wrong contract. "
                  "No bug was found.", ""]
    # ---- every event-minus-control interval in the result files that excludes zero (the price of many looks)
    mm = r.m[r.m.diff_ci_lo.notna() & r.m.diff_ci_hi.notna()]
    hit = mm[(mm.diff_ci_lo > 0) | (mm.diff_ci_hi < 0)]
    sc_ = r.sc[r.sc.diff_ci_lo.notna() & r.sc.diff_ci_hi.notna()]
    hit2 = sc_[(sc_.diff_ci_lo > 0) | (sc_.diff_ci_hi < 0)]
    after += ["## Every event-minus-control interval that excludes zero, anywhere in the result files", "",
              f"`metrics.csv` holds {len(mm)} event-minus-control comparisons with an interval (trades, variants, segments, cost levels, case files; many of "
              f"them overlap); {len(hit)} exclude zero. `speed_curve.csv` holds {len(sc_)}; {len(hit2)} exclude zero. At a 95% level about one in twenty "
              "would do so by chance if nothing were there. The list:", ""]
    after += [f"- {y.scope}, {y.variant}, {y.hypothesis}, {y.segment}, {y.costs}: {pct(y.diff_mean)} {ci(y.diff_ci_lo, y.diff_ci_hi)} ({int(y.pairs)} pairs)"
              for y in hit.itertuples()] or ["- none in `metrics.csv`"]
    after += [f"- speed curve, {y.sample}, {y.segment}, {y.instrument}, from {y[4]}: {pct(y.diff_mean)} {ci(y.diff_ci_lo, y.diff_ci_hi)} ({int(y.pairs)} pairs)"
              for y in hit2.itertuples()] or ["- none in `speed_curve.csv`"]
    after += ["", "## Looked at after the run (not pre-registered; nothing here is a test)", ""]
    f = RESULTS / "after_the_run_spread_split.csv"
    if f.exists():
        ss_ = pd.read_csv(f)
        if len(ss_):
            cut = ss_.median_cut_spread_share.iloc[0]
            after += [f"Thinly quoted tickers dominate a mean return, most of all for H-rich, whose return is measured on the small premium received at the "
                      f"bid. The primary trades are therefore split at the median entry spread of the event straddles ({upct(cut)} of the premium). No "
                      f"threshold was chosen; the split was written while the pull ran, after the first 16 events were seen.", "",
                      "| Half | Trade | Trades | Net return at 1x | 95% interval | Median | Mid to mid | Event minus control, mid to mid |", "|---|---|---|---|---|---|---|---|"]
            for half in ("tighter half", "wider half"):
                for hyp in cfg.HYPOTHESES:
                    a = ss_[(ss_.half == half) & (ss_.hypothesis == hyp) & (ss_.costs == "1x")].iloc[0]
                    m = ss_[(ss_.half == half) & (ss_.hypothesis == hyp) & (ss_.costs == "mid")].iloc[0]
                    after.append(f"| {half} | {hyp} | {int(a.trades)} | {pct(a['mean'])} | {ci(a.ci_lo, a.ci_hi)} | {pct(a['median'])} | {pct(m['mean'])} "
                                 f"{ci(m.ci_lo, m.ci_hi)} | {pct(m.diff_mean)} {ci(m.diff_ci_lo, m.diff_ci_hi)} |")
            t = ss_[(ss_.half == "tighter half") & (ss_.hypothesis == "H-slow") & (ss_.costs == "1x")].iloc[0]
            after += ["", f"Tickers with at least one ticker-day in the tighter half: {t.tickers_list}. Even there every trade loses at real quotes."]
    after += ["", f"Also noted: on event mornings the straddle's mid price at 09:31 was {pct(ov_s['mean'])} {ci(ov_s.ci_lo, ov_s.ci_hi)} against the previous "
              "15:55. The previous close was pulled for events only, so this is not compared with quiet nights and says nothing on its own about events.",
              "", "## Caveats", "",
              "- Fifteen looks at one sample (three trades, five variants), plus the case files. No look passes its own line; a pass would have been a lead only.",
              f"- A control is matched on ticker and date, not on the day of the week; {int(r.obs[(r.obs['sample'] == 'main') & (r.obs.kind == 'event')].weekend.sum())} "
              f"of the {n_ev} events follow a weekend or holiday.",
              "- The first instant is 09:31. Nothing here measures the opening rotation itself or the first seconds of quoting.",
              "- Mid prices inside a wide quote are not prices anyone traded. The speed curve is a measurement of where quotes sat, not of a fill.",
              f"- USO, XLE and XOP hold {int(ev.ticker.isin(cfg.OIL_TICKERS).sum())} of the {n_ok} traded event ticker-days; the result leans on one theme (Iran and oil).",
              "- The links are model judgements, and most of these markets had resolved when they were linked (S5 amendment 1)."]

    notes = [
        "The partial draft of SUMMARY.md that the coordinating session saw (in-sample trades only, 0 out-of-sample) was produced during the pull as a "
        "mechanical check of the code. It was **not a bug in the split or in the control matching**: tier 1 is pulled in event-date order and had reached "
        "2025-12-19, while out-of-sample starts on 2026-06-22. At that moment all 54 planned out-of-sample events (each with a matched control) had status "
        "\"not pulled\". The final SUMMARY.md is generated from the complete pull and its Answer section is built from the final result files.",
        f"Final out-of-sample main events with valid quotes: {oos_n} of 54 planned.",
        "One out-of-sample event has its control on 2026-06-18, before the out-of-sample boundary; by METHOD.md section 8 a control belongs to its event's segment.",
        "Amendment timestamps in METHOD.md were typed a few minutes ahead of the clock (amendment 1 says 23:45, committed 23:38; amendment 2 says 23:40, "
        "committed 23:39; amendment 3 says 23:50, committed 23:46). The commit times in the table above are the true ones.",
        "The label changed twice at the coordinating session's request (S16, S17, S16). Commits `d80ff94` and `b8c53ac` carry the S17 label in their "
        "message; they belong to this study.",
        "The analysis and report code were run on the partial cache while the pull ran, to catch code errors. No rule was changed after any result was seen. "
        "One addition was made after the first 16 events were visible: the median spread split, which is reported under \"Looked at after the run\" and "
        "enters no verdict.",
        "Tests: `cd research && .venv/bin/python -m pytest s16_overnight_options/tests -q` gave 21 passed, exit code 0.",
        "An interim result was committed and pushed at 00:44 (`25abd7e`) when the main sample was complete and the case tiers were still pulling; its "
        "SUMMARY.md carried an INTERIM banner. The main-sample numbers did not change between that commit and the final one.",
        "The pull ended at 01:34 New York time, before the 01:50 hard stop of METHOD.md section 10, so no tier was cut. It ran at 2 requests a second "
        "throughout; the recorder's `fetch failed` count was 51 before, at every check during, and after the pull, so the rate was never lowered.",
        f"Pull tiers finished: {fin}." + (f" The pull stopped: {stopped}." if stopped else ""),
        "Could not verify: the election date itself (the metadata on disk gives only the questions' end date, 2026-10-05T03:59Z); whether a strike listed "
        "today for an expired expiry was already listed on the event morning (if it was not, there is no quote and the ticker-day is dropped, so no fill "
        "is invented); dividends inside the put-call parity check (the check is a screen for a wrong contract, not a pricing test).",
    ]
    return A, after, notes
