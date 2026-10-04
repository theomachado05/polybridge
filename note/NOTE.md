# PolyBridge: Evidence-Gated 24/7 Hedging

Gator Quant Hacks 2026 · Systematic Trading track and Massive "Trade the 8-K" challenge · Jacob Crainic and Theo Machado

US stocks trade 6.5 hours a day; prediction markets (PMs) trade around the clock. PolyBridge turns PM prices into hedges for an equity book, under one rule: a market's signal may act on a position only after it passes a pre-registered out-of-sample test, and the product says so when it fails. Every signal carries the label **validated** or **unvalidated estimate**, enforced in code (`backend/app/closed/evidence.py`; an order on an unvalidated market returns HTTP 409 without an explicit acknowledgement). Every study below had its method committed to git before its data was fetched and was run once; extra passes are disclosed in each run log.

**Headline.** On 4,561 fresh Polymarket stock and SPY "close above $K" markets, the option-implied probability was a more accurate forecast of the outcome than the Polymarket price (Brier difference +0.0108, 95% CI +0.0064 to +0.0158; 89 resolution-date clusters). Most of our tests of the PM-predicts-the-open idea failed, and that is why the product gates every signal.

## Part I · The 8-K test (Massive challenge)

**Hypotheses** (committed before any event or price was downloaded, `research/HYPOTHESIS.md`). We measure whether the option chain misprices the move after two kinds of 8-K filing, using the parity ratio R (realized move over the move the chain priced the session before, scaled to each horizon). **H1:** after litigation, investigation, cybersecurity or impairment 8-Ks, the stock keeps moving by more than the options priced, because implied volatility is marked down once the headline passes while the damage resolves over weeks; a protective put opened at the close of the session after the filing should beat the same position on an ordinary day. **H2:** after restructuring, layoff, facility-closure or exit 8-Ks, holders who must stay in the stock buy puts and dealers charge for absorbing that demand (Gârleanu, Pedersen and Poteshman, 2009); a cash-secured put sold then should beat one sold on an ordinary day.

**Method.** Top-100 US stocks; in-sample 2024-01-01 to 2025-12-31; out-of-sample 2026-01-01 to 2026-08-31, frozen at 13:00 ET on 3 October and run once. One event per company per filing date; every filing treated as public after the close. Options 90 to 180 days out, put 5% out of the money, legs marked from daily bars. Baseline: 120 ordinary days per family for the same companies. Pass rule: a 97.5% bootstrap interval on the event-minus-ordinary-day edge above zero at 2 or more of 21 sessions, 42 sessions and expiry, with R moving the predicted way.

**Results.** Neither hypothesis passes. Edge per $1 of stock, 97.5% intervals (other horizons in `research/results/in_sample/`):

| | Sessions | n events / ordinary | Edge | 97.5% CI |
|---|---|---|---|---|
| H1 in-sample | 21 / 42 / expiry | 32 / 30 / 28 | +0.001 / +0.005 / +0.033 | [−0.027, +0.029] / [−0.045, +0.058] / [−0.030, +0.101] |
| H2 in-sample | 21 / 42 / expiry | 24 / 24 / 23 | +0.001 / +0.002 / +0.009 | [−0.007, +0.009] / [−0.009, +0.014] / [−0.004, +0.023] |
| H1 out of sample | 21 / 42 | 3 / 3 | not computable (n < 5) | |
| H2 out of sample | 21 / 42 | 7 / 7 | −0.022 / −0.014 | [−0.076, +0.020] / [−0.073, +0.026] |

Out of sample, H1's computed verdict under the frozen method is NULL on 3 events, too few for an interval. H2 is NULL with its sign reversed. In 2024 and 2025 a stock-plus-put position after an H1 filing did no better or worse than on ordinary days by more than about 3% of spot at 21 sessions, and short puts after H2 filings were not overpriced by more than about 0.9%. The in-sample H1 parity ratio (0.68 one session after the filing, 1.36 at 42, ordinary days 0.92 to 1.15) had the shape H1 predicts, but its intervals overlap the placebo at every horizon and the out-of-sample points went the other way. Costs: the 5% premium haircut moves the edge by at most 0.04% of spot; median option leg volume was 33.5 (H1) and 48.5 (H2) contracts.

**What would break it, and the forecast.** 24 to 36 events per family in-sample and 3 and 8 out of sample, a static top-100 list, spot inferred from put-call parity, last-trade marks. Before the out-of-sample run we committed a forecast (`research/FORECAST.md`). It had "no pass" and H2's count right, and got H1's count (3, not about 11), the interval width (2 to 3 times wider) and the one scorable sign wrong. For a 3-month sealed window it predicts too few events for an interval in both families.

**How to trade it.** We would not. PolyBridge shows 8-K tags as untested and never lets them size a hedge.

## Part II · Closed-market mode and which price to trust

**The exposure.** Of 380 closures in our main panel, 305 are overnight, 63 weekends and 12 holidays; the median absolute SPY opening gap is 28 bp. A PM on a macro outcome reprices while the stock is shut. The open question was whether it tells a holder anything that equity and options markets do not already price. Three pre-registered results answer it.

**1. Options are the better forecaster (fresh data, confirmatory).** `research/fresh_accuracy/`: 7,111 scored rows from 4,561 Polymarket markets on 89 resolution dates, none used by any earlier study, selected by a frozen rule committed with the market list before any price was fetched.

| Score | Polymarket | Options | Difference (positive = options better), 95% date-cluster CI |
|---|---|---|---|
| Brier | 0.0938 | 0.0831 | +0.0108 [+0.0064, +0.0158] |
| Log score | 0.3044 | 0.2726 | +0.0318 [+0.0170, +0.0471] |

It holds on daily and weekly markets, at both snapshots, with equal weight per date, after dropping the five most influential dates (+0.0064 [+0.0036, +0.0093]) and with a symmetric price filter (+0.0077 [+0.0036, +0.0129]). About half the headline size comes from the inherited filter, so +0.0077 is the safer magnitude. The PM price is a per-minute series about 47 seconds older than the option quote on average, which favours options; on the 669 rows where the PM point is under 30 seconds old there is no significant difference. Polymarket still adds some information (encompassing logit: options +0.85 [+0.63, +1.07], PM +0.30 [+0.15, +0.45]) and leans toward 0.5 relative to options (slope −0.105 [−0.133, −0.077]). On Kalshi's deeper S&P 500 and Nasdaq-100 markets, the venue price matched options within the pre-set ±0.003 Brier margin (90% CI [+0.0001, +0.0025]). This is an accuracy result, not a trade: the median option half-band is 2.3 points per $1 of payoff.

**2. Pre-market SPY absorbs the overnight PM signal.** `research/pm_vs_premarket/`, on the already-seen 380-closure panel. Alone, the PM move during the closure has the familiar slope (+7.27 bp of gap per pp). Given SPY's own move to 08:00, the PM coefficient is −0.60 bp per pp [−2.64, +1.44] (permutation p = 0.57); at 09:25 it is +0.17 [−0.23, +0.57]. Index futures were not available on our data key, so this is against pre-market SPY only.

**3. Part of the PM's closure move is overshoot.** `research/overshoot/`, a pre-registered re-analysis of R3's already-seen rows (1,123 events, 43 closures). At the reopening options had repriced 0.44 of the PM's closure move. Of the gap, the PM gives back +3.84 pt [+1.84, +6.22] by the close, options catch up −0.59 pt [−2.43, +0.88], and +4.59 pt [+2.87, +6.26] persists to the end of the day. After option costs the residual gap is NULL (+0.79 pt [−1.21, +2.78], R3).

**4. Trading the gap: too few trades to confirm, and it vanishes at the reopening.** The direct trade is to take a Polymarket print that sits at least 5 points from the option-implied probability, in the options' direction, and hold to settlement. On fresh April to August 2026 markets (`research/pm_taker_v2/`) it made +29.8 pt per $1 after fees and a tick [+13.0, +44.6], but on only 40 trades over 21 days, short of the pre-registered 100, so the verdict is INSUFFICIENT. Of the +31 pt gross, about 7 pt is the edge the options price implied at entry; the other 24 pt is outcomes landing the options' way, mostly on bullish trades (31 of 40) in a rising market, so the 7 pt figure is the honest expectation. Capacity was tiny: taking half of each qualifying print would have deployed $747. At weekend reopenings, where the PM overshoots most, the same rule at actual print prices made −0.40 pt [−4.68, +3.74] on 402 trades: the overshoot shows up in per-minute prices, not in prices anyone traded at. A forward test of the reopening rule for Monday 5 October onward is committed in git before the open (`research/forward_monday/`).

**What the product does with this.** Where an options price exists for the same outcome, PolyBridge shows it as the reference probability and the PM as a secondary, noisier input. Closed-market mode stages an equity hedge for the first tradable moment (hedge B) rather than acting on the PM during the closure, and labels every PM-driven estimate unvalidated until its market passes its own test.

## Part III · Evidence table, strategy backtest, risk and liquidity

| Test (method committed first, run once) | Data | Verdict | Key numbers |
|---|---|---|---|
| Options vs Polymarket accuracy | fresh, 4,561 markets | **PASS** | Brier +0.0108 [+0.0064, +0.0158] |
| Kalshi index vs options accuracy | fresh | **equivalent** | within ±0.003, 90% CI [+0.0001, +0.0025] |
| 8-K parity, out of sample | new | NULL (H1 3 events) | H2 −0.022 [−0.076, +0.020] |
| Overnight relation, replication | new PM series, mostly seen dates | does not replicate | +0.63 bp per pp (p = 0.126) vs +7.52 |
| Overnight relation, US macro panel | 36 new markets, 353 dates | does not hold | +0.81 [−0.14, +1.76], perm p = 0.053; macro = geopolitics |
| PM vs pre-market SPY | seen panel | PM adds nothing | 08:00: −0.60 [−2.64, +1.44] |
| Options catch-up at the reopening (R3) | mostly new, 44 closures | NULL after costs | +0.79 pt [−1.21, +2.78] |
| Expected-gap model (R2) | seen panel | passes via one market | recession 97 of 151 signs; replication 50.2% |
| Staged 09:30 hedge (R1, hedge B) | seen panel | passes, fragile | +6.82% [+0.50, +13.54] vs same-size static |
| AI fit walk-forward | time split of seen histories | fails | median −0.0040 vs static |
| Options-anchored PM taker, Jan-Feb 2026 | fresh | insufficient trades | 77 projected vs 100 required |
| Options-anchored PM taker, Apr-Aug 2026 | fresh | insufficient trades (40 of 100) | +29.8 pt per $1 [+13.0, +44.6], 21 days; see text |
| Same trade at weekend reopenings | seen closures, real trade prints | NULL | −0.40 pt [−4.68, +3.74], 402 trades, 44 closures |
| Overlay backtest on long SPY | 2024-01 to 2026-10 | **Fail** | no out-of-sample trade |

**Strategy backtest** (`research/strategy_backtest/`, method `3c6b280`). A $1M book long SPY from the 2024-01-02 close. At 09:30 the overlay shorts up to 50% when a market that has passed its own walk-forward gate signals an adverse expected gap, and covers at 10:00. Costs 1 bp per side (2× stress). The last 20% of days (from 2026-03-18) are out of sample; nothing is tuned on them.

| Segment | Book | Ann. return | Vol | Sharpe | Max DD | Turnover | Hedge days | Hedge P&L |
|---|---|---|---|---|---|---|---|---|
| Out of sample | Buy-and-hold | 29.57% | 13.18% | 2.031 | −5.40% | 0 | | |
| Out of sample | Overlay, 1× | 29.73% | 13.25% | 2.032 | −5.43% | 0 | 0 | $0 |
| In sample | Buy-and-hold | 18.47% | 15.81% | 1.151 | −18.51% | 0 | | |
| In sample | Overlay, 1× | 18.20% | 15.63% | 1.148 | −18.52% | 9.2×/yr | 37 | −$7,318 |
| In sample | Overlay, 2× | 18.10% | 15.63% | 1.142 | −18.52% | 9.2×/yr | 37 | −$9,858 |

Verdict: **Fail.** In sample the overlay traded on 37 days, almost all driven by the 2025 recession market, and lost $7.3k net. Out of sample no market passed the gate, so it did not trade; the books differ only by the in-sample loss carried as cash. Every variant (pre-market entry, no gate, hold to the close, wider universe) lost money in sample. The gate's out-of-sample behaviour is the product working as designed: with no validated market, it stood aside.

**Risk controls.** Coverage cap, fee gate, no-trade band, drawdown kill, gap-flip kill and an approval gate on every hedge (`docs/library.md`); an equity fill needs a fresh in-session price. Gross hedge notional is capped at 50% of equity and per-event exposure at 20%; short equity carries Reg T margin; short puts are cash-secured; an order that breaches a limit, or comes from an unreadable account, is refused.

**Liquidity and capital.** Equity orders are capped at 10% of the opening five-minute volume and 1% of ADV per session; option legs at 10% of volume and 5% of open interest; PM legs at 50% of the depth within 2 cents. Cost is half the spread plus k·σ·√(q/ADV) with k = 1.0 (conservative end of Toth et al., 2011, and Almgren et al., 2005), assumed rather than fitted, since there are no live fills. In the backtest, the largest hedge (50% of the book) stays under 1% of the first five minutes' SPY dollar volume for books up to $19.0M on a median day and $9.7M on a 5th-percentile day; at 08:00 pre-market the limit falls to $749k. On the $1M Webull paper account the 20% per-event limit binds long before liquidity.

## Part IV · What didn't work, limits, next steps

**What didn't work.** The overnight relation that started the project (+7.52 bp per pp over 380 closures) rested on one market, did not replicate on 10 new markets or on a 36-market macro panel, and disappears once SPY's own pre-market move is known. No PM lead in market hours (PM first 9, equities first 9, simultaneous 2). No executable PM-versus-options arbitrage (5 verified gaps, 0 executable). The AI preset fit does not hold out of sample, including on both demo markets. The PM-contract hedge (hedge A) showed no variance reduction and increased variance on the replication panel. The 8-K study is NULL in and out of sample. The overlay backtest failed.

**Limits.** The accuracy result is about prices, not traders: the PM series PolyBridge reads is a per-minute history that can be a stale last trade or a thin-book midpoint, and it is about 47 seconds older than the option quote. Closed-market results rest on few markets and closures that are not independent; PM fills are simulated; index futures were not tested; engine latency (27.1 to 34.6 ns per decision) is measured on a synthetic tape, decision logic only.

**Next.** Test the accuracy gap with time-matched PM trade prints instead of per-minute history; benchmark against index futures; and score the forward test committed for the reopenings from 5 October. Until a market passes its own test, PolyBridge labels it an unvalidated estimate.
