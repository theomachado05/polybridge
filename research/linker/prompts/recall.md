# Recall check

You read this one file and nothing else. No other file, no web, no search.

`questions` lists Polymarket yes/no questions. For each one, say how it resolved **only if you actually remember
the outcome**. Do not reason about what was likely: a guess defeats the purpose of this check.

For every question return:
- `id`
- `resolved`: `yes`, `no`, or `unknown` (you do not remember, or as far as you know it had not resolved)
- `confidence`, 0 to 1, that your `yes` or `no` is right (0 for `unknown`)

Write one JSON object to the answer file you were told, and nothing else there:

```json
{"labeller": "<the name you were given>", "chunk": <number>, "answers": [
  {"id": "polymarket:123", "resolved": "unknown", "confidence": 0}
]}
```

Every question gets exactly one answer, in the same order.
