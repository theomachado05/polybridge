"""S24 notes: the run log entries and the sentences of SUMMARY.md. Every number in a sentence is taken from the result
files by report.py (or read here from audit.json) and passed in; nothing here holds a result."""
from __future__ import annotations

import json

PREREG_COMMIT = "c5e0b22"
CUT_COMMIT = "pending"
RECORDER_BEFORE = 51
RECORDER_AFTER = "pending"

RUN_LOG = [
    ("Sun 01:40", "Brief, PARALLEL_BRIEF.md and S11's method, code and results read. No `s24_*` folder existed, so the number is 24."),
    ("Sun 01:45", "Four catalogue probes (page size, date filters, results by market id), counted in the request budget. `fetch failed` lines in the recorder's log: 51."),
    ("Sun 01:48", "First catalogue run: plain offsets stopped at 2,100 events a query (the catalogue serves no deeper offset). 44 requests; list replaced."),
    ("Sun 01:49–01:57", "Catalogue read again, restarting below the last volume: 5,998 events for set (a), 37,988 for set (b), 440 requests. Every price field dropped before storing (asserted)."),
    ("Sun 01:58", "Every template shape of the list read (text only). One strike ladder removed by a new text rule (\"or lower\" against the word \"reach\"). 22 tests pass."),
    ("Sun 01:59", "METHOD.md, config.py, the list, engine, pull and run code and tests committed and pushed before any print was pulled: `c5e0b22`."),
    ("Sun 01:59", "Print pull started: one worker, one request a second at most, the two sets in turns, largest event first."),
    ("Sun 02:01", "Report, audit and notes code and an end-to-end test on made-up prints committed while the pull ran: `eee3a9b`."),
    ("Sun 02:02", "Format check of the prints of the first 110 markets: counts of sides and outcomes, no detection."),
    ("Sun 02:04", "**A detection smoke test on part of the pull** (127 pairs), written to a scratch folder only: 43 matches at 10 minutes, 34 at 2 minutes, provisional cut dates, seconds between prints, events with the most matches. No result read, no P&L."),
    ("Sun 02:30", "The coordinator's message arrived: the partner's study `research/ladder_replay` (origin/main `a876979` 02:11, `b57d2a8` 02:21, `4d9ac93` 02:21) found that S11's year rule misdates some rungs, and had seen results on a fresh universe that overlaps this one. Read with `git show` at 02:31."),
    ("Sun 02:31–02:35", "**Which case applied: prints had already been analysed (the 02:04 smoke test), so the registered test was not changed.** Amendment 1 written: the registered test stands; a secondary analysis (the partner's year check and nesting rule, and an unseen sample without the 58 shared markets) fixed before any result or P&L. Committed and pushed at 02:34:58: `61c05e0`. At that moment the pull was still running, no result had been read and `run detect` had not been run on the full pull."),
]

WENT_WRONG: list[str] = [
    "The freshness claim of METHOD.md section 1 failed for 58 markets: the partner's study analysed them (set (a), 20 date ladders, 38 pairs) "
    "between 02:00 and 02:21, while this study's pull ran. Results are shown with and without them.",
    "A detection smoke test was run on part of the pull at 02:04, before the partner's finding was known. It showed match counts only, but it means "
    "the corrected rule could not be registered as this study's test. It is a secondary analysis, fixed before any result or P&L (`61c05e0`).",
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
    out += [f"- **What was tested.** {n_lad:,} fresh ladders ({n_pairs:,} pairs of neighbouring rungs) that S11 never used: "
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
        out += [f"- **Where the profit comes from.** {f(pp['entry_edge_mean'])} points per trade are locked in at entry. "
                f"{f(pp['result_part_mean'])} points come from the result: {rs['rich NO, cheap YES (pays $1)']} trades were paid $1 because the cheap "
                f"rung resolved YES and the rich rung NO. Without those trades the mean is {f(pp['mean_without_one_dollar_payouts'])} points.",
                f"- **Ladder order at the result.** {rs['rich YES, cheap NO (order violated)']} of {int(A1.trades):,} trades resolved with the "
                f"ladder's order violated." + (" That is what a correct ladder list gives." if rs['rich YES, cheap NO (order violated)'] == 0 else
                                               " Each case is read and explained below.")]
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
        out += [f"The Sharpe is {f(A1.sharpe, 2, False)}, so METHOD.md section 9 applies. What was checked:", "",
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
    if BROKEN_NOTES:
        out += ["**Trades whose ladder order was violated at the result, one by one:**", ""] + [f"- {x}" for x in BROKEN_NOTES] + [""]

    # ---- after the run
    if au:
        out += ["## Looked at after the run (not part of the test)", "",
                "**How far apart the two prints were.** The closer the two prints, the closer the trade is to a proven simultaneous fill.", "",
                "| Seconds between the two prints | Trades | Dates | Net, points per trade, 1× | 95% interval | At 2× | Entry edge, points | P&L, cap |", "|---|---|---|---|---|---|---|---|"]
        for lab, r in au["pnl_by_seconds_apart"].items():
            out.append(f"| {lab} | {r['trades']} | {r['dates']} | {f(r['points_1x'])} | [{f(r['lo'])}, {f(r['hi'])}] | {f(r['points_2x'])} | {f(r['entry_edge_points'])} | {usd(r['usd_capped_1x'])} |")
        out += ["", "**How large the gap between the two prints was.**", "",
                "| Gap, sale print minus purchase print | Trades | Dates | Net, points per trade, 1× | 95% interval | At 2× | Entry edge, points | P&L, cap |", "|---|---|---|---|---|---|---|---|"]
        for lab, r in au["pnl_by_gap"].items():
            out.append(f"| {lab} | {r['trades']} | {r['dates']} | {f(r['points_1x'])} | [{f(r['lo'])}, {f(r['hi'])}] | {f(r['points_2x'])} | {f(r['entry_edge_points'])} | {usd(r['usd_capped_1x'])} |")
        out += ["", "**Was the earlier print's price still there at the entry?** \"Same second\": both prints in one second. \"Confirmed after\": the earlier "
                "rung printed again on the same side, at our fill price or better, between the entry and 10 minutes later. \"Moved away\": not confirmed, and "
                "the earlier rung printed at a worse price than our fill before the entry. \"Not confirmed\": neither.", "",
                "| Group | Segment | Trades | Dates | Net, points per trade, 1× | 95% interval | At 2× | Entry edge, points | P&L, cap | P&L, full size |", "|---|---|---|---|---|---|---|---|---|---|"]
        for lab, r in au["pnl_by_confirmation"].items():
            g, seg = lab.split(" | ")
            out.append(f"| {g} | {seg} | {r['trades']} | {r['dates']} | {f(r['points_1x'])} | [{f(r['lo'])}, {f(r['hi'])}] | {f(r['points_2x'])} | {f(r['entry_edge_points'])} | "
                       f"{usd(r['usd_capped_1x'])} | {usd(r['usd_uncapped_1x'])} |")
        eb = au["event_bootstrap"]
        out += ["", "**Bootstrap over events instead of dates** (one event can trade on many dates): "
                + "; ".join(f"{seg} {f(r['points_1x'])} [{f(r['lo'])}, {f(r['hi'])}] on {r['events']} events" for seg, r in eb.items()) + "."]
        out += ["", "**Where the trades were** (events with the most trades):", "", "| Event | Trades | Sum of points | P&L, cap |", "|---|---|---|---|"]
        for r in au["by_event_top"][:10]:
            out.append(f"| {r['event_title']} | {r['trades']} | {f(r['points'], 1)} | {usd(r['usd_cap'])} |")
        out += [""]
    out += AFTER
    return out


AFTER: list[str] = []
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
           "written, in METHOD.md amendment 1 (`61c05e0`, 02:34:58). **When that was committed, this study had read no result and computed no "
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
            one("Corrected rule, unseen sample, prints within 2 minutes", "corrected rule, unseen sample", "W120"), ""]
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
