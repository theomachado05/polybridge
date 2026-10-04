# S25 capacity

The Polymarket side limits this trade, and the option lot size makes the hedge lumpy; listed-option liquidity does not.

## Rule subset (52 hedged markets)

- **Option quotes at entry (Monday 09:35):** the long leg is quoted a median of $0.11 wide (3% of its mid), the short leg $0.10 (4%). Crossing both, with commission, costs a median of 5.30 points per ticket against the mid.
- **Size at the quote:** a median of 48 contracts offered on the long leg and 58 bid on the short leg.
- **Option volume on the hedge day:** a median of 214 contracts on the long leg and 202 on the short leg (52 markets with volume pulled); 6% of the hedges have a leg that did not trade that day.
- **The ticket's printed size:** a median of 64 tickets sold into bids per market over the first weekend (quartiles 20 to 465); 28,983 tickets and $12,132 of premium in all.
- **Lot size is the binding limit.** One listed spread is 100 shares; with a median width of $5.00 it pays $500 at most, which hedges 250 tickets at 2 spreads per ticket. Only 31% of these markets printed that many tickets in their first weekend. The book in the summary holds up to 100 tickets per market and so holds a fraction of one option contract: it is an accounting of the trade per ticket, not an order that could be sent.

## Full set (252 hedged markets)

- **Option quotes at entry (Monday 09:35):** the long leg is quoted a median of $0.10 wide (4% of its mid), the short leg $0.10 (5%). Crossing both, with commission, costs a median of 4.30 points per ticket against the mid.
- **Size at the quote:** a median of 66 contracts offered on the long leg and 64 bid on the short leg.
- **Option volume on the hedge day:** a median of 194 contracts on the long leg and 148 on the short leg (252 markets with volume pulled); 8% of the hedges have a leg that did not trade that day.
- **The ticket's printed size:** a median of 82 tickets sold into bids per market over the first weekend (quartiles 21 to 418); 182,286 tickets and $88,841 of premium in all.
- **Lot size is the binding limit.** One listed spread is 100 shares; with a median width of $5.00 it pays $500 at most, which hedges 250 tickets at 2 spreads per ticket. Only 28% of these markets printed that many tickets in their first weekend. The book in the summary holds up to 100 tickets per market and so holds a fraction of one option contract: it is an accounting of the trade per ticket, not an order that could be sent.

Sources: option NBBO and daily option volume from Massive; printed ticket sizes from S18's `prints_markets.csv` (takers' sales, Friday 20:00 to Sunday 20:00 New York). The prints show what did trade; a newcomer hitting the same bids would have moved them.
