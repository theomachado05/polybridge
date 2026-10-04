# S14: is the missing edge a link problem, a signal problem, or neither?

Method, pre-registered before anything was computed: [`research/s14_link_ceiling/METHOD.md`](../../s14_link_ceiling/METHOD.md) (commit `2e1d1c0`). A diagnostic on cached data: 254 links, 253 sessions, out-of-sample from 2026-07-23. No trade, no P&L. Files: [`tests.csv`](tests.csv), [`links.csv`](links.csv), [`RUN_LOG.md`](RUN_LOG.md).

## Answer

**The links work, and that is measurable.** 34% of links show a significant opening-gap relation on their own (t of +2 or more). Shuffling each link's odds moves across its own sessions gives 5%, and none of the 500 shuffles comes close (largest 11%).

**The signal is not measured badly.** Four definitions of the overnight odds move give the same picture: the opening gap responds (t = 5.86 in points, 5.81 in log-odds, 5.53 for the early night alone), and the move after the open does not, under any of them (largest |t| = 1.06; the line was 3).

**Links picked with hindsight do not keep working.** Choosing, on the first 80% of sessions, the links with the strongest relation after the open gives 24 links and an in-sample slope of +5.50 bp per point (t = 3.38). On the last 20% the same links give -2.04 (t = -0.59). The top and bottom tenth: +5.39 (t = 4.45) in-sample, +1.37 (t = 0.37) out-of-sample. This is the most favourable selection that history allows for the trade after the open, and it does not carry forward.

**One line of the pre-registered reading was crossed, and it has to be said.** More links show a strong relation after the open than shuffling produces: 15.1% with |t| of 2 or more against 10.5% (2.8% of shuffles reach it), and the top tenth average |t| = 5.29 against 2.94. By the rule fixed in advance that counts toward "the links are the bottleneck". Looked at after the run, it is not a usable link effect: the strong links split 12 positive and 15 negative; the three largest (GOOGL, t = -30.05; GLD, t = 12.94; UUP, t = 8.27) each rest on one event day, which carries 98%, 89%, 89% of that link's variation in odds; and the test above shows they do not persist. Some questions had a large move after the open on their own event day, in one direction or the other. That is not something a better link predicts.

**So: neither, on this evidence.** The relation is real, it holds under every definition tried, and it is in the price at the open whichever links are chosen. What is missing is not a better link to the same assets at the same times; it is a place or a moment where the signal is not yet priced.

## How the pre-registered reading came out

| Reading | Needed | Result |
|---|---|---|
| The links are the bottleneck | hindsight-picked links keep a slope above zero out-of-sample, t ≥ 2 | **not met**: -2.04, t = -0.59 |
| The links are the bottleneck | or: more strong after-open links than 95% of shuffles | **met**: 15.1% against 14.0% at the 95th percentile |
| The signal is measured badly | an after-open slope with \|t\| ≥ 3 under another definition | **not met**: largest \|t\| = 1.06 |
| Positive control: the gap relation shows up link by link | share of links with gap t ≥ 2 beyond the shuffles | **yes**: 34% against 5% |

## C1, the oracle link

| Links | Sessions | Outcome | Links | Link-days | Slope, bp per point | t |
|---|---|---|---|---|---|---|
| links with in-sample after-open t >= +2 (continuation) | in-sample (where the links were picked) | after the open | 9 | 767 | +3.75 | 11.57 |
| links with in-sample after-open t >= +2 (continuation) | out-of-sample | after the open | 9 | 0 | n/a | n/a |
| links with in-sample after-open t <= -2 (reversal) | in-sample (where the links were picked) | after the open | 15 | 1354 | -6.94 | -3.07 |
| links with in-sample after-open t <= -2 (reversal) | out-of-sample | after the open | 15 | 117 | +2.04 | 0.59 |
| both groups, reversal links flipped | in-sample (where the links were picked) | after the open | 24 | 2121 | +5.50 | 3.38 |
| both groups, reversal links flipped | out-of-sample | after the open | 24 | 117 | -2.04 | -0.59 |
| top tenth by in-sample after-open t | in-sample (where the links were picked) | after the open | 17 | 1435 | +4.31 | 7.04 |
| top tenth by in-sample after-open t | out-of-sample | after the open | 17 | 153 | +6.23 | 0.98 |
| bottom tenth by in-sample after-open t | in-sample (where the links were picked) | after the open | 17 | 1477 | -6.92 | -3.13 |
| bottom tenth by in-sample after-open t | out-of-sample | after the open | 17 | 117 | +2.04 | 0.59 |
| top and bottom tenth, bottom flipped | in-sample (where the links were picked) | after the open | 34 | 2912 | +5.39 | 4.45 |
| top and bottom tenth, bottom flipped | out-of-sample | after the open | 34 | 270 | +1.37 | 0.37 |
| every link | in-sample (where the links were picked) | after the open | 167 | 14061 | -0.09 | -0.10 |
| every link | out-of-sample | after the open | 167 | 894 | +9.93 | 2.07 |
| every link | out-of-sample | opening gap | 167 | 894 | +10.28 | 3.01 |

The continuation group has no out-of-sample sessions: all 9 of its links are on markets that resolved before the out-of-sample window.

The row "every link, out-of-sample, after the open" (+9.93, t = 2.07) covers only the links that had enough in-sample sessions to be ranked. Checked after the run: on every out-of-sample link-day the slope is +0.81 (t = 0.46), S5 reported -0.63 (t = -0.37) for the same period, and without its two largest dates the row is -0.95 (t = -0.74). It is not a finding.

## C2, more strong links than chance?

| Statistic | Outcome | Links | Observed | Shuffle mean | Shuffle 95th percentile | Share of shuffles at or above |
|---|---|---|---|---|---|---|
| share of links with |t| >= 2 | after the open | 179 | 0.151 | 0.105 | 0.140 | 0.028 |
| mean |t| of the top tenth of links | after the open | 179 | 5.293 | 2.940 | 3.609 | 0.000 |
| share of links with t >= +2 (positive control) | opening gap | 179 | 0.341 | 0.052 | 0.084 | 0.000 |

The shuffle mean for |t| ≥ 2 is above 5% because a link's slope often rests on a few large odds moves; the shuffles reproduce that.

## C3, other definitions of the signal

| Definition of the odds move | Nights | Outcome | Link-days | Slope | t |
|---|---|---|---|---|---|
| points, previous close to 09:29 | all nights | opening gap | 17138 | +7.58 | 5.86 |
| points, previous close to 09:29 | all nights | after the open | 17143 | -0.47 | -0.59 |
| points, previous close to 09:29 | weekends and holidays | opening gap | 3799 | +6.79 | 5.55 |
| points, previous close to 09:29 | weekends and holidays | after the open | 3804 | +0.44 | 0.42 |
| log-odds, previous close to 09:29 | all nights | opening gap | 17138 | +98.17 | 5.81 |
| log-odds, previous close to 09:29 | all nights | after the open | 17143 | -4.11 | -0.39 |
| log-odds, previous close to 09:29 | weekends and holidays | opening gap | 3799 | +89.51 | 5.75 |
| log-odds, previous close to 09:29 | weekends and holidays | after the open | 3804 | +4.47 | 0.34 |
| points, previous close to 08:00 (early night) | all nights | opening gap | 17105 | +7.40 | 5.53 |
| points, previous close to 08:00 (early night) | all nights | after the open | 17110 | -0.29 | -0.35 |
| points, previous close to 08:00 (early night) | weekends and holidays | opening gap | 3802 | +6.55 | 5.19 |
| points, previous close to 08:00 (early night) | weekends and holidays | after the open | 3807 | +0.43 | 0.41 |
| points, 08:00 to 09:29 (late night) | all nights | opening gap | 17229 | +6.02 | 1.53 |
| points, 08:00 to 09:29 (late night) | all nights | after the open | 17289 | -1.51 | -1.06 |
| points, 08:00 to 09:29 (late night) | weekends and holidays | opening gap | 3828 | +7.32 | 2.55 |
| points, 08:00 to 09:29 (late night) | weekends and holidays | after the open | 3833 | -0.07 | -0.03 |

Slopes are in bp per point, except the log-odds rows (bp per unit of log-odds).

## Looked at after the run (not pre-registered)

- **Oil, where the link is strongest:** gap +11.83 bp per point (t = 5.44), after the open -1.11 (t = -0.84), 81 links. The link-level reversals on two Kharg Island questions do not add up to a theme.
- **Is the day simply more volatile after a big odds move?** Barely: the absolute move after the open is 1.27 times the ticker's usual on quiet nights and 1.35 times [1.21, 1.51] after an odds move of 10 points or more.

## Caveats

- One year of data; 51 out-of-sample sessions; many markets had resolved before them.
- This asks whether a better link *to these assets at the open* would have helped. It says nothing about markets the menu does not contain, or about trading somewhere the signal is not yet priced.

## Reproduce

```
cd research
python -m s14_link_ceiling.run
python -m s14_link_ceiling.report
python -m pytest s14_link_ceiling/tests -q
```
