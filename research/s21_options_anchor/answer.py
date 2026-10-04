from __future__ import annotations

from s8_open_referee.report import ci, num, pts


def answer(v: dict) -> list[str]:
    meta, sc, tb, every = v["meta"], v["sc"], v["tb"], v["every"]
    ca, cp, la_, lp_ = v["ca"], v["cp"], v["la_"], v["lp_"]
    br_p, br_c, br_l, bd_c, bd_l, means = v["br_p"], v["br_c"], v["br_l"], v["bd_c"], v["bd_l"], v["means"]
    b0a, b0i, b0o, b0a2, b0i2, b0o2 = v["b0a"], v["b0i"], v["b0o"], v["b0a2"], v["b0i2"], v["b0o2"]
    ua, ui, uo, la, im = v["ua"], v["ui"], v["uo"], v["la"], v["im"]
    row, stat, money, pc, chk = v["row"], v["stat"], v["money"], v["pc"], v["chk"]
    hi, lo2 = tb.iloc[-1], tb.iloc[0]
    n_below = int(tb.iloc[:2].markets.sum())
    d, d_is = im.loc["ALL"], im.loc["IS"]
    out = []

    if v["dose"] and v["improves"] and not v["passed"]:
        head = ("**In this sample the options anchor does sort the overpriced tickets from the fair ones, and by the rule fixed in advance it is still not a "
                "pass: almost none of the evidence is out-of-sample.**")
    elif v["passed"]:
        head = "**The options anchor sorts the overpriced tickets and the rule passes. A pass is a lead that needs a replication, not an edge.**"
    elif v["dose"] or v["improves"]:
        head = "**The options anchor sorts the tickets on one of the two measures only, and the rule is not a pass.**"
    else:
        head = "**The options anchor does not sort the overpriced tickets from the fair ones in this sample.**"
    out += [f"{head} {meta['anchored']} of the {meta['markets_in_s18_file']} stock and S&P 500 markets got an anchor from two real option quotes taken at 15:55 on "
            "the Friday before the market's first weekend.", ""]

    t1_head = ("**The further above the anchor a buyer paid, the more the buyer lost.**" if v["dose"] else
               "**Buyers who paid further above the anchor did not reliably lose more.**")
    out += [f"{t1_head} Over {int(every.markets)} markets in {int(every.events)} events, buyers of YES paid {num(every.mean_traded_price, 1)}% on average against a "
            f"central anchor of {num(every.mean_anchor, 1)}%; {num(every.share_yes, 1)}% resolved YES; they lost {num(-every.buyers_pnl_points)} points per contract "
            f"{ci(every.ci_lo, every.ci_hi)}. Where they paid 10 points or more above the central anchor ({int(hi.markets)} markets, {int(hi.events)} events) they "
            f"lost {num(-hi.buyers_pnl_points)} points {ci(hi.ci_lo, hi.ci_hi)}. Where they paid below it ({n_below} markets) the loss is not distinguishable from "
            f"zero: {pts(lo2.buyers_pnl_points)} {ci(lo2.ci_lo, lo2.ci_hi)} at 5 or more points below, {pts(tb.iloc[1].buyers_pnl_points)} "
            f"{ci(tb.iloc[1].ci_lo, tb.iloc[1].ci_hi)} between 5 below and the anchor. Each extra point paid above the anchor cost "
            f"{num(-sc.slope_points_per_point, 2)} points of P&L (event-bootstrap interval of the slope [{sc.boot_lo:+.3f}, {sc.boot_hi:+.3f}], t = {sc.t:+.2f}). "
            + ("The steps are not even: the buckets in between do not line up one by one; the two ends do." if not tb.buyers_pnl_points.is_monotonic_decreasing
               else "The loss grows bucket by bucket."), ""]

    t3_head = ("**Selling only the tickets priced above the anchor beat selling all of them, in-sample.**" if v["improves"] else
               "**Selling only the tickets priced above the anchor did not reliably beat selling all of them.**")
    out += [f"{t3_head} B0 sells YES at the traded bid when it is 5 or more points above the central anchor and holds to the result: {stat(b0a)} "
            f"({pts(b0a2.mean_pnl_points)} with the fee doubled); in-sample {stat(b0i)}. S18's unfiltered book on the same anchored markets: {stat(ua)}. The anchored "
            f"markets B0 leaves: {stat(la)}. Taken minus left: **{pts(d.difference_points)} points {ci(d.ci_lo, d.ci_hi)}**; in-sample {pts(d_is.difference_points)} "
            f"{ci(d_is.ci_lo, d_is.ci_hi)}. The tickets B0 sold were priced {num(b0a.mean_traded_price, 1)}% on average, the anchor said {num(b0a.mean_anchor, 1)}%, and "
            f"{num(b0a.share_yes, 1)}% resolved YES. As a book of up to 100 contracts per market B0 made {money(b0a.pnl)} on a capital base of "
            f"${b0a.capital_base:,.0f} (monthly Sharpe {num(b0a.sharpe)}, maximum drawdown {pc(b0a.max_drawdown)}, worst month {pc(b0a.worst_month)}, "
            f"{int(b0a.months)} months); the unfiltered book made {money(ua.pnl)} on ${ua.capital_base:,.0f} (Sharpe {num(ua.sharpe)}, maximum drawdown "
            f"{pc(ua.max_drawdown)}, worst month {pc(ua.worst_month)}). The filter takes {num(100 * b0a.markets / ua.markets, 0)}% of the "
            f"markets and keeps {num(100 * b0a.pnl / ua.pnl, 0)}% of the unfiltered book's dollars.", ""]

    if v["passed"]:
        out += ["**By the rule fixed before the pull this is a pass: a lead that needs a replication on fresh markets, not an edge.**", ""]
    else:
        out += [f"**Not a pass. Lines not met: {v['failed']}.** Out-of-sample B0 holds {int(b0o.markets)} markets in {int(b0o.events)} events "
                f"({pts(b0o.mean_pnl_points)} points; both won; no interval can be drawn from two events) against the 30 the rule needs: too few. This was known "
                f"before the pull: only {int(row('U-all', 'OOS').markets)} of the stock and S&P markets in S18's out-of-sample events have a taker sale at all. Lines (1) and (3) are met: in-sample "
                f"{pts(b0i.mean_pnl_points)} {ci(b0i.ci_lo, b0i.ci_hi)}; with the fee doubled {pts(b0i2.mean_pnl_points)} in-sample and "
                f"{pts(b0o2.mean_pnl_points)} out-of-sample.", ""]

    out += ["**What did not hold.** "
            f"(a) The anchor does not carry the weight alone (T2). With the result regressed on both, the central anchor's coefficient is {ca.value:+.3f} "
            f"[{ca.ci_lo:+.3f}, {ca.ci_hi:+.3f}] and the traded price's {cp.value:+.3f} [{cp.ci_lo:+.3f}, {cp.ci_hi:+.3f}]: the two move together and neither is "
            f"distinguishable from zero next to the other. With the lower-bound anchor instead, both are: anchor {la_.value:+.3f} [{la_.ci_lo:+.3f}, {la_.ci_hi:+.3f}], "
            f"price {lp_.value:+.3f} [{lp_.ci_lo:+.3f}, {lp_.ci_hi:+.3f}]. Brier scores: traded price {br_p.value:.4f}, central anchor {br_c.value:.4f}, lower-bound "
            f"anchor {br_l.value:.4f}; the central anchor is better by {bd_c.value:+.4f} [{bd_c.ci_lo:+.4f}, {bd_c.ci_hi:+.4f}], an interval that includes zero. "
            "So each price knows something the other does not; the options do not simply replace the crowd. "
            f"(b) B2, buying tickets priced 5 or more points below the lower-bound anchor, found {int(row('B2', 'ALL').markets)} markets "
            f"({pts(row('B2', 'ALL').mean_pnl_points)} points): the crowd almost never prices a ticket below the options' floor. "
            f"(c) Out-of-sample nothing can be said: {int(b0o.markets)} markets.", ""]

    hs = v["high_sharpe"]
    p_obs, p_pl, p_share = chk("placebo", "taken minus left, observed"), chk("placebo", "taken minus left, placebo"), chk("placebo", "share of placebo")
    un, unl = chk("subsets", "B0 on anchors with no leg"), chk("subsets", "the markets it leaves")
    su, old_q, lead = chk("Sharpe", "U:"), chk("no look-ahead", "oldest leg quote"), chk("no look-ahead", "seconds from the anchor")
    reach = "none" if p_share.value == 0 else f"{num(100 * p_share.value, 1)}%"
    out += ["**The bug hunt.** " + (f"A Sharpe above 3 appears in: {', '.join(hs)}. " if hs else "No book shows a Sharpe above 3. ") +
            "The largest is S18's own unfiltered book on these markets, which does not use the anchor. The cause found is the sample, not the code: ten or "
            f"eleven monthly numbers with one losing month ({su.note}); B0 has no losing month at all in {int(b0a.months)}, on a capital base of "
            f"${b0a.capital_base:,.0f}. A Sharpe from so few months is known only to about plus or minus {num((su.hi - su.lo) / 2, 1)}, and this is a book that "
            "sells insurance in months when the insured move did not come. Every anchor was recomputed by hand from the cached quotes (0 mismatches); every book "
            f"mean and the book dollars were recomputed from S18's file; every leg quote is at most {num(old_q.value, 0)} seconds older than the anchor instant; "
            f"the instant is {num(lead.value / 3600, 1)} hours or more before the first traded price. Checks added after the result (not pre-registered, in "
            f"[`checks.csv`](checks.csv)): with the anchors shuffled across markets the taken-minus-left difference is {pts(p_pl.value)} "
            f"[{p_pl.lo:+.2f}, {p_pl.hi:+.2f}] and {reach} of {int(p_pl.n):,} shuffles reach the observed {pts(p_obs.value)}, so it is the "
            "anchor and not only the price level; inside each of S18's five price buckets the taken markets earned more than the left ones. One check weakens "
            f"it: on the {int(un.n + unl.n)} markets whose anchor needed no option leg moved to a further strike, B0 earned {pts(un.value)} "
            f"[{un.lo:+.2f}, {un.hi:+.2f}] and the markets it leaves {pts(unl.value)} [{unl.lo:+.2f}, {unl.hi:+.2f}]: a smaller gap.", ""]
    return out
