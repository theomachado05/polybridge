"""S24 notes: the run log entries and the sentences of SUMMARY.md. Every number in a sentence is taken from the result
files by report.py (or read here from audit.json) and passed in; nothing here holds a result."""
from __future__ import annotations

import json

PREREG_COMMIT = "c5e0b22"
CUT_COMMIT = "e10f593"
AMENDMENT_COMMIT = "61c05e0"
RECORDER_BEFORE = 51
RECORDER_AFTER = 51

RUN_LOG = [
    ("Sun 01:40", "Brief, PARALLEL_BRIEF.md and S11's method, code and results read. No `s24_*` folder existed, so the number is 24."),
    ("Sun 01:45", "Four catalogue probes (page size, date filters, results by market id), counted in the request budget. `fetch failed` lines in the recorder's log: 51."),
    ("Sun 01:48", "First catalogue run: plain offsets stopped at 2,100 events a query (the catalogue serves no deeper offset). 44 requests; list replaced."),
    ("Sun 01:49–01:57", "Catalogue read again, restarting below the last volume: 5,998 events for set (a), 37,988 for set (b), 440 requests. Every price field dropped before storing (asserted)."),
    ("Sun 01:58", "Every template shape of the list read (text only). One strike ladder removed by a new text rule (\"or lower\" against the word \"reach\"). 22 tests pass."),
    ("Sun 01:59", "METHOD.md, config.py, the list, engine, pull and run code and tests committed and pushed before any print was pulled: `c5e0b22`."),
    ("Sun 01:59", "Print pull started: one worker, one request a second at most, the two sets in turns, largest event first."),
    ("Sun 02:02–02:03", "Format check of the prints of the first 110 markets: counts of sides and outcomes, how many markets hit the 20,000 cap. No detection."),
    ("Sun 02:04", "Report, audit and notes code and an end-to-end test on made-up prints committed while the pull ran: `eee3a9b`."),
    ("Sun 02:04", "**A detection smoke test on part of the pull** (127 pairs), written to a scratch folder only: 43 matches at 10 minutes, 34 at 2 minutes, provisional cut dates, seconds between prints, events with the most matches. No result read, no P&L."),
    ("Sun 02:30", "The coordinator's message arrived: the partner's study `research/ladder_replay` (origin/main `a876979` 02:11, `b57d2a8` 02:21, `4d9ac93` 02:21) found that S11's year rule misdates some rungs, and had seen results on a fresh universe that overlaps this one. Read with `git show` at 02:31."),
    ("Sun 02:31–02:35", "**Which case applied: prints had already been analysed (the 02:04 smoke test), so the registered test was not changed.** Amendment 1 written: the registered test stands; a secondary analysis (the partner's year check and nesting rule, and an unseen sample without the 58 shared markets) fixed before any result or P&L. Committed and pushed at 02:34:58: `61c05e0`. At that moment the pull was still running, no result had been read and `run detect` had not been run on the full pull."),
    ("Sun 02:42", "Print pull done in 2,537 s: 662 ladders (all 214 of set a; 448 of set b, 861 left out), 2,392 print requests. Results read for 2,342 rungs (2,275 resolved), 40 requests. `fetch failed` lines in the recorder's log: still 51; no pause was needed."),
    ("Sun 02:42", "`run detect` on the full pull (prints only): 375 primary trades. Cut dates from the trade dates alone: set (a) from 2025-09-11, set (b) from 2026-07-18. `secondary` classified the 161 pairs that traded from catalogue texts (7 requests, 273 markets) and compared the `outcome` text with the token on one market (9,450 prints, no disagreement)."),
    ("Sun 02:42:36", "Cut dates, matches, coverage and pair verdicts committed and pushed **before any P&L was computed**: `e10f593`."),
    ("Sun 02:42:40", "`run settle`: first P&L. 86 of 375 primary trades resolved with the ladder's order violated."),
    ("Sun 02:43–02:50", "The 11 pairs behind those 86 trades read one by one, with their descriptions. Two faults in S11's ladder rules: the year of a rung (8 date pairs, 61 trades; the partner's finding) and the word \"reach\" used for levels below the price (3 strike pairs, 25 trades; new). Every pair that traded was then read (161 pairs)."),
    ("Sun 02:45", "Amendment 2, post hoc: a direction check from the descriptions (`secondary direction`, no request), written to its own file so the files committed in `e10f593` stay as they were."),
    ("Sun 02:51", "Audit, report, tests (26 pass, exit code 0). SUMMARY.md written by `report.py` from the result files. Results committed and pushed: `3a482a3`."),
    ("Sun 02:53", "After the commit: the pooled means and intervals recomputed from `trades.csv` by separate code (they match `metrics.csv`), three trades checked by hand, the split rule and the pull order verified. Run log regenerated; this commit."),
]

WENT_WRONG: list[str] = [
    "The freshness claim of METHOD.md section 1 failed for 58 markets: the partner's study analysed them (set (a), 20 date ladders, 38 pairs) "
    "between 02:00 and 02:21, while this study's pull ran. Results are shown with and without them.",
    "A detection smoke test was run on part of the pull at 02:04, before the partner's finding was known. It showed match counts only, but it means "
    "the corrected rule could not be registered as this study's test. It is a secondary analysis, fixed before any result or P&L (`61c05e0`).",
    "S11's rules built wrong ladders on fresh markets (the count is in SUMMARY.md). The registered test is reported as "
    "registered; the corrected rows are secondary (the partner's rule) or post hoc (the direction check).",
    "The descriptions and sources were read only for the pairs that traded, so the nesting rule's count over the whole list is unknown.",
    "The first catalogue run stopped at 2,100 events a query (offset cap) and cost 44 requests.",
    "Both catalogue queries stopped at their page cap: events under $289,305 (set a) and $169,507 (set b) of volume were never read.",
]

S11 = {"points": 3.89, "lo": 2.49, "hi": 5.43, "trades": 99, "dates": 71, "oos": 3.24, "oos_lo": 0.62, "oos_hi": 7.09, "oos_trades": 11,
       "two_x": 4.34, "usd": 385, "sharpe": 4.64}          # from research/results/s11_bundles/SUMMARY.md, for the comparison line only


def _audit() -> dict:
    from .run import RESULTS
    f = RESULTS / "audit.json"
    return json.loads(f.read_text()) if f.exists() else {}


def answer(v: dict) -> list[str]:
    from . import report as rp
    f, usd, pct = rp.f, rp.usd, rp.pct
    A1, A2, I1, O1, built = v["A1"], v["A2"], v["I1"], v["O1"], v["built"]
    if not A1.trades:
        return ["No trade was found on the fresh ladders."]
    au = _audit()
    n_lad = built["a"]["pulled_ladders"] + built["b"]["pulled_ladders"]
    n_pairs = built["a"]["pulled_pairs"] + built["b"]["pulled_pairs"]
    out = []
    out += ANSWER_LEAD(v, au) if ANSWER_LEAD else []
    out += [f"- **What was tested (registered).** {n_lad:,} fresh ladders ({n_pairs:,} pairs of neighbouring rungs) that S11 never used: "
            f"{built['a']['pulled_ladders']:,} listed before S11's year (set a) and {built['b']['pulled_ladders']:,} inside S11's year but below its "
            f"volume floor (set b). A trade needs two public prints within 10 minutes: a taker selling YES on the rich rung above a taker buying "
            f"YES on the cheap rung, by more than both fees. No mid price is used.",
            f"- **Trades.** {int(A1.trades):,} trades on {int(A1.dates):,} dates, in {int(A1.pairs):,} pairs and {int(A1.events):,} events.",
            f"- **Profit per trade, 1× costs.** {f(A1.net_points_per_trade)} points [{f(A1.ci_lo)}, {f(A1.ci_hi)}]. "
            f"In-sample {f(I1.net_points_per_trade)} [{f(I1.ci_lo)}, {f(I1.ci_hi)}] on {int(I1.trades):,} trades. "
            f"Out-of-sample {f(O1.net_points_per_trade)} [{f(O1.ci_lo)}, {f(O1.ci_hi)}] on {int(O1.trades):,} trades and {int(O1.dates):,} dates.",
            f"- **At 2× costs** (fees doubled, two cents worse on each price, the same trades): {f(A2.net_points_per_trade)} points "
            f"[{f(A2.ci_lo)}, {f(A2.ci_hi)}].",
            f"- **Money.** {usd(A1.usd_capped)} in all at 100 contracts a leg at most ({usd(A2.usd_capped)} at 2×). {usd(A1.usd_uncapped)} at the full "
            f"printed size, an upper bound. The most capital locked at once was {usd(A1.capital_base_usd)}; a pair stays locked "
            f"{A1.median_days_locked:.0f} days at the median ({A1.mean_days_locked:.0f} on average).",
            f"- **Sharpe {f(A1.sharpe, 2, False)}**, maximum drawdown {pct(A1.max_drawdown)}, worst month {pct(A1.worst_month, 2)} "
            f"(daily P&L over {int(A1.calendar_days):,} calendar days, as a share of the most capital locked at once)."]
    if au:
        pp, rs = au["pnl_points"], au["result"]
        out += [f"- **Where the P&L comes from.** The entry edge averages {f(pp['entry_edge_mean'])} points per trade, but on the wrongly built pairs that "
                f"\"edge\" is the correct price order, not a mispricing. The results take {f(pp['result_part_mean'])} points per trade: "
                f"{rs['rich NO, cheap YES (pays $1)']} trades were paid $1 (the cheap rung YES, the rich rung NO) and "
                f"{rs['rich YES, cheap NO (order violated)']} lost $1 (the reverse).",
                f"- **Ladder order at the result.** {rs['rich YES, cheap NO (order violated)']} of {int(A1.trades):,} trades resolved with the "
                f"ladder's order violated." + (" That is what a correct ladder list gives." if rs['rich YES, cheap NO (order violated)'] == 0 else
                                               " It should be zero. Each case is read and explained below.")]
    return out


ANSWER_LEAD = None


def body(v: dict) -> list[str]:
    return BODY(v, _audit()) if BODY else []


BODY = None


# ---------------------------------------------------------------- the body of SUMMARY.md

READING: list[str] = []          # what reading the trades one by one found; filled in after the run
BROKEN_NOTES: list[str] = []     # each trade whose ladder order was violated at the result, explained


def _body(v: dict, au: dict) -> list[str]:
    from . import report as rp
    f, usd, pct, get = rp.f, rp.usd, rp.pct, rp.get
    M, A1, A2, cut = v["M"], v["A1"], v["A2"], v["cut"]
    out = []

    # ---- the 2-minute variant
    W, WI, WO, W2 = v["W"], v["WI"], v["WO"], v["W2"]
    out += ["## Variant: the two prints within 2 minutes", ""]
    if W.trades:
        out += [f"{int(W.trades):,} trades on {int(W.dates):,} dates. Net {f(W.net_points_per_trade)} points per trade at 1× "
                f"[{f(W.ci_lo)}, {f(W.ci_hi)}]; in-sample {f(WI.net_points_per_trade)} [{f(WI.ci_lo)}, {f(WI.ci_hi)}] on {int(WI.trades):,}; "
                f"out-of-sample {f(WO.net_points_per_trade)} [{f(WO.ci_lo)}, {f(WO.ci_hi)}] on {int(WO.trades):,} trades and {int(WO.dates):,} dates; "
                f"{f(W2.net_points_per_trade)} at 2×. P&L {usd(W.usd_capped)} at the cap, {usd(W.usd_uncapped)} at full size. "
                f"Sharpe {f(W.sharpe, 2, False)}. Against the same four lines: "
                + "; ".join(f"line {name[0]} {'holds' if ok else 'fails'}" for name, ok, _ in v["wl"]) + ".", ""]
    else:
        out += ["No trade.", ""]

    # ---- other pre-registered variants
    out += ["## The other pre-registered rows", "",
            "| Row | Trades | Dates | Net, points per trade, 1× | 95% interval | At 2× | P&L, cap |", "|---|---|---|---|---|---|---|"]

    def line(label, r, r2):
        if not r.trades:
            return f"| {label} | 0 | | | | | |"
        return (f"| {label} | {int(r.trades):,} | {int(r.dates):,} | {f(r.net_points_per_trade)} | [{f(r.ci_lo)}, {f(r.ci_hi)}] | "
                f"{f(r2.net_points_per_trade) if r2 is not None and r2.trades else 'n/a'} | {usd(r.usd_capped)} |")
    out += [line("Locked at entry only (entry edge above zero after the haircut)", get(M, scope="locked at entry"), get(M, scope="locked at entry", costs="2x")),
            line("Locked at entry, out-of-sample", get(M, scope="locked at entry", segment="OOS"), get(M, scope="locked at entry", segment="OOS", costs="2x")),
            line("Resolved pairs only (both rungs have a result)", get(M, scope="resolved pairs only"), get(M, scope="resolved pairs only", costs="2x")),
            line("Resolved pairs only, out-of-sample", get(M, scope="resolved pairs only", segment="OOS"), get(M, scope="resolved pairs only", segment="OOS", costs="2x")),
            line("Calendar split, in-sample (a: before 2025-05-26; b: before 2026-07-22)", get(M, split="calendar", segment="IS"), get(M, split="calendar", segment="IS", costs="2x")),
            line("Calendar split, out-of-sample", get(M, split="calendar", segment="OOS"), get(M, split="calendar", segment="OOS", costs="2x")),
            "",
            f"S11's Sharpe convention (P&L booked on the entry date, capital base = the most capital opened in one day) gives "
            f"{f(A1.sharpe_s11_convention, 2, False)} on the pooled trades (S11's own figure was {S11['sharpe']}). "
            f"{int(A1.open_pairs)} of the {int(A1.trades):,} trades have a rung still open tonight and are booked at their entry edge alone.", ""]

    # ---- money
    out += ["## Money and capital", "",
            f"- At 100 contracts a leg at most: **{usd(A1.usd_capped)}** at 1× costs, {usd(A2.usd_capped)} at 2×, over {int(A1.calendar_days):,} calendar days. "
            f"That is {usd(A1.usd_per_trade_capped, 2)} a trade.",
            f"- At the full printed size: {usd(A1.usd_uncapped)} at 1×, {usd(A2.usd_uncapped)} at 2×. An upper bound (see [`capacity.md`](capacity.md)).",
            f"- Locked in at entry (before any result): {usd(A1.entry_edge_usd_capped)} at the cap, {usd(A1.entry_edge_usd_uncapped)} at full size.",
            f"- Capital: about $1 a contract until the later rung closes. Most locked at once {usd(A1.capital_base_usd)}; on an average day "
            f"{usd(A1.mean_capital_locked_usd)}. Days locked: median {A1.median_days_locked:.0f}, mean {A1.mean_days_locked:.1f}, longest {int(A1.max_days_locked)}. "
            f"Net P&L per year on the capital actually locked: {pct(A1.return_on_locked_capital_per_year)}.",
            f"- Costs: the fees and the one-cent haircuts took the entry gap from {f(au['gap_points']['mean']) if au else 'n/a'} points (print against print) to "
            f"{f(A1.entry_edge_points)} points at 1× and {f(A2.entry_edge_points)} at 2×. Net of costs the trade earned {f(A1.net_bp_of_capital, 0)} bp of the "
            f"capital tied up at 1× and {f(A2.net_bp_of_capital, 0)} bp at 2×.", ""]

    # ---- the bug hunt
    out += ["## The bug hunt (looked at after the run)", ""]
    if au:
        sc, rc = au["side_check"], au["recheck"]
        out += [f"The registered Sharpe is {f(A1.sharpe, 2, False)}, so no hunt was owed for a Sharpe above 3. The checks of METHOD.md section 9 were run "
                "anyway, because trades that break a ladder's order mean the ladder list is wrong. What was checked:", "",
                f"- **Each trade's two prints were found again in the stored prints** (right market, a taker sale of YES on the rich rung, a taker purchase of "
                f"YES on the cheap rung, the stated prices and sizes, within 10 minutes, gap above the fees): {rc['trades'] - rc['failed']:,} of {rc['trades']:,} pass.",
                f"- **No trade uses a print at or after a rung's close**: {au['print_after_close']} such trades (checked against the close times read with the results).",
                f"- **The sides are the takers'.** Over {sc['pairs_of_prints']:,} pairs of consecutive prints of one market on opposite sides, at most 60 seconds "
                f"apart, the taker purchase of YES printed {f(sc['mean_points'])} points above the taker sale on average (median {f(sc['median_points'])}); "
                f"above in {pct(sc['share_positive'], 0)} of cases, below in {pct(sc['share_negative'], 0)}. A purchase at the ask prints above a sale at the bid, "
                f"so the side field is the taker's side.",
                f"- **Results**: both NO {au['result']['both NO']}, both YES {au['result']['both YES']}, rich NO and cheap YES (pays $1) "
                f"{au['result']['rich NO, cheap YES (pays $1)']}, rich YES and cheap NO (order violated) {au['result']['rich YES, cheap NO (order violated)']}, "
                f"a rung still open {au['result']['open']}."]
    out += [f"- {x}" for x in READING]
    out += [""]
    bn = broken_notes(v)
    if bn:
        out += ["**Trades whose ladder order was violated at the result, pair by pair (each is a ladder-building error):**", ""] + [f"- {x}" for x in bn] + [""]

    # ---- after the run
    if au:
        out += ["## Looked at after the run (not part of the test)", "",
                "**Registered trades by the size of the gap between the two prints.** A real out-of-order ladder is a gap of a few points. The gaps "
                "over 20 points are the wrongly built pairs: the \"gap\" is the fair price difference between two rungs in the wrong order.", "",
                "| Gap, sale print minus purchase print | Trades | Dates | Net, points per trade, 1× | 95% interval | At 2× | Entry edge, points | P&L, cap |", "|---|---|---|---|---|---|---|---|"]
        for lab, r in au["pnl_by_gap"].items():
            out.append(f"| {lab} | {r['trades']} | {r['dates']} | {f(r['points_1x'])} | [{f(r['lo'])}, {f(r['hi'])}] | {f(r['points_2x'])} | {f(r['entry_edge_points'])} | {usd(r['usd_capped_1x'])} |")
        eb = au["event_bootstrap"]
        out += ["", "Registered trades, bootstrap over events instead of dates (one event can trade on many dates): "
                + "; ".join(f"{seg} {f(r['points_1x'])} [{f(r['lo'])}, {f(r['hi'])}] on {r['events']} events" for seg, r in eb.items()) + ".", ""]
        cl = au.get("clean")
        if cl:
            out += [f"**The cleaned sample ({cl['trades']} trades: corrected rule, direction check, unseen markets; post hoc) by how far apart the two prints "
                    "were.** The closer the two prints, the closer the trade is to a proven simultaneous fill.", "",
                    "| Seconds between the two prints | Trades | Dates | Net, points per trade, 1× | 95% interval | At 2× | Entry edge, points | P&L, cap |", "|---|---|---|---|---|---|---|---|"]
            for lab, r in cl["pnl_by_seconds_apart"].items():
                out.append(f"| {lab} | {r['trades']} | {r['dates']} | {f(r['points_1x'])} | [{f(r['lo'])}, {f(r['hi'])}] | {f(r['points_2x'])} | {f(r['entry_edge_points'])} | {usd(r['usd_capped_1x'])} |")
            out += ["", "**The cleaned sample: was the earlier print's price still there at the entry?** \"Same second\": both prints in one second. "
                    "\"Confirmed after\": the earlier rung printed again on the same side, at our fill price or better, between the entry and 10 minutes "
                    "later. \"Moved away\": not confirmed, and the earlier rung had already printed at a worse price than our fill before the entry. "
                    "\"Not confirmed\": neither.", "",
                    "| Group | Trades | Dates | Net, points per trade, 1× | 95% interval | At 2× | Entry edge, points | P&L, cap | P&L, full size |", "|---|---|---|---|---|---|---|---|---|"]
            for lab, r in cl["pnl_by_confirmation"].items():
                out.append(f"| {lab} | {r['trades']} | {r['dates']} | {f(r['points_1x'])} | [{f(r['lo'])}, {f(r['hi'])}] | {f(r['points_2x'])} | {f(r['entry_edge_points'])} | "
                           f"{usd(r['usd_capped_1x'])} | {usd(r['usd_uncapped_1x'])} |")
            sm, mv = cl["pnl_by_confirmation"]["same second"], cl["pnl_by_confirmation"]["moved away"]
            far = cl["pnl_by_seconds_apart"]["121 to 600 s"]
            ce = cl["event_bootstrap"]
            out += ["",
                    f"- **The profit sits where the fill is least proven.** {far['trades']} of the {cl['trades']} trades have prints more than 2 minutes apart, and "
                    f"they earn {f(far['points_1x'])} points per trade. {mv['trades']} trades are \"moved away\": the earlier rung had already traded at a worse "
                    f"price than our fill before the second print came, so that fill was probably not there. They earn {f(mv['points_1x'])} points per trade "
                    f"and {usd(mv['usd_uncapped_1x'])} of the full-size dollars.",
                    f"- **Same-second trades**, the only ones where both prices are proven at one instant: {sm['trades']} trades on {sm['dates']} dates, "
                    f"{f(sm['points_1x'])} points per trade [{f(sm['lo'])}, {f(sm['hi'])}] at 1×, {f(sm['points_2x'])} at 2×. The interval includes zero.",
                    f"- **Without the $1 payouts** ({cl['paid_one_dollar']} trades) the cleaned sample averages {f(cl['mean_without_one_dollar_payouts'])} points per "
                    f"trade at 1× and {f(cl['mean_2x_without_one_dollar_payouts'])} at 2×.",
                    f"- **Size.** The median trade is {cl['median_size']:.0f} contracts; {cl['under_5_contracts']} trades are under Polymarket's 5-contract minimum. "
                    f"The 5 largest trades carry {pct(cl['top5_share_of_uncapped_usd'], 0)} of the full-size dollars; the largest alone is "
                    f"{usd(cl['largest_trade_uncapped_usd'])}.",
                    "- **Bootstrap over events instead of dates:** " + "; ".join(f"{seg} {f(r['points_1x'])} [{f(r['lo'])}, {f(r['hi'])}] on {r['events']} events"
                                                                                   for seg, r in ce.items()) + ".",
                    "- **When.** " + ", ".join(f"{k}: {v_}" for k, v_ in cl["by_month"].items()) + " (trades a month).", ""]
        out += ["**Where the registered trades were** (events with the most trades):", "", "| Event | Trades | Sum of points | P&L, cap |", "|---|---|---|---|"]
        for r in au["by_event_top"][:10]:
            out.append(f"| {r['event_title']} | {r['trades']} | {f(r['points'], 1)} | {usd(r['usd_cap'])} |")
        out += [""]
    out += closing(v, au)
    return out


def closing(v: dict, au: dict) -> list[str]:
    from . import report as rp
    f, usd, get, M, T = rp.f, rp.usd, rp.get, v["M"], v["T"]
    built = v["built"]
    L = json.loads((rp.HERE / "ladders.json").read_text())
    pm = rp.HERE / "partner_markets.json"
    shared = len(set(json.loads(pm.read_text())["markets"]) & set(L["markets"])) if pm.exists() else 0
    oos_n = sorted(int(get(M, scope=s, segment="OOS").trades) for s in (CU, "corrected rule", POST) if ((M.scope == s) & (M.variant == "W600")).any())
    oos_txt = f"{oos_n[0]} to {oos_n[-1]}" if oos_n else "n/a"
    med = (au.get("clean") or {}).get("median_size")
    viol_a = int(get(M, scope="set a").order_violated_at_result)
    if not ((M.scope == CU) & (M.variant == "W600")).any():
        return []                        # no secondary rows (the made-up data of the tests): nothing to conclude about them
    sb_o, dl_o = get(M, scope=CU + ", set b", segment="OOS"), get(M, scope=CU + ", date ladders", segment="OOS")
    out = ["## What this does and does not show", "",
           "- **It shows that S11's ladder rules cannot be trusted on new markets.** They need a year check and a direction check before any pair is "
           "called a ladder. S11's own figure was never tested against this: the partner's replay found the year fault on S11's pairs too.",
           "- **It does not show that the trade fails on real ladders.** On pairs that pass the corrected rule, the pooled rows are positive in-sample, "
           f"out-of-sample and at doubled costs, with intervals above zero. By set it is weaker: set (b) alone is {f(sb_o.net_points_per_trade)} "
           f"[{f(sb_o.ci_lo)}, {f(sb_o.ci_hi)}] out-of-sample on {int(sb_o.trades)} trades, and date ladders alone {f(dl_o.net_points_per_trade)} "
           f"[{f(dl_o.ci_lo)}, {f(dl_o.ci_hi)}] on {int(dl_o.trades)}. Those rows are secondary (a rule taken from the partner's data, fixed before our results) or post hoc "
           f"(the direction check), the out-of-sample count is {oos_txt} against the {30} required, and the profit is a handful of $1 payouts.",
           "- **It does not show that both legs could be filled together.** The two prints are up to 10 minutes apart. In the cleaned sample the profit "
           "sits in the trades with the widest time gaps and in trades where the first price had already moved away. The same-second trades have an "
           "interval that includes zero.",
           f"- **It does not show size.** A print proves one taker's trade, not a second order of our size. The median trade is {med:.0f} contracts." if med else
           "- **It does not show size.** A print proves one taker's trade, not a second order of our size.",
           f"- **Freshness.** The claim that nobody had seen these markets failed for {shared} of them: the partner's study analysed them while this pull "
           "ran. The unseen rows remove them.", "",
           "## What didn't work", "",
           f"- **The registered test**: not a pass (lines {', '.join(name[0] for name in v['failed'])} fail). {f(v['A1'].net_points_per_trade)} points per trade, "
           f"{usd(v['A1'].usd_capped)} at the cap.",
           f"- **The 2-minute variant** under the registered rule: {f(v['W'].net_points_per_trade)} points per trade on {int(v['W'].trades)} trades.",
           f"- **Locked-at-entry trades only**: {f(get(M, scope='locked at entry').net_points_per_trade)} points per trade. A positive entry edge did not protect "
           "against a wrongly built pair; it selected them.",
           f"- **Set (a)** (older, larger rungs): {f(get(M, scope='set a').net_points_per_trade)} points per trade, with {viol_a} order violations.",
           f"- **Set (b) out-of-sample**: {int(get(M, scope='set b', segment='OOS').trades)} trades, short of 30, interval includes zero.",
           f"- **Coverage**: {built['b']['left_ladders']:,} of set (b)'s {built['b']['ladders']:,} ladders were not pulled (request budget).", "",
           "## Every variant tried", "",
           "Registered before the pull: primary (10 minutes, 100-contract cap, 1×); 2× costs on the same trades; prints within 2 minutes; uncapped size; "
           "locked at entry only; resolved pairs only; the calendar split; S11's Sharpe convention; set (a) and set (b); date and strike ladders. "
           "Amendment 1 (after the partner's finding, before any result): year check; corrected rule; corrected rule on the unseen sample; registered "
           "rule on the unseen sample. Amendment 2 (post hoc): the direction check. After the run: cuts by seconds apart, by gap, by whether the earlier "
           "price was still there, a bootstrap over events. Every row is in [`metrics.csv`](metrics.csv) and [`audit.json`](audit.json).", ""]
    return out


BODY = _body


# ---------------------------------------------------------------- amendment 1: the secondary analysis

def secondary(v: dict) -> list[str]:
    from . import report as rp
    from .run import RESULTS
    f, usd, get, M, T = rp.f, rp.usd, rp.get, v["M"], v["T"]
    if "corrected_ok" not in T:
        return []
    pc = json.loads((RESULTS / "pair_checks.json").read_text()) if (RESULTS / "pair_checks.json").exists() else {}
    P = T[T.variant == "W600"]
    out = ["## Secondary: the corrected ladder rule (added after the partner's finding; not the registered test)", "",
           "At 02:30 the partner's study (`research/ladder_replay`, origin/main `4d9ac93`) became known here. It found that S11's year rule puts "
           "some date rungs in the wrong order, and that some pairs are not truly nested. Its year check and its nesting rule were adopted as "
           "written, in METHOD.md amendment 1 (`61c05e0`, committed 02:34:58). **When that was committed, this study had read no result and computed no "
           "P&L. It had run one detection pass on part of the pull (127 pairs, counts of matches only) at 02:04.** So these rows are not "
           "the registered test. They are fixed before the results, by a rule that came from someone else's data.", "",
           "| Row (10-minute trades) | Trades | Dates | Net, points per trade, 1× | 95% interval | In-sample | Out-of-sample | At 2× | P&L, cap | P&L, full size | Losing trades | Order violated at the result | The four pass lines |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]

    def one(label, scope, variant="W600"):
        a, i, o, a2 = get(M, variant, scope), get(M, variant, scope, segment="IS"), get(M, variant, scope, segment="OOS"), get(M, variant, scope, costs="2x")
        if not a.trades:
            return f"| {label} | 0 | | | | | | | | | | | |"
        lines = rp.pass_lines(M, scope, variant)
        verdict = "all hold" if all(ok for _, ok, _ in lines) else "fails " + ", ".join(name[0] for name, ok, _ in lines if not ok)

        def seg(r):
            return f"{f(r.net_points_per_trade)} [{f(r.ci_lo)}, {f(r.ci_hi)}], {int(r.trades)} on {int(r.dates)} dates" if r.trades else "none"
        return (f"| {label} | {int(a.trades):,} | {int(a.dates):,} | {f(a.net_points_per_trade)} | [{f(a.ci_lo)}, {f(a.ci_hi)}] | {seg(i)} | {seg(o)} | "
                f"{f(a2.net_points_per_trade)} | {usd(a.usd_capped)} | {usd(a.usd_uncapped)} | {int(round(a.losers * a.trades))} | {int(a.order_violated_at_result)} | {verdict} |")
    out += [one("Registered rule, every pulled pair (the registered test)", "pooled"),
            one("Year check", "year check"),
            one("Corrected rule (year check + nesting)", "corrected rule"),
            one("**Corrected rule, unseen sample**", "corrected rule, unseen sample"),
            one("Registered rule, unseen sample", "registered rule, unseen sample"),
            one("Corrected rule, unseen sample, set (a)", "corrected rule, unseen sample, set a"),
            one("Corrected rule, unseen sample, set (b)", "corrected rule, unseen sample, set b"),
            one("Corrected rule, unseen sample, date ladders", "corrected rule, unseen sample, date ladders"),
            one("Corrected rule, unseen sample, strike ladders", "corrected rule, unseen sample, strike ladders"),
            one("Corrected rule, unseen sample, prints within 2 minutes", "corrected rule, unseen sample", "W120")]
    if "direction_ok" in T:
        ph = "post hoc: corrected rule + direction check, unseen sample"
        out += [one("**Post hoc:** corrected rule + direction check, unseen sample", ph),
                one("Post hoc, set (a)", ph + ", set a"), one("Post hoc, set (b)", ph + ", set b"),
                one("Post hoc, date ladders", ph + ", date ladders"), one("Post hoc, strike ladders", ph + ", strike ladders"),
                one("Post hoc, prints within 2 minutes", ph, "W120")]
    out += ["",
            "\"Losing trades\" counts every trade below zero; most lose a cent or two to the haircut on a 1-cent or 2-cent gap. \"Order violated\" is "
            "the count that matters for the ladder list: those trades lose $1. The post hoc rows use the direction check of amendment 2, which was "
            "chosen after seeing this study's own losing trades.", ""]
    if pc:
        pairs = P[["rich", "cheap", "corrected_ok", "corrected_reason", "year_ok", "partner_used"]].drop_duplicates(["rich", "cheap"])
        n_tr = len(P)
        reasons = P.groupby("corrected_reason").agg(trades=("pnl_1x", "size"), pairs=("rich", lambda s: len(set(zip(s, P.loc[s.index, "cheap"])))),
                                                    points=("pnl_1x", lambda s: float(s.mean() * 100)), losers=("pnl_1x", lambda s: int((s < 0).sum())),
                                                    violated=("broken", "sum"), usd=("usd_capped_1x", "sum")).reset_index()
        out += ["**What the corrected rule says about the pairs that traded** (10-minute trades):", "",
                "| Verdict | Pairs | Trades | Net, points per trade, 1× | Losing trades | Order violated at the result | P&L, cap |", "|---|---|---|---|---|---|---|"]
        for r in reasons.sort_values("trades", ascending=False).itertuples():
            out.append(f"| {r.corrected_reason} | {r.pairs} | {r.trades} | {f(r.points)} | {r.losers} | {int(r.violated)} | {usd(r.usd)} |")
        pu = P[P.partner_used.astype(bool)]
        u = pc.get("universe", {})
        oc = pc.get("outcome_text_check") or {}
        out += ["",
                f"- **Markets the partner's study had used**: {int(pairs.partner_used.sum())} of the {len(pairs)} pairs that traded, carrying {len(pu)} of the "
                f"{n_tr:,} trades ({f(float(pu.pnl_1x.mean() * 100)) if len(pu) else 'n/a'} points per trade). They are removed from the unseen rows. "
                f"In the pulled list: {u.get('a date pairs with a market the partner used', 0)} of {u.get('a date pairs', 0)} date pairs of set (a); none in set (b).",
                f"- **Year check over every pulled date pair** (from the question and the start date): "
                f"{u.get('a date pairs failing the year check', 0)} of {u.get('a date pairs', 0)} fail in set (a), "
                f"{u.get('b date pairs failing the year check', 0)} of {u.get('b date pairs', 0)} in set (b). "
                f"Among pairs that traded: {pc.get('year_check_fails_traded', 0)}.",
                f"- The descriptions and sources were read for the {pc.get('traded_pairs', 0)} pairs that traded only ({pc.get('texts_read', 0)} markets), "
                "so the nesting rule's count over the whole list is not known."]
        if oc:
            out += [f"- **Print mapping.** The partner found the API's `outcomeIndex` wrong on many prints. This study maps by the `outcome` text. On one market "
                    f"read again ({oc['prints']:,} prints) the text agreed with the token on {oc['outcome_text_agrees_with_token']:,} prints and disagreed on "
                    f"{oc['disagrees']}; `outcomeIndex` disagreed with the token on {oc['outcomeIndex_disagrees_with_token']:,}."]
        out += [""]
    return out


# ---------------------------------------------------------------- the lead of the answer, the reading, the closing sections

POST = "post hoc: corrected rule + direction check, unseen sample"
CU = "corrected rule, unseen sample"


def _fault(r) -> str:
    if r.kind == "date":
        return "year fault"
    return "direction fault"


def _lead(v: dict, au: dict) -> list[str]:
    from . import report as rp
    f, usd, pct, get, M, T = rp.f, rp.usd, rp.pct, rp.get, v["M"], v["T"]
    A1, A2, I1, O1 = v["A1"], v["A2"], v["I1"], v["O1"]
    P = T[T.variant == "W600"]
    B = P[P.broken.astype(bool)]
    bp = B.drop_duplicates(["rich", "cheap"])
    yr, dr = B[B.kind == "date"], B[B.kind == "strike"]
    out = [f"**No. Under S11's own rules the ladder trade does not hold on fresh ladders.** It made {f(A1.net_points_per_trade)} points per trade "
           f"(95% interval over dates [{f(A1.ci_lo)}, {f(A1.ci_hi)}]) on {int(A1.trades)} trades on {int(A1.dates)} dates, and "
           f"{f(A2.net_points_per_trade)} [{f(A2.ci_lo)}, {f(A2.ci_hi)}] at doubled costs. In-sample {f(I1.net_points_per_trade)} "
           f"[{f(I1.ci_lo)}, {f(I1.ci_hi)}] on {int(I1.trades)} trades. Out-of-sample {f(O1.net_points_per_trade)} [{f(O1.ci_lo)}, {f(O1.ci_hi)}] on "
           f"{int(O1.trades)} trades on {int(O1.dates)} dates. P&L at 100 contracts a leg: {usd(A1.usd_capped)}. S11's +{S11['points']} does not replicate "
           "under S11's rules.", "",
           f"**The reason is the ladder list, not the prints.** {len(B)} of the {int(A1.trades)} trades ({pct(len(B) / A1.trades, 0)}) resolved with the "
           f"ladder's order violated: the rung we sold resolved YES and the rung we bought resolved NO. A real ladder cannot do that. All {len(B)} are on "
           f"{len(bp)} pairs that S11's rules built wrong, in two ways:", "",
           f"- **The year of a rung** ({yr.drop_duplicates(['rich', 'cheap']).shape[0]} date pairs, {len(yr)} trades). \"Will Russia capture Pokrovsk by December 31?\" "
           "was read as the year before, so it was placed ahead of \"... by March 31?\" and sold against it. The partner's study found this fault shortly "
           "before these results.",
           f"- **The direction of a level** ({dr.drop_duplicates(['rich', 'cheap']).shape[0]} strike pairs, {len(dr)} trades). \"Will Bitcoin reach $65,000 in November?\" "
           "was a level below the price: its description says YES needs a low of $65,000 or lower. S11 reads \"reach\" as up. This fault is new.", "",
           "On those pairs the trade sold the more likely rung. The \"gap\" it saw was the correct price order, and the pair can lose $1."]
    if "corrected_ok" in T:
        c, ci, co, c2 = get(M, scope=CU), get(M, scope=CU, segment="IS"), get(M, scope=CU, segment="OOS"), get(M, scope=CU, costs="2x")
        out += ["",
                f"**On pairs that are real ladders the trade was positive in-sample, out-of-sample and at doubled costs. It is short of the 30 out-of-sample "
                f"trades, it is not the registered test, and its profit is a few $1 payouts.** With the partner's year check and nesting rule (adopted at "
                f"02:35, before any result here was read) and without the markets the partner had used: {f(c.net_points_per_trade)} points per trade "
                f"[{f(c.ci_lo)}, {f(c.ci_hi)}] on {int(c.trades)} trades on {int(c.dates)} dates; in-sample {f(ci.net_points_per_trade)} "
                f"[{f(ci.ci_lo)}, {f(ci.ci_hi)}]; out-of-sample {f(co.net_points_per_trade)} [{f(co.ci_lo)}, {f(co.ci_hi)}] on {int(co.trades)} trades on "
                f"{int(co.dates)} dates; {f(c2.net_points_per_trade)} [{f(c2.ci_lo)}, {f(c2.ci_hi)}] at 2×. {int(c.order_violated_at_result)} of its trades "
                f"still resolved with the order violated (the direction fault)."]
        if "direction_ok" in T:
            p, pi, po, p2 = get(M, scope=POST), get(M, scope=POST, segment="IS"), get(M, scope=POST, segment="OOS"), get(M, scope=POST, costs="2x")
            out += [f"With the direction check added after seeing those losers (post hoc): {f(p.net_points_per_trade)} [{f(p.ci_lo)}, {f(p.ci_hi)}] on "
                    f"{int(p.trades)} trades on {int(p.dates)} dates; in-sample {f(pi.net_points_per_trade)} [{f(pi.ci_lo)}, {f(pi.ci_hi)}]; out-of-sample "
                    f"{f(po.net_points_per_trade)} [{f(po.ci_lo)}, {f(po.ci_hi)}] on {int(po.trades)} trades on {int(po.dates)} dates; "
                    f"{f(p2.net_points_per_trade)} [{f(p2.ci_lo)}, {f(p2.ci_hi)}] at 2×; {int(p.order_violated_at_result)} trades with the order violated.", "",
                    f"**What that profit is made of.** In the cleaned sample the edge locked in at entry is {f(p.entry_edge_points)} points per trade at 1× "
                    f"and {f(p2.entry_edge_points)} at 2×. {int(p.paid_one_dollar)} of the {int(p.trades)} trades were paid $1 because the result fell between "
                    f"the two rungs; they carry the mean. The median trade made {f(p.median_points)} points and {pct(p.losers, 0)} of trades lost a little. "
                    f"Money: {usd(p.usd_capped)} at 100 contracts a leg ({usd(p2.usd_capped)} at 2×), {usd(p.usd_uncapped)} at the full printed size, on "
                    f"{usd(p.capital_base_usd)} of capital at the most."]
        b, bi, bo, b2 = get(M, scope="set b"), get(M, scope="set b", segment="IS"), get(M, scope="set b", segment="OOS"), get(M, scope="set b", costs="2x")
        out += ["",
                f"**Set (b) on its own** (S11's year, rungs under S11's volume floor, registered rule): no trade resolved with the order violated. "
                f"{f(b.net_points_per_trade)} [{f(b.ci_lo)}, {f(b.ci_hi)}] on {int(b.trades)} trades on {int(b.dates)} dates; in-sample "
                f"{f(bi.net_points_per_trade)} [{f(bi.ci_lo)}, {f(bi.ci_hi)}]; out-of-sample {f(bo.net_points_per_trade)} [{f(bo.ci_lo)}, {f(bo.ci_hi)}] on "
                f"{int(bo.trades)} trades on {int(bo.dates)} dates; {f(b2.net_points_per_trade)} [{f(b2.ci_lo)}, {f(b2.ci_hi)}] at 2×. {usd(b.usd_capped)} at the cap. "
                "Positive, small, and not a pass by itself."]
    out += ["", "The registered numbers, line by line:", ""]
    return out


ANSWER_LEAD = _lead


def broken_notes(v: dict) -> list[str]:
    T = v["T"]
    P = T[(T.variant == "W600") & T.broken.astype(bool)]
    out = []
    if not len(P):
        return out
    if "corrected_reason" not in P:
        P = P.assign(corrected_reason="")
    g = P.assign(gap=(P.sale_print - P.buy_print) * 100).groupby(["kind", "rich_q", "cheap_q"]).agg(
        n=("pnl_1x", "size"), gap=("gap", "mean"), pts=("pnl_1x", lambda s: float(s.mean() * 100)), first=("date", "min"), last=("date", "max"),
        why=("corrected_reason", "first")).reset_index().sort_values("n", ascending=False)
    for r in g.itertuples():
        if r.kind == "date":
            why = ("year fault: S11's year rule placed the rung we sold before the rung we bought; by their descriptions it is the later one. "
                   "The partner's year check removes the pair")
        elif r.why == "descriptions differ":
            why = ("direction fault: the rung we sold is an up level (a \"High\" price or higher) and the rung we bought is a down level (a \"Low\" "
                   "price or lower); the two have no order. The partner's nesting rule removes the pair (descriptions differ)")
        else:
            why = ("direction fault: both rungs are down levels (a \"Low\" price or lower), so the lower level is the less likely one; S11 read "
                   "\"reach\" as up and reversed the pair. The partner's nesting rule does not catch it; the post hoc direction check does")
        from . import report as rp
        out.append(f"Sold \"{r.rich_q}\", bought \"{r.cheap_q}\": {r.n} trade{'s' if r.n != 1 else ''}, {r.first} to {r.last}, mean gap "
                   f"{rp.f(r.gap, 1, False)} points, mean P&L {rp.f(r.pts, 1)} points. {why[0].upper() + why[1:]}.")
    return out


def went_wrong(v: dict) -> list[str]:
    """The limits whose numbers come from the result files."""
    b, c, A1 = v["built"], v["cov_n"], v["A1"]
    return [f"{b['b']['left_ladders']:,} of set (b)'s {b['b']['ladders']:,} ladders ({b['b']['left_pairs']:,} of {b['b']['pairs']:,} pairs) were not pulled: "
            f"the print budget ran out. Set (a): {b['a']['left_ladders']} left out.",
            f"{c['a']['latest 20,000 prints only'] + c['b']['latest 20,000 prints only']} pulled pairs have a rung with 20,000 or more prints; their earlier life "
            "could not be checked.",
            f"{int(A1.order_violated_at_result)} of {int(A1.trades)} registered trades resolved with the ladder's order violated.",
            f"{int(A1.open_pairs)} registered trades have a rung still open tonight; they are booked at their entry edge alone."]
