# Rung pair reader

You are one of two independent readers. The other one cannot see your answers. You read this one file and nothing
else: no other file, no web, no prices, no search.

`pairs` lists pairs of Polymarket questions from one event. In each pair, `earlier` has the earlier deadline and
`later` the later one. Each side has `question`, `rules` (the market's own rules text, possibly cut short),
`resolution_source` and `created`.

For each pair decide whether it is **nested**: if `earlier` resolves yes, must `later` resolve yes too? That holds
when the two rules define the same event, with the same resolution source and the same start of the window, and
differ only by the deadline. It fails when the later question's window starts after the earlier one's (for example
a window that opens on the later market's creation day), when the two count different things, or when their sources
differ in a way that could split the outcome.

Return for each pair:
- `pair`: its id
- `nested`: true or false
- `earlier_date` and `later_date`, as YYYY-MM-DD: each side's deadline, with the year from the rules text when it is
  written there, else the first such day on or after that side's `created`
- `reason`: one sentence
- `sure`: false if the rules text was too short to tell

Write one JSON object to the answer file you were told, and nothing else there:

```json
{"labeller": "<the name you were given>", "chunk": "<the chunk you were given>", "answers": [
  {"pair": "p001", "nested": true, "earlier_date": "2026-01-15", "later_date": "2026-01-31",
   "reason": "...", "sure": true}
]}
```

Every pair gets exactly one answer, in the same order.
