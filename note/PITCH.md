# Five-minute pitch

| Time | Slide | Say |
|---|---|---|
| 0:00 | Title + one line | "Options put a price on every 8-K before it is filed. We tested whether that price is wrong for slow bad news and for restructurings." |
| 0:30 | The two bets | H1: litigation, investigations, cyber, impairments, so buy the put. H2: restructurings, so sell the put. Show the git timestamp: both committed before any data. |
| 1:15 | Decay chart (H1 R by horizon, events vs ordinary days) | "The chain prices the first day generously, 0.68, and the follow-through cheaply, 1.36 at 42 sessions. That is our mechanism. With 30 events it is inside the noise." |
| 2:15 | Results table, headline horizons | "Both nulls. They still tell a PM something: post-headline insurance is not overpriced by more than about 3% (H1) or 0.9% (H2)." |
| 3:00 | Forecast slide | "Before running your sealed window we wrote down what it would show: a 3-month window is INSUFFICIENT, longer ones NULL, and four signs with probabilities." |
| 3:45 | Demo, 60 seconds | PolyBridge applies the same priced-versus-realized check to any priced event, including a Kalshi market, and labels anything we have not tested as "Not tested". |
| 4:45 | Close | "Next test: H2 entry timing, a few sessions after the filing, on a fresh window." |

## Questions to expect

- **Why protective put and not the put alone?** The library fixes the strategy; we report the put's own edge as a robustness check.
- **Isn't H1 the starter's own example?** The pairing is; the test of *when* the chain misprices it (the decay curve) and the cost bound are ours.
- **The atlas has q-values of 0.01.** Up to 15 events per tag and a shared placebo; leads, not findings.
- **Capacity?** Median 34 to 49 contracts traded on the entry day; a few contracts per event.
