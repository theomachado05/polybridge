# S6, S18 and S19: evidence and micro-market selection audit

Audit dated 2026-10-04. This uses existing completed outputs and source code only. No original files or Git state were changed. No protected forward/raw data, sealed 8-K outcomes or network were accessed by this audit. The three current contract descriptions supplied by the coordinating agent are used only to inspect mechanics; they are not proof of historical rule versions. All historical results have been reused and are exploratory for the current selection.

**Recommendation: make S18 traded-price calibration the paper's central finding. Use the prespecified 50–75% price bucket across the noncrypto universe as the strongest positive quantitative exhibit, and monthly SPY ETF touch contracts as the single prospective execution pilot.** Keep SPX monthly contracts as a separate control. S6's modeled 4.27 Sharpe is poorly supported by traded prices. S19 supplies a useful boundary condition: buyer losses recur, but the positive seller premium does not replicate over its full crypto sample.

This is a publishable observational question about calibration and transaction costs. It is not evidence of an already executable, funded daily Sharpe of 2–7. Selecting S18 and these cohorts after reading existing results requires an untouched future confirmation window.

## Reproduction and definitions

[option_micro_audit.py](../../cx5_strategy_selection/option_micro_audit.py) independently reconstructs seller P&L, event-cluster intervals, capped printed-size books, peak locked collateral and reported Sharpes. It asserts that the broad S18/S19 1x means, interval endpoints, P&L, capital and drawdown match the saved outputs to numerical tolerance. Five synthetic cash-ledger invariants check fees, losses, overlapping positions and redemption before a same-time new entry; every historical reconstructed ledger reconciles terminal cash to net P&L. It imports no original strategy module and never invokes its data-pull or forward-data calibration code.

Reproduce from `research/`:

```sh
.venv/bin/python -m cx5_strategy_selection.option_micro_audit
```

[OPTION_MICRO_METRICS.csv](OPTION_MICRO_METRICS.csv) contains all cuts, IS/OOS segments and cost cases; [OPTION_MICRO_EVENTS.csv](OPTION_MICRO_EVENTS.csv) exposes every S&P event; [OPTION_MICRO_SOURCE_HASHES.csv](OPTION_MICRO_SOURCE_HASHES.csv) records byte counts and SHA-256 hashes of inputs and the reproduction code. Use the module invocation above to reproduce from the research environment.

One P&L point is $0.01 per binary contract. Seller P&L is `YES traded bid − fee − resolved YES indicator`; a fully funded implementation buys NO at the complementary price. The illustrative book takes `min(100, total eligible printed size)` contracts per market. Means weight markets equally, while cash books weight their capped size. Bootstrap intervals resample whole event ladders, 2,000 draws, seed 0; they do not assume independent strikes. Original reporting omits intervals below five events. The new CSV preserves that convention and additionally labels small-n empirical intervals as descriptive, not tail-risk evidence.

For S18/S19, “2x” here doubles the documented entry **fee**, using the same prints; it does not double an independently measured spread, adverse selection or execution slippage. Fees are evaluated at the market's size-weighted average price, which may differ from charging every individual print. Capacity measures aggregate trades during 48 hours, not inventory simultaneously available for an additional trader.

## Comparison of the actual evidence

| Evidence | Sample | 1x net result | 2x result | Judgment |
|---|---:|---|---|---|
| S6 V0 modeled Monday fade, ALL | 187 trades, 36 active closures on 45-closure grid | +$3,765.41; closure Sharpe 4.2683 | 110 trades, +$2,324.46; Sharpe 3.2511 | High headline depends on unsupported assumed fills |
| S6 V0 price-print-supported, capped size, ALL | 21 trades, 12 closures | +$294.43; mean $14.02, CI [−3.99, +36.94]; grid Sharpe 1.0352 | 8 trades, 7 closures; +$94.46; mean $11.81, CI [−1.43, +21.24] | Positive small pilot evidence, concentrated in one day |
| S18 all actual sellers, ALL | 657 markets, 101 events | +3.6263 points, CI [+0.7214, +6.5652]; +$2,171; settlement-month Sharpe 1.5267 | +3.2887 points, CI [+0.3563, +6.2813]; Sharpe 1.4091 | Positive aggregate finding, recent seller premium failed |
| S18 50–75% actual seller VWAP, ALL | 88 markets, 51 events | +13.3021 points, CI [+5.1650, +21.3257]; +$1,134.43; Sharpe 2.1703 | +12.6926 points, CI [+4.5603, +20.7167]; +$1,088.35; Sharpe 2.1085 | Strongest positive observational cohort in this comparison |
| S19 actual sellers, ALL | 1,132 markets, 322 events | −0.2456 points, CI [−2.2237, +1.6027]; −$211.53; Sharpe −0.0915 | −0.4433 points; −$434.92; Sharpe −0.1900 | Seller premium did not replicate broadly |
| S19 actual sellers, OOS | 184 markets, 60 events; 5 settlement months | +2.8420 points, CI [−3.0834, +7.8010]; +$561.30; Sharpe 2.2139 | +2.1875 points; +$440.92; Sharpe 1.7475 | Real recent positive period, too regime-specific to lead the paper |

S18 broad sellers are +4.6892 points in IS (534 markets/81 events), but −0.9881 in OOS (123/20), with OOS Sharpe −0.5388 and −0.6825 at doubled fees. The proposed paper must show that deterioration alongside the positive bucket. Its recent 20% starts 2026-06-27 by event's first eligible weekend. S19 recent 20% starts 2026-06-15 by listing; its IS is −0.8449 points (948/262). Neither split is pristine for this new selection.

Buyer evidence strengthens the calibration interpretation without mechanically establishing seller alpha. S18 actual buyers lost −8.8663 points across 606 markets/97 events, CI [−11.9404, −5.9309]. Buyers whose **own** actual VWAP was 50–75% lost −17.2535 across 105/56, CI [−24.5017, −10.2815]. Their IS loss is −13.2815 [−21.1830, −4.8350] on 80/44; OOS loss is −29.9638 [−48.4589, −15.2987] on 25/12. These are separately conditioned cohorts, not necessarily the same contracts as the seller bucket. S19 broad buyers also lost −2.8258 [−5.1848, −0.4483] on 880/301 even while sellers made no aggregate premium: spreads, selection and different buy/sell cohorts matter.

## The 50–75% bucket: strongest paper exhibit

| Segment | Markets/events | 1x net mean and event CI, points | 2x fee mean and CI | Capped cash P&L, 1x/2x | Settlement-month Sharpe, 1x/2x |
|---|---:|---|---|---:|---:|
| IS | 72/40 | 11.3461 [2.5842, 20.5425] | 10.8091 [1.9850, 20.0536] | $769.31 / $736.56 | 1.8870 / 1.8317 |
| OOS | 16/11 | 22.1040 [−1.0966, 39.0518] | 21.1684 [−2.0760, 38.1191] | $365.12 / $351.78 | 2.5081 / 2.4293 |
| ALL | 88/51 | 13.3021 [5.1650, 21.3257] | 12.6926 [4.5603, 20.7167] | $1,134.43 / $1,088.35 | 2.1703 / 2.1085 |

Gross ALL mean is 13.9115 points and fee drag 0.6095. The best cash event is only 12.59% of net book profit. Removing it leaves +$991.59 and mean +12.0769, CI [4.0384, 20.4355] across the remaining 50 events; the full-sample finding is not one jackpot. OOS best-event removal leaves +$222.28 but mean CI [−8.4919, +37.6864], so recent precision remains weak. Fixed-peak-cash drawdown is 19.01% ALL and 23.57% OOS; selling this cohort still has substantial tails.

This bucket was specified before S18's initial run, but promoting it as the main positive result after reading all buckets is a selection. Its completed 48h VWAP and presence of sell prints are known after the putative entry. Thus the research shows **a cohort of actual transaction prices paid more than subsequent outcomes justified after fees**. It does not demonstrate that an investor could at Friday 20:00 identify the same markets, trade their completed-window VWAP, or obtain all historical capacity. A future policy must condition on contemporaneous executable quotes rather than the later VWAP.

## The S&P family, separated correctly

The `sp500` tag contains 56 seller markets on 10 events: **31 monthly SPY ETF markets/5 events, 21 monthly SPX index markets/4 events, and 4 weekly SPY markets/1 event**. Classification uses explicit question tokens and “Week”, with a completeness assertion. The original 93 S&P entries include contracts without usable seller prints; counts here describe the tested printed cohort.

| Cut / segment | Markets/events | 1x / 2x mean points | 1x event CI | 1x / 2x net cash P&L | 1x / 2x settlement-month Sharpe |
|---|---:|---:|---|---:|---:|
| Mixed S&P, ALL | 56/10 | 17.4326 / 17.0191 | [8.2210, 26.7718] | $628.71 / $613.56 | 3.2071 / 3.2078 |
| Mixed S&P, IS | 46/7 | 16.7725 / 16.3906 | [6.0391, 27.3458] | $520.52 / $508.24 | 3.7610 / 3.7652 |
| Mixed S&P, OOS | 10/3 | 20.4687 / 19.9099 | n/a (<5 events) | $108.19 / $105.32 | 2.5028 / 2.5005 |
| Monthly SPY, ALL | 31/5 | 11.4145 / 10.8208 | [−1.5249, 22.5728] | $283.06 / $269.99 | 1.6584 / 1.6188 |
| Monthly SPY, IS | 21/2 | 7.1029 / 6.4927 | n/a | $174.86 / $164.67 | n/a (2 settlement months) |
| Monthly SPY, OOS | 10/3 | 20.4687 / 19.9099 | n/a | $108.19 / $105.32 | 2.5028 / 2.5005 |
| Monthly SPX, ALL = IS | 21/4 | 26.3857 / 26.2465 | n/a | $336.38 / $334.58 | 3.9755 / 3.9694 |
| Weekly SPY, ALL = IS | 4/1 | 17.0688 / 16.6116 | n/a | $9.27 / $8.99 | n/a |

The mixed S&P doubled-fee CI is [7.8271, 26.4384]. Removing its best cash event (SPY May, $242.00, 38.49% of profit) leaves +$386.71, mean +18.0003, CI [5.8544, 28.8993] on 9 events. At 2x it leaves +$379.57. The SPY-only best event is 85.49% of its profit; removing it leaves just +$41.06 and mean +7.8611 on 4 events. SPX's four events all have NO outcomes among their seller contracts, have no OOS observations, and have distinct reference/source rules. Its higher Sharpe is a poor basis for choosing it as the primary pilot.

The OOS S&P sample is exactly the three SPY July/August/September monthly events. All ten tested seller contracts resolved NO; August supplies 86.29% of OOS profit. The empirical three-event bootstrap is descriptively positive [15.5591, 39.0400] at 1x, but cannot generate an unseen hit-loss regime. It must not be promoted as a reliable positive population interval. The aggregate mixed book has zero settlement-month drawdown because profitable other events offset the loss-making SPY June; SPY-only shows 9.93% fixed-peak-cash drawdown. Neither number measures intramonth mark-to-market losses.

Counterpart buyer losses exist: mixed S&P 57 markets / 10 events mean −20.1041, CI [−29.5047, −12.0977]; monthly SPY 29/5 mean −19.8215, CI [−32.7480, −13.1141]. Buyer and seller cohorts differ, and event bootstrap does not remove a shared market regime.

**Combining the price bucket with SPY is thin, not another confirmation.** Monthly SPY 50–75% seller VWAP is only 6 markets / 3 events: IS 5/2 mean +3.0187 points (+2.1247 at 2x), +$35.80; OOS 1/1 mean +54.8454 (+53.8590 at 2x), +$54.85. ALL +$90.65 and Sharpe 1.9503. Any prospective quoted-price 50–75 SPY rule is a new fixed hypothesis informed by broad S18, not a historical strategy already validated in this intersection.

## Funding, time, costs and capacity

S18/S19 Sharpe is `mean(monthly settlement cash P&L / constant K) / std × sqrt(12)`. The source field `daily_sharpe` is an unannualized **monthly** mean/std ratio. It is not daily risk. K is maximum concurrently locked stake, excluding fees; constant K cancels from Sharpe. The reported drawdown is additive cumulative P&L divided by K, not percentage drawdown from funded NAV. Booking only at resolution suppresses interim price risk, and a historical entry event may resolve in a later month than its IS/OOS label. Do not splice those segments into a purported funded daily curve.

The supplemental ledger uses the source's putative first-weekend entry time (before the completed 48h VWAP is known), charges NO stake plus the fee at entry and credits the winning NO payout at recorded `closed_time`. It computes the minimum initial cash needed to replay known trades while recycling redemptions. This assumes immediate payout on that timestamp, no operational delay or liquidation, and uses realized outcomes. It is a diagnostic, not an ex ante sizing rule or a daily NAV backtest.

| ALL cohort | Peak locked stake K | Realized minimum initial cash, 1x | Net P&L, 1x | Median / capital-weighted lock days | Illustrative 4% annual capital-time charge |
|---|---:|---:|---:|---:|---:|
| S18 50–75% | $741.63 | $675.26 | $1,134.43 | 25.02 / 25.22 | $7.25 |
| Mixed S&P | $825.19 | $612.87 | $628.71 | 25.23 / 24.74 | $7.34 |
| Monthly SPY | $676.01 | $759.35 | $283.06 | 28.10 / 26.46 | $4.33 |
| S19 broad sellers | $4,097.92 | $5,130.97 | −$211.53 | 7.09 / 13.00 | See CSV |

Monthly SPY needs more actual initial cash than K because losses and fees precede later entries; K alone is insufficient funding. The 4% carry figure is an illustrative assumption, not a verified contemporary rate, and gives no interest credit on collateral. It leaves the broad 50–75 net +$1,127.19 and monthly SPY +$278.72. Cash staking is only one resource constraint: market/group limits, minimum order size, actual displayed book depth and redemption lag also matter. Median eligible 48h seller size is 346.69 contracts for 50–75 and 502.59 for monthly SPY; a single market can be far smaller, as July SPY's seller cohort demonstrates (only 5 printed shares at its tested side). These totals cannot justify live 100-contract marketable orders throughout the cohort.

S18 coverage: 1,092 eligible entries / 130 events, 800 markets checked for first-weekend prints; exclusions were 1 no-print/request-empty, 285 no first-weekend trade and 6 whose early prints were beyond the API's 20,000-row retention. Only 657 have taker sell prints. Quiet and busy missing cohorts can differ economically, so no zero-return placeholders were inserted. S19 checked 1,265 drawn markets / 336 events; 101 had no $50-or-larger print in 48h, 1,132 had taker sells. Its resolved-and-total-volume≥$5,000 eligibility is ex post relative to listing, as is its completed-window VWAP. This is a selected transaction sample, not a live market-universe replay.

## Why S6 and S19 remain useful controls

S6's causal idea is coherent: at 09:45 after reopening, trade a prediction-market terminal threshold toward a listed-options price band after costs. Its 4.2683 headline uses closure-grid returns at 51.0093 closures/year, not 252 daily observations. OOS has 16 modeled trades on 6 active closures; only 1 trade / 1 closure has price-print support. The 2x screen reselects entries (16 becomes 5 OOS), so it is not simply a cost stress on an unchanged portfolio.

Of its 187 modeled entries, 166 without price-print support contribute +$3,364.15, 89.34% of modeled profit. 54 readings are between .45 and .55, where empty or wide-book midpoints can masquerade as probabilities. Even the 21 supported trades have +$298.24 on March 9 alone, more than their total +$294.43; all other supported dates sum −$3.81. A public trade within ±10min of 09:45 can precede the decision, and aggregate prints cannot establish future additional capacity. The source K = $2,165 is the largest stake deployed on one entry closure, while trades may remain open to later resolution; it is not maximum full-lifecycle concurrent capital. Those limitations matter more than merely missing a campaign sample-count gate.

Options used as a reference are not traded or a hedge in S6. The finite-width call-spread band is a discount-normalized risk-neutral option-implied bound, not automatically the physical outcome frequency, and requires the right expiry, strikes, settlement time, exercise/dividend treatment and liquid timely quotes. It does not replicate a path-dependent touch contract.

S19 is better sampled and has actual traded-price support. Its positive OOS 2.2139 Sharpe across 5 settlement months deserves reporting, but the full 25-month seller Sharpe is −.0915, IS is −.3607, and full fixed-K drawdown is 30.01% (worst month −11.24%). Its four crypto assets, weekly and monthly overlapping windows, and nearby event listings share large move regimes. Event IDs are not independent market shocks. A prospective replication should block by calendar time and preserve correlated asset exposures. No single crypto asset's full seller result in existing outputs establishes a strong Sharpe 2–7 premium.

## Exact mechanics and proposed future rule

Current descriptions inspected by the coordinating agent make the distinction concrete. May 2026 SPY high and July 2026 SPY low contracts refer to **Pyth Equity.US.SPY/USD final 1-minute high/low candles**, regular exchange hours only, exact published prices without rounding, split-adjusted target treatment, and exchange daily high/low fallback if the relevant Pyth history is unavailable. The March 2026 SPX high example instead refers to **Yahoo Finance ^GSPC 1-minute data**, with a window from market creation through the final trading day. These are path-dependent oracle barriers, not expiry-close European digitals. SPY options and spot are useful risk references, but a vanilla spread is not a complete replication: intraperiod touch timing, Pyth versus exchange feed, regular-session filters, dividends, corporate-action adjustment and fallback provenance create basis risk. These descriptions were read now, after settlement; historical version invariance was not verified.

I recommend the **broad 50–75 cohort for the paper's primary empirical evidence**, rather than narrowing its headline to mixed S&P's Sharpe 3.21. For the next operational experiment choose **monthly SPY ETF high/low touch ladders governed by the explicitly archived Pyth rule**, because one highly liquid reference instrument and one horizon allow resolution and market-risk checks. That choice prioritizes mechanism and verification over the larger SPX or mixed-family Sharpe. Single stocks add corporate-action/earnings concentration; crude adds futures/reference-roll ambiguity and had negative recent seller results. Those are reasons for a cleaner pilot, not proof SPY sellers have alpha.

The coordinator's [prospective protocol](PROTOCOL.md) adopts the following proposed causal baseline, not yet executed: observe each ticket's first eligible weekend beginning at 20:00 ET on the last exchange session day, then act at its first synchronized valid observation during the following 48 hours. Buy NO only when the current executable YES-equivalent sale price `1 − ask_NO` lies in [.50, .75). Require exchange/receive freshness of at most one second, positive actual depth, minimum-size feasibility, and a second fresh snapshot at least one second later that still satisfies the rule; use that second snapshot's price and size. Require the barrier not already met under the archived source's full resolution window. Use proposed paper capital of $10,000, cap cost plus fees at 5% per underlying/source/month event and 25% across the pilot, and use integer quantities in timestamp order with market ID breaking ties. Preserve idle cash and skipped/failed entries, hold to actual redemption, retain daily executable marks and payout lag, and compare the same quantities with doubled execution costs. SPX remains a separate control. These are new operational choices informed by the observational finding, not historical parameters shown to produce the reported Sharpe. The final configuration and every implementation amendment must be frozen before the future data they test.

## Selection disclosure and defensible claim

S6 reported 4 variants at 2 cost levels, 24 segment rows. S18 had 5 historical variants at 2 cost levels, 99 calibration rows and 28 traded-price tests spanning both sides and 6 price buckets. S19 had 38 traded-price tests across sides, assets, horizons, eras and buckets. This audit reports 10 S18 seller cohorts (all sellers, prespecified price bucket, and 8 post-hoc reference/horizon/comparator cuts), plus 5 buyer cohorts, with all IS/OOS/cost cases in the CSV. These are dependent comparisons; no count of independent discoveries is implied. No multiplicity-adjusted confidence level or confirmation status is claimed. The wider prior campaign adds selection exposure that the five-variant deflated-Sharpe calculation cannot capture.

A defensible paper claim is: **in this archived noncrypto transaction cohort, YES purchases substantially overpaid relative to subsequent barrier outcomes after fees, most clearly at traded prices of 50–75%; selling into observed bids earned a positive full-sample mean in that cohort, while recent broad seller returns and the crypto replication reveal meaningful regime and execution limits.** Investigate demand, spreads and risk premium as mechanisms; the current data do not identify investor preferences or establish an arbitrage. Present monthly settlement Sharpe 2.17 as a descriptive supplement, the price/result calibration and event-level uncertainty as the primary finding, and future monthly SPY quote-based trading as the confirmation study.
