# The link agent

**Job.** Given a prediction-market question, say which listed instrument it moves, in which direction, how sure we
are, and which option contract carries that risk. Every study that compares odds with equities or options depends on
this step. It is the bottleneck: a wrong or missing link makes the test meaningless whatever the statistics.

Written 2026-10-03 night. Results are in `research/results/linker/`.

## The pipeline

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

The loop is: change one stage, re-run `python -m linker.benchmark` and `python -m linker.scorer`, compare the
confirmed share and the AUC on markets the change did not see. Next changes, in order of expected gain:
1. A proposer prompt that works by event (main market, ladders collapsed, expected value for multi-outcome events),
   tested on the next 240 markets by volume against the current two-labeller links.
2. Instruments beyond US ETFs where the ETF is too quiet (rate futures for the Fed, the local index for elections).
3. The option stage scored the same way: does the option-implied move line up with the odds-implied move?

## What this does not show

A confirmed link means the instrument reacts to the odds. It does not mean there is a trade: on the best-linked theme
(Iran and oil, 88% confirmed) the equity is fully repriced by the open and every trade tested lost money after costs
(`research/results/s5_big_moves/SUMMARY.md`).
