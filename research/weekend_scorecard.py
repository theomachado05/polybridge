"""One scorecard for the weekend and cross-venue studies, the way the track scores them, built from the committed
`metrics.csv` files only. Writes `results/WEEKEND_SCORECARD.md` and refreshes the table between the scorecard markers
in `EVIDENCE.md`.

Run from `research/`:  python weekend_scorecard.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE / "results"
START, END = "<!-- scorecard:start -->", "<!-- scorecard:end -->"


def f(x: float, d: int = 2, sign: bool = True) -> str:
    return "n/a" if x != x else (f"{x:+.{d}f}" if sign else f"{x:.{d}f}")


def pc(x: float, d: int = 1) -> str:
    return "n/a" if x != x else f"{100 * x:.{d}f}%"


def cell(r, value: str, lo: str, hi: str, n: str, scale: float = 1.0, d: int = 2) -> str:
    v = r[value] * scale
    ci = "" if r[lo] != r[lo] else f" [{r[lo] * scale:+.{d}f}, {r[hi] * scale:+.{d}f}]"
    return f"{f(v, d)}{ci}, n {int(r[n])}"


def generic(folder: str, name: str, trade: str, unit: str, verdict: str, *, value="mean_net_points", lo="ci_lo", hi="ci_hi", n="trades",
            seg=("IS", "OOS", "ALL"), cost=None, where=None, scale=1.0, d=2, summed_returns=False) -> dict | None:
    p = R / folder / "metrics.csv"
    if not p.exists():
        return None
    m = pd.read_csv(p)
    for k, v in (where or {"variant": "V0"}).items():
        m = m[m[k] == v]

    def row(s, c):
        x = m[(m.segment == s) & (m.cost_mult == c)]
        return x.iloc[0] if len(x) else None

    i1, o1 = row(seg[0], 1.0), row(seg[1], 1.0)
    whole1, whole2 = (row(seg[2], 1.0), row(seg[2], 2.0)) if seg[2] else (None, None)
    ref = whole1 if whole1 is not None else i1
    two = whole2 if whole2 is not None else row(seg[1], 2.0)
    return {"Study": f"**{name}.** {trade}", "Unit": unit,
            "In-sample, 1× costs": cell(i1, value, lo, hi, n, scale, d), "Out-of-sample, 1× costs": cell(o1, value, lo, hi, n, scale, d),
            "At 2× costs": f"{f(two[value] * scale, d)} ({'whole sample' if whole2 is not None else 'out-of-sample'})",
            "Sharpe (in / out)": f"{f(i1.sharpe, 2)} / {f(o1.sharpe, 2)}",
            "Max drawdown": f"{ref.max_drawdown:.1f} premiums (sum of weekend returns)" if summed_returns else pc(ref.max_drawdown),
            "Worst month": f"{ref.worst_month:+.2f} premiums" if summed_returns else pc(ref.worst_month),
            "Turnover a year": "n/a" if "turnover_ann" not in ref or ref.turnover_ann != ref.turnover_ann else f"{ref.turnover_ann:.1f}×",
            "Cost of a round trip": cost(ref) if cost else "n/a", "Verdict": verdict}


def forward_note(m: pd.DataFrame) -> str:
    """S1's forward paper test on the recorded weekend books, when it has been run."""
    f = m[(m.segment == "forward") & (m.variant == "V0") & (m.cost_mult == 1.0)]
    if f.empty:
        return ""
    f = f.iloc[0]
    return f". On this weekend's recorded books: {int(f.entries)} fills, +${f.pnl_locked:.2f} locked on ${f.capital:,.2f} after costs"


def rows() -> list[dict]:
    out = []
    p = R / "s1_twin_spread" / "metrics.csv"
    if p.exists():
        m_all = pd.read_csv(p)
        m = m_all[(m_all.quote_rule == "registered") & (m_all.variant == "V0")]
        i1, o1, o2 = (m[(m.segment == s) & (m.cost_mult == c)].iloc[0] for s, c in (("IS", 1.0), ("OOS", 1.0), ("OOS", 2.0)))
        out.append({"Study": "**S1 twin spread.** Same question on Polymarket and Kalshi: buy the cheap YES and the other venue's NO", "Unit": "$ per trade",
                    "In-sample, 1× costs": cell(i1, "mean_pnl_per_trade_mid", "ci_lo_mid", "ci_hi_mid", "entries"),
                    "Out-of-sample, 1× costs": cell(o1, "mean_pnl_per_trade_mid", "ci_lo_mid", "ci_hi_mid", "entries") + f"; {int(o1.verified_entries)} print-verified",
                    "At 2× costs": f"{f(o2.mean_pnl_per_trade_mid)} (out-of-sample)", "Sharpe (in / out)": f"{f(i1.sharpe_mid)} / {f(o1.sharpe_mid)} (unverified prices)",
                    "Max drawdown": pc(o1.max_drawdown), "Worst month": pc(o1.worst_month), "Turnover a year": f"{o1.turnover_ann:.1f}×",
                    "Cost of a round trip": f"fees {o1.fees_bp:.0f} bp, spreads {o1.spread_bp:.0f} bp, carry {o1.carry_bp:.0f} bp of capital",
                    "Verdict": "not a pass: 15% of out-of-sample entries are print-verified, 50% needed" + forward_note(m_all)})
    p = R / "s3_three_way" / "metrics.csv"
    if p.exists():
        m = pd.read_csv(p)
        a = m[(m.variant == "V0") & (m.segment == "ALL") & (m.cost_mult == 1.0)].iloc[0]
        out.append({"Study": "**S3 three-way.** Polymarket, Kalshi and options on the same index level", "Unit": "$ per trade",
                    "In-sample, 1× costs": "no trade", "Out-of-sample, 1× costs": "no trade", "At 2× costs": "no trade", "Sharpe (in / out)": "n/a",
                    "Max drawdown": "n/a", "Worst month": "n/a", "Turnover a year": "n/a", "Cost of a round trip": "n/a",
                    "Verdict": f"no trade: the rule fired {int(a.entries)} times in {int(a.sets)} matched sets on {int(a.dates)} dates"})
    specs = [
        generic("s4_linked_assets", "S4 linked assets", "Buy the linked stock at the open in the direction of the overnight odds move (trusted links)",
                "bp per trade", "too few observations, and negative", value="mean_net_bp", seg=("IS", "OOS", None), d=1,
                cost=lambda r: f"{r.mean_cost_bp:.1f} bp"),
        generic("s5_big_moves", "S5 big moves", "The same after odds moves of 10+ points, 93 fresh markets", "bp per trade", "not a pass",
                value="mean_net_bp", seg=("earlier", "recent", "all"), d=1, cost=lambda r: f"{r.mean_cost_bp:.1f} bp"),
        generic("s6_monday_fade", "S6 Monday fade", "Monday 09:45: take the options' side against Polymarket, hold to resolution", "$ per trade",
                "too few observations; the modelled figures are unverified prices", value="mean_pnl_per_trade",
                cost=lambda r: f"{r.cost_bp_of_capital:,.0f} bp of capital"),
        generic("s7_weekend_straddle", "S7 weekend straddles", "Friday 15:55 straddle on flagged tickers, sold Monday 09:45", "% of premium",
                "too few out-of-sample trades; a loss over the year, the same as ordinary weekends", value="mean_ret_flagged", n="flagged_trades",
                scale=100.0, d=1, summed_returns=True, cost=lambda r: f"{100 * r.cost_share_of_premium:.0f}% of the premium"),
        generic("s8_open_referee", "S8 open referee", "Sell the overnight odds move on Polymarket when the asset's open does not confirm it",
                "points per trade", "null", cost=lambda r: f"{r.mean_cost_points:.2f} points ({r.cost_bp_of_capital:,.0f} bp of capital)"),
        generic("s9_weekend_price_markets", "S9 weekend price markets", "Sell the weekend move in Polymarket's price markets on Sunday 17:55",
                "points per trade", "not a pass", cost=lambda r: f"{r.mean_cost_points:.2f} points ({r.cost_bp_of_capital:,.0f} bp of capital)"),
        generic("s10_weekend_lag", "S10 weekend lag", "Trade the oil price market after the event question jumps, 30-minute hold",
                "points per trade", "not a pass", cost=lambda r: f"{r.mean_cost_points:.2f} points ({r.cost_bp_of_capital:,.0f} bp of capital)"),
        generic("s12_resting_orders", "S12 resting orders", "S9's fades posted as resting orders, judged against public prints", "points per filled order",
                "not a pass: adverse selection out-of-sample", value="net_per_filled", lo="net_lo", hi="net_hi", n="filled",
                where={"sample": "S9", "variant": "R0"}, cost=lambda r: f"{r.cost_points:.2f} points ({r.cost_bp:,.0f} bp of capital)"),
        generic("s16_kalshi_quotes", "S16 Kalshi quotes", "Fade overnight moves of 5+ points at Kalshi's real bid and ask", "points per trade",
                "not a pass", cost=lambda r: f"spread {r.mean_spread_cost_points:.2f} points, fee {r.mean_fee_cost_points:.2f} ({r.cost_bp_of_capital:,.0f} bp of capital)"),
        generic("s18_price_market_calibration", "S18 price-market calibration", "Sell YES at 5 to 25% on a market's first weekend at the history mid, hold to the result",
                "points per trade", "not a pass; at traded bids +3.63 over the year and -0.99 out-of-sample (see its summary)", n="trades",
                cost=lambda r: f"{r.mean_cost_points:.2f} points, paid once ({r.cost_bp_of_capital:,.0f} bp of capital)"),
        generic("s15_weekend_scare", "S15 weekend rises", "Sell weekend rises of 5+ points on 871 price markets S9 did not use", "points per trade",
                "not a pass; the reversal holds in quoted prices only", cost=lambda r: f"{r.mean_cost_points:.2f} points ({r.cost_bp_of_capital:,.0f} bp of capital)"),
    ]
    out = out + [s for s in specs if s]
    sell = "sellers: sold YES into a bid, held to the result"
    for folder, tests_csv, book_csv, name, trade in (
            ("s18_price_market_calibration", "prints_tests.csv", "prints_book.csv", "S18 at traded prices",
             "Sell YES into the bid on a market's first weekend, hold to the result (oil, metals, S&P 500, stocks)"),
            ("s19_crypto_price_markets", "tests.csv", "book.csv", "S19 crypto replication",
             "The same on Bitcoin, Ethereum, Solana and XRP price markets, first 48 hours, two years")):
        if not (R / folder / tests_csv).exists():
            continue
        t, b = pd.read_csv(R / folder / tests_csv), pd.read_csv(R / folder / book_csv)

        def tr(scope, test=sell):
            return t[(t.test == test) & (t.scope == scope)].iloc[0]

        def bk(seg):
            return b[(b.book == "sellers") & (b.segment == seg)].iloc[0]

        i1, o1, two, allb = tr("in-sample events"), tr("out-of-sample events"), tr("all markets", sell + ", fee doubled"), bk("ALL")
        out.append({"Study": f"**{name}.** {trade}", "Unit": "points per contract",
                    "In-sample, 1× costs": cell(i1, "mean_pnl_points", "ci_lo", "ci_hi", "markets"),
                    "Out-of-sample, 1× costs": cell(o1, "mean_pnl_points", "ci_lo", "ci_hi", "markets"),
                    "At 2× costs": f"{f(two.mean_pnl_points)} (whole sample, fee doubled)", "Sharpe (in / out)": f"{f(bk('IS').sharpe)} / {f(bk('OOS').sharpe)} (monthly)",
                    "Max drawdown": pc(allb.max_drawdown), "Worst month": pc(allb.worst_month), "Turnover a year": f"{allb.turnover_ann:.1f}×",
                    "Cost of a round trip": "the market's taker fee, once; the price is the print",
                    "Verdict": "not a pass: nothing out-of-sample" if folder.startswith("s18") else "does not replicate"})
    return out


def table() -> str:
    rs = rows()
    cols = list(rs[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rs]
    return "\n".join(lines)


NOTE = ("Primary variant of each study, as pre-registered. Net result per trade with a 95% bootstrap interval where the study reports one "
        "(resampling pairs, dates, closures or weekends) and the number of trades. Maximum drawdown and worst month are shares of each "
        "study's capital base, on the whole sample where the study reports it, otherwise in-sample. Every variant, the capacity note and the "
        "charts are in each study's `SUMMARY.md` under `research/results/`. Built by `research/weekend_scorecard.py` from the committed "
        "`metrics.csv` files.")


def main() -> int:
    t = table()
    (R / "WEEKEND_SCORECARD.md").write_text("# Weekend and cross-venue studies: scorecard\n\n" + NOTE + "\n\n" + t + "\n")
    ev = HERE / "EVIDENCE.md"
    s = ev.read_text()
    if START in s and END in s:
        a, b = s.index(START) + len(START), s.index(END)
        ev.write_text(s[:a] + "\n" + t + "\n" + s[b:])
    print(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
