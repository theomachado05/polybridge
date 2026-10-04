# S1 capacity

## History

The historical backtest makes **no capacity claim**: Kalshi candles and Polymarket price history carry no sizes (METHOD.md section 5). It trades a fixed 100 contract pairs per entry, about $100.

The only size evidence in history is the Polymarket trade prints behind the verified entries (primary variant, out-of-sample, 1× costs): 15 entries, median printed size 200 shares, smallest 10, largest 2,742. Counted at the printed size and capped at 100, they are 1,234 contract pairs and $1,177 of capital over 73 days. Kalshi's size at those quotes is unknown.

## Forward recording (real books, sizes that were on the book)

Primary variant, 1× costs. Pairs with a fillable edge at any snapshot: 6 of 33. Largest fillable amount per pair, summed: $2,836 (2,976 contract pairs), locking +$63.60.

| Pair | Snapshots with an edge | Max fillable pairs | Max fillable $ | Edge locked at that size | Share of visible top-5 depth |
|---|---|---|---|---|---|
| KXIPODISCORD-26DEC01 | 2572 | 221 | $212 | +$5.70 | 80.6% |
| KXIPO-26-DEEP | 2572 | 20 | $19 | +$0.29 | 5.8% |
| KXGEMINI-GEM4-26NOV01 | 698 | 211 | $205 | +$2.74 | 20.7% |
| KXGEMINI-GEM4-26OCT16 | 225 | 561 | $519 | +$26.05 | 84.9% |
| KXTRUMPAICZAR-26SEP-JCLA | 20 | 11 | $11 | +$0.18 | 1.2% |
| KXIPO-26-ANTHROPIC | 2127 | 1,952 | $1,869 | +$28.64 | 42.2% |
