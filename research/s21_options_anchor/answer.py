"""S21: the plain-language answer of SUMMARY.md. Every number comes from the result files through report.main's
variables; the wording of each verdict follows the reading fixed in METHOD.md."""
from __future__ import annotations

from s8_open_referee.report import ci, num, pts


def answer(v: dict) -> list[str]:
    meta, sc, tb, every = v["meta"], v["sc"], v["tb"], v["every"]
    ca, cp, br_p, br_c, br_l, bd_c, bd_l, means = v["ca"], v["cp"], v["br_p"], v["br_c"], v["br_l"], v["bd_c"], v["bd_l"], v["means"]
    b0a, b0i, b0o, b0a2, ua, ui, uo, la, im = v["b0a"], v["b0i"], v["b0o"], v["b0a2"], v["ua"], v["ui"], v["uo"], v["la"], v["im"]
    row, stat, money = v["row"], v["stat"], v["money"]
    hi, lo2 = tb.iloc[-1], tb.iloc[0]
    below = tb.iloc[:2]
    n_below = int(below.markets.sum())
    out = []

    # ---- T1
    if v["dose"]:
        head = "**The options anchor sorts the tickets: the further above it a buyer paid, the more the buyer lost.**"
    elif sc.slope_points_per_point < 0:
        head = "**Buyers who paid further above the options anchor lost more on average, but the slope's interval includes zero: the dose-response is not established.**"
    else:
        head = "**The options anchor does not sort the tickets: buyers who paid further above it did not lose more.**"
    out += [f"{head} Over {int(every.markets)} markets in {int(every.events)} events with a first-weekend purchase and an anchor, buyers paid "
            f"{num(every.mean_traded_price, 1)}% on average against a central anchor of {num(every.mean_anchor, 1)}%, {num(every.share_yes, 1)}% resolved YES, and "
            f"they lost {num(-every.buyers_pnl_points)} points per contract {ci(every.ci_lo, every.ci_hi)}. Where they paid 10 points or more above the central "
            f"anchor ({int(hi.markets)} markets, {int(hi.events)} events): {pts(hi.buyers_pnl_points)} points {ci(hi.ci_lo, hi.ci_hi)}. Where they paid 5 points or "
            f"more below it ({int(lo2.markets)} markets, {int(lo2.events)} events): {pts(lo2.buyers_pnl_points)} points {ci(lo2.ci_lo, lo2.ci_hi)}. "
            f"Slope: {sc.slope_points_per_point:+.3f} points of P&L per point of gap, event-bootstrap interval [{sc.boot_lo:+.3f}, {sc.boot_hi:+.3f}] "
            f"(t = {sc.t:+.2f}). {n_below} of the {int(every.markets)} purchases were below the central anchor at all.", ""]

    # ---- T2
    if v["carries"] and v["better"]:
        h2 = "**The options anchor is the better forecast and carries the weight.**"
    elif v["worse"] and not v["carries"]:
        h2 = "**The traded price is the better forecast; the central anchor adds nothing the price does not have.**"
    elif v["carries"]:
        h2 = "**In the regression the anchor carries the weight, but its Brier score is not better than the traded price's.**"
    elif ca.ci_lo > 0:
        h2 = "**Both prices carry information; the anchor does not carry the weight alone.**"
    else:
        h2 = "**The anchor does not carry the weight: with the traded price in the regression its coefficient is not distinguishable from zero.**"
    out += [f"{h2} Result regressed on both ({int(means.markets)} markets, errors clustered by event): central anchor {ca.value:+.3f} "
            f"[{ca.ci_lo:+.3f}, {ca.ci_hi:+.3f}] (t = {ca.t:+.2f}), traded price {cp.value:+.3f} [{cp.ci_lo:+.3f}, {cp.ci_hi:+.3f}] (t = {cp.t:+.2f}). Brier scores: "
            f"traded price {br_p.value:.4f}, central anchor {br_c.value:.4f}, lower-bound anchor {br_l.value:.4f}. Traded price minus central anchor: "
            f"{bd_c.value:+.4f} [{bd_c.ci_lo:+.4f}, {bd_c.ci_hi:+.4f}]; minus lower-bound anchor: {bd_l.value:+.4f} [{bd_l.ci_lo:+.4f}, {bd_l.ci_hi:+.4f}] "
            "(positive = the anchor is better).", ""]

    # ---- T3
    d = im.loc["ALL"]
    if v["improves"]:
        h3 = "**The rule beats S18's unfiltered book on the same markets.**"
    elif d.difference_points > 0:
        h3 = "**The rule's markets earned more than the ones it leaves, but the difference's interval includes zero.**"
    else:
        h3 = "**The rule does not improve S18's unfiltered book.**"
    out += [f"{h3} B0 (sell YES at the traded bid when it is 5 or more points above the central anchor, hold to the result): {stat(b0a)}; in-sample {stat(b0i)}; "
            f"out-of-sample {stat(b0o)}; with the fee doubled {pts(b0a2.mean_pnl_points)}. S18's unfiltered book on the same anchored markets: {stat(ua)}; in-sample "
            f"{pts(ui.mean_pnl_points)} {ci(ui.ci_lo, ui.ci_hi)}; out-of-sample {pts(uo.mean_pnl_points)} {ci(uo.ci_lo, uo.ci_hi)} on {int(uo.markets)} markets. "
            f"The anchored markets B0 leaves: {stat(la)}. Difference, taken minus left: {pts(d.difference_points)} points {ci(d.ci_lo, d.ci_hi)}. As a book of up "
            f"to 100 contracts per market B0 made {money(b0a.pnl)} on a capital base of ${b0a.capital_base:,.0f}, monthly Sharpe {num(b0a.sharpe)}, maximum drawdown "
            f"{v['pc'](b0a.max_drawdown)}, worst month {v['pc'](b0a.worst_month)}; the unfiltered book {money(ua.pnl)} on ${ua.capital_base:,.0f}, Sharpe "
            f"{num(ua.sharpe)}, maximum drawdown {v['pc'](ua.max_drawdown)}, worst month {v['pc'](ua.worst_month)}.", ""]
    b1, b2 = row("B1", "ALL"), row("B2", "ALL")
    out += [f"Variants: B1 (10 or more points above) {stat(b1)}. B2 (buy YES when the traded ask is 5 or more points below the lower-bound anchor) {stat(b2)}.", ""]

    # ---- verdict
    if v["passed"]:
        out += ["**By the rule fixed before the pull this is a pass. A pass is a lead that needs a replication on fresh markets, not an edge.**", ""]
    else:
        out += [f"**By the rule fixed before the pull this is not a pass.** Lines not met: {v['failed']}. Line (4) was known to be out of reach before the pull: "
                f"only 15 of the out-of-sample markets have a taker sale at all, and B0 holds {int(b0o.markets)} of them.", ""]
    return out
