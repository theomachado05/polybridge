# S11 capacity

## Live books (the only fills that are certain)

See `live_arbitrages.csv` and `live_totals.json`. Each arbitrage's size is the depth at which one more contract still
locks in money after both fees: the dollars shown are the most that could be locked in at that snapshot. The numbers
are given in SUMMARY.md. They are cents to dollars, not a strategy.

## History, print-verified violation trades (1× costs, 98 monotone pairs; 1 one-of-many set)

The print check proves that a taker traded each leg at our price or better within 10 minutes. It does not prove that
both legs could be filled at the same moment. The size proven is the smaller of the two legs' qualifying print sizes:

| | Contracts |
|---|---|
| Median trade | 137 |
| 75th percentile | 881 |
| Largest | 37,972 |

- Entry edge locked in at 100 contracts a leg (the study's size), summed over the year: **$214**.
- The same at the full proven print size of every trade: **$7,962**. This is an upper bound. It is dominated by a few
  trades with very large prints, and it assumes both legs could be filled together.
- Capital: a pair contract ties up about $1 until the gap closes or the market resolves (median 4 to 29 minutes to the
  gap close; to resolution for the variant that holds). The one-of-many sets and the "all entries" rows are not capacity:
  most of those prices did not exist (SUMMARY.md).

## Propagation

The trade loses at every cost level (SUMMARY.md), so it has no capacity.
