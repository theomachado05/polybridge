# PolyBridge: Evidence-Gated 24/7 Hedging

Gator Quant Hacks 2026 · Systematic Trading track · quant note · Jacob Crainic and Theo Machado

## Summary

US stocks trade about 6.5 hours a day; prediction markets trade around the clock. A holder of equities is exposed to news that breaks overnight and at weekends, and a prediction market is often the only liquid price that moves with that news while the stock is shut. PolyBridge turns prediction-market prices into hedges for an equity book. Its principle is that a market's signal may act on a position only after it has passed a pre-registered out-of-sample test, and the product says so when a market fails. Every signal carries the label **validated** or **unvalidated estimate**, and the label is enforced in code: an order on an unvalidated market needs an explicit acknowledgement at approval (`backend/app/closed/evidence.py`, HTTP 409 without it).

We ran six pre-registered tests on 3 October, each with its method committed to git before its data was fetched. The four on new data failed or were NULL. The two that passed did so on a panel we had already seen, and we state that scope wherever we cite them. The record is the reason for the gate: most markets carry no usable signal, and a hedging product that acts on all of them by default would add noise to a book.

## 1. Economic foundation

**The exposure.** Of the 380 closures in our main panel, 305 are overnight, 63 weekends and 12 holidays. The median absolute SPY opening gap on that panel is 28 bp; on the 17 closures we selected for news it is 94 bp. A long holder cannot trade SPY in the regular session during any of these windows.

**Why a prediction market could help.** A prediction market on a macro outcome (a US recession in 2025, a Fed decision) reprices when news arrives, whatever the hour. If its moves line up with the next equity open, they give a holder an estimate of the gap before the open and a time to prepare a hedge. Who is on the other side matters. Prediction markets are thin, retail-heavy and fee-light; equity index futures are deep and trade nearly 24 hours. Any value a prediction market adds must survive that comparison, and the futures objection is the first thing our own evidence leaves open (section 5).

**Why a signal would persist or vanish.** A thin market can overshoot. If prediction-market moves during a closure partly reverse after the open, they are noise to a hedger. If options or futures absorb the same news more slowly, they are information. The tests below are built to tell these apart, and for most markets they cannot.

## 2. Framework and method (innovation)

**Two prices of one risk.** A prediction-market contract and an option chain both price the same event risk: the contract as a probability, the chain as a distribution of moves. PolyBridge compares them, and compares both with what the stock then does.

**Pre-registration as the gate.** Each study has a METHOD.md committed before any data for it was fetched, a single run, a run log and a `.done` marker that refuses a second run. Commit order is checked for every METHOD.md. Exploratory results are labelled exploratory and never become headlines.

**A compiled library that the AI only configures.** The hedging logic is a C++20 library of 17 families and 1,386 presets (`engine/hedgecore/manifest.json`). The AI step classifies a market, shortlists families and picks a preset by replaying the market's own history; it cannot write trading logic. A decision costs 27.1 to 34.6 ns per `on_tick` on a synthetic benchmark tape (`engine/hedgecore/BENCH.md`), so tuning a preset per market is cheap. The fit is configuration, not edge (section 3).

**Closed-market mode.** While stocks are shut, PolyBridge stages an equity hedge for the first tradable moment (hedge B) and, only on the holder's opt-in, holds the adverse prediction-market contract during the closure (hedge A). The broker enforces the session: Webull paper refuses orders outside 09:30 to 16:00 ET, so a staged order waits for the open.

## 3. Results (performance and evidence)

### Six pre-registered tests

| Test | Data | Verdict | Key numbers |
|---|---|---|---|
| Replication of the 380-closure relation | new PM series, 10 rule-selected markets | does not replicate | pooled slope +0.63 bp per pp (date-permutation p = 0.126, n = 1,211) against +7.52 originally |
| Walk-forward of the AI fit | live histories, 122 markets | fails | median test gain over a static hedge −0.0040; 19 above 0, 72 below; Wilcoxon p = 1.000 |
| 8-K implied-move parity, out of sample | new, 2026-01 to 2026-08 | H1 INSUFFICIENT, H2 NULL | H1 3 events; H2 edge −0.0215 [−0.0759, +0.0203] at 21 sessions, sign opposite to in-sample |
| R3 options catch-up at the Monday open | new, 1,535 events over 44 closures | NULL | net residual gap +0.79 pt [−1.21, +2.78]; catch-up slope 0.44 [0.33, 0.57] |
| R2 expected-gap model | already-seen 380 panel | passes on the panel via one market; fails on replication | recession market 97 of 151 signs (64.2%), slope +1.28; election 52.4% (p = 0.744); replication 50.2% of 878 |
| R1 closed-market hedge | already-seen 380 panel | hedge A no evidence; hedge B passes, fragile | hedge B variance cut +11.42% [+5.10, +18.14] vs no hedge, +6.82% [+0.50, +13.54] vs a same-size static hedge |

Sources: `research/results/<study>/SUMMARY.md` for each row; methods and commit hashes in `research/EVIDENCE.md`.

### What cleared a test, with its scope

**Options lag the prediction market at the Monday open, but not in a way anyone can trade.** At 09:45 on the reopening day, options had repriced 0.44 of the prediction market's closure move (95% CI 0.33 to 0.57; closure-clustered bootstrap over 44 closures). R3's pass test was the residual gap net of option costs, +0.79 pt [−1.21, +2.78], so its verdict is NULL. After the open the options did not keep moving toward the prediction market (−0.59 pt), the prediction market gave back part of its move (−3.48 pt [−5.40, −1.62]), and on the 1,535 resolved events the options were the better forecaster (Brier 0.120 against 0.146). The gap looks at least as much like prediction-market overshoot as slow options.

**The expected-gap model held out of sample in time on one market.** Fitting each closure's rate only on earlier closures, the US-recession market predicted the sign of the SPY gap in 97 of 151 closures (64.2%, p < 0.001). The election market did not (52.4%), and on the 10-market replication panel the model failed (50.2%, slope −0.23). Out-of-sample R-squared on the panel is +0.050. This is a pre-registered re-analysis of a panel we had already seen.

**Staging the hedge for the open cut post-open variance, fragilely.** Hedge B shorts a fraction of SPY at 09:30 when the expected gap is adverse and covers at 10:00. It met R1's rule against both controls, but it is partial under a block bootstrap ([−0.71, +14.60] against static), and dropping the 5 closures that contribute most turns its gain over static to −0.78%. It works by timing: the half-hour after an adverse expected gap is more volatile (sd 36.5 bp against 24.8 bp), and hedge size does not predict direction (correlation +0.00). It cannot reduce the gap itself.

### What didn't work

- **The overnight relation did not replicate.** Over 380 unselected closures of two markets the prediction-market move lined up with the next SPY gap (+7.52 bp per pp, permutation p = 0.001), but that was our reading of the placebo arm after the results, it rests on one market (recession 58 of 83 signs; election 31 of 66), and on 10 new, mostly geopolitical markets the slope was +0.63 (p = 0.126).
- **No prediction-market lead during market hours.** In 20 stress events with a move in both series, the prediction market moved first 9 times, equities 9 times, 2 simultaneous (sign test p = 1.000); pooled Granger tests lean toward equities leading.
- **No executable arbitrage between prediction markets and options.** 224 resolved rows passed a cost screen; 5 had a trade print at the needed price, each a single print of 5 to 100 shares; 0 were executable.
- **The AI fit does not hold out of sample.** In-sample the median gain over a static hedge is 0.0053; on walk-forward the picked preset loses (median −0.0040), including on both demo markets (−0.245 and −0.418).
- **The 8-K study is NULL in-sample and out of sample.** Two hypotheses pre-registered before any event was fetched, a 97.5% bootstrap against ordinary days for the same companies: no headline horizon passes for either. Our separate Massive write-up gives the detail.
- **Hedge A shows no evidence** (variance cut +4.76% [−0.80, +10.01] against no hedge) and increased variance on the replication panel (−3.79% [−8.19, −0.91]).

[Tonight's pre-registered pass on the open questions of section 5 goes here: macro-only panel and power, prediction market against pre-market SPY or futures, overshoot against slow options. Verdicts as run, whatever they show.]

## 4. Risk management, liquidity and capital

**What the evidence does to the product.** Closed-market mode defaults to staged equity orders (hedge B), labelled fragile. The prediction-market hedge (hedge A) is opt-in and always labelled an unvalidated estimate. Options at the open is an unvalidated estimate whose simulated trade needs an explicit acknowledgement. The expected gap is shown as a direction-and-size hint with its band and closure count, and is informative only where a market has its own well-determined rate. The AI fit is configuration.

**Controls in the library.** Coverage cap, fee gate, no-trade band, drawdown kill, gap-flip kill and an approval gate on every hedge (`docs/library.md`). An equity fill needs a fresh in-session price, so a stale close is never booked as hedge P&L.

**Liquidity caps and cost model.** Equity orders are capped at 10% of the opening five-minute volume (hedge B executes at the open) and 1% of ADV per session; option legs at 10% of volume and 5% of open interest; prediction-market legs at 50% of the depth within 2 cents. Cost is half the spread plus k × σ_daily × √(q / ADV) with k = 1.0, the conservative end of Toth et al. (2011) and Almgren et al. (2005); k is assumed, not fitted, since there are no live fills. Every order path passes these caps (`backend/app/liquidity/model.py`).

**Capital.** Gross hedge notional is capped at 50% of equity and per-event exposure at 20%; short equity carries Reg T 50% initial and 30% maintenance margin; short puts are cash-secured. An exposure-increasing order that breaches a limit is refused, and an unreadable account refuses such orders.

**One capacity snapshot.** Run once on Saturday 3 October on Friday's data (`docs/liquidity-snapshot-2026-10-03.json`):

| | SPY | TLT | ITA |
|---|---|---|---|
| 20-day ADV | 46.0M shares ($35.2B) | 47.8M ($3.82B) | 0.86M ($184M) |
| Max order at the open (10% of 5-min volume) | 124,240 shares | 80,510 | 3,099 |
| Est. cost at that size | 4.22 bp | 3.31 bp | 89.44 bp (after-hours spread; upper bound) |
| Holding whose 50% hedge fits one order at the open | $191.2M | $12.5M | $1.29M |

On the $1M Webull paper account, the per-event limit is $200,000 of hedge notional (259 SPY shares at Friday's close), far below the liquidity cap, so capital binds before liquidity for any book under about $191M in SPY. This is what the product enforces, not a capacity claim for returns: there is no signal edge to scale.

**Costs where the studies measured them.** Hedge A pays 0.60 bp per closure at today's top-of-book prediction-market half-spread (0.05 pp) and far more than it saves at thin-book spreads (5.0 pp: variance cut −74.15%). R3's median option cost at the open was 2.60 pt of half-band plus 0.26 pt of commission, and a round trip toward the prediction market cost −22.83 pt.

## 5. Limits and next steps

**Limits.** Closed-market results rest on two markets loosely tied to SPY, closures that are not independent, simulated prediction-market fills at mid plus a half-spread taken from today's books, and no live fills. The engine latency is measured on a synthetic tape for `on_tick` only, not end to end. Polymarket publishes mid-price history without book depth. The 380-closure relation was never compared with index futures or pre-market SPY, and 305 of its closures are overnight, when futures trade.

**Next.** A fresh-sample test of hedge B on closures outside the panel; the expected gap on a rule-selected US macro panel with clustered errors; a benchmark against pre-market SPY or index futures; and a decomposition of the Monday-open gap into prediction-market overshoot and options lag. Each will run under the same rule: method committed first, run once, reported whatever it shows. Until a market passes, PolyBridge labels it an unvalidated estimate.
