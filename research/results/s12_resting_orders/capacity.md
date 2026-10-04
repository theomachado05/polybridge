# S12 capacity

Qualifying volume = the taker prints that would have reached a resting order (through its price in full, at its price beyond the 500-contract queue allowance) inside its window. The share of reachable orders that would have filled completely at each order size, primary posting at the mid (1x rule):

| Sample | Variant | Window | Reachable | 100 | 500 | 2,000 | 10,000 | Median qualifying volume |
|---|---|---|---|---|---|---|---|---|
| S9 | R0 | 30 min, mid | 301 | 23% | 17% | 9% | 1% | 0 |
| S9 | R1 | 120 min, mid | 301 | 32% | 20% | 13% | 3% | 0 |
| S9 | R2 | 30 min, one cent better | 301 | 28% | 19% | 10% | 1% | 0 |
| S9 | R3 | 120 min, one cent better | 301 | 38% | 24% | 15% | 3% | 5 |
| S8 | R0 | 30 min, mid | 80 | 42% | 32% | 20% | 8% | 9 |
| S8 | R1 | 120 min, mid | 80 | 59% | 51% | 40% | 28% | 565 |
| S8 | R2 | 30 min, one cent better | 80 | 62% | 49% | 26% | 8% | 415 |
| S8 | R3 | 120 min, one cent better | 80 | 76% | 66% | 46% | 32% | 1,691 |

Capacity is bounded by the taker flow that comes through the price inside the window. At 100 contracts most reachable S9 orders never fill at all (the median qualifying volume is shown in the last column); a book of 10,000 contracts would almost never have been filled in 30 minutes.
