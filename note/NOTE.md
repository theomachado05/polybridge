# Where Prediction Markets Are Mispriced, and How Much of It Can Be Traded

Gator Quant Hacks 2026 · Systematic Trading track · PolyBridge · Jacob Crainic and Theo Machado

## Summary

Prediction markets now price elections, macro events and stock levels around the clock, but most of their books are thin and retail. We test two places where such a book can be checked against something firmer: its own internal logic, and the listed options on the same stock. **Foundation:** on 4,561 fresh Polymarket stock markets, pre-registered and run once, the option-implied probability was a more accurate forecast than the Polymarket price (Brier difference +0.0108, 95% CI +0.0064 to +0.0158). **Mechanism 1, date ladders:** a contract that resolves YES by an earlier date can never be worth more than the same contract for a later date; we measure how often that rule breaks and whether the break can be traded. **Mechanism 2, "will it hit" tickets:** in past data, tickets priced above an options-derived reference lost money for their buyers, but a fresh test could not confirm it. We report every approach that failed, including our pre-registered 8-K study for the Massive challenge, and describe the C++ system that watches these markets and acts only on signals that have passed their tests.

## 1. Economic foundation

**Who is on the other side.** Polymarket's stock and event books are thin: a median trade of about 20 shares, quotes that go stale for tens of seconds, and many retail buyers of YES. Listed options on the same stocks are quoted continuously by professional market makers. A thin book can drift from the price that a deeper market or plain logic implies, and nobody large corrects it.

**Why the drift persists.** Limits to arbitrage. The gaps are a few cents a contract, capital is locked until resolution, the two venues share no margin, and printed size is small. A desk would earn too little to bother. That predicts what we find: real, measurable mispricings with small capacity.

**What would make the edge disappear.** Depth. Kalshi's S&P 500 and Nasdaq-100 markets, which professional market makers quote, matched options within a pre-set ±0.003 Brier margin (90% CI +0.0001 to +0.0025). The gaps live in the thin books.

## 2. Foundation: options are the more accurate price

`research/fresh_accuracy/`: 7,111 scored rows from 4,561 Polymarket "close above $K" markets on 89 resolution dates, none used by any earlier study, chosen by a frozen rule committed with the market list before any price was fetched.

| Score | Polymarket | Options | Difference (positive = options better), 95% date-cluster CI |
|---|---|---|---|
| Brier | 0.0938 | 0.0831 | +0.0108 [+0.0064, +0.0158] |
| Log score | 0.3044 | 0.2726 | +0.0318 [+0.0170, +0.0471] |

The result holds on daily and weekly markets, at both snapshots, with equal weight per date, after dropping the five most influential dates (+0.0064 [+0.0036, +0.0093]) and with a symmetric price filter (+0.0077 [+0.0036, +0.0129]), the safer magnitude. Two limits: the Polymarket price series is about 47 seconds older than the option quote on average, and where it is under 30 seconds old (669 rows) the gap is not significant. Polymarket still adds information (encompassing logit: options +0.85 [+0.63, +1.07], Polymarket +0.30 [+0.15, +0.45]) and leans toward 0.5 relative to options (slope −0.105 [−0.133, −0.077]). This is a statement about prices, not traders, and it tells both mechanisms below which reference to use.

## 3. Mechanism 1: date ladders that break their own logic

**The rule.** If "X happens by 15 January" resolves YES, then "X happens by 16 January" also resolves YES. The earlier rung can never be worth more. When it trades above the later rung, selling the earlier rung and buying the later one cannot lose if both are held to resolution, provided the two markets share the same event definition and resolution source.

**Prior evidence (seen data, `research/s11_bundles/`).** Over the year, 99 violations had public trade prints on both legs at the needed prices. They earned +3.89 points per trade at 1× costs (95% interval over dates +2.49 to +5.43, 71 dates) and +4.34 at 2× costs. Of 1,425 violations a mid-price backtest would trade, 965 had no print at that price, so most apparent violations are not real. Out of sample there were 11 trades. Capacity was about $385 a year at 100 contracts a leg.

**Validation tonight (`research/ladder_replay/`, method committed before data).** [LADDER: settlement-rule check counts; causal chronological replay with both legs filled at prints within the fixed window, fees, capital locked to resolution; fresh-universe verdict with n, CI, return on locked capital, Sharpe, drawdown; live violations at real bid and ask.]

## 4. Mechanism 2: "will it hit" tickets above the options reference

**The idea.** A ticket that pays if a stock touches a level by a date can be compared with a touch probability built from the listed options at the same moment. Where buyers pay well above that reference, sellers should earn a premium.

**Prior evidence (seen data, exploratory).** In `research/s21_options_anchor/`, buyers of YES who paid 10 or more points above the central options reference lost 29.8 points per contract [−40.1, −18.3] (53 markets, 29 events). Selling only tickets priced 5 or more points above the reference earned +22.3 points [+10.4, +33.1] on 60 markets in 33 events, against +3.1 [−1.5, +7.9] on the tickets it left; taken minus left +19.2 [+5.8, +31.5], and no anchor-shuffle reached that gap. It failed its own confirmation rule: only 2 markets were out of sample. The touch reference rests on modeling choices (barrier versus terminal probability, option expiry later than the ticket window), and the broader first-weekend seller result (S18) was negative in its recent period.

**Fresh test (`research/touch_fresh/`, method committed before data): INSUFFICIENT.** Earlier studies had already used almost every heavily traded stock "will it hit" event. Under S21's rules only 32 fresh markets in 4 events remained, below the pre-set 30 markets in 15 events, so the confirmatory test could not run. A secondary sample, fixed before the pull, relaxed one volume floor (142 markets, 85 events), but only 7 markets met the sell rule: −15.4 points per contract [−48.8, +21.8], with the unfiltered seller book at −2.6 [−19.0, +11.5]. The point estimates lean against the S21 result, and the samples are too thin to decide. A delta-hedged unfiltered book earned +10.5 [−0.1, +20.0], and seller returns fell 2.3 points for each 1% the stock moved toward the level, so much of the premium is compensation for market exposure. A forward test for markets listed from 5 October is committed (`research/touch_fresh/FORWARD.md`). We treat this mechanism as an open lead, not a trading thesis.

## 5. Risk, capital and the system that acts on it

**Evidence gate.** Every signal carries the label validated or unvalidated estimate, enforced in code (`backend/app/closed/evidence.py`; an order on an unvalidated market returns HTTP 409 without an explicit acknowledgement). A signal acts on capital only after its pre-registered test passes.

**Monitoring and execution.** A C++20 library (17 families, 1,386 presets) holds the trading logic; an AI step only selects and tunes a compiled preset. A live recorder streams every Polymarket book update for 200 markets and runs a C++ stale-quote detector on each one. Measured on the live feed, receive to decision takes 39 µs at the median and 3.9 ms at p99 (58,610 decisions; the C++ call itself is 158 ns; network time excluded). Over the weekend its options reference is Friday's close, so its flags are a latency demonstration, not trades.

**Risk controls.** Orders need approval. Equity orders are capped at 10% of the opening five-minute volume and 1% of ADV per session; option legs at 10% of volume and 5% of open interest; prediction-market legs at 50% of the depth within 2 cents. Gross hedge notional is capped at 50% of equity and per-event exposure at 20%. Ladder positions carry no market risk if held to resolution, but they carry settlement-rule risk and capital lock-up; touch-ticket sales carry tail risk when the level is hit, and correlated tickets on one underlying can lose together.

**Capacity.** Printed size, not order-book depth, bounds every estimate here. Historical printed size is an upper limit on what a new trader could have filled, not deployable capital. [CAPACITY from the two validations.]

## 6. What failed

We pre-registered and ran about 40 tests. The table lists the ones a reader might expect to work.

| Test | Verdict | Key number |
|---|---|---|
| 8-K options mispricing (Massive challenge, separate write-up) | NULL in-sample; out of sample H1 3 events, H2 sign reversed | H2 −0.022 [−0.076, +0.020] |
| Polymarket move overnight predicts the SPY open (380 closures) | did not replicate | 10 new markets +0.63 bp per pp (p = 0.126) |
| Same, on 36 rule-selected US macro markets | does not hold | +0.81 [−0.14, +1.76], perm p = 0.053 |
| Polymarket adds information beyond pre-market SPY | no | 08:00: −0.60 bp per pp [−2.64, +1.44] |
| Trade Polymarket toward options at weekend reopenings, at printed prices | NULL | −0.40 pt [−4.68, +3.74], 402 trades |
| Same, all weekdays, fresh 2026 window | insufficient trades | 40 of 100 required |
| Closed-market overlay on a long SPY book (equity curve) | Fail | in sample −$7,318, Sharpe 1.148 vs 1.151; no out-of-sample trade |
| 23 weekend and cross-venue studies (S1 to S23) | none passes its own rule | best leads above; full scorecard in `research/results/WEEKEND_SCORECARD.md` |

## 7. Limits and next steps

Most prior evidence for both mechanisms is in-sample; tonight's validations are the confirmatory part, and forward tests from 5 October are committed in git before they run. Capacity is small by construction. Prices on thin books are a per-minute history that can be a stale last trade. Fills are simulated from public prints, not our own orders. Next: score the forward tests, record order-book depth to replace printed size, and extend the ladder rule to every venue that lists nested contracts.
