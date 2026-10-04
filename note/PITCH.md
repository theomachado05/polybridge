# Five-minute pitch (Sunday, market closed)

| Time | Slide | Say |
|---|---|---|
| 0:00 | Question | "Prediction markets price events around the clock, but their books are thin. We asked where they are mispriced, against options and against their own logic, and how much of it can be traded." |
| 0:30 | Foundation | "On 4,561 fresh Polymarket stock markets, pre-registered and run once, the options price was the more accurate forecast. Brier difference +0.0108, CI +0.0064 to +0.0158. The gap closes where books are deep: Kalshi's index markets matched options." |
| 1:20 | Ladders | "'By January 15' can never be worth more than 'by January 16'. When that broke and both legs traded within a minute, the pair paid. As registered our fresh test was NULL, and every loss came from one bug: a misread year. With dates read correctly, 562 trades, no losses, +8.8 points a trade. We fixed that after the run, so we say it plainly. Capacity is about $3,300 a year." |
| 2:20 | Touch tickets | "Tickets priced above the options reference lost money for buyers in past data. A fresh test found too few markets, and much of the premium is market exposure. It is a lead with a forward test committed for Monday." |
| 2:50 | What failed | "About 40 pre-registered tests. The 8-K study for Massive, the overnight thesis, the overlay backtest and 23 weekend strategies did not pass. That is why the product gates every signal." |
| 3:20 | Demo, 90 seconds | "The C++ detector runs on the live Polymarket feed: 39 microseconds from message to decision at the median. Signals are labelled validated or unvalidated, orders need approval, and the broker refuses orders until the open, so hedges are staged." |
| 4:50 | Close | "Thin markets are measurably mispriced, the mispricing is small, and we built the system that only trades it after it passes." |

## Questions to expect

- **Is the ladder fix data snooping?** It was chosen after the run, so the confirmatory verdict is NULL and we report both numbers. The fix only corrects which rung is earlier; no correctly ordered pair lost.
- **Could you really get both fills?** A print shows one trader filled at that price, not that a second could. We require both legs to print within 60 seconds and pay one tick each side.
- **Does it beat futures?** We did not test futures. Given SPY's own pre-market move, the Polymarket move added nothing.
- **Capacity?** Small by construction: about $3,300 a year for ladders at 100 contracts a leg.
- **Is the latency end to end?** Receive to decision on the live feed, network time excluded.
