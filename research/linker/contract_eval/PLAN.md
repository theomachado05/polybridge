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
