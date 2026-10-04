# Link labeller, control arm: the by-event linker of the first held-out test

You are one of two independent labellers. The other one cannot see your answers. A link counts only if both of you
name it.

**You read this one file and nothing else.** No other file, no web, no prices, no search. Use the question text and
general knowledge of how markets work. Do not use any memory of how a question resolved or of how a price moved
around it. If you do remember either, set `remembered: true` on that question.

## What you are given

- `tickers`: the only tickers you may name.
- `events`: Polymarket yes/no questions grouped by event.

## What you return for every question

- `id`
- `family`: `event` (a real-world outcome that would move a listed instrument from outside), `spot_proxy` (the
  question is settled by a traded price or only happens because that price moved), or `none`.
- `role`: `carrier` (the question that carries its event), `duplicate` (another deadline of the same event, or a
  question that says the same thing as the carrier), `tail` (an outcome too remote for its odds to move), or `none`.
- `links`, only on a carrier: each with `ticker`, `direction` (`up_on_yes` or `down_on_yes`), `confidence` (0 to 1),
  `impact_pct` (the instrument's move in percent on full resolution), `alternative` (the outcome the direction is
  measured against) and `mechanism` (one sentence).
- `remembered`: true or false.

## Rules

1. Link the question that carries the event: the main market, not a side market.
2. One deadline per ladder: "by April 30", "by May 31", "by June 30" are one event. Link one of them.
3. For an event with several outcomes, state the alternative; the direction is measured against it.
4. Pick an instrument the event would move by about 1% or more.
5. A question driven by the asset's own price is a `spot_proxy`, not an event.
6. No hindsight.

## Output

Write one JSON object to the answer file you were told, and nothing else there:

```json
{"labeller": "<the name you were given>", "chunk": <number>, "answers": [
  {"id": "polymarket:123", "family": "event", "role": "carrier", "remembered": false,
   "links": [{"ticker": "USO", "direction": "up_on_yes", "confidence": 0.6, "impact_pct": 6,
              "alternative": "...", "mechanism": "..."}]}
]}
```

Every question gets exactly one answer.
