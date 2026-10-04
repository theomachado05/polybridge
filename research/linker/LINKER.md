# The link agent

**Job.** Given a prediction-market question, say which listed instrument it moves, in which direction, how sure we
are, and which option contract carries that risk. Every study that compares odds with equities or options depends on
this step. It is the bottleneck: a wrong or missing link makes the test meaningless whatever the statistics.

Written 2026-10-03 night. Results are in `research/results/linker/`.

## Version 3 and the second held-out test (2026-10-03, 23:40 ET)

Plan, set, instructions, code and a hash manifest were committed before any label existed for these markets; the
labels were committed before this study pulled any price; the pooled test was added as a dated amendment between the
two (`linker/heldout2/PLAN.md`; its last note discloses that another study on the same machine had pulled odds for
some of these markets, which the linker never read). The set: 291 markets in 149 event clusters, from ranks 361 on, whose events no study
had used. It was scored once. Results: `results/linker/heldout2.json`, `heldout2_links.csv`, `pooled_heldout2.json`,
`option_evidence_heldout2.json`.

### 1. The mechanism holds across every link the agent named

Pooled over all 71 links (46 events, 8,078 link-nights), with instruments put on one scale: when the odds of the
linked signal rise by a point overnight, the instrument opens **0.026 daily standard deviations** in the stated
direction, **t = 3.3** (errors clustered by date).

| Pooled slope, per point of odds | Slope | t | Link-nights |
|---|---|---|---|
| All version-3 links | 0.026 | 3.3 | 8,078 |
| One observation per instrument and night | 0.028 | 3.1 | |
| Without the theme with the most confirmed links (the catch-all "Other": elections and country events) | 0.026 | 2.9 | 4,939 |
| The previous linker's links, same markets | 0.020 | 2.8 | 5,455 |
| Links the scorer trusts / the rest | 0.029 / 0.014 | 3.3 / 2.2 | 1,561 / 6,517 |
| Nights with a move of 5 points or more / other nights | 0.027 / 0.023 | 3.1 / 2.5 | 461 / 7,617 |
| Markets whose odds move often / seldom | 0.029 / 0.010 | 3.4 / 1.8 | 3,157 / 4,921 |
| Sessions from 2026-07-01 only | 0.009 | 0.9 | 2,070 |

**What an independent verification found** (five agents, each rebuilding the numbers with its own code; every
reported figure reproduced to the last digit; the checks below were chosen after the result, so they are post hoc):

- **The labels carry the information.** Flip each link's direction at random and the t reaches 3.3 in none of
  1,000 draws. Pair each signal with another link's instrument and the actual t beats 99.4% of 500 draws. The
  night before and the night after show nothing (t −0.9 and −0.9). Other ways of clustering the errors give t
  between 3.0 and 3.7.
- **A few nights carry most of the size.** Colombia's first round (2026-06-01, a 151-point move in the signal)
  is 45% of the evidence and Argentina's lower-house vote (2025-10-27) 27%. Without the Colombia night t is 2.05;
  without both nights the slope is 0.012 (t 2.3); on nights under 20 points it is 0.015 (t 2.4). Leaving out any
  one event, instrument or link keeps t at 2.1 or more. So the sign is robust; the 0.026 is an average pulled up
  by election and strike nights, and about 0.015 is the size on an ordinary night.
- **It is not one slope shared by all links.** If every link had the pooled slope, about 19 of the 62 testable
  links would confirm; 11 do. With no effect at all, about 3 would. A few links on election and war nights react
  strongly and most barely at all.
- **Not shown after the labellers' knowledge ends.** From 2026-07-01 the slope is 0.009 (t 0.9), and 0.001 with one
  observation per instrument and night. That period had enough data to show an unchanged slope (it would have
  given t 2.4). Ten of the eleven confirmed links are on markets that resolved before July. Against hindsight as
  the cause: the labellers' reasons argue from the mechanism, the share of links with the right sign is the same
  on remembered and other events (69% and 71%), and on the markets alive on both sides of the date the slope
  barely changes (0.015 before, 0.009 after, difference t −0.4). The honest reading: the link is real on resolution
  nights the models could have known, and unproven on data they could not.
- **Active against quiet odds is not settled.** The slope is three times larger where the odds move often (0.029
  against 0.010), but the difference has t 1.8. Both readings stay open: quiet links are right but short of data,
  or a move in a quiet market carries little.

### 2. One link at a time, the bar is not met

| On the fresh set | Links | Testable | Confirmed | Contradicted | Events with a confirmed link |
|---|---|---|---|---|---|
| Version 3, all links | 71 | 62 | 11 (18%) | 1 | 7 of 39 testable |
| Version 3, trusted links (score 0.5 or more) | 26 | 20 | 6 (30%) | 0 | 3 |
| The previous linker (control arm) | 58 | 42 | 5 (12%) | 0 | 5 of 34 testable |
| For reference, first held-out test, by event | 42 | 21 | 9 (43%) | 0 | |

- The bar was above 43% confirmed, 9 or more confirmed, none contradicted, scorer AUC 0.85 or more. Version 3 has
  11 confirmed, but 18%, one contradicted link (Bank of Japan against the yen ETF) and an AUC of 0.64. On the
  trusted links: 30%, 6 confirmed, none contradicted. **Not met on either reading.**
- The first test's 43% did not travel either: the previous linker scores 12% here. That figure rested on the Iran
  and oil ladders of larger markets. On this set version 3 finds more than the previous linker (11 links on 7
  events against 5 on 5), from the same markets.
- **The scorer did not travel.** AUC 0.64 for version 2, 0.63 for version 1, 0.61 on the odds alone, against 0.88 on
  the first held-out set. Adding the instrument's class, its earlier volatility, the mechanism and text features
  did not beat version 1 out of fold (0.852 against 0.851 on average), so version 2 is version 1's inputs refit on
  more links.
- Under the stricter verdict (30 days, at least 10 nights with a move of a point, HC3 errors): 3 of 57 for version
  3 and 3 of 36 for the previous linker. Several confirmations rest on a handful of nights.
- Hindsight checks: without the clusters a labeller flagged as remembered, 6 of 53; without the clusters the recall
  agent got right, 7 of 52. For links testable both before and after 2026-07-01, 44% keep the sign of their slope,
  and 1 of 32 links testable after that date is confirmed. The recall agent answered 66 of 304 questions and was
  right on 41 of the 44 that can be checked: the model remembers the events it chooses to answer.
- The two largest confirmations (Bancolombia t 6.0, Ecopetrol t 4.4) rest on the single Colombia night; with HC3
  errors they are t 1.4 and 1.0.
- Confirmed links: Colombia's first round against Bancolombia and Ecopetrol, Argentina's lower-house vote against
  ARGT, Galicia and YPF, the Israel-Iran ceasefire against USO, Greece-Turkey against TUR and GREK, Macron against
  EWQ, China-Taiwan against FXI, MicroStrategy's index status against MSTR.
- 64 clusters got "no listed instrument" from both labellers; the previous linker linked one of them, unproven.
- Price-proxy links (questions settled by a traded price), kept apart: 15 links, 9 testable, 3 confirmed.

### 3. Options

- One link at a time (`linker/option_evidence.py`, monthly at-the-money contracts): of 31 testable links, the
  directional leg confirmed on 4 and contradicted on 3; the straddle confirmed on 3 and contradicted on 2. Where
  the equity link is confirmed the option never contradicts it (2 confirmed, 2 unproven); the 3 contradictions
  are all on links the equity did not confirm.
- Pooled over 3,353 link-nights on 52 links: the directional leg gains 42 bp per point of odds in its favour,
  **t = 1.95**, just under the line; the straddle's reaction to the size of the move, t = 1.1. By the rule fixed in
  advance, the option is not shown to carry the mechanism on this set.
- Every trusted link of an open question has a listed contract except one (EIS has no listed options).

### 4. Brazil

The event's largest market by volume is a long shot ("Will Renan Santos win", $16.2 million against $14.2 million
for Flávio Bolsonaro), so "take the largest market" picks the wrong one. With no hint, both labellers built one
signal over the candidates by camp (Flávio Bolsonaro and Tarcísio de Freitas up, Lula and Haddad down) and agreed
on EWZ, Itaú and Petrobras, all up. On that signal Itaú is confirmed (t 2.1); EWZ (t 1.5) and Petrobras (t 0.9)
are not.

### What changed in the linker, and why

| Change | Why |
|---|---|
| Markets are grouped into event clusters by code (`linker/events.py`); a ladder is one cluster with one rung | Rungs of one ladder were counted as separate links and decayed with the calendar |
| For a multi-outcome event the labellers give signed weights by camp; the code builds one signal from the weights both agree on (`linker/signal.py`) | The sign of one outcome depends on which other outcome loses; and the largest market can be a long shot (Brazil) |
| The two labellers are lined up on a common question before comparing; a link needs the same ticker and direction, a common signal carrying two thirds of each one's weight, and a confidence of 0.3 from both | Opposite sign conventions lost true links; all four contradicted links of the development run had a confidence of 0.2 or less |
| 204 instruments in 31 classes instead of 132, off-list tickers allowed when Massive lists them, and "no listed instrument" as a full answer (`linker/instruments.json`) | Country ETFs and ADRs for foreign elections, currencies and short rates for central banks; a weak link is worse than none |
| Labellers see scheduled deadlines, never closing times; they flag what they remember; a separate agent is asked how each question resolved | A closing time before the deadline gives the resolution away |
| A pooled test next to the per-link verdicts (`linker/pooled.py`) | A link needs 30 days and a t of 2 on its own; most markets in this range are too short or too quiet for that |
| The plan, the code and the scorer are hashed before labelling, and the evaluator refuses to run if one changes (`linker/freeze.py`) | So that nothing can be tuned after the labels or the prices are seen |

### The link map the backend can serve

`python -m linker.link_map2` writes `results/linker/link_map_v2.json` and a copy at `backend/app/data/link_map.json`,
in the shape of `ai_map.json`: 184 links on 76 open questions, **40 trusted on 20 questions, 32 of them confirmed by
prices, 39 with a listed option contract**, and 17 questions answered "no listed instrument".
`backend/app/link_map.py` loads it. The product still serves `ai_map.json`; setting `POLYBRIDGE_LINK_MAP=1` serves the
link map instead.

## The pipeline (versions 1 and 2)

| Stage | What it does | Where |
|---|---|---|
| 0. Universe | Picks the questions: by total volume and length of life, the main market of each event first | `s5_big_moves/universe.py` |
| 1. Proposer | A model reads the question and names tickers with a direction | `backend/app/data/ai_map.json` (the original, text only) |
| 2. Blind second opinion | A second model does the same without seeing the first. A link needs both | `s4_linked_assets/critic_*.json`, `s5_big_moves/labels_*.json` |
| 3. Link scorer | A trained model predicts, before any equity price is used, whether the link will hold | `linker/scorer.py`, `results/linker/scorer.json` |
| 4. Data gate | The equity and the odds must have moved together on earlier days only. Gives the measured sensitivity | `s4_linked_assets/engine.py` (`gate`) |
| 5. Option resolver | Turns a trusted link into a contract: first expiry on or after the resolution day, strike at the money | `linker/options.py` |

## The benchmark (what "correct" means)

`linker/benchmark.py` scores every link tested so far against prices. A link is **confirmed** if the instrument's
excess opening gap rises with the direction-signed overnight move in odds with t ≥ 2, **contradicted** if t ≤ −2,
**unproven** in between, **untestable** with under 30 days of data (or when the ticker is SPY, whose excess over SPY
is zero by construction).

| Linker | Links | Testable | Confirmed | Contradicted | Right sign |
|---|---|---|---|---|---|
| Original text map only (the critic did not name the ticker), S4 | 187 | 69 | 38% | 5 | 75% |
| Two models agree, S4 | 196 | 46 | 50% | 4 | 78% |
| Two models agree, S5 (240 largest markets of the year) | 220 | 164 | 37% | 6 | 76% |

By theme the spread is wide: Iran and oil 88% confirmed (45 of 51), Bitcoin-linked 57%, Russia–Ukraine 25%, Fed chair
18%, Fed rate decisions 13%, China and Taiwan 12%, US politics 0%.

## The scorer (the trained part)

A logistic regression on what is known before any equity price is looked at: the labellers' confidence, whether two
models agreed, how many links the question has, and how alive the odds are (mean overnight move, share of nights with
a move of a point or more, share of time between 10% and 90%). Trained on 279 testable links, 110 confirmed.

| Validation (no link is scored by a model that saw its market) | Links | Base rate | AUC | Confirmed in the top third |
|---|---|---|---|---|
| By market, 5 folds | 279 | 39% | 0.88 | 75% |
| Train on S5, test on S4 | 115 | 43% | 0.73 | 58% |
| Train on S4, test on S5 | 164 | 37% | 0.90 | 78% |
| Leave one theme out | 279 | 39% | 0.86 | 71% |

By score quarter (out-of-fold): lowest 1% confirmed and 11% contradicted; highest **87% confirmed and none
contradicted**. A plain rule (two models agree, odds between 10% and 90% at least half the time, a move of a point
or more on at least 30% of nights) keeps 109 links at 64% confirmed.

**What it learned.** The strongest signal is how alive the odds are, then the labellers' confidence. Read this with
care: a link with active odds is also easier to confirm statistically, so the scorer finds links that are both true
and testable. That is what a trade needs, but it is not proof that quiet links are false.

## Held-out test (120 markets no study had used)

Plan committed before any label or price existed: `linker/heldout/PLAN.md`. Results: `results/linker/heldout.json`,
`heldout_links.csv`.

| | Links | Questions linked | Testable | Confirmed | Contradicted | Right sign |
|---|---|---|---|---|---|---|
| Arm A, by question (the current linker) | 101 | 53 | 55 | 13 (24%) | 4 | 71% |
| Arm B, by event (the revised linker) | 42 | 24 | 21 | 9 (43%) | 0 | 86% |

- **Linking by event is more precise and less broad.** It names fewer than half as many links, loses
  4 confirmed ones, and drops every contradicted one. By the rule fixed in the plan
  (higher confirmed share and no more contradicted links) arm B is the better linker. The counts are small
  (9 of 21 against 13 of 55), so this is a direction, not a proof.
- **The scorer holds up on unseen markets.** Trained on S4 and S5 only: AUC 0.88 on 55 held-out
  links; 50% confirmed in its top third against a base rate of 24%,
  and 0% in its bottom third.
- **The confirmed links are again almost all one theme:** Iran and oil (USO, XLE, JETS). Tariffs, AI-model and
  Bitcoin-reserve links stayed unproven.

## The live link map

`python -m linker.link_map` writes `results/linker/link_map.csv` and `link_map.json`: every link on a question that is
still open, with its score, what the prices say, its measured sensitivity and its option contract. As of 2026-10-02:
130 links on 51 open questions, of which **26 are trusted**
(13 questions). 9 of the trusted links are on events
(6 questions: the Clarity Act, Hormuz, a US invasion of Iran, the best AI model, Fed cuts
in 2026); the other 17 are price proxies (Bitcoin and Ethereum thresholds). Every trusted
link has a listed option contract.

## What breaks a link (found in the data)

1. **The wrong market of the event.** The original map tied EWZ to five-week-old side markets ("finishes second in
   the first round") and missed the main one, "Will Flávio Bolsonaro win the 2026 election?" (a year of history,
   $14 million). On the main market: EWZ +7.1 bp per point (t = 1.4), Petrobras +12.2 (t = 1.9), Itaú +10.8
   (t = 2.0). Rule: link the highest-volume, longest-lived market of each event.
2. **An instrument that is too quiet.** Fed-meeting questions are tied to Treasury ETFs that move a fraction of a bp
   per point of odds: 13% confirmed. Tying a meeting's questions into one expected-rate number
   (`linker/composite.py`) removes the contradicted links (0 of 18 against 3 of 61) but does not raise confirmation
   (3 of 18). The instrument is the problem, not the sign: a meeting's odds belong with rate futures, which this
   data set does not have.
3. **Odds that do not move.** Tail outcomes ("hike by 50+") and remote events ("China invades Taiwan") sit near 0 and
   give no signal. The scorer handles this.
4. **Deadline ladders.** "By April 30", "by May 31", "by June 30" are one event; each decays with the calendar. Link
   the event once, through its furthest live deadline.
5. **A sign that depends on the alternative.** "Cut by 25 bps" is dovish against a hold and hawkish against a bigger
   cut. Link the event's expected value, not one outcome.
6. **Cause running the other way.** "MicroStrategy sells Bitcoin" moves because Bitcoin's price moves. It is a price
   proxy, not an event.
7. **The hedge instrument as the target.** A link to SPY, measured in excess of SPY, is empty.
8. **Hindsight.** For resolved questions a model may remember the reaction (Warsh and gold). Score those links only on
   dates after the model's knowledge ends.

## Question to option

`linker/options.py` resolves a trusted link to listed contracts (`results/linker/option_examples.csv`), as of
Friday 2026-10-02:

| Question | Link | Contract |
|---|---|---|
| Flávio Bolsonaro wins (first round Sun 2026-10-04) | EWZ up | `O:EWZ261009C00038000`; straddle with `O:EWZ261009P00038000` |
| Brazil runoff (Sun 2026-10-25) | EWZ up | `O:EWZ261030C00038000`; straddle with the 38 put |
| Hormuz traffic normal by December 31 | USO down | `O:USO270115P00147000` |
| US invades Iran before 2027 | XLE up | `O:XLE261231C00065000` |
| Fed hikes 25 bps in October (decision 2026-10-28) | TLT down | `O:TLT261030P00077000` |

No option has been priced or back-tested yet. This stage only says which contract a question maps to.

## How to train it further

What the second test says to do next, in order:
1. **Score the open links again on dates no model has seen.** 35 version-3 links sit on markets still open; every
   session from now adds data the labellers cannot know. The pooled test of `linker/pooled.py` on those sessions is
   the clean test of the mechanism. The plan for it must be committed before the first new session is read.
2. **Stop judging links one at a time.** A link needs 30 days and a t of 2 on its own, and most markets below the
   largest 360 are too short or too quiet for that: 18% confirm against 12% for the previous linker, and the scorer
   cannot tell which (AUC 0.64). Pool links by instrument class and mechanism, and trust a class, not a link.
3. **The scorer needs inputs that travel.** How alive the odds are separated links on the Iran ladders and not here.
   Train on the pooled slope of a class, with the second held-out set added, and test on the next one.
4. **Options need better prices.** Daily bars give the first and last trade, hours from the open and the close.
   With quotes at 09:30 and 16:00 the directional test (t 1.95 here) can be settled either way.

## What this does not show

A confirmed link means the instrument reacts to the odds. It does not mean there is a trade: on the best-linked theme
(Iran and oil, 88% confirmed) the equity is fully repriced by the open and every trade tested lost money after costs
(`research/results/s5_big_moves/SUMMARY.md`).
