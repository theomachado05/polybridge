# Capacity is unmeasured

No eligible completion contract or verified order was found. There is no supported dollar capacity estimate; missing depth is not zero tradable depth.

The frozen evaluator caps an order at 1% of displayed executable event/equity/put depth and 1% of prior 20-session target equity volume, at $10,000 maximum capital per deal. Each portfolio includes all premium/collateral plus cash. Same-share comparisons use common lots funded for the most expensive comparator at 2x costs. Equity share, event token and option contract units remain separate.

A midpoint series cannot prove executable depth. Public prints can corroborate an entry but cannot prove the entire order book. The current Gamma fee rate (4%, exponent 1, taker-only on the five-company basket) is metadata about today; it cannot be applied backward without a contemporaneous schedule and exact fee formula. The fixture evaluator accepts documented dollar fees and refuses unfunded purchases. Zero borrowing means funding costs are zero in this conservative implementation; the preregistered borrowing rate is not a source of invented return. Options use observed bid/ask plus $0.65 per contract per side. Returns/cost basis points cannot be computed without a funded historical trade.

Potential tails include a target falling below the planning reference, noncompletion before a contract deadline without actual deal failure, a changed offer/buyer, and option cash-deliverable adjustments. Actual breakup prices, source-authenticated fills and settlement marks are required to estimate these risks.
