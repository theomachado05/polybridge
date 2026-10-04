# Contract reader

You are one of two independent readers. The other one cannot see your answers. You read this one file and nothing
else: no other file, no web, no prices, no search.

`questions` lists Polymarket yes/no questions. Each has `id`, `question`, `event_title`, `rules` (the market's own
rules text, possibly cut short), and `created` (the day the market was created). Read each one into fields. Do not
judge prices, odds or trades.

## Fields

- `type`, one of:
  - `touch_ticket`: will a single stock listed in the US, or the S&P 500, **hit, reach, touch, dip to or fall to** a
    dollar level at any time within a window.
  - `close_above_ticket`: will a single stock listed in the US, or the S&P 500, **close, finish or settle** above
    or below a dollar level on one given day.
  - `ladder_rung`: "X by <date>": the question resolves yes if something happens on or before a deadline, so that
    the same question with a later deadline would also resolve yes. A price question on anything that is not a US
    stock or the S&P 500 (Bitcoin, gold, oil, another index) is a rung when it has such a deadline.
  - `other`: everything else: a question about one fixed day or one fixed month that is not cumulative, a range
    ("between $A and $B"), an up-or-down market over minutes or hours, an election, a ranking.
- `underlying`: for the two ticket types, the ticker as its US exchange shows it (NVDA, TSLA; `SPX` for the S&P 500
  index, `SPY` only if the question is about the SPY fund itself). Otherwise "".
- `level`: for tickets, the dollar level as a number. Otherwise 0.
- `direction`: for tickets, `up` when yes means the price went up to the level or closed above it, `down` when yes
  means it dipped or fell to the level or closed below it. If the question's verb is neutral ("hit") take the
  direction from the rules text ("at or above", "at or below") or from an arrow in the event title or question; if
  nothing says, `none`. For other types, `none`.
- `date`, as YYYY-MM-DD: a rung's deadline, a touch ticket's last day, a close ticket's day. Take the year from the
  rules text when it is written there, else from the question or the event title, else use the first such day on
  or after `created`. Use the calendar day in US Eastern time as the rules state it. For `other`, "".
- `year_from`: `rules`, `question`, `title` or `created`: where the year came from. For `other`, "".
- `sure`: false if you had to guess any field.

## Output

Write one JSON object to the answer file you were told, and nothing else there:

```json
{"labeller": "<the name you were given>", "chunk": "<the chunk you were given>", "answers": [
  {"id": "123", "type": "touch_ticket", "underlying": "NVDA", "level": 200, "direction": "up",
   "date": "2026-12-31", "year_from": "rules", "sure": true}
]}
```

Every question gets exactly one answer, in the same order.
