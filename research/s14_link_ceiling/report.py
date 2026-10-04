from __future__ import annotations

import json
import sys

import pandas as pd

from s8_open_referee.report import md_table, num, pct, pts

from . import config as cfg
from .run import RESULTS as R


def main() -> int:
    t, links, meta = pd.read_csv(R / "tests.csv"), pd.read_csv(R / "links.csv"), json.loads((R / "run_meta.json").read_text())
    c1, c2, c3 = t[t.test == "C1 oracle link"], t[t.test == "C2 count of strong links"], t[t.test == "C3 signal definition"]

    def r1(group, sample, outcome="after the open"):
        return c1[(c1.group == group) & (c1["sample"] == sample) & (c1.outcome == outcome)].iloc[0]

    IS, OOS = "in-sample (where the links were picked)", "out-of-sample"
    both, tenths = "both groups, reversal links flipped", "top and bottom tenth, bottom flipped"
    b_is, b_oos, t_is, t_oos = r1(both, IS), r1(both, OOS), r1(tenths, IS), r1(tenths, OOS)
    share, top, ctrl = c2.iloc[0], c2.iloc[1], c2.iloc[2]
    has_t = links[links.after_t.notna()]
    pos, neg = int((has_t.after_t >= cfg.T_PICK).sum()), int((has_t.after_t <= -cfg.T_PICK).sum())
    big = has_t.reindex(has_t.after_t.abs().sort_values(ascending=False).index).head(3)
    after = c3[c3.outcome == "after the open"]
    gap = c3[(c3.outcome == "opening gap") & (c3["sample"] == "all nights")]
    link_line = b_oos.t >= cfg.T_PICK and b_oos.slope > 0
    count_line = share.share_of_shuffles_at_or_above <= 0.05
    signal_line = bool((after[after.group != "points, previous close to 09:29"].t.abs() >= cfg.T_DEFINITION).any())
    c1tab = md_table(c1.assign(G=c1.group, S=c1["sample"], O=c1.outcome, L=c1.links.astype(int), N=c1.n.astype(int), B=c1.slope.map(pts), T=c1.t.map(num)),
                     {"G": "Links", "S": "Sessions", "O": "Outcome", "L": "Links", "N": "Link-days", "B": "Slope, bp per point", "T": "t"})
    c3tab = md_table(c3.assign(G=c3.group, S=c3["sample"], O=c3.outcome, N=c3.n.astype(int), B=c3.slope.map(pts), T=c3.t.map(num)),
                     {"G": "Definition of the odds move", "S": "Nights", "O": "Outcome", "N": "Link-days", "B": "Slope", "T": "t"})
    S = ["# S14: is the missing edge a link problem, a signal problem, or neither?", "",
         "Method, pre-registered before anything was computed: [`research/s14_link_ceiling/METHOD.md`](../../s14_link_ceiling/METHOD.md) "
         f"(commit `2e1d1c0`). A diagnostic on cached data: {meta['links_in_panel']} links, {meta['sessions']} sessions, out-of-sample from "
         f"{meta['oos_from']}. No trade, no P&L. Files: [`tests.csv`](tests.csv), [`links.csv`](links.csv), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**The links work, and that is measurable.** {pct(ctrl.observed, 0)} of links show a significant opening-gap relation on their own "
         f"(t of +2 or more). Shuffling each link's odds moves across its own sessions gives {pct(ctrl.shuffle_mean, 0)}, and none of the "
         f"{meta['shuffles']} shuffles comes close (largest {pct(ctrl.shuffle_max, 0)}).", "",
         "**The signal is not measured badly.** Four definitions of the overnight odds move give the same picture: the opening gap responds "
         f"(t = {num(gap.iloc[0].t)} in points, {num(gap.iloc[1].t)} in log-odds, {num(gap.iloc[2].t)} for the early night alone), and the move "
         f"after the open does not, under any of them (largest |t| = {num(after.t.abs().max())}; the line was {cfg.T_DEFINITION:.0f}).", "",
         "**Links picked with hindsight do not keep working.** Choosing, on the first 80% of sessions, the links with the strongest relation "
         f"after the open gives {int(b_is.links)} links and an in-sample slope of {pts(b_is.slope)} bp per point (t = {num(b_is.t)}). On the "
         f"last 20% the same links give {pts(b_oos.slope)} (t = {num(b_oos.t)}). The top and bottom tenth: {pts(t_is.slope)} (t = {num(t_is.t)}) "
         f"in-sample, {pts(t_oos.slope)} (t = {num(t_oos.t)}) out-of-sample. This is the most favourable selection that history allows for the trade "
         "after the open, and it does not carry forward.", "",
         f"**One line of the pre-registered reading was crossed, and it has to be said.** More links show a strong relation after the open than "
         f"shuffling produces: {pct(share.observed)} with |t| of 2 or more against {pct(share.shuffle_mean)} ({pct(share.share_of_shuffles_at_or_above)} "
         f"of shuffles reach it), and the top tenth average |t| = {num(top.observed)} against {num(top.shuffle_mean)}. By the rule fixed in advance "
         "that counts toward \"the links are the bottleneck\". Looked at after the run, it is not a usable link effect: the strong links split "
         f"{pos} positive and {neg} negative; the three largest (" + "; ".join(f"{r.ticker}, t = {num(r.after_t)}" for r in big.itertuples())
         + ") each rest on one event day, which carries " + ", ".join(pct(r.largest_day_share_of_odds_variation, 0) for r in big.itertuples())
         + " of that link's variation in odds; and the test above shows they do not persist. Some questions had a large move after the open on their "
         "own event day, in one direction or the other. That is not something a better link predicts.", "",
         "**So: neither, on this evidence.** The relation is real, it holds under every definition tried, and it is in the price at the open "
         "whichever links are chosen. What is missing is not a better link to the same assets at the same times; it is a place or a moment "
         "where the signal is not yet priced.", "",
         "## How the pre-registered reading came out", "", "| Reading | Needed | Result |", "|---|---|---|",
         f"| The links are the bottleneck | hindsight-picked links keep a slope above zero out-of-sample, t ≥ 2 | {'met' if link_line else '**not met**'}: {pts(b_oos.slope)}, t = {num(b_oos.t)} |",
         f"| The links are the bottleneck | or: more strong after-open links than 95% of shuffles | {'**met**' if count_line else 'not met'}: {pct(share.observed)} against {pct(share.shuffle_p95)} at the 95th percentile |",
         f"| The signal is measured badly | an after-open slope with \\|t\\| ≥ 3 under another definition | {'met' if signal_line else '**not met**'}: largest \\|t\\| = {num(after.t.abs().max())} |",
         f"| Positive control: the gap relation shows up link by link | share of links with gap t ≥ 2 beyond the shuffles | **yes**: {pct(ctrl.observed, 0)} against {pct(ctrl.shuffle_mean, 0)} |", "",
         "## C1, the oracle link", "", c1tab, "",
         f"The continuation group has no out-of-sample sessions: all {int(r1('links with in-sample after-open t >= +2 (continuation)', IS).links)} of "
         "its links are on markets that resolved before the out-of-sample window.", "",
         f"The row \"every link, out-of-sample, after the open\" ({pts(r1('every link', OOS).slope)}, t = {num(r1('every link', OOS).t)}) covers only "
         "the links that had enough in-sample sessions to be ranked. Checked after the run: on every out-of-sample link-day the slope is +0.81 "
         "(t = 0.46), S5 reported -0.63 (t = -0.37) for the same period, and without its two largest dates the row is -0.95 (t = -0.74). "
         "It is not a finding.", "",
         "## C2, more strong links than chance?", "",
         md_table(c2.assign(G=c2.group, O=c2.outcome, L=c2.links.astype(int), A=c2.observed.map(lambda x: num(x, 3)), M=c2.shuffle_mean.map(lambda x: num(x, 3)),
                            P=c2.shuffle_p95.map(lambda x: num(x, 3)), S=c2.share_of_shuffles_at_or_above.map(lambda x: num(x, 3))),
                  {"G": "Statistic", "O": "Outcome", "L": "Links", "A": "Observed", "M": "Shuffle mean", "P": "Shuffle 95th percentile",
                   "S": "Share of shuffles at or above"}), "",
         "The shuffle mean for |t| ≥ 2 is above 5% because a link's slope often rests on a few large odds moves; the shuffles reproduce that.", "",
         "## C3, other definitions of the signal", "", c3tab, "",
         "Slopes are in bp per point, except the log-odds rows (bp per unit of log-odds).", "",
         "## Looked at after the run (not pre-registered)", "",
         "- **Oil, where the link is strongest:** gap +11.83 bp per point (t = 5.44), after the open -1.11 (t = -0.84), 81 links. The link-level "
         "reversals on two Kharg Island questions do not add up to a theme.",
         "- **Is the day simply more volatile after a big odds move?** Barely: the absolute move after the open is 1.27 times the ticker's "
         "usual on quiet nights and 1.35 times [1.21, 1.51] after an odds move of 10 points or more.", "",
         "## Caveats", "",
         "- One year of data; 51 out-of-sample sessions; many markets had resolved before them.",
         "- This asks whether a better link *to these assets at the open* would have helped. It says nothing about markets the menu does not "
         "contain, or about trading somewhere the signal is not yet priced.", "",
         "## Reproduce", "", "```", "cd research", "python -m s14_link_ceiling.run", "python -m s14_link_ceiling.report",
         "python -m pytest s14_link_ceiling/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    print("\n".join(S[4:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
