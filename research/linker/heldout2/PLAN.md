# Second held-out test of the link agent (written before any label or price exists for these markets)

Written 2026-10-03, on branch `r/link-agent`. Amendments are dated and appended at the end; nothing above them is
rewritten after the commit that holds this file.

## 0. What was known before this commit

- Everything in `linker/LINKER.md`: the benchmark (about 40% of testable links confirmed; Iran and oil 88%, Fed rate
  decisions 13%, US politics 0%), the scorer (AUC 0.88 by market and 0.88 on the first held-out set), and the first
  held-out test (by event: 9 of 21 testable links confirmed, none contradicted; by question: 13 of 55, 4 contradicted).
- **The development run** (`linker/dev/`, `results/linker/dev_v3.json`): the new linker and the rebuilt control
  instructions run on the first held-out set, whose prices were already known. It was used to debug the code and
  the instructions, it is committed with this plan, and its figures are never compared with the bar below. What it
  showed, and what was decided from it:
  - Before any floor, version 3 named 88 event links on 44 clusters: 62 testable, 17 confirmed (27%), 4
    contradicted. The rebuilt control: 30 links, 17 testable, 6 confirmed, 1 contradicted. The first test's
    original by-event arm: 42, 21, 9, 0. So version 3 finds more (11 clusters with a confirmed link against 6) and
    is less precise on all its links.
  - All four contradicted links had a confidence of 0.2 or less from one labeller. Hence the **confidence floor**
    of section 2.3 (0.3 from both). With it: 66 links, 46 testable, 17 confirmed (37%), none contradicted. The
    floor was chosen on this run, so that figure flatters it.
  - The links the scorer puts at 0.5 or more: 16 testable, 11 confirmed (69%), none contradicted. Hence the
    **trusted-links bar** of section 5. Version 2 of the scorer was trained on links of these same markets, so
    this is partly in sample; version 1, which never saw them, gives 11 of 17 (65%) with the floor.
  - Two of the four contradictions came from a market whose odds moved a point on 3 nights. The robust verdict of
    section 4 exists for that case.
  - Options, on the 46 testable links: the directional leg confirmed on 5 of 22 testable and contradicted on none;
    the straddle confirmed on none of 22.
- **The names in the fresh set.** No label and no price of theirs. The set was built by code
  (`linker/events.py`). Its reviewers read the questions to check the grouping. The author of this plan had seen,
  before fixing the instrument list and the instructions: the tag counts of ranks 361 onward (Iran, Israel, Fed
  rates, crypto, AI and elections lead), five event names (best AI model at the end of March and of April, the next
  Israeli prime minister, the largest company at the end of January, SpaceX's market value at its listing), one
  question (a Russian parliamentary election), and the counts printed by the set builder.
- **The instrument list** (`linker/instruments.json`) was fixed before the fresh set was built. After that, tickers
  were only dropped where Massive does not serve them.
- A plan review by three independent critics. Their findings changed this plan before it was committed.
- From four benchmark links used to debug the options code: with weekly expiries the option legs of USO and XLE
  traded on about 40% of nights, with monthly expiries on 80% to 90%.

## 1. The set

From `s5_big_moves/candidates.json` (892 markets that pass S5's universe rule, by volume): ranks 361 to 892, less
every market whose Polymarket event already had a market in ranks 1 to 360 (S5 and the first held-out test), less
every market of an event that holds a market of the product's map (`backend/app/data/ai_map.json`, S4). What is left
is `linker/heldout2/universe.json`: the counts are in that file.

For every event the list of its markets is read from Polymarket. Only the id, question, volume, start date,
scheduled end date, closing time, closed flag and token are kept; every price field is dropped when the answer is
parsed. Events are merged into **clusters**: questions that differ only by a deadline or a threshold are one cluster
even when Polymarket lists them as separate events; a question about a window ("in 2025", "on March 31") is not
merged with the next window. The labellers see the scheduled end date only (the event's scheduled end date where
a market has none of its own), never the closing time, which would give away an early resolution.

A cluster is flagged `seen_ladder` when one of its questions, with dates, numbers and month names removed, matches a
question of S4, S5 or the first held-out test: another rung of a ladder already studied.

## 2. The linker under test (version 3, by event)

1. **Grouping (code, names only).** `linker/events.py`: clusters, their structure, and the main market of each
   cluster, chosen among markets with at least 20 trading sessions of life in the window (all of them if none has):
   for a ladder the rung with the latest deadline (the one written in the question, else the scheduled one) among
   rungs with at least 25% of the largest rung's volume; otherwise the largest volume, then the longest life.
2. **A proposer and a blind second labeller** read the clusters and the instrument list with the instructions in
   `linker/prompts/labeller_v3.md`. For each cluster: event, price proxy or nothing; the signal (the main question
   for a binary or a ladder; signed weights over the outcomes of a multi-outcome event, on one axis that does not
   depend on any instrument, chosen by the labeller whatever the volume flag says); the alternative; up to 4 instruments with direction, confidence, size and mechanism;
   or "no listed instrument". Each reads only its input file. Each runs once per input file. A rerun is allowed
   only when the output is not valid JSON or answers fewer than all clusters; every attempt is kept.
3. **Agreement (code).** `linker/signal.py`.
   - An answer that breaks a hard rule of the instructions is discarded: its cluster gets no link. So is an answer
     given out of the input's order, and every answer of a cluster that a labeller answered twice. No answer is
     edited by hand.
   - Each labeller's weights are turned so that the highest-volume question with a non-zero weight in both signals
     is positive (weights, link directions and the market-wide direction flip together). If there is no such
     question there is no common signal.
   - The common signal is the set of questions both gave a weight of the same sign, each with the mean of the two
     weights, scaled so the largest is 1. It is valid only if it carries at least two thirds of each labeller's
     total absolute weight.
   - A **link** is a (cluster, ticker, direction) both labellers named, on a cluster both called an event, with a
     valid common signal, **each with a confidence of 0.3 or more**. SPY is never a link. A ticker off the list
     counts when both named the same symbol and Massive serves it as a common stock, an ADR or an exchange-traded
     fund or product, on an exchange, listed for at least three years; the ones kept are listed in the results so
     their names can be checked by eye.
   - Clusters both called a price proxy give **price-proxy links** by the same rule. They are scored and reported
     outside every table below.
4. **Scorer, version 2.** `linker/scorer2.py`, trained on the S4 and S5 benchmark links and the first held-out
   test's links only, frozen in `results/linker/scorer_v2.json` and committed with this plan, before any labeller
   runs on the fresh set. Its features and their exact definitions are in that file and in `linker/features.py`:
   the labellers' confidence, how alive the odds are, the instrument's class and its volatility before 2025-10-01,
   and fixed keyword features of the question. It uses the odds and the instrument's earlier volatility; it never
   uses the link's own equity-against-odds data. No feature is used that some training or test rows lack.
5. **Option contract.** `linker/options.py`, unchanged: first listed expiry on or after the resolution day, strike at
   the money, a call for up and a put for down.

## 3. The control arm

The previous linker on the same markets: two blind labellers, questions grouped by Polymarket event, S5's ticker
list, the instructions in `linker/prompts/labeller_control.md`. A link is a (question, ticker, direction) both named
on a question both called an event; a question answered twice is dropped and a link with no valid ticker or
direction is skipped. It answers one question: is this set easier or harder than the first one?

The control is a reconstruction: the first test's exact wording was not kept. It was run once on the first held-out
set in the development run and is reported next to the original (9 of 21 confirmed, none contradicted); its
instructions are frozen whatever that showed. The two arms differ in grouping, signal, instrument list and
instructions together, so a gap between them is the gap between two whole linkers, not the effect of one change.
Version 3 is also reported on S5's ticker list alone.

## 4. Scoring

As `linker/benchmark.py`. For each link: the through-origin slope of the instrument's excess opening gap (in excess
of beta × SPY) on the overnight, direction-signed move of the signal in points, errors clustered by date. Window
2025-10-01 to 2026-10-02.

- The signal of a weighted cluster is 100 × the sum of weight × probability. Its main leg (the largest weight, then
  the largest volume) must have a price at most 30 minutes old, or the signal has no value at that minute; every
  other leg is carried at its last price, and counts as 0 before its first price. How alive the odds are (a scorer
  input) is read from the main leg's own odds.
- **confirmed** t ≥ 2; **contradicted** t ≤ −2; **unproven** in between; **untestable** under 30 days with both
  prices.
- **Robust verdict**, reported next to it for both arms and for the first test's by-event links re-scored the same
  way: testable only with 30 days and at least 10 nights on which the signal moved a point or more; t from HC3
  standard errors.

## 5. The bar and what is reported

**The brief's bar**, fixed before this plan, on all version-3 event links (the confidence floor applied):

| Measure | Bar (from the first held-out test, by event) |
|---|---|
| Confirmed share of testable links | above 9 of 21 (42.9%) |
| Confirmed links | 9 or more |
| Contradicted links | 0 |
| Scorer version 2, AUC on version-3 testable links (confirmed against not) | 0.85 or more |

All four hold: the linker meets the brief's bar. Fewer than 20 testable version-3 links: the test is inconclusive.

**The same bar on the trusted links.** The agent's answer to "how far to trust it" is the scorer: a link is
**trusted** when version 2 scores it 0.5 or more, the threshold `linker/LINKER.md` already used. The score is
computed from the labels and the odds, before the link's equity is compared with them. On the trusted links alone:
confirmed share above 9 of 21, 9 or more confirmed, none contradicted. This bar was added after the development run
showed that all links together are less precise than the first test's; both bars are reported whatever they show,
and neither replaces the other.

**How much the bar can tell.** The first test's 43% came from 21 links on other markets. Links that are right can
still come out contradicted by chance: 6 of 164 in S5. With 30 testable links that alone fails "no contradicted
link" about two times in three, and a linker as good as the first one clears 43% about half the time. So next to
the bar, whatever it shows:

- **Against the control arm on the same markets**: confirmed share, confirmed and contradicted counts of each arm;
  and paired by cluster (for every cluster with a testable link in either arm: any confirmed link, any contradicted
  link, in each arm).
- **Without `seen_ladder` clusters**: the same four measures.
- **By cluster**: clusters linked, testable, with at least one confirmed link (links on one cluster are not
  independent), and the same without the theme that has the most confirmed links.
- The contradicted share with a 95% interval; the right-sign share; the median t; by theme.
- The robust verdicts of section 4.
- **Hindsight**, section 9.
- **The scorer**: version 1 (frozen, `results/linker/scorer.json`), version 2 and an odds-only model (the three
  odds features and the day count, same training rows) on the same links; AUC on control links alone and on both
  arms pooled as the first test did; confirmed share in the top and bottom third; and the links scoring 0.5 or more
  ("trusted before any equity-against-odds test").
- "No listed instrument" answers: how many clusters, and what the control arm did on the same markets.
- Market-wide answers both labellers gave with the same direction, scored on SPY's raw opening gap, outside every
  table above.
- The Brazil check (section 6) and the options evidence (section 7).

## 6. The Brazil check

The Brazilian election event is added to one input file, read by both labellers, like any other cluster and with no
mark. It counts in no figure: its prices were studied in `linker/brazil.py`, and the instructions' election rule
came from it. So it is a regression check, not evidence. The grouping code flags the largest market by volume, which
here is a long shot ("Will Renan Santos win"), so the labellers have to find the market that carries the event
themselves. The check passes if the common signal of the two labellers gives a non-zero weight to "Will Flávio
Bolsonaro win the 2026 Brazilian presidential election?" and they agree on a Brazilian instrument.

## 7. Options evidence (secondary)

For every testable version-3 link, whatever its equity verdict: does the listed option react?
`linker/option_evidence.py`, rules fixed here. For each calendar month of the link's life: the call and the put
struck nearest the instrument's last close of the previous month (as it traded then, later splits undone), in the
first standard monthly expiry (third Friday) at least 30 days after the month begins, among contracts already listed
before the month. Nothing dated inside the month chooses the contract. Daily bars from Massive. Two slopes, errors
clustered by date, on days when both legs traded on that day and the session before:

- direction: the overnight return of the directional leg (a call on an up link, a put on a down link; previous close
  to open) on the overnight move in the signal, through the origin. A rise in the signal should lift the leg, so a
  positive slope is the link holding for both kinds of leg. The same fit with an intercept is reported next to it.
- size: the overnight return of the straddle (call plus put) on the absolute overnight move in the signal, fitted
  with an intercept, because a straddle loses value most nights whatever the odds do.

Same thresholds (t ≥ 2 confirmed, t ≤ −2 contradicted, under 30 days untestable). Reported split by the equity
verdict. No position is sized, no cost is charged and no profit is computed.

What it can and cannot show. An option moves with its underlying, so where the equity link is confirmed a confirmed
directional leg mostly says the listed contract trades enough to carry it; it is not independent evidence. The
size test is the one with content of its own. A thin contract's daily open and close are its first and last trades,
which can be hours from 09:30 and 16:00.

## 8. Order of work

0. The development run on the first held-out set is finished and committed.
1. **One commit** holds this plan, the set (`universe.json`), the labellers' input files, both instructions, the
   instrument list, all the code (`events.py`, `signal.py`, `study.py`, `features.py`, `scorer2.py` with its frozen
   weights, `option_evidence.py`), their tests, and `linker/heldout2/FROZEN.json`: the sha256 of each of those files.
2. The labellers run on the fresh set. Their answers are committed with nothing else.
3. Prices are pulled once and the evaluation runs once. `study.py` refuses to score the fresh set if a frozen
   file's hash has changed, unless the change is listed in an amendment below with its reason.
4. After step 1 the code changes only for a crash or a failing test. Each such change is a dated amendment that
   says what changed and whether it can change a link count.

## 9. Hindsight

Most of these markets have resolved and the labelling models' knowledge runs to about June 2026. Three checks:

- The instructions forbid using remembered resolutions and price reactions, ask for a `remembered` flag in both
  arms, and tell the labellers not to judge whether an outcome was likely. Figures are repeated without flagged
  clusters.
- **Sessions from 2026-07-01**, which no labeller can have seen: for links testable both before and after that day
  (30 days in each), the slope and t in each period and the share with the same sign in both. About 65 sessions
  fall after the day, so few links will qualify and fewer will reach t ≥ 2 there; the comparison is of slopes, not
  of confirmed shares.
- **A recall run**: a separate agent, given only the questions (every test market and every cluster's main market,
  in two files, with the instructions of `linker/prompts/recall.md`), is asked how each resolved. After the pull,
  a market counts as resolved yes if it is closed and its last price is 0.9 or more, no if 0.1 or less. A cluster
  whose main market the agent got right is flagged as recalled, and the version-3 table is repeated without
  recalled clusters. A question answered twice counts for nothing.

## Amendments

**Amendment 1, 2026-10-03 23:27 ET (2026-10-04 03:27 UTC). After the labels were committed (05e04ec), before any
price of the fresh set was pulled: a pooled test of the mechanism.** The tables of section 5 count links one at a
time, and a link needs 30 days of its own to count. That drops the short-lived markets and does not say why a link
fails. So one more test, on the mechanism and not on single links: `linker/pooled.py`, new, with
`linker/tests/test_pooled.py`. Its rules, fixed here:

- **Population.** Every version-3 event link (floor applied, the Brazil cluster left out), including links with
  under 30 days. Each link-day is one observation: x is the direction-signed overnight move of the link's signal in
  points; y is the instrument's excess opening gap divided by the instrument's daily volatility before 2025-10-01,
  so that instruments of different volatility are on one scale. Links whose instrument has no such figure are left
  out and counted.
- **The test.** One through-origin slope of y on x over all link-days, errors clustered by date. **The mechanism
  holds if the slope is above zero with t ≥ 2.** Reported with the number of link-days, links, clusters and dates,
  and again with one observation per instrument and date (the mean x over that instrument's links that night),
  because one instrument can sit on several links.
- **Reported whatever it shows:** the same slope without the theme that has the most confirmed links; by instrument
  class; by the labellers' mechanism class; for trusted links and for the rest; on nights when the signal moved 5
  points or more and on the other nights; on sessions from 2026-07-01; and for the control arm.
- **Why links fail: active odds against quiet odds.** Links are split at the median of the share of nights on which
  their signal moved a point or more. If the slope per point is about the same in both halves, the unconfirmed
  links are right but short of data. If it is near zero in the quiet half, a move in a quiet market carries no
  information. Reported: both slopes, their t, and the t of their difference.
- **Options, pooled.** Over every link-day of section 7 on which both legs traded, for every version-3 link with
  any such day: the directional leg's overnight return on the overnight move in the signal, through the origin; and
  the straddle's overnight return on the absolute move, with an intercept. Errors clustered by date. The option
  carries the mechanism if the first slope is above zero with t ≥ 2; the size of the move is priced if the second is.
- The code is written after this amendment and checked on the development run only; the development figures are not
  evidence. Nothing in sections 1 to 9 changes: this test adds no link and removes none.

**Note, 2026-10-03 23:25 ET.** The heading of amendment 1 gives 23:27 ET; its commit (dd7e1a5) is stamped 23:24 ET.
The commit time is the right one.

**Note, 2026-10-03 23:37 ET, while the pull was running and before any price of the fresh set was read: two
readings fixed in `linker/pooled.py` (with `test_pooled.py`).** (1) The pooled options test covers the links of
section 7, that is the version-3 links that are testable on the equity side, with no minimum on their own number
of option days. Amendment 1's words ("every version-3 link with any such day") are wider; the narrower reading is
the one the frozen options code can pull for, and it is the one that runs. (2) Ties at the median of the
active-against-quiet split go to the quiet half. The code was checked on the development run only, where the pooled
slope was 0.034 daily standard deviations per point (t 4.7) and the options directional slope had t 6.1; those are
development figures, not evidence.

**Note, 2026-10-03 23:49 ET, after the result (commit e476728) and its verification by five independent agents. No figure is
changed; the run is not repeated.** Disclosures and two figures the plan promised that the results files lack:

- **Odds of some of these markets were on this machine before the labels**, pulled by another study (S11, in the
  main checkout, another session) for 93 of the 291 test markets. Eight of them are legs of version-3 links and
  were pulled before the labels commit, one of them before the plan commit; they touch four of the eleven confirmed
  links (EWQ, USO, GREK, TUR). The linker's code reads only its own cache and those of S4 and S5, the labellers read
  only their input files, and this session never opened that cache. The first line of this plan ("before any price
  exists") is true of this study's pulls, not of the machine.
- `linker/pooled.py` was finished at 23:35, while the odds were being pulled (249 of 290 files on disk) and before
  any equity of a new ticker was pulled; nothing was scored before 23:38.
- The plan and the code are in two commits of the same second (5ce5b2c, 748fe0c), not one; the manifest covers
  both. The labellers were started right after the second.
- The control arm's 58 links include one link to SPY, which is never scored.
- **Robust verdict of the first test's by-event links** (section 4): 42 links, 19 testable, 6 confirmed, none
  contradicted.
- **Options evidence split by the equity verdict** (section 7), directional leg: on equity-confirmed links 2
  confirmed, 2 unproven, none contradicted; on equity-unproven links 2 confirmed, 22 unproven, 3 contradicted.
- The verification reproduced every reported figure from its own code and found the pre-registration intact. Its
  checks on the pooled result are post hoc and are reported as such in `linker/LINKER.md`.
