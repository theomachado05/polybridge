# Five-minute pitch (Sunday, market closed)

| Time | Slide | Say |
|---|---|---|
| 0:00 | Title | "Stocks close; prediction markets don't. PolyBridge hedges a stock book around the clock, and lets a market's signal touch a position only after it passes an out-of-sample test." |
| 0:30 | The record | "Six pre-registered follow-up tests yesterday, each method committed to git before its data. Four did not pass, including both that used mostly new data. The two that passed did so on a panel we had already seen, and we say so." |
| 1:15 | Monday-open chart | "At the reopening after a weekend or holiday, options had repriced only 0.44 of the prediction market's weekend move, CI 0.33 to 0.57, 1,535 events over 44 closures. After option costs it is NULL, and the prediction market gives part of its move back. Information, not arbitrage." |
| 2:00 | The 8-K test | "Our Massive entry by the book: two hypotheses committed before any data, NULL in-sample; out of sample H1 had 3 events, too few to test, and H2 flipped sign. So 8-K tags never act on a position." |
| 2:40 | Forecast slide | "We wrote down the out-of-sample result before running it. We had 'no pass' right. We got the H1 event count (3, not about 11) and H2's sign wrong." |
| 3:15 | Demo, 90 seconds | "It's Sunday: stocks are shut, the prediction market is live. PolyBridge labels each market validated or an unvalidated estimate, and stages the equity hedge for 09:30. The broker refuses orders until then, which is the design. The staged hedge is the one closed-market hedge that met its rule: fragile, +6.82% [+0.50, +13.54] over a same-size static hedge." |
| 4:45 | Close | "Next: a fresh-sample test of the staged hedge and of the expected gap on US macro markets, against a futures benchmark." |

## Questions to expect

- **Does the prediction market beat futures?** We have not shown it; 305 of the 380 closures are overnight, when futures trade. It is the first open test.
- **Why should anyone use a product whose signals mostly fail?** Because it tells you which ones fail before they touch your book.
- **The 8-K atlas has low q-values.** The lowest is 0.014, with 5 to 15 events per tag and 96,390 variants counted; leads, not findings.
- **Capacity?** For a $1M book the capital budget binds before liquidity; one order at the open fits a $191M SPY holding at 50% coverage (Saturday snapshot of Friday's data).
- **Is the latency claim end to end?** No: 27.1 to 34.6 ns per decision on a synthetic tape, decision logic only.
