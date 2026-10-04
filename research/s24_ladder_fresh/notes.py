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
]

WENT_WRONG: list[str] = []

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
