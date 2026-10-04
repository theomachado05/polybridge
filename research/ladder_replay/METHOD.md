# Ladder replay: does the S11 ladder-violation trade survive simultaneous taker fills?

Pre-registered Sun 2026-10-04, about 02:05 New York time, before any new data pull or computation by this study. Every
number is fixed in [`config.py`](config.py). Changes after this commit go under "Amendments", dated.

## 0. What is already known (seen)

S11 (`research/s11_bundles/`, results in `research/results/s11_bundles/`) found that when a date or strike ladder is out
of order, selling the rich rung and buying the cheap rung earned +3.89 points per trade [+2.49, +5.43] on 99
print-verified trades (98 monotone pairs, 1 one-of-many set), +3.24 on 11 out-of-sample trades, about $385 a year.
S11's prices were one-minute mids moved by a half-spread; its print check asked only for a print on each leg within 10
minutes, so it never proved both legs could be filled together. Those results have been seen; step 2 below re-runs the
same pairs and is labelled a **mechanics check on seen data**, never evidence. Step 3 is the confirmatory test.

## 1. Settlement-rule verification (every pair used)

For every pair of steps 2 and 3, the market records are read from gamma (`description`, `resolutionSource`, the
event's `resolutionSource`). Frozen rule (`config.py`): a pair is **nested** when the two descriptions are identical
after lower-casing, collapsing whitespace and replacing each rung's own key (its date, or its level) in all its
spellings by a placeholder, and the resolution sources are identical. Anything else (a different window start, cutoff
hour, timezone, source, or any wording difference) is **not nested**: excluded from the replay and counted. A random
sample of 20 classified pairs (seed in `config.py`) is read by hand against the full texts and the hand verdict is listed
next to the rule's in `manual_check.md`, with the disagreement count.

## 2. Causal replay on S11's pairs (mechanics check, seen data)

Pairs: every monotone pair (date and strike ladders) in `s11_bundles/bundles.json`, nested by step 1.

- **Prints.** `data-api.polymarket.com/trades` (taker prints only, its default), the latest 20,000 prints of each market
  (two pages of 10,000), as S11. A print on the NO token is turned into YES terms: a taker buying NO at q is a YES sale
  available at 1 − q; a taker selling NO at q is a YES purchase available at 1 − q. Reachable history per market is
  reported (the oldest print served against the market's start).
- **Walk forward in time.** Prints of both legs are merged in time order. At each print, the only information used is
  the prints up to and including it. A **YES-sale print** on the rich leg A at price a (a taker sold YES at a) and a
  **YES-purchase print** on the cheap leg B at price b (a taker bought YES at b), the two within 60 seconds of each other,
  open a trade at the later print's time when
  `(a − tick_A − fee_A(a − tick_A)) − (b + tick_B + fee_B(b + tick_B)) > 0`.
  When several prints of the other leg qualify in the window, the one with the largest edge is used.
- **Fills.** Sell A (buy NO on A) at a − one tick; buy B at b + one tick; tick = each market's `orderPriceMinTickSize`
  (0.01 when missing). Fee per contract = `rate × (p(1 − p))^exponent` at the fill price, from each market's
  `feeSchedule` (0 when fees are off), taker, both legs. Size = min(print size A, print size B, 100 contracts).
- **Limits.** Entries only between 2025-10-01 and 2026-10-03 (New York dates) and before either market closes. A pair
  is entered again only 3,600 s after its last entry. At most 10 new trades per New York day, first come first served.
- **Hold to resolution.** Capital per contract = (1 − fill_A) + fill_B + both fees, locked from entry until the later of
  the two markets' close times (the cheap, later rung for a date ladder). Payoff per contract = (1 − result_A) + result_B
  with results read from gamma after the replay (1 = YES, 0 = NO, a 50-50 split counts as 0.5). A trade whose legs are not
  both resolved is valued at its guaranteed floor (payoff 1, true for a nested pair) and counted apart; its lock ends
  at the cheap rung's `endDate`.
- **Reported** (all trades, date ladders alone, and S11's in-sample / out-of-sample split at 2026-07-22): trades,
  pairs, dates; net P&L per trade in points per contract (mean, trade-weighted), its date-clustered 95% bootstrap
  interval (2,000 draws, New York entry dates, ratio of sums as S11); total $; capital-weighted return (Σ P&L / Σ
  capital); annualized return on locked capital (Σ P&L / Σ capital × lock days / 365, lock at least 1 day); Sharpe of
  resolution-month returns (month return = Σ P&L / Σ capital of trades resolving that month, every month from the first
  to the last counts, an empty month is 0; mean / sd × √12); maximum drawdown of cumulative P&L booked at resolution, in
  $ and over the largest capital locked at once; how many trades lost money (only possible if the rule's nesting is wrong).
- **S11 survival.** For each of S11's 98 print-verified monotone trades: does the replay's entry condition (prints
  within 60 s, edge beyond tick and fees) hold at some moment within ±10 minutes of S11's entry minute, ignoring the
  cooldown and day cap? Count survivors.

## 3. Fresh universe (confirmatory)

- **Catalogue rule, from metadata only.** Every gamma event whose end date is on or after 2025-10-01 and that holds at
  least one closed market (gamma `/events`, closed and open, paged). S11's date-ladder rule
  (`s11_bundles.universe.date_ladders`, unchanged: same event, "by"/"before" wording, word for word the same apart from
  the last date phrase, rungs with catalogue volume of $50,000 or more, two rungs on one date drops the ladder, adjacent
  pairs). Events already in `s11_bundles/bundles.json`, and pairs with a leg in it, are left out. Price fields are dropped
  before storing; results are read only after the replay. Built and committed (`fresh_universe.json`) before any print
  of these markets is read.
- **Step 1 on these pairs**, then the replay of step 2 unchanged, entries 2025-10-01 to 2026-10-03.
- **Pass rule (fixed now).** PASS when the date-clustered 95% interval of net P&L per trade (points per contract) lies
  entirely above 0 with at least 30 trades on at least 15 New York entry dates. NULL with at least 30 trades on 15 dates
  and an interval that does not lie above 0. INSUFFICIENT otherwise.
- **Capacity.** $ a year at the 100-contract cap, and at the full simultaneous print size without the cap (upper bound).

## 4. Live check (once)

Current open date ladders: gamma open events, S11's date-ladder rule on their open, order-taking markets. One
`POST clob.polymarket.com/books` sweep. A violation net of fees: best bid of the rich rung − fee − (best ask of the cheap
rung + fee) > 0; the depth walk of `s11_bundles.engine.pair_arb` gives contracts and dollars locked in. Counted and
listed. No pass/fail.

## 5. What would change the reading

- Many non-nested pairs: S11's "cannot lose" premise is wrong for those, and their P&L is not arbitrage.
- Few S11 trades surviving the 60-second rule: S11's number came from prices that could not be traded together.
- The fresh universe is the only test. Seen-data results are mechanics, not evidence.

## Amendments

**0. Clock.** The pre-registration commit (`08a0236`) was made at 01:50 New York time, not 02:05 as written above.

**1. Sun 01:52: prints paged back by time.** An API probe (format only, three prints of one S11 market) showed that
`data-api/trades` honours an `end` timestamp. Instead of the latest 20,000 prints, each market's prints are paged back
with `end` = the oldest print served, 10,000 at a time, until a page is short or reaches before 2025-10-01, at most 30
pages (300,000 prints); a market that hits the cap is reported as truncated. Prints are de-duplicated on (transaction,
token, side, size, price, time). No print of a study pair had been read for analysis.

**2. Sun 01:53: windows that start at market creation.** The same probe returned the gamma description of a WTI strike
rung: "at any point after market creation". For such texts, identical wording does not make two rungs nested, because a
rung created later watches a shorter window. Rule added before any classification was run: when the masked description
mentions market creation, the pair is nested only if the cheap rung was created (gamma `startDate`) no later than the
rich rung (60 s tolerance). The rule also returns "not nested" when the rung's own key does not appear in its
description.

**3. Sun 01:56: catalogue mechanics.** Gamma's `/events` refuses deep offsets, so the fresh catalogue pages
`/events/keyset` (closed and open events, `end_date_min` 2025-10-01) with `volume_min` = $100,000, a necessary condition
of the rule (two rungs of $50,000 each). Built at 01:56 (`fresh_universe.json`): 68,571 events read, 68,052 with a closed
market, 200 already in S11; 373 date ladders, 861 pairs, 1,234 markets. Nothing but catalogue text was read.

**4. Sun 02:03: dates and levels given only in the title; creation wording.** Running the frozen rule on the gamma
records (metadata only; no print had been read) put 1,232 of 1,779 pairs in "key not found in description": most
descriptions say "the listed date", "the date specified in the title" or "the listed price", so the rung's key lives only
in the question, which the ladder rule already requires to be word for word the same apart from the key. Amended rule:
a pair whose masked descriptions and sources are identical is nested whether or not the key appears in the text (the
creation check still applies). The creation pattern of amendment 2 also missed "this market's creation"; it now matches
"market's creation", "market was/is created" and "creation of this/the market". Primary results use nested pairs only.
Labelled sensitivity (not confirmatory): the same replay with the creation-window pairs added back, with those pairs'
trades reported apart, so the reader sees whether the written-rule gap ever cost money.
