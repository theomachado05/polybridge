# Capacity and cost evidence

Historical capacity is NA. No source in the audited price caches provides direct
historical PM ask/bid depth. Kalshi candle traded volume is not available size, and
public print size is somebody else's execution at another instant. Zero qualified
entries means no capacity evidence, not a proven zero capacity market.

The frozen target is 100 basket units or winner shares. With 10% participation at
each level, executing 100 needs at least 1,000 displayed shares across the eligible
ask levels on **each** leg, including the worst leg. A full unwind or daily liquid
mark needs correspondingly sufficient bid depth. The actual observed VWAP matters;
100 shares at the best ask cannot be assumed from 100 shares of deeper aggregate
liquidity. FOK leg failure triggers an unwind; insufficient unwind depth leaves
funded exposure. Cash remains separate by venue. Capital is $10,000, up to 50%
locked overall and 5% by family. There is no historical size at which these gates
can be shown to pass.

| Component | Frozen 1× convention | 2× stress | Historical numerical estimate |
|---|---|---|---|
| Spread | Actual ask VWAP minus simultaneous midpoint | Add one extra spread copy | NA |
| Fee | Contemporaneous schedule applied to each order | Double | NA |
| Adverse price move | One observed contract tick per leg/fill | Two ticks | NA |
| Funding | 10% annual simple on actual locked entry collateral | 20% | NA |
| Redemption/conversion/transfer cash flows | Actual recorded cash flow | Actual recorded cash flow | NA |

Costs must be reported in dollars, cents per $1 payoff (one probability point),
and basis points of total entry collateral when a dataset exists. Missing material
conversion and release cash flows prevent net-return claims.

The current official [PM fee page](https://docs.polymarket.com/trading/fees) describes
share-count × market fee rate × p × (1-p), with market-specific rates and five-decimal
fee precision. It is a mechanics check; current terms are not a historical schedule.
The official [Kalshi schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) has a
general coefficient 0.07 with contract multipliers and product exceptions, and no
settlement fee. A timestamped applicable schedule, its order-level rounding rule
and the actual fee cash flow are required for evaluation. The evaluator accepts
explicit fee coefficient, exponent and rounding terms; its synthetic cent-rounded
Kalshi-like example does not assert that every 2025–2026 contract used that schedule.
The PDF currently states an effective date of July 7, 2026 and describes rounding
of fee plus position cost, another reason to archive contemporaneous terms instead
of importing one rule throughout history.

A source publication is not free cash. At 10% funding, a 30-day lock consumes about
0.82% of entry collateral; a 60-day lock doubles that. This is the frozen hurdle,
not the current Treasury yield. A disputed source-determined winner may pay zero
or $0.50, and all such cases must remain in the eventual test.
