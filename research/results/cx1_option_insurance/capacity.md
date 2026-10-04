# Capacity and trading-unit limits

The fixed rule has 55 executable quoted closure dates. Weakest displayed entry bid size: 1 contracts; weakest exit ask size: 2; minimum bottleneck: 1. Median bottleneck: 26; 10th percentile: 7.

One put contract needs full strike cash of $63,500 to $77,600, median $69,000. The median displayed bottleneck corresponds to $1,932,500 cash collateral; the smallest date to $68,400. These figures are quote touch sizes, not executable capacity guarantees.

The portfolio curves use fractional normalized contracts and compound account equity. At one-contract cash capital, the half/full gate cannot be implemented exactly. An integer gate needs at least two strike cash obligations at full exposure and one at half exposure, roughly $127,000 to $155,200. That exact two-lot/full and one-lot/half book fits the historical displayed entry-and-exit bottleneck on 54/55 dates. Capital changes, rounding and changing strikes make a live integer book different from the fractional research curve; no integer-capital optimization was run.

Capacity uses the lesser of the observed entry bid size and later exit ask size. Those are not simultaneous quotes, and no option volume or order-book-depth data were pulled. Larger orders, queue position, market movement, impact and assignment liquidation are unsupported. The $0.65 commission per contract per side is a stated S7-compatible assumption; it is not a claimed universal tariff.

| Book | Costs | All-period premium turnover / initial cash | All-period collateral turnover / initial cash |
|---|---:|---:|---:|
| V0 | 1x | 0.7811 | 113.6794 |
| V1 | 1x | 0.5162 | 77.8237 |
| STATIC_IS_MATCH | 1x | 0.5154 | 74.9601 |
| V0 | 2x | 0.7762 | 113.1573 |
| V1 | 2x | 0.5136 | 77.5659 |
| STATIC_IS_MATCH | 2x | 0.5129 | 74.7309 |

Premium turnover sums actual entry plus exit option consideration per initial portfolio cash. Collateral turnover counts the full allocated strike obligation at entry and exit. Both use compounded portfolio capital. Their different magnitudes show why returns and capacity must be normalized by full cash, not the small premium received.
