# S24 capacity

Every figure is read from `trades.csv` (primary trades: two prints within 10 minutes, 1× costs unless stated).

## Size that the prints prove

The size of a trade is the smaller of its two prints. A print proves that one taker traded that size at that price.
It does not prove that a second order of the same size would have been filled, or that both legs were there at once.

| | Contracts |
|---|---|
| Median trade | 19 |
| 75th percentile | 50 |
| 95th percentile | 354 |
| Largest | 5,000 |
| Trades under 100 contracts | 312 of 375 |
| Trades under 5 contracts (Polymarket's minimum order) | 60 of 375 |

## Money

| | 100-contract cap | Full printed size |
|---|---|---|
| Net P&L, 1× costs | −$387 | $1,843 |
| Net P&L, 2× costs | −$658 | $1,126 |
| Of which locked in at entry, 1× | $2,060 | $4,529 |
| Contracts traded (per leg) | 12,512 | 34,618 |

- The uncapped figure is an upper bound. The 5 largest trades carry $3,862 of it (209.6%).
- P&L that came from the result (the cheap rung paid $1 and the rich rung $0), not from the entry: 13 trades.

## Capital and how long it is locked

A pair contract ties up about $1 (the NO side of the rich rung plus the YES side of the cheap rung) until the later rung
closes. Capital is counted from the entry date to that day; pairs with a rung still open are carried to 2026-10-04.

| | 100-contract cap |
|---|---|
| Capital per contract, mean | $0.831 |
| Most capital locked at once | $1,943 |
| Mean capital locked, every calendar day | $457 |
| Days locked: median / mean / longest | 15 / 35.8 / 241 |
| Net P&L per year on the capital actually locked | −44.0% |
| Calendar days from the first entry to the last day | 703 |

## By set

| Set | Trades | Net P&L, cap | Net P&L, full size | Most capital locked | Median days locked |
|---|---|---|---|---|---|
| (a) | 280 | −$498 | $1,748 | $1,943 | 20 |
| (b) | 95 | $111 | $94.53 | $563 | 5 |

## Real ladders only (post hoc: corrected rule, direction check, unseen markets)

The registered trades include wrongly built pairs, so their dollars are not a capacity. This table is the cleaned sample. It is post hoc.

| | 100-contract cap | Full printed size |
|---|---|---|
| Trades | 160 | 160 |
| Net P&L, 1× costs | $425 | $3,570 |
| Net P&L, 2× costs | $300 | $3,134 |
| Of which locked in at entry, 1× | $25.57 | $81.29 |
| Most capital locked at once | $1,325 | |
| Median days locked | 3 | |
| Net P&L per year on the capital actually locked | 157.2% | |
| Median trade, contracts | 20 | |
| Largest trade, contracts | 5,000 | |

- The full-size figure is one trade: the largest carries $3,263. Its two prints were 292 seconds apart.
- 12 trades were paid $1 by the result; the rest average +0.56 points.
