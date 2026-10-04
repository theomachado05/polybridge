# The contract link agent, measured (written before any label exists for these questions)

Written 2026-10-04, about 04:00 ET, on branch `r/link-agent`. Amendments are dated and appended at the end.

## 0. Why, and what was known

The final deliverable no longer rests on "question → likely ticker". It rests on **exact contract links**
(`research/linker/link_map.py`, served by `backend/app/contracts/`): every question is one of four types, a date-ladder
rung, a "will it hit" ticket, a "close above" ticket, or other; a ticket links to an option expiry and two bracketing
strikes, a rung to its ladder in date order. Both mechanisms of the note depend on those links being exactly right.
The registered ladder test was lost to a link error: three ladders had their year read wrong.

Known before this plan: the parser's code and its unit tests; the note (`note/NOTE.md`), including the year error
and its fix; the second held-out test of the generic linker (`linker/heldout2/PLAN.md`: 18% of testable links
confirmed, the pooled mechanism at t 3.3). No question of the sample below had been read by the author.

## 1. The sample (names, rules text and dates only; no price is fetched)

Built by `linker/contract_eval.py sample` from Polymarket's public listing:

- the open events the product's boards read (the two ticket tags and the open events above $100,000 of volume that
  the ladder board reads), and
- closed events of the last twelve months under the same tags and volume rule, which is where a missing year has to
  be derived.

Every market of those events is run through the parser as it stands at this commit. The sample is drawn with a fixed
seed, stratified by the parser's own answer: up to 110 questions for each of its three contract types and 110 it
calls "other" (taken from the same events and from other price questions, where a missed ticket would hide). Each
stratum is dealt alternately into **half A (development)** and **half B (held out)**. Adjacent rung pairs of the
sampled ladders are drawn the same way, up to 40 per half. The parser's answers are stored apart from the
labellers' input files.

## 2. The truth

Two blind labellers per file read the question, its event title, its rules text and its creation date, with the
instructions of `linker/prompts/contract_fields.md`, and return the type, the ticker, the level, the direction and
the date. Two more read each rung pair with `linker/prompts/contract_pairs.md` and say whether the earlier rung
resolving yes forces the later one to. Each reads one file only and runs once; a rerun is allowed only for output
that is not valid JSON or does not answer every item. **The truth is what both labellers agree on.** Where they
disagree on a field, that field of that question is left out of the figures and counted.

## 3. Measures and the bar

On half B, scored once, with the parser as it stands after any fix made on half A:

| Measure | Bar |
|---|---|
| Exact ticket links: of the tickets the parser calls linkable, the share with ticker, level, direction and date all equal to the truth | 95% or more |
| Rung dates: of the questions both the parser and the labellers call a rung, the share with the exact date | 95% or more |
| Nested pairs: of the pairs the code calls nested, the share both labellers call nested | 95% or more |

Reported whatever they show, each with its count and a 95% exact interval: the type table (parser against truth),
precision and recall by type, each field's accuracy on its own, the tickets the parser refuses to link and why, the
nested pairs the code misses, the labellers' own agreement rate, and every error by name.

## 4. Order of work

1. This plan, the sample, the input files, both instructions and the scoring code are committed.
2. The labellers run on both halves; their answers are committed with nothing else.
3. Half A is scored. Its errors are read, and the parser is fixed where it is wrong, each fix with a unit test.
   The fixes and half A's figures before and after are committed.
4. Half B is scored once: with the parser as it stood at step 1 and with the fixed parser. Both are reported.

## Amendments

**Amendment 1, 2026-10-04 04:22 ET. After half A was scored and its errors read (labels commit d44b2a2); before half B is
scored or any of its labels is read.** Half A, as planned: exact ticket links 45 of 87 (52%), rung dates 53 of 54,
nested pairs 30 of 30. Reading the errors gave one fault in the measure and four in the parser.

- **The measure.** A ticket's date is compared on the session the option link uses: the last weekday on or before
  the parser's window end against the last weekday on or before the readers' date. Most of half A's date "errors"
  were this and nothing else: "close above $840 end of October" is Saturday the 31st to the parser and Friday the
  30th to the readers, and the link uses the Friday either way. Half B is reported under this rule, and the parser
  as it stood at step 1 is also reported under the rule as first written.
- **Parser faults found on half A, to be fixed with a unit test each** (`linker/link_map.py`,
  `linker/tests/test_contract_links.py`):
  1. a month followed by a year is read as day 20 of the month ("the final trading day of January 2026" becomes
     January 20), which links a ticket to the wrong expiry and gives a rung the wrong date;
  2. weekly close tickets ("finish week of October 5 above $365") are not recognised and fall to "other";
  3. a negated deadline question ("will X not happen by <date>") is read as a ladder rung, although for it the
     earlier deadline is worth more, not less;
  4. a token written with a dollar sign ($ANSEM) is read as a stock ticker, and other tokens' price questions are
     typed as stock tickets with no ticker.
- **Not changed.** The readers were told "a single stock", so they called a ticket on an exchange-traded fund
  (EWY) "other"; such questions stay counted as the plan says and are listed by name. The three nested pairs the
  code refuses because the two rules texts differ are left as they are: refusing is the safe side.
- Half A is re-scored with the fixed parser as a development figure. Half B is then scored once.

**Note, 2026-10-04 04:38 ET, before half B is scored or read.** The four fixes are in `linker/link_map.py` with tests in
`linker/tests/test_contract_links.py`; an independent review of them found one wrong-contract fault in the new
weekly rule (a ticket created mid-week took its year from the Monday and linked a year out) and a negation rule
that was too wide; both were repaired before this note. Half A with the fixed parser, a development figure: exact
ticket links 91 of 92, rung dates 64 of 64, nested pairs 30 of 30. Side effects accepted, and known:

- "Will the S&P 500 hit 7000 by December 31?" (no dollar sign, no SPX or SPY written) was a linkable rung and is
  now an unlinkable touch ticket, as its dollar-sign twin already was.
- A price question on something that is not a stock ("Will Hyperliquid reach $100 by December 31, 2026?") is now a
  rung, not a ticket with no ticker. One backend assertion that encoded the old shape was changed to match.
- Not fixed, left for the owners: a token written with a symbol in parentheses that is also a US stock symbol
  ("Chainlink (LINK)") still links to that stock's options; a negated ticket ("not close above") is still read as
  up; "in 2026" and "before 2027" deadlines, which the readers call rungs, stay "other"; one pair's year comes out a
  year early from the frozen ladder rule (a market created on 2024-12-30 for "by December 31").

**Result, 2026-10-04 04:41 ET. Half B, held out, scored once (commit d287a16; parser as committed at 70736db).**

| Measure | Parser before the fixes | Fixed parser | Bar |
|---|---|---|---|
| Exact ticket links, dates on the session the link uses | 89 of 99 (90%) | **100 of 104 (96%, 95% interval 90% to 99%)** | 95%: met |
| Same, dates on the calendar day (the rule as first written) | 75 of 99 (76%) | 84 of 104 (81%) | 95%: not met |
| Rung dates | 53 of 54 | 53 of 54 (98%) | 95%: met |
| Nested pairs the code accepts | 30 of 30 | 30 of 30 | 95%: met |

- On the questions where both readers agree on the type, the fixed parser's type is right on all 202; the readers
  disagreed on the type of 18 of 220.
- The code refuses 6 of the 36 pairs both readers call nested, each because the two rules texts differ. That is the
  safe side, and it costs ladder trades.
- The calendar-day figures stay low because "end of October" is Saturday the 31st to the parser and Friday the 30th
  to the readers. The link uses the Friday in both cases, which is why amendment 1 changed the measure before this
  half was read.
- **A fifth fault, found on this half after it was scored:** all four ticket misses are "close above ... end of
  February", which the parser dated 2028-02-29 (it keyed the month's end on a leap day and waited for the next leap
  year). The step-1 parser had it too. Fixed after scoring with a test; with that fix the half reads 104 of 104, a
  figure that is not held out and is not the result.
- The one rung miss ("Will Ethereum hit $10,000 by December 31?", a year early) comes from the frozen ladder rule
  for a market created on 30 December; left for the ladder study's owners.
